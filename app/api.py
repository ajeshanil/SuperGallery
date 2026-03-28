"""SuperGallery FastAPI backend — serves all data and the web frontend."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from pathlib import Path

# Repo root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# File logging — write to ~/.supergallery/app.log
_LOG_DIR = Path.home() / ".supergallery"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "app.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
# Suppress PIL noise before any imports
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("ultralytics").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func

from database.db import get_session, init_db
from database.models import (
    Album, AlbumPhoto, Location, ObjectDetection, Photo, PhotoPerson, Person, Tag,
)
from utils.search import search_photos

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="SuperGallery", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
THUMB_DIR  = Path.home() / ".supergallery" / "thumbs"
THUMB_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Shared operation state (updated by background tasks, polled by SSE)
# ---------------------------------------------------------------------------

_op: dict = {
    "running": False, "operation": "", "op_label": "",
    "done": 0, "total": 0, "message": "Ready", "current_file": "",
}
_op_lock = threading.Lock()


def _set(**kw):
    with _op_lock:
        _op.update(kw)


def _format_event_name(start_date, end_date) -> str:
    """Format album name: '12 Mar 2024' or '12–15 Mar 2024'."""
    _MONTHS = ['Jan','Feb','Mar','Apr','May','Jun',
               'Jul','Aug','Sep','Oct','Nov','Dec']
    d1, d2 = start_date, end_date
    if d1.date() == d2.date():
        return f"{d1.day} {_MONTHS[d1.month-1]} {d1.year}"
    elif d1.month == d2.month and d1.year == d2.year:
        return f"{d1.day}\u2013{d2.day} {_MONTHS[d1.month-1]} {d1.year}"
    elif d1.year == d2.year:
        return f"{d1.day} {_MONTHS[d1.month-1]} \u2013 {d2.day} {_MONTHS[d2.month-1]} {d1.year}"
    else:
        return f"{d1.day} {_MONTHS[d1.month-1]} {d1.year} \u2013 {d2.day} {_MONTHS[d2.month-1]} {d2.year}"


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup():
    init_db()

    # Pre-warm AI model imports in the main thread to avoid Windows DLL
    # initialisation failures when they are first imported from a background thread.
    try:
        import models.object_detector   # noqa: F401  — triggers the module-level try/except
        import models.scene_classifier  # noqa: F401
        import models.face_recognizer   # noqa: F401
        logger.info("AI model modules pre-warmed successfully")
    except Exception as exc:
        logger.warning("AI model pre-warm failed: %s", exc)

    import threading

    def _auto_analyze_check():
        import time
        time.sleep(1.5)  # let server finish initialising
        if _op["running"]:
            return
        session = get_session()
        try:
            from database.models import Photo, Tag
            total = session.query(Photo).count()
            if total == 0:
                return
            analyzed = session.query(Tag.photo_id).filter(
                Tag.category.in_(["Objects", "Scenes"])
            ).distinct().count()
            if analyzed < total:
                logger.info("Auto-triggering AI analysis for %d unanalyzed photos", total - analyzed)
                _bg_analyze()
        except Exception:
            logger.exception("Auto-analyze check failed")
        finally:
            session.close()

    threading.Thread(target=_auto_analyze_check, daemon=True).start()


# ---------------------------------------------------------------------------
# Static files + SPA root
# ---------------------------------------------------------------------------

@app.get("/")
async def spa_root():
    return FileResponse(str(STATIC_DIR / "index.html"))


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------

def _photo_dict(p: Photo) -> dict:
    return {
        "id":           p.id,
        "filename":     p.filename,
        "date_taken":   p.date_taken.isoformat() if p.date_taken else None,
        "width":        p.width,
        "height":       p.height,
        "lat":          p.lat,
        "lng":          p.lng,
        "camera_model": p.camera_model,
        "is_favorite":  bool(p.is_favorite),
    }


@app.get("/api/photos")
def list_photos(
    sort: str    = "month_desc",
    filters: str = "{}",
    page: int    = 1,
    page_size: int = 120,
    favorite: bool = False,
):
    session = get_session()
    try:
        f = json.loads(filters)
        photos = search_photos(session, f) if any(f.values()) else session.query(Photo).all()
        if favorite:
            photos = [p for p in photos if p.is_favorite]

        # Sort
        dated   = [(p, p.date_taken) for p in photos if p.date_taken]
        undated = [p for p in photos if not p.date_taken]
        dated.sort(key=lambda x: x[1], reverse=("desc" in sort))
        ordered = [p for p, _ in dated] + undated

        total   = len(ordered)
        start   = (page - 1) * page_size
        chunk   = ordered[start : start + page_size]
        return {
            "total":  total,
            "page":   page,
            "pages":  max(1, (total + page_size - 1) // page_size),
            "photos": [_photo_dict(p) for p in chunk],
        }
    finally:
        session.close()


@app.get("/api/photos/{photo_id}/thumb")
async def photo_thumb(photo_id: int, size: int = 220):
    thumb = THUMB_DIR / f"{photo_id}_{size}.jpg"
    if not thumb.exists():
        session = get_session()
        try:
            photo = session.get(Photo, photo_id)
            if not photo or not Path(photo.file_path).exists():
                raise HTTPException(404)
            from PIL import Image
            img = Image.open(photo.file_path)
            img.draft("RGB", (size, size))
            img.thumbnail((size, size), Image.BILINEAR)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(str(thumb), "JPEG", quality=82)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Thumb gen failed photo %d: %s", photo_id, e)
            raise HTTPException(500, str(e))
        finally:
            session.close()
    return FileResponse(str(thumb), media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400"})


@app.get("/api/photos/{photo_id}/image")
async def photo_image(photo_id: int):
    session = get_session()
    try:
        photo = session.get(Photo, photo_id)
        if not photo or not Path(photo.file_path).exists():
            raise HTTPException(404)
        return FileResponse(photo.file_path,
                            headers={"Cache-Control": "max-age=3600"})
    finally:
        session.close()


@app.post("/api/photos/{photo_id}/favorite")
def toggle_favorite(photo_id: int):
    session = get_session()
    try:
        photo = session.get(Photo, photo_id)
        if not photo:
            raise HTTPException(404)
        photo.is_favorite = not photo.is_favorite
        session.commit()
        return {"is_favorite": bool(photo.is_favorite)}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@app.get("/api/photos/{photo_id}/tags")
def photo_tags(photo_id: int):
    session = get_session()
    try:
        tags = (
            session.query(Tag)
            .filter(Tag.photo_id == photo_id)
            .order_by(Tag.category, Tag.label)
            .all()
        )
        return [
            {"id": t.id, "label": t.label, "category": t.category,
             "confidence": t.confidence, "is_manual": t.is_manual}
            for t in tags
        ]
    finally:
        session.close()


class _TagCreate(BaseModel):
    photo_id: int
    label: str
    category: str


@app.post("/api/tags")
def create_tag(body: _TagCreate):
    session = get_session()
    try:
        tag = Tag(photo_id=body.photo_id, label=body.label.strip(),
                  category=body.category, is_manual=True)
        session.add(tag)
        session.commit()
        return {"id": tag.id, "label": tag.label, "category": tag.category,
                "confidence": None, "is_manual": True}
    finally:
        session.close()


@app.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int):
    session = get_session()
    try:
        tag = session.get(Tag, tag_id)
        if tag:
            session.delete(tag)
            session.commit()
        return {"ok": True}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tag counts (for the tag-browser filter panel)
# ---------------------------------------------------------------------------

@app.get("/api/tags/counts")
def tag_counts():
    """Return all (category, label) pairs with photo counts, grouped by category.
    Used by the tag-browser panel to render clickable filter chips."""
    session = get_session()
    try:
        rows = (
            session.query(Tag.category, Tag.label, func.count().label("cnt"))
            .group_by(Tag.category, Tag.label)
            .order_by(Tag.category, func.count().desc(), Tag.label)
            .all()
        )
        result: dict = {}
        for cat, lbl, cnt in rows:
            result.setdefault(cat, []).append({"label": lbl, "count": cnt})
        return result
    finally:
        session.close()


@app.get("/api/search")
def api_search_photos(q: str = ""):
    """Full-text search across tag labels, filename, and person names."""
    if not q or not q.strip():
        return {"photo_ids": []}
    session = get_session()
    try:
        pattern = f"%{q.strip()}%"
        tag_match_ids = {
            r[0] for r in session.query(Tag.photo_id)
            .filter(Tag.label.ilike(pattern)).distinct()
        }
        filename_match_ids = {
            r[0] for r in session.query(Photo.id)
            .filter(Photo.filename.ilike(pattern))
        }
        person_match_ids = {
            r[0] for r in session.query(PhotoPerson.photo_id)
            .join(Person, Person.id == PhotoPerson.person_id)
            .filter(Person.name.ilike(pattern)).distinct()
        }
        all_ids = tag_match_ids | filename_match_ids | person_match_ids
        if not all_ids:
            return {"photo_ids": []}
        photos = (
            session.query(Photo)
            .filter(Photo.id.in_(all_ids))
            .order_by(Photo.date_taken.desc().nullslast())
            .all()
        )
        return {"photo_ids": [p.id for p in photos]}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Per-photo analysis (re-analyse a single photo in-place)
# ---------------------------------------------------------------------------

@app.post("/api/photos/{photo_id}/analyze")
def analyze_single(photo_id: int):
    """Delete existing AI tags for one photo, re-run object detection + scene
    classification + face processing, and return the updated tag list.
    Runs synchronously (typically 2–5 s per photo)."""
    session = get_session()
    try:
        photo = session.get(Photo, photo_id)
        if not photo:
            raise HTTPException(404)

        # ── Clear previous AI data for this photo ──
        session.query(Tag).filter(
            Tag.photo_id == photo_id,
            Tag.category.in_(["Objects", "Scenes", "People"]),
            Tag.is_manual == False,  # noqa: E712
        ).delete(synchronize_session=False)
        session.query(Tag).filter(
            Tag.photo_id == photo_id,
            Tag.category == "PhotoType",
            Tag.confidence.isnot(None),
            Tag.is_manual == False,  # noqa: E712
        ).delete(synchronize_session=False)
        session.query(ObjectDetection).filter(
            ObjectDetection.photo_id == photo_id
        ).delete(synchronize_session=False)
        session.query(PhotoPerson).filter(
            PhotoPerson.photo_id == photo_id
        ).delete(synchronize_session=False)
        session.commit()

        from models.object_detector import ObjectDetector
        from models.scene_classifier import SceneClassifier
        from models.config import DEFAULT_CONFIDENCE, SCENE_CONFIDENCE

        detector   = ObjectDetector(confidence=DEFAULT_CONFIDENCE)
        classifier = SceneClassifier(confidence=SCENE_CONFIDENCE)

        dets = detector.detect(photo.file_path)
        for det in dets:
            if det["label"].lower() != "person":
                session.add(Tag(photo_id=photo_id, label=det["label"],
                               category="Objects", confidence=det["confidence"],
                               is_manual=False))
            bx, by, bw, bh = det["bbox"]
            session.add(ObjectDetection(
                photo_id=photo_id, label=det["label"],
                confidence=det["confidence"],
                bbox_x=bx, bbox_y=by, bbox_w=bw, bbox_h=bh,
            ))
        for s in classifier.classify(photo.file_path):
            session.add(Tag(photo_id=photo_id, label=s["label"],
                           category="Scenes", confidence=s["confidence"],
                           is_manual=False))
        pt = detector.infer_photo_type(dets)
        if pt:
            session.add(Tag(photo_id=photo_id, label=pt,
                           category="PhotoType", is_manual=False))
        for qt in _detect_photo_quality_type(photo):
            session.add(Tag(photo_id=photo_id, label=qt,
                           category="PhotoType", is_manual=False))
        session.commit()

        # Face processing for this photo
        try:
            import numpy as np
            from models.face_recognizer import FaceRecognizer
            from models.config import FACE_MATCH_THRESHOLD
            from utils.face_processor import _save_face_thumbnail

            recognizer = FaceRecognizer()
            faces = recognizer.detect_and_embed(photo.file_path)

            if faces:
                existing_persons = session.query(Person).filter(
                    Person.embedding_vector.isnot(None)
                ).all()
                existing_embs = {}
                for p in existing_persons:
                    emb = np.frombuffer(p.embedding_vector, dtype=np.float32).copy()
                    norm = np.linalg.norm(emb)
                    if norm > 0:
                        existing_embs[p.id] = emb / norm

                person_cache: dict = {}
                for face in faces:
                    bbox, embedding, confidence = face["bbox"], face["embedding"], face["confidence"]
                    norm = np.linalg.norm(embedding)
                    emb_n = embedding / norm if norm > 0 else embedding

                    matched_pid = None
                    if existing_embs:
                        best_dist, best_pid = min(
                            ((1.0 - float(np.dot(emb_n, pem)), pid)
                             for pid, pem in existing_embs.items()),
                            key=lambda t: t[0],
                        )
                        if best_dist < FACE_MATCH_THRESHOLD:
                            matched_pid = best_pid

                    if matched_pid is None:
                        # New person
                        existing_count = session.query(Person).count()
                        person = Person(
                            name=f"Person {existing_count + 1}",
                            embedding_vector=embedding.tobytes(),
                        )
                        session.add(person)
                        session.flush()
                        _save_face_thumbnail(session, person, (photo_id, bbox, confidence))
                    else:
                        if matched_pid not in person_cache:
                            person_cache[matched_pid] = session.get(Person, matched_pid)
                        person = person_cache[matched_pid]

                    x, y, w, h = bbox
                    session.add(PhotoPerson(
                        photo_id=photo_id, person_id=person.id,
                        confidence=confidence, bbox_x=x, bbox_y=y, bbox_w=w, bbox_h=h,
                    ))
                    session.add(Tag(
                        photo_id=photo_id, label=person.name,
                        category="People", confidence=confidence, is_manual=False,
                    ))
                session.commit()
        except Exception as exc:
            logger.warning("Face processing failed for photo %d: %s", photo_id, exc)
            session.rollback()

        # Return updated tag list
        tags = (
            session.query(Tag)
            .filter(Tag.photo_id == photo_id)
            .order_by(Tag.category, Tag.label)
            .all()
        )
        return [
            {"id": t.id, "label": t.label, "category": t.category,
             "confidence": t.confidence, "is_manual": t.is_manual}
            for t in tags
        ]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Object detections
# ---------------------------------------------------------------------------

@app.get("/api/photos/{photo_id}/detections")
def photo_detections(photo_id: int):
    session = get_session()
    try:
        dets = (
            session.query(ObjectDetection)
            .filter(ObjectDetection.photo_id == photo_id)
            .all()
        )
        return [
            {"id": d.id, "label": d.label, "confidence": d.confidence,
             "bbox": [d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h]}
            for d in dets
        ]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# People  (order matters: /similar before /{person_id}/…)
# ---------------------------------------------------------------------------

@app.get("/api/people/similar")
def similar_people():
    try:
        import numpy as np
    except ImportError:
        return []
    session = get_session()
    try:
        people = (
            session.query(Person)
            .filter(Person.embedding_vector.isnot(None))
            .all()
        )
        pairs = []
        for i, p1 in enumerate(people):
            # Only surface pairs where both persons have a face thumbnail
            if not (p1.thumbnail_path and Path(p1.thumbnail_path).exists()):
                continue
            e1 = np.frombuffer(p1.embedding_vector, dtype=np.float32)
            for p2 in people[i + 1:]:
                if not (p2.thumbnail_path and Path(p2.thumbnail_path).exists()):
                    continue
                e2 = np.frombuffer(p2.embedding_vector, dtype=np.float32)
                n = np.linalg.norm(e1) * np.linalg.norm(e2)
                sim = float(np.dot(e1, e2) / (n + 1e-8)) if n else 0.0
                # Only surface pairs that are genuinely close — high enough that a
                # human should verify, but below the level where clustering would
                # have already merged them.
                # cosine similarity > 0.70: faces look noticeably alike (same person
                #   with different angle/lighting, or close family members).
                # cosine similarity < 0.92: below this they'd likely already be in
                #   the same cluster or are clearly identical shots.
                if 0.70 < sim < 0.92:
                    pairs.append({
                        "person_a": p1.id, "name_a": p1.name,
                        "person_b": p2.id, "name_b": p2.name,
                        "similarity": round(sim, 3),
                    })
        return sorted(pairs, key=lambda x: -x["similarity"])
    finally:
        session.close()


@app.get("/api/people")
def list_people():
    session = get_session()
    try:
        people = session.query(Person).order_by(Person.name).all()
        result = []
        for p in people:
            count = (
                session.query(PhotoPerson)
                .filter(PhotoPerson.person_id == p.id)
                .count()
            )
            result.append({
                "id": p.id, "name": p.name,
                "has_thumb": bool(p.thumbnail_path and Path(p.thumbnail_path).exists()),
                "photo_count": count,
            })
        return result
    finally:
        session.close()


@app.get("/api/people/{person_id}/thumb")
async def person_thumb(person_id: int):
    session = get_session()
    try:
        person = session.get(Person, person_id)
        if person and person.thumbnail_path and Path(person.thumbnail_path).exists():
            return FileResponse(person.thumbnail_path, media_type="image/jpeg",
                                headers={"Cache-Control": "max-age=3600"})
        raise HTTPException(404)
    finally:
        session.close()


@app.get("/api/people/{person_id}/photos")
def person_photos(person_id: int):
    session = get_session()
    try:
        person = session.get(Person, person_id)
        if not person:
            raise HTTPException(404)
        photos = search_photos(session, {"People": [person.name]})
        return [_photo_dict(p) for p in photos]
    finally:
        session.close()


@app.get("/api/people/{person_id}/top-tags")
def person_top_tags(person_id: int):
    session = get_session()
    try:
        person = session.get(Person, person_id)
        if not person:
            raise HTTPException(404)
        photos = search_photos(session, {"People": [person.name]})
        photo_ids = [p.id for p in photos]
        if not photo_ids:
            return []
        rows = (
            session.query(Tag.label, Tag.category, func.count().label("cnt"))
            .filter(Tag.photo_id.in_(photo_ids),
                    Tag.category.in_(["Objects", "Scenes"]))
            .group_by(Tag.label, Tag.category)
            .order_by(func.count().desc())
            .limit(8)
            .all()
        )
        return [{"label": r.label, "category": r.category, "count": r.cnt} for r in rows]
    finally:
        session.close()


class _Rename(BaseModel):
    name: str


@app.post("/api/people/{person_id}/rename")
def rename_person(person_id: int, body: _Rename):
    session = get_session()
    try:
        person = session.get(Person, person_id)
        if not person:
            raise HTTPException(404)
        old = person.name
        person.name = body.name.strip()
        session.query(Tag).filter(
            Tag.category == "People", Tag.label == old
        ).update({"label": person.name})
        session.commit()
        return {"ok": True, "name": person.name}
    finally:
        session.close()


@app.delete("/api/people/{person_id}")
def delete_person(person_id: int):
    """Delete a Person and all their PhotoPerson links and People tags."""
    session = get_session()
    try:
        person = session.get(Person, person_id)
        if not person:
            raise HTTPException(404)
        # Remove face thumbnail file
        if person.thumbnail_path:
            try:
                Path(person.thumbnail_path).unlink(missing_ok=True)
            except Exception:
                pass
        session.query(PhotoPerson).filter(PhotoPerson.person_id == person_id).delete()
        session.query(Tag).filter(Tag.category == "People", Tag.label == person.name).delete()
        session.delete(person)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


class _Merge(BaseModel):
    keep_id: int
    remove_id: int


@app.post("/api/people/merge")
def merge_people(body: _Merge):
    session = get_session()
    try:
        keep   = session.get(Person, body.keep_id)
        remove = session.get(Person, body.remove_id)
        if not keep or not remove:
            raise HTTPException(404)
        session.query(PhotoPerson).filter(
            PhotoPerson.person_id == remove.id
        ).update({"person_id": keep.id})
        session.query(Tag).filter(
            Tag.category == "People", Tag.label == remove.name
        ).update({"label": keep.name})
        session.delete(remove)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


class _BulkDeletePeople(BaseModel):
    person_ids: list[int]


@app.post("/api/people/bulk-delete")
def bulk_delete_people(body: _BulkDeletePeople):
    """Delete multiple persons at once."""
    if not body.person_ids:
        return {"ok": True, "deleted": 0}
    session = get_session()
    try:
        deleted = 0
        for person_id in body.person_ids:
            person = session.get(Person, person_id)
            if not person:
                continue
            if person.thumbnail_path:
                try:
                    Path(person.thumbnail_path).unlink(missing_ok=True)
                except Exception:
                    pass
            session.query(PhotoPerson).filter(PhotoPerson.person_id == person_id).delete()
            session.query(Tag).filter(
                Tag.category == "People", Tag.label == person.name
            ).delete()
            session.delete(person)
            deleted += 1
        session.commit()
        return {"ok": True, "deleted": deleted}
    except Exception as exc:
        session.rollback()
        raise HTTPException(500, str(exc))
    finally:
        session.close()


# ── Albums ──────────────────────────────────────────────────────────────────

class _AlbumCreate(BaseModel):
    name: str


@app.post("/api/albums/generate-events")
def generate_event_albums():
    """Auto-group photos into event albums by 6-hour time gaps."""
    from datetime import timedelta
    session = get_session()
    try:
        # Delete previously auto-generated event albums
        old_ids = [r[0] for r in session.query(Album.id)
                   .filter(Album.filter_query == "event")]
        if old_ids:
            session.query(AlbumPhoto).filter(
                AlbumPhoto.album_id.in_(old_ids)
            ).delete(synchronize_session=False)
            session.query(Album).filter(Album.id.in_(old_ids)).delete(
                synchronize_session=False)
            session.commit()

        photos = (
            session.query(Photo)
            .filter(Photo.date_taken.isnot(None))
            .order_by(Photo.date_taken)
            .all()
        )
        if not photos:
            return {"ok": True, "albums_created": 0}

        events = []
        current_event = [photos[0]]
        for photo in photos[1:]:
            if photo.date_taken - current_event[-1].date_taken > timedelta(hours=6):
                events.append(current_event)
                current_event = [photo]
            else:
                current_event.append(photo)
        events.append(current_event)

        albums_created = 0
        for event_photos in events:
            if len(event_photos) < 2:
                continue
            start = event_photos[0].date_taken
            end = event_photos[-1].date_taken
            name = _format_event_name(start, end)
            album = Album(
                name=name,
                filter_query="event",
                is_smart=False,
                cover_photo_id=event_photos[0].id,
            )
            session.add(album)
            session.flush()
            for order, photo in enumerate(event_photos):
                session.add(AlbumPhoto(album_id=album.id,
                                       photo_id=photo.id,
                                       sort_order=order))
            albums_created += 1
        session.commit()
        return {"ok": True, "albums_created": albums_created}
    except Exception as exc:
        session.rollback()
        raise HTTPException(500, str(exc))
    finally:
        session.close()


@app.get("/api/albums")
def list_albums_api():
    session = get_session()
    try:
        albums = session.query(Album).order_by(Album.created_at.desc()).all()
        result = []
        for a in albums:
            count = session.query(AlbumPhoto).filter(
                AlbumPhoto.album_id == a.id).count()
            result.append({
                "id": a.id,
                "name": a.name,
                "is_smart": bool(a.is_smart),
                "photo_count": count,
                "cover_photo_id": a.cover_photo_id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            })
        return result
    finally:
        session.close()


@app.get("/api/albums/{album_id}/photos")
def album_photos_api(album_id: int):
    session = get_session()
    try:
        album = session.get(Album, album_id)
        if not album:
            raise HTTPException(404)
        rows = (session.query(AlbumPhoto)
                .filter(AlbumPhoto.album_id == album_id)
                .order_by(AlbumPhoto.sort_order)
                .all())
        photo_ids = [r.photo_id for r in rows]
        photos_by_id = {
            p.id: p for p in
            session.query(Photo).filter(Photo.id.in_(photo_ids)).all()
        }
        return [_photo_dict(photos_by_id[pid]) for pid in photo_ids if pid in photos_by_id]
    finally:
        session.close()


@app.post("/api/albums")
def create_album_api(body: _AlbumCreate):
    session = get_session()
    try:
        album = Album(name=body.name.strip(), filter_query=None, is_smart=False)
        session.add(album)
        session.commit()
        return {
            "id": album.id, "name": album.name, "photo_count": 0,
            "cover_photo_id": None,
            "created_at": album.created_at.isoformat() if album.created_at else None,
        }
    finally:
        session.close()


@app.delete("/api/albums/{album_id}")
def delete_album_api(album_id: int):
    session = get_session()
    try:
        album = session.get(Album, album_id)
        if not album:
            raise HTTPException(404)
        session.query(AlbumPhoto).filter(AlbumPhoto.album_id == album_id).delete()
        session.delete(album)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Thumbnail pre-generation
# ---------------------------------------------------------------------------

@app.post("/api/admin/gen-thumbs")
def gen_thumbs(background_tasks: BackgroundTasks):
    """Pre-generate all missing photo thumbnails in background."""
    with _op_lock:
        if _op["running"]:
            return {"error": "Operation already running"}
    background_tasks.add_task(_bg_gen_thumbs)
    return {"ok": True}


def _bg_gen_thumbs():
    from PIL import Image
    _set(running=True, operation="thumbs", op_label="Generating thumbnails",
         done=0, total=0, message="Counting photos…")
    session = get_session()
    try:
        photos = session.query(Photo).all()
        total  = len(photos)
        _set(total=total)
        size   = 220
        for i, photo in enumerate(photos):
            thumb = THUMB_DIR / f"{photo.id}_{size}.jpg"
            if not thumb.exists():
                try:
                    img = Image.open(photo.file_path)
                    img.draft("RGB", (size, size))
                    img.thumbnail((size, size), Image.BILINEAR)
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    img.save(str(thumb), "JPEG", quality=82)
                except Exception as exc:
                    logger.warning("Thumb gen %s: %s", photo.file_path, exc)
            _set(done=i + 1, message=f"Thumbnails {i+1}/{total}")
    finally:
        session.close()
    _set(running=False, operation="thumbs_done",
         message=f"Thumbnails ready for {total} photos")


# ---------------------------------------------------------------------------
# Admin resets  (for testing / re-analysis)
# ---------------------------------------------------------------------------

@app.post("/api/admin/reset-analysis")
def reset_analysis():
    """Delete all AI-derived data (Objects/Scenes/People tags, ObjectDetections,
    Person and PhotoPerson rows) while keeping photos and EXIF-derived tags
    (Date, Camera, Location, PhotoType from import).  Use this to re-run
    AI analysis from scratch without re-importing photos."""
    with _op_lock:
        if _op["running"]:
            return {"error": "Operation already running"}
    session = get_session()
    try:
        from database.models import ObjectDetection, Person, PhotoPerson, Tag
        # AI-generated tags only; keep Date, Camera, Location (EXIF)
        deleted_tags = (
            session.query(Tag)
            .filter(Tag.category.in_(["Objects", "Scenes", "People"]),
                    Tag.is_manual == False)  # noqa: E712
            .delete(synchronize_session=False)
        )
        # Also delete AI-generated PhotoType tags (selfie / portrait / group photo)
        # but keep the EXIF orientation/resolution PhotoType tags written during import.
        # Distinguish: AI PhotoType tags have confidence set, EXIF ones don't.
        deleted_pt = (
            session.query(Tag)
            .filter(Tag.category == "PhotoType",
                    Tag.confidence.isnot(None),
                    Tag.is_manual == False)  # noqa: E712
            .delete(synchronize_session=False)
        )
        deleted_od  = session.query(ObjectDetection).delete(synchronize_session=False)
        deleted_pp  = session.query(PhotoPerson).delete(synchronize_session=False)
        deleted_p   = session.query(Person).delete(synchronize_session=False)
        session.commit()

        # Remove face thumbnail files
        face_thumb_dir = Path.home() / ".supergallery" / "face_thumbs"
        removed_thumbs = 0
        if face_thumb_dir.exists():
            for f in face_thumb_dir.glob("*.jpg"):
                try:
                    f.unlink()
                    removed_thumbs += 1
                except Exception:
                    pass

        _set(running=False, operation="", message="Ready")
        return {
            "ok": True,
            "deleted_tags": deleted_tags + deleted_pt,
            "deleted_detections": deleted_od,
            "deleted_persons": deleted_p,
            "deleted_photo_person": deleted_pp,
            "removed_face_thumbs": removed_thumbs,
        }
    except Exception as exc:
        session.rollback()
        raise HTTPException(500, str(exc))
    finally:
        session.close()


@app.post("/api/admin/reset-all")
def reset_all():
    """Hard reset: delete ALL data (photos, tags, people, detections) and
    clear the thumbnail cache.  Equivalent to deleting the DB and restarting."""
    with _op_lock:
        if _op["running"]:
            return {"error": "Operation already running"}
    session = get_session()
    try:
        from database.models import (
            Location, ObjectDetection, Person, Photo, PhotoPerson, Tag,
        )
        session.query(PhotoPerson).delete(synchronize_session=False)
        session.query(Tag).delete(synchronize_session=False)
        session.query(ObjectDetection).delete(synchronize_session=False)
        session.query(Location).delete(synchronize_session=False)
        session.query(Person).delete(synchronize_session=False)
        session.query(Photo).delete(synchronize_session=False)
        session.commit()

        # Clear thumbnail caches
        removed = 0
        for d in [THUMB_DIR, Path.home() / ".supergallery" / "face_thumbs"]:
            if d.exists():
                for f in d.glob("*.jpg"):
                    try:
                        f.unlink()
                        removed += 1
                    except Exception:
                        pass

        _set(running=False, operation="", message="Ready")
        return {"ok": True, "removed_thumbs": removed}
    except Exception as exc:
        session.rollback()
        raise HTTPException(500, str(exc))
    finally:
        session.close()


@app.post("/api/admin/run-quality-tags")
def run_quality_tags(background_tasks: BackgroundTasks):
    """Backfill quality PhotoType tags on all photos that don't have them yet."""
    with _op_lock:
        if _op["running"]:
            return {"error": "Operation already running"}
    background_tasks.add_task(_bg_run_quality_tags)
    return {"ok": True}


