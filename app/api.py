"""SuperGallery FastAPI backend — serves all data and the web frontend."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from pathlib import Path

# Repo root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Suppress PIL noise before any imports
logging.getLogger("PIL").setLevel(logging.WARNING)

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func

from database.db import get_session, init_db
from database.models import (
    Location, ObjectDetection, Photo, PhotoPerson, Person, Tag,
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
    "done": 0, "total": 0, "message": "Ready",
}
_op_lock = threading.Lock()


def _set(**kw):
    with _op_lock:
        _op.update(kw)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup():
    init_db()


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
    }


@app.get("/api/photos")
def list_photos(
    sort: str    = "month_desc",
    filters: str = "{}",
    page: int    = 1,
    page_size: int = 120,
):
    session = get_session()
    try:
        f = json.loads(filters)
        photos = search_photos(session, f) if any(f.values()) else session.query(Photo).all()

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
                if 0.45 < sim < 0.72:
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


@app.post("/api/import")
def start_import(body: _ImportReq, background_tasks: BackgroundTasks):
    with _op_lock:
        if _op["running"]:
            return {"error": "Operation already running"}
    background_tasks.add_task(_bg_import, body.folder)
    return {"ok": True}


def _bg_import(folder: str):
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


def _bg_analyze():
    from models.object_detector import ObjectDetector
    from models.scene_classifier import SceneClassifier
    from models.config import DEFAULT_CONFIDENCE
    from utils.tagger import _AI_CATEGORIES

    _set(running=True, operation="analyze", op_label="AI Analysis",
         done=0, total=0, message="Loading AI models…")

    session = get_session()
    try:
        tagged_ids = {
            r[0] for r in session.query(Tag.photo_id)
            .filter(Tag.category.in_(_AI_CATEGORIES)).distinct()
        }
        photos = session.query(Photo).filter(~Photo.id.in_(tagged_ids)).all()
        total  = len(photos)
        _set(total=total, message=f"Tagging {total} photos…")

        detector   = ObjectDetector(confidence=DEFAULT_CONFIDENCE)
        classifier = SceneClassifier(confidence=DEFAULT_CONFIDENCE)

        for i, photo in enumerate(photos):
            try:
                dets = detector.detect(photo.file_path)
                for det in dets:
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
                session.commit()
            except Exception as exc:
                logger.warning("Tag error photo %d: %s", photo.id, exc)
                session.rollback()

            _set(done=i + 1, message=f"Tagged {i+1}/{total}")
    finally:
        session.close()

    _set(running=False, operation="analyze_done",
         message="AI analysis complete")

    # Auto-trigger face processing if needed
    _auto_faces_if_needed()


def _auto_faces_if_needed():
    session = get_session()
    try:
        done_ids = {r[0] for r in session.query(PhotoPerson.photo_id).distinct()}
        needs = (
            session.query(Tag.photo_id)
            .filter(Tag.category == "Objects", Tag.label == "person")
            .filter(~Tag.photo_id.in_(done_ids))
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
    _set(running=True, operation="faces", op_label="Face Processing",
         done=0, total=0, message="Starting face processing…")
    try:
        import numpy as np
        from models.face_recognizer import FaceRecognizer, cluster_embeddings
        from utils.face_processor import _save_face_thumbnail

        session = get_session()
        try:
            done_ids = {r[0] for r in session.query(PhotoPerson.photo_id).distinct()}
            photos   = session.query(Photo).filter(~Photo.id.in_(done_ids)).all()
            total    = len(photos)
            _set(total=total, message=f"Detecting faces in {total} photos…")

            recognizer = FaceRecognizer()
            all_faces: list = []

            for i, photo in enumerate(photos):
                try:
                    faces = recognizer.detect_and_embed(photo.file_path)
                    for f in faces:
                        all_faces.append((photo.id, f["bbox"], f["embedding"], f["confidence"]))
                except Exception as exc:
                    logger.warning("Face detect error %s: %s", photo.file_path, exc)
                _set(done=i + 1, message=f"Detecting faces {i+1}/{total}")

            if not all_faces:
                _set(running=False, operation="faces_done",
                     message="No faces found")
                return

            _set(message="Clustering faces…")
            labels = cluster_embeddings([f[2] for f in all_faces])

            # Best face per cluster (for thumbnail)
            best: dict = {}
            for (pid, bbox, emb, conf), lbl in zip(all_faces, labels):
                if lbl not in best or conf > best[lbl][2]:
                    best[lbl] = (pid, bbox, conf)

            existing_count  = session.query(Person).count()
            cluster_to_person: dict = {}
            person_index    = existing_count + 1

            for face_data, cluster_label in zip(all_faces, labels):
                photo_id, bbox, embedding, confidence = face_data
                if cluster_label not in cluster_to_person:
                    cluster_embs = [
                        all_faces[i][2] for i, lbl in enumerate(labels)
                        if lbl == cluster_label
                    ]
                    mean_emb = np.mean(np.stack(cluster_embs), axis=0)
                    person   = Person(
                        name=f"Person {person_index}",
                        embedding_vector=mean_emb.tobytes(),
                    )
                    session.add(person)
                    session.flush()
                    _save_face_thumbnail(session, person, best[cluster_label])
                    cluster_to_person[cluster_label] = person
                    person_index += 1

                person = cluster_to_person[cluster_label]
                x, y, w, h = bbox
                session.add(PhotoPerson(
                    photo_id=photo_id, person_id=person.id,
                    confidence=confidence,
                    bbox_x=x, bbox_y=y, bbox_w=w, bbox_h=h,
                ))
                session.add(Tag(
                    photo_id=photo_id, label=person.name,
                    category="People", confidence=confidence, is_manual=False,
                ))

            session.commit()
            count = len(cluster_to_person)
        finally:
            session.close()

        _set(running=False, operation="faces_done",
             message=f"Done — {count} person(s) identified")

    except Exception as exc:
        logger.exception("Face processing failed")
        _set(running=False, operation="error", message=str(exc))
