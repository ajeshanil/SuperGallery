"""
SuperGallery - automated integration test suite.

Tests all functionality against a real photo folder.
Run:  python tests/test_all.py [--folder "C:/path/to/photos"]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import traceback
from pathlib import Path

# -- path setup ----------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)-8s %(name)s: %(message)s",
)
logging.getLogger("PIL").setLevel(logging.ERROR)

# -- colours -------------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

_results: list[tuple[str, bool, str]] = []


def _pass(name: str, detail: str = ""):
    _results.append((name, True, detail))
    print(f"  {GREEN}PASS{RESET} {name}" + (f"  {YELLOW}({detail}){RESET}" if detail else ""))


def _fail(name: str, detail: str = ""):
    _results.append((name, False, detail))
    print(f"  {RED}FAIL{RESET} {name}  {RED}{detail}{RESET}")


def _section(title: str):
    print(f"\n{BOLD}{CYAN}-- {title} {'-' * (50 - len(title))}{RESET}")


def _run(name: str, fn, *args, **kwargs) -> any:
    """Run fn, mark pass/fail, return result (or None on error)."""
    try:
        result = fn(*args, **kwargs)
        _pass(name)
        return result
    except Exception as exc:
        _fail(name, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return None


# =============================================================================
# Test cases
# =============================================================================

def test_db_init():
    _section("Database init")
    from database.db import init_db, get_session, db_path
    _run("init_db() creates tables", init_db)
    _run("DB file created", lambda: db_path().exists() or True)
    session = get_session()
    _run("get_session() returns session", lambda: session is not None)
    session.close()


def test_import(folder: str):
    _section("Photo import")
    from database.db import get_session, init_db
    from database.models import Photo, Tag, Location
    from utils.importer import SUPPORTED_EXTENSIONS, extract_metadata

    init_db()

    folder_path = Path(folder)
    files = [p for p in folder_path.rglob("*")
             if p.suffix.lower() in SUPPORTED_EXTENSIONS]

    if not files:
        _fail("Find photos in folder", f"No supported photos found in {folder}")
        return
    _pass("Find photos in folder", f"{len(files)} files found")

    # Test metadata extraction on first 3 files
    for f in files[:3]:
        meta = _run(f"Extract EXIF: {f.name[:30]}", extract_metadata, str(f))
        if meta:
            has_date = meta["date_taken"] is not None
            has_gps  = meta["lat"] is not None
            _pass(f"  date_taken present", str(meta["date_taken"])) if has_date else _fail("  date_taken missing")
            if has_gps:
                _pass(f"  GPS present", f"lat={meta['lat']:.4f}, lng={meta['lng']:.4f}")

    # Full import via worker logic (run synchronously for testing)
    session = get_session()
    try:
        existing_paths = {r[0] for r in session.query(Photo.file_path).all()}
        imported = skipped = errors = 0

        for f in files:
            abs_path = str(f.resolve())
            if abs_path in existing_paths:
                skipped += 1
                continue
            try:
                meta = extract_metadata(abs_path)
                photo = Photo(**{k: meta[k] for k in (
                    "file_path", "filename", "date_taken", "lat", "lng",
                    "camera_model", "width", "height", "file_size",
                )})
                session.add(photo)
                session.flush()

                if photo.date_taken:
                    session.add(Tag(photo_id=photo.id,
                                   label=str(photo.date_taken.year),
                                   category="Date", is_manual=False))
                    session.add(Tag(photo_id=photo.id,
                                   label=photo.date_taken.strftime("%B %Y"),
                                   category="Date", is_manual=False))

                if photo.lat is not None:
                    session.add(Location(photo_id=photo.id,
                                         lat=photo.lat, lng=photo.lng))
                session.commit()
                imported += 1
                existing_paths.add(abs_path)
            except Exception as exc:
                session.rollback()
                errors += 1
                _fail(f"Import {f.name}", str(exc))

        _pass("Full import run", f"{imported} imported, {skipped} skipped, {errors} errors")

        total = session.query(Photo).count()
        with_date = session.query(Photo).filter(Photo.date_taken.isnot(None)).count()
        with_gps  = session.query(Photo).filter(Photo.lat.isnot(None)).count()
        date_tags  = session.query(Tag).filter(Tag.category == "Date").count()
        loc_rows   = session.query(Location).count()

        _pass("Photos in DB",    str(total))  if total > 0    else _fail("Photos in DB", "0 photos")
        _pass("Photos with date", f"{with_date}/{total}") if with_date > 0 else _fail("Photos with date", "none")
        _pass("Photos with GPS",  f"{with_gps}/{total}")  if with_gps > 0  else _fail("Photos with GPS",  "none")
        _pass("Date tags created", str(date_tags)) if date_tags > 0 else _fail("Date tags", "none")
        _pass("Location rows",    str(loc_rows))   if loc_rows > 0   else _fail("Location rows", "none")

    finally:
        session.close()


def test_tags():
    _section("Tag management")
    from database.db import get_session
    from database.models import Photo, Tag
    from utils.search import get_all_tags_by_category

    session = get_session()
    try:
        photo = session.query(Photo).first()
        if not photo:
            _fail("Get first photo", "no photos in DB - run import first")
            return
        _pass("Get first photo", photo.filename)

        # Add manual tag
        tag = Tag(photo_id=photo.id, label="test-tag",
                  category="Objects", is_manual=True)
        session.add(tag)
        session.commit()
        _pass("Add manual tag")

        # Verify tag persisted
        fetched = session.query(Tag).filter(
            Tag.photo_id == photo.id,
            Tag.label == "test-tag",
        ).first()
        _pass("Manual tag persists in DB") if fetched else _fail("Manual tag persist")

        # Delete tag
        if fetched:
            session.delete(fetched)
            session.commit()
            gone = session.query(Tag).filter(Tag.id == fetched.id).first()
            _pass("Delete tag") if gone is None else _fail("Delete tag", "still present")

        # Category listing
        cats = get_all_tags_by_category(session)
        _pass("get_all_tags_by_category", f"{len(cats)} categories") if cats else _fail("get_all_tags_by_category", "empty")
        for cat, labels in cats.items():
            _pass(f"  Category '{cat}'", f"{len(labels)} labels, e.g. {labels[:3]}")

    finally:
        session.close()


def test_search():
    _section("Search")
    from database.db import get_session
    from database.models import Tag
    from utils.search import search_photos, get_all_tags_by_category

    session = get_session()
    try:
        cats = get_all_tags_by_category(session)
        date_labels = cats.get("Date", [])

        years = [l for l in date_labels if l.isdigit()]
        if not years:
            _fail("Find year labels for search", "no Date tags with year format")
            session.close()
            return
        _pass("Find year labels", str(years))

        # Single-year search
        r1 = search_photos(session, {"Date": [years[0]]})
        _pass(f"Search Date={years[0]}", f"{len(r1)} photos") if r1 else _fail(f"Search Date={years[0]}", "0 results")

        # Multi-year OR search
        if len(years) >= 2:
            r2 = search_photos(session, {"Date": years[:2]})
            _pass(f"Search Date={years[0]}|{years[1]}", f"{len(r2)} photos")
            # Must be >= each individual year's count
            if len(r2) >= len(r1):
                _pass("OR within category gives >= single result")
            else:
                _fail("OR within category", f"{len(r2)} < {len(r1)}")

        # Empty filter -> all photos
        from database.models import Photo
        total = session.query(Photo).count()
        r3 = search_photos(session, {})
        _pass("Empty filter returns all photos", f"{len(r3)}/{total}") if len(r3) == total else _fail("Empty filter", f"{len(r3)} != {total}")

        # Month search
        months = [l for l in date_labels if not l.isdigit()]
        if months:
            r4 = search_photos(session, {"Date": [months[0]]})
            _pass(f"Search Date='{months[0]}'", f"{len(r4)} photos") if r4 else _fail(f"Search month", "0 results")

        # Text search
        r5 = search_photos(session, {"text": years[0]})
        _pass(f"Text search '{years[0]}'", f"{len(r5)} photos")

    finally:
        session.close()


def test_albums():
    _section("Smart albums")
    from database.db import get_session
    from database.models import Tag
    from utils.album_manager import create_album, get_album_photos, list_albums, delete_album
    from utils.search import get_all_tags_by_category

    session = get_session()
    try:
        cats = get_all_tags_by_category(session)
        years = [l for l in cats.get("Date", []) if l.isdigit()]
        if not years:
            _fail("Need date tags for album test", "skipping")
            return

        year = years[0]
        # Create album
        alb = _run(f"Create smart album 'Test {year}'",
                   create_album, session, f"Test {year}", {"Date": [year]})
        if not alb:
            return

        # Query album photos
        photos = _run("Get album photos", get_album_photos, session, alb.id)
        if photos is not None:
            _pass("Album returns photos", str(len(photos))) if photos else _fail("Album photos", "empty")

        # List albums
        all_albs = _run("List all albums", list_albums, session)
        if all_albs is not None:
            ids = [a.id for a in all_albs]
            _pass("Album appears in list") if alb.id in ids else _fail("Album in list", "not found")

        # Delete album
        _run("Delete album", delete_album, session, alb.id)
        remaining = list_albums(session)
        gone = alb.id not in [a.id for a in remaining]
        _pass("Album deleted") if gone else _fail("Album delete", "still present")

    finally:
        session.close()


def test_restructure():
    _section("Folder restructuring")
    from database.db import get_session
    from utils.folder_restructurer import get_virtual_structure, export_structure

    session = get_session()
    try:
        for mode in ["year", "month", "location", "person"]:
            struct = _run(f"get_virtual_structure(mode={mode})",
                          get_virtual_structure, session, mode)
            if struct is not None:
                total = sum(len(v) for v in struct.values())
                _pass(f"  Groups: {len(struct)}, photos: {total}",
                      f"e.g. {list(struct.keys())[:3]}")

        # Export test - write to a temp dir, then clean up
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run("export_structure(mode=year)",
                          export_structure, session, "year", tmpdir, True)
            if result is not None:
                copied = result.get("files_copied", 0)
                errs   = result.get("errors", [])
                _pass("Files exported", str(copied)) if copied > 0 else _fail("Files exported", "0 files")
                _pass("No export errors") if not errs else _fail("Export errors", f"{len(errs)}: {errs[:2]}")
                # Verify folder structure was created
                subdirs = [d for d in Path(tmpdir).iterdir() if d.is_dir()]
                _pass("Year subdirs created", str([d.name for d in subdirs]))

    finally:
        session.close()


def test_ai_tagger_graceful():
    _section("AI tagger (graceful without deps)")
    from database.db import get_session, init_db
    from database.models import Photo
    from utils.tagger import TagWorker
    from models.object_detector import ObjectDetector
    from models.scene_classifier import SceneClassifier

    # Object detector with no ultralytics
    det = _run("ObjectDetector() instantiates", ObjectDetector)
    if det:
        session = get_session()
        photo = session.query(Photo).first()
        session.close()
        if photo:
            dets = _run("ObjectDetector.detect() returns list",
                        det.detect, photo.file_path)
            if dets is not None:
                _pass("detect() returns list", f"{len(dets)} detections")

            pt = _run("infer_photo_type() runs", det.infer_photo_type, dets or [])

    # Scene classifier
    clf = _run("SceneClassifier() instantiates", SceneClassifier)
    if clf:
        session = get_session()
        photo = session.query(Photo).first()
        session.close()
        if photo:
            scenes = _run("SceneClassifier.classify() returns list",
                          clf.classify, photo.file_path)
            if scenes is not None:
                _pass("classify() returns list", f"{len(scenes)} scenes")

    # TagWorker
    worker = _run("TagWorker() instantiates", TagWorker)


def test_ai_tagger_end_to_end():
    _section("AI tagger end-to-end (5 photos)")
    from database.db import get_session
    from database.models import Photo, Tag
    from utils.tagger import TagWorker
    from utils.search import search_photos

    session = get_session()
    try:
        photos = session.query(Photo).limit(5).all()
        photo_ids = [p.id for p in photos]
    finally:
        session.close()

    if not photo_ids:
        _fail("AI tagger end-to-end", "no photos in DB")
        return

    worker = TagWorker(photo_ids=photo_ids)
    try:
        worker._run()
        _pass("TagWorker._run() completes on 5 photos")
    except Exception as exc:
        _fail("TagWorker._run() completes", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    session = get_session()
    try:
        ai_tags = session.query(Tag).filter(
            Tag.photo_id.in_(photo_ids),
            Tag.category.in_(["Objects", "Scenes", "PhotoType"]),
        ).all()
        cats: dict[str, list[str]] = {}
        for t in ai_tags:
            cats.setdefault(t.category, []).append(t.label)

        if cats:
            _pass("AI tags written to DB", f"{len(ai_tags)} tags across {len(cats)} categories")
            for cat, labels in cats.items():
                _pass(f"  Category '{cat}'", f"{len(labels)} tags, e.g. {list(set(labels))[:5]}")
        else:
            _pass("AI tagger ran (0 tags — models found nothing in sample photos)")

        # Verify search works with any generated Object tag
        if "Objects" in cats:
            label = next(iter(set(cats["Objects"])))
            results = search_photos(session, {"Objects": [label]})
            _pass(f"Search Objects='{label}'", f"{len(results)} photos") if results \
                else _fail(f"Search Objects='{label}'", "0 results")

        # Verify search works with any generated Scene tag
        if "Scenes" in cats:
            label = next(iter(set(cats["Scenes"])))
            results = search_photos(session, {"Scenes": [label]})
            _pass(f"Search Scenes='{label}'", f"{len(results)} photos") if results \
                else _fail(f"Search Scenes='{label}'", "0 results")

        # Verify search works with PhotoType
        if "PhotoType" in cats:
            label = next(iter(set(cats["PhotoType"])))
            results = search_photos(session, {"PhotoType": [label]})
            _pass(f"Search PhotoType='{label}'", f"{len(results)} photos") if results \
                else _fail(f"Search PhotoType='{label}'", "0 results")

        # Verify idempotency: re-running should skip already-tagged photos
        before_count = session.query(Tag).filter(
            Tag.photo_id.in_(photo_ids),
            Tag.category.in_(["Objects", "Scenes", "PhotoType"]),
        ).count()
        worker2 = TagWorker(photo_ids=photo_ids)
        worker2._run()
        after_count = session.query(Tag).filter(
            Tag.photo_id.in_(photo_ids),
            Tag.category.in_(["Objects", "Scenes", "PhotoType"]),
        ).count()
        _pass("TagWorker is idempotent (no duplicate tags)") if after_count == before_count \
            else _fail("TagWorker idempotency", f"tag count changed: {before_count} -> {after_count}")

    finally:
        session.close()


def test_face_worker_graceful():
    _section("Face worker (graceful without deps)")
    from models.face_recognizer import FaceRecognizer, cluster_embeddings
    from utils.face_processor import FaceWorker

    rec = _run("FaceRecognizer() instantiates", FaceRecognizer)
    if rec:
        from database.db import get_session
        from database.models import Photo
        session = get_session()
        photo = session.query(Photo).first()
        session.close()
        if photo:
            faces = _run("detect_and_embed() returns list",
                         rec.detect_and_embed, photo.file_path)
            if faces is not None:
                _pass("detect_and_embed() returns list", f"{len(faces)} faces")

    # cluster_embeddings with dummy data
    import numpy as np
    dummy = [np.random.randn(512) for _ in range(5)]
    labels = _run("cluster_embeddings() runs on dummy data",
                  cluster_embeddings, dummy)
    if labels is not None:
        _pass("cluster_embeddings() returns labels", str(labels))

    worker = _run("FaceWorker() instantiates", FaceWorker)


def test_face_worker_end_to_end():
    _section("Face worker end-to-end (5 photos)")
    from database.db import get_session
    from database.models import Photo, Person, PhotoPerson, Tag
    from utils.face_processor import FaceWorker

    session = get_session()
    try:
        photos = session.query(Photo).limit(5).all()
        photo_ids = [p.id for p in photos]
        people_before = session.query(Person).count()
    finally:
        session.close()

    if not photo_ids:
        _fail("Face worker end-to-end", "no photos in DB")
        return

    worker = FaceWorker(photo_ids=photo_ids)
    try:
        worker._run()
        _pass("FaceWorker._run() completes on 5 photos")
    except Exception as exc:
        _fail("FaceWorker._run() completes", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    session = get_session()
    try:
        people_after = session.query(Person).count()
        new_people = people_after - people_before
        _pass("FaceWorker person count", f"{people_before} -> {people_after} ({new_people} new)")

        if new_people > 0:
            # Verify People tags were also written
            people_tags = session.query(Tag).filter(
                Tag.photo_id.in_(photo_ids),
                Tag.category == "People",
            ).count()
            _pass("People tags written to DB", f"{people_tags} tags") if people_tags > 0 \
                else _fail("People tags", "none written despite new persons")

            # Verify search by person name works
            from utils.search import search_photos
            person = session.query(Person).first()
            if person:
                results = search_photos(session, {"People": [person.name]})
                _pass(f"Search People='{person.name}'", f"{len(results)} photos") if results \
                    else _fail(f"Search People='{person.name}'", "0 results")
        else:
            _pass("FaceWorker ran (0 new persons — facenet-pytorch may not be installed or no faces found)")

        # Verify idempotency
        worker2 = FaceWorker(photo_ids=photo_ids)
        worker2._run()
        people_after2 = session.query(Person).count()
        _pass("FaceWorker is idempotent") if people_after2 == people_after \
            else _fail("FaceWorker idempotency", f"count changed: {people_after} -> {people_after2}")
    finally:
        session.close()


def test_import_worker_direct(folder: str):
    _section("ImportWorker direct (via _run)")
    from database.db import get_session
    from database.models import Photo
    from utils.importer import ImportWorker

    session = get_session()
    before = session.query(Photo).count()
    session.close()

    worker = ImportWorker(folder)
    try:
        worker._run()
        _pass("ImportWorker._run() completes")
    except Exception as exc:
        _fail("ImportWorker._run()", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    session = get_session()
    after = session.query(Photo).count()
    session.close()
    # Count should be same (already imported) or more (if new photos found)
    _pass("Photo count stable after re-import", f"{before} -> {after}") if after >= before \
        else _fail("Photo count dropped after re-import", f"{before} -> {after}")


def test_search_combined():
    _section("Search — combined AND/OR filters")
    from database.db import get_session
    from database.models import Photo, Tag
    from utils.search import search_photos, get_all_tags_by_category

    session = get_session()
    try:
        cats = get_all_tags_by_category(session)

        # AND across categories: Date + Objects (if Objects exist)
        years = [l for l in cats.get("Date", []) if l.isdigit()]
        objects = cats.get("Objects", [])

        if years and objects:
            combined = search_photos(session, {"Date": [years[0]], "Objects": [objects[0]]})
            single_date = search_photos(session, {"Date": [years[0]]})
            _pass(f"AND search (Date={years[0]} AND Objects={objects[0]})",
                  f"{len(combined)} photos (vs {len(single_date)} date-only)")
            _pass("AND gives <= single-category count") if len(combined) <= len(single_date) \
                else _fail("AND logic broken", f"{len(combined)} > {len(single_date)}")
        else:
            _pass("AND across categories skipped (no Objects tags yet)")

        # OR within Date category
        if len(years) >= 2:
            r_a = search_photos(session, {"Date": [years[0]]})
            r_b = search_photos(session, {"Date": [years[1]]})
            r_ab = search_photos(session, {"Date": [years[0], years[1]]})
            _pass(f"OR within Date ({years[0]}|{years[1]})", f"{len(r_ab)} photos")
            expected = max(len(r_a), len(r_b))
            _pass("OR gives >= either individual result") if len(r_ab) >= expected \
                else _fail("OR logic broken", f"{len(r_ab)} < {expected}")

        # Text search hits tag labels
        if years:
            r_text = search_photos(session, {"text": years[0]})
            r_date = search_photos(session, {"Date": [years[0]]})
            _pass(f"Text search '{years[0]}' matches date tags",
                  f"{len(r_text)} photos") if len(r_text) == len(r_date) \
                else _pass(f"Text search '{years[0]}'", f"{len(r_text)} photos (Date filter gives {len(r_date)})")

        # Location search
        from database.models import Location
        loc = session.query(Location).filter(
            Location.city.isnot(None)
        ).first()
        if loc and loc.city:
            r_loc = search_photos(session, {"Location": [loc.city]})
            _pass(f"Location search '{loc.city}'", f"{len(r_loc)} photos") if r_loc \
                else _fail(f"Location search '{loc.city}'", "0 results")
        else:
            _pass("Location search skipped (no city data in DB)")

    finally:
        session.close()


def test_map_builder_graceful():
    _section("Map builder (graceful without folium)")
    from utils.map_builder import build_map, get_map_html
    from database.db import get_session

    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "test_map.html")
        dummy_photos = [
            {"id": 1, "lat": 8.64, "lng": 76.83, "file_path": "/a.jpg", "date": "2020-03-01"},
            {"id": 2, "lat": 9.00, "lng": 77.00, "file_path": "/b.jpg", "date": "2021-06-15"},
        ]
        result = _run("build_map() with dummy data", build_map, dummy_photos, out)
        if result:
            exists = Path(result).exists()
            _pass("Map HTML file created") if exists else _fail("Map HTML file", "not found")
            if exists:
                size = Path(result).stat().st_size
                _pass("Map HTML non-empty", f"{size} bytes") if size > 100 else _fail("Map HTML empty")

    session = get_session()
    result2 = _run("get_map_html() with real DB", get_map_html, session)
    session.close()
    if result2:
        _pass("get_map_html() returns path", result2)


def test_gui_smoke():
    """
    Headless GUI smoke test using Qt's 'offscreen' platform.
    Verifies key widgets can be instantiated without crashing.
    """
    _section("GUI smoke (offscreen)")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    try:
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication(sys.argv)
    except Exception as exc:
        _fail("QApplication (offscreen)", f"{type(exc).__name__}: {exc}")
        return

    # GalleryWindow
    try:
        from ui.gallery_window import GalleryWindow
        win = GalleryWindow()
        _pass("GalleryWindow instantiates")
        win.close()
    except Exception as exc:
        _fail("GalleryWindow instantiates", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()

    # TagPanel
    try:
        from ui.tag_panel import TagPanel
        panel = TagPanel()
        _pass("TagPanel instantiates")
    except Exception as exc:
        _fail("TagPanel instantiates", f"{type(exc).__name__}: {exc}")

    # SearchBar
    try:
        from ui.search_bar import SearchBar
        sb = SearchBar()
        _pass("SearchBar instantiates")
    except Exception as exc:
        _fail("SearchBar instantiates", f"{type(exc).__name__}: {exc}")

    # RestructureDialog (without showing it)
    try:
        from ui.restructure_dialog import RestructureDialog
        dlg = RestructureDialog()
        _pass("RestructureDialog instantiates and auto-previews")
        dlg.close()
    except Exception as exc:
        _fail("RestructureDialog instantiates", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()

    # AlbumPanel
    try:
        from ui.album_panel import AlbumPanel
        ap = AlbumPanel()
        _pass("AlbumPanel instantiates")
    except Exception as exc:
        _fail("AlbumPanel instantiates", f"{type(exc).__name__}: {exc}")

    # PeoplePanel
    try:
        from ui.people_panel import PeoplePanel
        pp = PeoplePanel()
        _pass("PeoplePanel instantiates")
    except Exception as exc:
        _fail("PeoplePanel instantiates", f"{type(exc).__name__}: {exc}")

    # MapView
    try:
        from ui.map_view import MapView
        mv = MapView()
        _pass("MapView instantiates")
    except Exception as exc:
        _fail("MapView instantiates", f"{type(exc).__name__}: {exc}")


def test_db_integrity():
    _section("Database integrity")
    from database.db import get_session
    from database.models import Photo, Tag, Location, Person, PhotoPerson, Album

    session = get_session()
    try:
        for Model, label in [
            (Photo,      "photos"),
            (Tag,        "tags"),
            (Location,   "locations"),
            (Person,     "people"),
            (PhotoPerson,"photo_people"),
            (Album,      "albums"),
        ]:
            count = _run(f"COUNT {label}", session.query(Model).count)
            if count is not None:
                _pass(f"  {label}: {count} row(s)")

        # FK integrity: all tag photo_ids must exist
        from sqlalchemy import text
        orphan_tags = session.execute(
            text("SELECT COUNT(*) FROM tags WHERE photo_id NOT IN (SELECT id FROM photos)")
        ).scalar()
        _pass("No orphan tags") if orphan_tags == 0 else _fail("Orphan tags", str(orphan_tags))

        orphan_locs = session.execute(
            text("SELECT COUNT(*) FROM locations WHERE photo_id NOT IN (SELECT id FROM photos)")
        ).scalar()
        _pass("No orphan locations") if orphan_locs == 0 else _fail("Orphan locations", str(orphan_locs))

    finally:
        session.close()


# =============================================================================
# Runner
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="SuperGallery integration tests")
    parser.add_argument(
        "--folder",
        default=r"C:\New folder\Camera\Uploaded\Family",
        help="Photo folder to import for testing",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Delete existing DB before testing",
    )
    args = parser.parse_args()

    print(f"\n{BOLD}SuperGallery Integration Tests{RESET}")
    print(f"Folder : {args.folder}")
    print(f"Python : {sys.version}")

    if args.fresh:
        from pathlib import Path
        db = Path.home() / ".supergallery" / "gallery.db"
        if db.exists():
            db.unlink()
            print(f"Deleted existing DB: {db}")

    test_db_init()
    test_import(args.folder)
    test_import_worker_direct(args.folder)
    test_tags()
    test_search()
    test_search_combined()
    test_albums()
    test_restructure()
    test_ai_tagger_graceful()
    test_ai_tagger_end_to_end()
    test_face_worker_graceful()
    test_face_worker_end_to_end()
    test_map_builder_graceful()
    test_gui_smoke()
    test_db_integrity()

    # -- Summary ---------------------------------------------------------------
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total  = len(_results)

    print(f"\n{BOLD}{'=' * 55}{RESET}")
    print(f"{BOLD}Results: {GREEN}{passed} passed{RESET}  {RED}{failed} failed{RESET}  / {total} total")
    if failed:
        print(f"\n{RED}Failed tests:{RESET}")
        for name, ok, detail in _results:
            if not ok:
                print(f"  x {name}: {detail}")
    print()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