def _bg_run_quality_tags():
    QUALITY_LABELS = {"Blurry", "Dark/Accidental", "Screenshot"}
    _set(running=True, operation="quality_tags", op_label="Quality tag backfill",
         done=0, total=0, message="Counting photos\u2026")
    session = get_session()
    try:
        already_done_ids = {
            r[0] for r in session.query(Tag.photo_id)
            .filter(Tag.category == "PhotoType",
                    Tag.label.in_(list(QUALITY_LABELS)))
            .distinct()
        }
        photos = session.query(Photo).filter(~Photo.id.in_(already_done_ids)).all()
        total = len(photos)
        _set(total=total, message=f"Processing {total} photos\u2026")

        for i, photo in enumerate(photos):
            _set(current_file=Path(photo.file_path).name)
            try:
                tags = _detect_photo_quality_type(photo)
                for qt in tags:
                    session.add(Tag(photo_id=photo.id, label=qt,
                                   category="PhotoType", is_manual=False))
                if tags:
                    session.commit()
                else:
                    session.rollback()
            except Exception as exc:
                logger.warning("Quality tag error photo %d: %s", photo.id, exc)
                session.rollback()
            _set(done=i + 1, message=f"Processed {i+1}/{total}")
    finally:
        session.close()
    _set(running=False, operation="quality_tags_done",
         message="Quality tag backfill complete", current_file="")


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

@app.get("/api/map")
async def get_map():
    session = get_session()
    try:
        from utils.map_builder import get_map_html
        path = get_map_html(session)
        if path and Path(path).exists():
            return FileResponse(path, media_type="text/html")
        return HTMLResponse(
            "<html><body style='background:#121212;color:#555;"
            "font-family:sans-serif;padding:40px;font-size:14px'>"
            "No location data available.</body></html>"
        )
    except Exception as exc:
        return HTMLResponse(
            f"<html><body style='background:#121212;color:#c62828;"
            f"padding:40px'>Error: {exc}</body></html>"
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Operation status (SSE stream)
# ---------------------------------------------------------------------------

async def _sse_stream():
    while True:
        with _op_lock:
            data = dict(_op)
        yield f"data: {json.dumps(data)}\n\n"
        await asyncio.sleep(0.4)


@app.get("/api/status/stream")
async def status_stream():
    return StreamingResponse(
        _sse_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/status")
def get_status():
    with _op_lock:
        return dict(_op)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

class _ImportReq(BaseModel):
    folder: str
    random_limit: int = 0   # if > 0, import a random subset of this many photos


@app.post("/api/import")
def start_import(body: _ImportReq, background_tasks: BackgroundTasks):
    with _op_lock:
        if _op["running"]:
            return {"error": "Operation already running"}
    background_tasks.add_task(_bg_import, body.folder, body.random_limit)
    return {"ok": True}


def _bg_import(folder: str, random_limit: int = 0):
    import random as _random
    from utils.importer import (
        SUPPORTED_EXTENSIONS, extract_metadata,
        _orientation_label, _resolution_label,
    )
    folder_path = Path(folder)
    if not folder_path.is_dir():
        _set(running=False, operation="error", message=f"Folder not found: {folder}")
        return

    files = [p for p in folder_path.rglob("*")
             if p.suffix.lower() in SUPPORTED_EXTENSIONS]

    if random_limit > 0 and len(files) > random_limit:
        files = _random.sample(files, random_limit)
        logger.info("Random import: selected %d/%d files", random_limit, len(files) + random_limit)

    total = len(files)
    _set(running=True, operation="import", op_label="Importing photos",
         done=0, total=total, message=f"Found {total} files…")

    session = get_session()
    try:
        existing = {r[0] for r in session.query(Photo.file_path).all()}
        imported = skipped = 0

        for i, fp in enumerate(files):
            abs_path = str(fp.resolve())
            if abs_path in existing:
                skipped += 1
            else:
                try:
                    meta  = extract_metadata(abs_path)
                    photo = Photo(**{k: meta[k] for k in (
                        "file_path", "filename", "date_taken",
                        "lat", "lng", "camera_model", "width", "height", "file_size"
                    )})
                    session.add(photo)
                    session.flush()

                    # Date tags
                    if photo.date_taken:
                        for lbl in [
                            str(photo.date_taken.year),
                            photo.date_taken.strftime("%B %Y"),
                            photo.date_taken.strftime("%B"),
                        ]:
                            session.add(Tag(photo_id=photo.id, label=lbl,
                                           category="Date", is_manual=False))
                    # Camera tag
                    if photo.camera_model:
                        session.add(Tag(photo_id=photo.id, label=photo.camera_model,
                                       category="Camera", is_manual=False))
                    # Orientation + resolution
                    if photo.width and photo.height:
                        orient = _orientation_label(photo.width, photo.height)
                        if orient:
                            session.add(Tag(photo_id=photo.id, label=orient,
                                           category="PhotoType", is_manual=False))
                        res_lbl = _resolution_label(photo.width, photo.height)
                        if res_lbl:
                            session.add(Tag(photo_id=photo.id, label=res_lbl,
                                           category="PhotoType", is_manual=False))
                    # GPS
                    if photo.lat is not None and photo.lng is not None:
                        session.add(Tag(photo_id=photo.id, label="Has GPS",
                                       category="Location", is_manual=False))
                        session.add(Location(photo_id=photo.id,
                                             lat=photo.lat, lng=photo.lng))
                    session.commit()
                    imported += 1
                except Exception as exc:
                    logger.warning("Import error %s: %s", abs_path, exc)
                    session.rollback()

            _set(done=i + 1,
                 message=f"Imported {imported}, skipped {skipped}")

    finally:
        session.close()

    _set(running=False, operation="import_done",
         message=f"Done — {imported} added, {skipped} skipped")

    # Auto-chain: thumbnails → AI analysis → face processing
    if imported > 0:
        _bg_gen_thumbs()
        _bg_analyze()


# ---------------------------------------------------------------------------
# Analyze (AI tagging)
# ---------------------------------------------------------------------------

@app.post("/api/analyze")
def start_analyze(background_tasks: BackgroundTasks):
    with _op_lock:
        if _op["running"]:
            return {"error": "Operation already running"}
    background_tasks.add_task(_bg_analyze)
    return {"ok": True}


def _detect_photo_quality_type(photo) -> list[str]:
    """Detect screenshots, blurry/dark accidental photos, and documents."""
    tags: list[str] = []
    try:
        from PIL import Image
        import numpy as np
        img = Image.open(photo.file_path).convert("L").resize((200, 200), Image.BILINEAR)
        arr = np.array(img, dtype=np.float32)

        # Blurry: low Laplacian variance
        lap = (np.roll(arr,1,0) + np.roll(arr,-1,0) +
               np.roll(arr,1,1) + np.roll(arr,-1,1) - 4 * arr)
        sharpness = float(lap.var())
        mean_brightness = float(arr.mean())

        if mean_brightness < 15:
            tags.append("Dark/Accidental")
        elif sharpness < 30:
            tags.append("Blurry")

        # Screenshot: no camera model + screen-like aspect ratio + no GPS
        if (not photo.camera_model and photo.lat is None and
                photo.width and photo.height):
            long_side = max(photo.width, photo.height)
            short_side = min(photo.width, photo.height)
            ratio = long_side / short_side if short_side else 0
            # Phone screen ratios: ~1.78 (16:9), ~2.05 (18:9), ~2.16 (19.5:9)
            if 1.7 < ratio < 2.3:
                # Common screenshot widths
                if short_side in (720, 750, 828, 1080, 1125, 1170, 1284, 1440):
                    tags.append("Screenshot")

    except Exception as exc:
        logger.debug("Quality type detection failed for %s: %s", photo.file_path, exc)
    return tags


def _bg_analyze():
    from models.object_detector import ObjectDetector
    from models.scene_classifier import SceneClassifier
    from models.config import DEFAULT_CONFIDENCE, SCENE_CONFIDENCE
    from utils.tagger import _AI_CATEGORIES

    _set(running=True, operation="analyze", op_label="AI Analysis",
         done=0, total=0, message="Loading AI models…")

    session = get_session()
    try:
        # Only treat a photo as already-analyzed when it has Objects or Scenes
        # tags — PhotoType tags are also in _AI_CATEGORIES but are written during
        # import via EXIF, so they must not block AI analysis here.
        tagged_ids = {
            r[0] for r in session.query(Tag.photo_id)
            .filter(Tag.category.in_(["Objects", "Scenes"])).distinct()
        }
        photos = session.query(Photo).filter(~Photo.id.in_(tagged_ids)).all()

        # Honour --test N limit (SG_TEST_LIMIT env var set by server.py)
        _test_limit = int(os.environ.get("SG_TEST_LIMIT", 0) or 0)
        if _test_limit > 0:
            photos = photos[:_test_limit]
            logger.info("TEST MODE: limiting analyze to %d photos", _test_limit)

        total  = len(photos)
        _set(total=total, message=f"Tagging {total} photos…")

        detector   = ObjectDetector(confidence=DEFAULT_CONFIDENCE)
        classifier = SceneClassifier(confidence=SCENE_CONFIDENCE)

        for i, photo in enumerate(photos):
            try:
                dets = detector.detect(photo.file_path)
                for det in dets:
                    # "person" detections are handled by face processing which
                    # creates named People tags — skip the generic Objects tag
                    # but always store the bbox row for the overlay canvas.
                    if det["label"].lower() != "person":
                        session.add(Tag(photo_id=photo.id, label=det["label"],
                                       category="Objects", confidence=det["confidence"],
                                       is_manual=False))
                    bx, by, bw, bh = det["bbox"]
                    session.add(ObjectDetection(
                        photo_id=photo.id, label=det["label"],
                        confidence=det["confidence"],
                        bbox_x=bx, bbox_y=by, bbox_w=bw, bbox_h=bh,
                    ))
                for s in classifier.classify(photo.file_path):
                    session.add(Tag(photo_id=photo.id, label=s["label"],
                                   category="Scenes", confidence=s["confidence"],
                                   is_manual=False))
                pt = detector.infer_photo_type(dets)
                if pt:
                    session.add(Tag(photo_id=photo.id, label=pt,
                                   category="PhotoType", is_manual=False))
                # Additional quality/type detection
                extra_types = _detect_photo_quality_type(photo)
                for qt in extra_types:
                    session.add(Tag(photo_id=photo.id, label=qt,
                                   category="PhotoType", is_manual=False))
                session.commit()
            except Exception as exc:
                logger.warning("Tag error photo %d: %s", photo.id, exc)
                session.rollback()

            _set(done=i + 1, message=f"Tagged {i+1}/{total}",
                 current_file=Path(photo.file_path).name)
    finally:
        session.close()

    _set(running=False, operation="analyze_done",
         message="AI analysis complete", current_file="")

    # Auto-trigger face processing if needed
    _auto_faces_if_needed()


def _auto_faces_if_needed():
    session = get_session()
    try:
        done_ids = {r[0] for r in session.query(PhotoPerson.photo_id).distinct()}
        # Check ObjectDetection rows (bbox store) for unprocessed person detections.
        # We no longer write an Objects tag for "person", so this is the authoritative
        # source for whether a photo contains a person needing face recognition.
        needs = (
            session.query(ObjectDetection.photo_id)
            .filter(ObjectDetection.label == "person")
            .filter(~ObjectDetection.photo_id.in_(done_ids))
            .first()
        )
    finally:
        session.close()
    if needs:
        _bg_faces()


# ---------------------------------------------------------------------------
# Face processing
# ---------------------------------------------------------------------------

@app.post("/api/faces")
def start_faces(background_tasks: BackgroundTasks):
    with _op_lock:
        if _op["running"]:
            return {"error": "Operation already running"}
    background_tasks.add_task(_bg_faces)
    return {"ok": True}


def _bg_faces():
    """Detect, embed and cluster faces — incremental: matches new faces against
    existing Person records so re-importing never creates duplicate persons."""
    _set(running=True, operation="faces", op_label="Face Processing",
         done=0, total=0, message="Starting face processing…")
    try:
        import numpy as np
        from models.face_recognizer import FaceRecognizer, cluster_embeddings
        from utils.face_processor import _save_face_thumbnail

        from models.config import FACE_MATCH_THRESHOLD
        MATCH_THRESHOLD = FACE_MATCH_THRESHOLD

        session = get_session()
        try:
            done_ids = {r[0] for r in session.query(PhotoPerson.photo_id).distinct()}
            photos   = session.query(Photo).filter(~Photo.id.in_(done_ids)).all()

            # Honour --test N limit (SG_TEST_LIMIT env var set by server.py)
            _test_limit = int(os.environ.get("SG_TEST_LIMIT", 0) or 0)
            if _test_limit > 0:
                photos = photos[:_test_limit]
                logger.info("TEST MODE: limiting face processing to %d photos", _test_limit)

            total    = len(photos)
            _set(total=total, message=f"Detecting faces in {total} photos…")

            recognizer = FaceRecognizer()
            all_faces: list = []   # (photo_id, bbox, embedding, confidence)

            for i, photo in enumerate(photos):
                try:
                    faces = recognizer.detect_and_embed(photo.file_path)
                    for f in faces:
                        all_faces.append((photo.id, f["bbox"], f["embedding"], f["confidence"]))
                except Exception as exc:
                    logger.warning("Face detect error %s: %s", photo.file_path, exc)
                _set(done=i + 1, message=f"Detecting faces {i+1}/{total}",
                     current_file=Path(photo.file_path).name)

            if not all_faces:
                _set(running=False, operation="faces_done", message="No faces found")
                return

            _set(message="Matching against existing people…")

            # ── Load existing person embeddings (normalised for cosine similarity) ──
            existing_persons = session.query(Person).filter(
                Person.embedding_vector.isnot(None)
            ).all()
            existing_embs: dict[int, np.ndarray] = {}   # person_id → unit vector
            for p in existing_persons:
                try:
                    emb = np.frombuffer(p.embedding_vector, dtype=np.float32).copy()
                    norm = np.linalg.norm(emb)
                    if norm > 0:
                        existing_embs[p.id] = emb / norm
                except Exception:
                    pass

            # ── Split into matched (existing person) and unmatched (new) ──
            matched:   list[tuple] = []   # (face_data, person_id)
            unmatched: list[tuple] = []   # face_data

            # Track best new face seen for each existing person (thumbnail refresh)
            best_for_existing: dict[int, tuple] = {}   # person_id → (photo_id, bbox, conf)

            for face_data in all_faces:
                photo_id, bbox, embedding, confidence = face_data
                norm = np.linalg.norm(embedding)
                emb_norm = embedding / norm if norm > 0 else embedding

                if existing_embs:
                    best_dist, best_pid = min(
                        ((1.0 - float(np.dot(emb_norm, pem)), pid)
                         for pid, pem in existing_embs.items()),
                        key=lambda t: t[0],
                    )
                    if best_dist < MATCH_THRESHOLD:
                        matched.append((face_data, best_pid))
                        prev = best_for_existing.get(best_pid)
                        if prev is None or confidence > prev[2]:
                            best_for_existing[best_pid] = (photo_id, bbox, confidence)
                        continue
                unmatched.append(face_data)

            # ── Write matched faces to existing persons ──
            person_cache: dict[int, Person] = {}
            # Track (photo_id, person_name) already written to avoid duplicate Tags
            people_tagged: set[tuple] = set()
            matched_count = 0
            for face_data, person_id in matched:
                photo_id, bbox, embedding, confidence = face_data
                if person_id not in person_cache:
                    person_cache[person_id] = session.get(Person, person_id)
                person = person_cache[person_id]
                if person is None:
                    unmatched.append(face_data)
                    continue
                x, y, w, h = bbox
                session.add(PhotoPerson(
                    photo_id=photo_id, person_id=person.id,
                    confidence=confidence,
                    bbox_x=x, bbox_y=y, bbox_w=w, bbox_h=h,
                ))
                # Only write one People tag per (photo, person) — a person appearing
                # multiple times in one photo still only gets one tag entry.
                tag_key = (photo_id, person.name)
                if tag_key not in people_tagged:
                    session.add(Tag(
                        photo_id=photo_id, label=person.name,
                        category="People", confidence=confidence, is_manual=False,
                    ))
                    people_tagged.add(tag_key)
                matched_count += 1

            # Update thumbnails for existing persons where we found a better face
            for person_id, face_data in best_for_existing.items():
                if person_id not in person_cache:
                    person_cache[person_id] = session.get(Person, person_id)
                person = person_cache.get(person_id)
                if person:
                    _save_face_thumbnail(session, person, face_data)

            # ── Cluster unmatched faces into new persons ──
            new_count = 0
            if unmatched:
                _set(message=f"Clustering {len(unmatched)} new face(s)…")
                labels = cluster_embeddings([f[2] for f in unmatched])

                # Best face per new cluster
                best_new: dict[int, tuple] = {}
                for face_data, lbl in zip(unmatched, labels):
                    pid2, bbox2, emb2, conf2 = face_data
                    if lbl not in best_new or conf2 > best_new[lbl][2]:
                        best_new[lbl] = (pid2, bbox2, conf2)

                existing_count = session.query(Person).count()
                cluster_to_person: dict[int, Person] = {}
                person_index = existing_count + 1

                for face_data, cluster_label in zip(unmatched, labels):
                    photo_id, bbox, embedding, confidence = face_data
                    if cluster_label not in cluster_to_person:
                        cluster_embs = [
                            unmatched[i][2] for i, lbl in enumerate(labels)
                            if lbl == cluster_label
                        ]
                        mean_emb = np.mean(np.stack(cluster_embs), axis=0)
                        person   = Person(
                            name=f"Person {person_index}",
                            embedding_vector=mean_emb.tobytes(),
                        )
                        session.add(person)
                        session.flush()
                        _save_face_thumbnail(session, person, best_new[cluster_label])
                        cluster_to_person[cluster_label] = person
                        person_index += 1
                        new_count += 1

                    person = cluster_to_person[cluster_label]
                    x, y, w, h = bbox
                    session.add(PhotoPerson(
                        photo_id=photo_id, person_id=person.id,
                        confidence=confidence,
                        bbox_x=x, bbox_y=y, bbox_w=w, bbox_h=h,
                    ))
                    tag_key = (photo_id, person.name)
                    if tag_key not in people_tagged:
                        session.add(Tag(
                            photo_id=photo_id, label=person.name,
                            category="People", confidence=confidence, is_manual=False,
                        ))
                        people_tagged.add(tag_key)

            session.commit()
            total_persons = session.query(Person).count()
        finally:
            session.close()

        parts = []
        if new_count:       parts.append(f"{new_count} new person(s)")
        if matched_count:   parts.append(f"{matched_count} face(s) matched to existing")
        _set(running=False, operation="faces_done",
             message=f"Done — {', '.join(parts) or 'no faces found'} ({total_persons} total)",
             current_file="")

    except Exception as exc:
        logger.exception("Face processing failed")
        _set(running=False, operation="error", message=str(exc))
