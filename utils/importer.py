"""
Photo importer: scans a folder, extracts EXIF metadata, stores in DB.
Emits Qt signals so the UI can show progress without blocking.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from PyQt6.QtCore import QObject, pyqtSignal

from database.db import get_session
from database.models import Photo, Tag, Location

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tiff", ".bmp"}


# ---------------------------------------------------------------------------
# EXIF helpers
# ---------------------------------------------------------------------------

def _exif_to_dict(img: Image.Image) -> dict:
    raw = img._getexif()
    if not raw:
        return {}
    return {TAGS.get(k, k): v for k, v in raw.items()}


def _parse_gps(exif: dict) -> tuple[Optional[float], Optional[float]]:
    gps_info = exif.get("GPSInfo")
    if not gps_info:
        return None, None
    gps = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}

    def dms_to_dd(dms, ref):
        d, m, s = dms
        dd = float(d) + float(m) / 60 + float(s) / 3600
        if ref in ("S", "W"):
            dd = -dd
        return dd

    try:
        lat = dms_to_dd(gps["GPSLatitude"], gps["GPSLatitudeRef"])
        lng = dms_to_dd(gps["GPSLongitude"], gps["GPSLongitudeRef"])
        return lat, lng
    except (KeyError, TypeError, ZeroDivisionError):
        return None, None


def _parse_date(exif: dict) -> Optional[datetime]:
    for field in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        raw = exif.get(field)
        if raw:
            try:
                return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                pass
    return None


def _parse_camera(exif: dict) -> Optional[str]:
    make = exif.get("Make", "").strip()
    model = exif.get("Model", "").strip()
    if make and model:
        return f"{make} {model}"
    return model or make or None


def extract_metadata(file_path: str) -> dict:
    """Return a dict with all extracted EXIF metadata for a single file."""
    path = Path(file_path)
    stat = path.stat()
    meta = {
        "file_path": str(path.resolve()),
        "filename": path.name,
        "file_size": stat.st_size,
        "date_taken": None,
        "lat": None,
        "lng": None,
        "camera_model": None,
        "width": None,
        "height": None,
    }
    try:
        with Image.open(file_path) as img:
            meta["width"], meta["height"] = img.size
            if img.format in ("JPEG", "TIFF"):
                exif = _exif_to_dict(img)
                meta["date_taken"] = _parse_date(exif)
                meta["lat"], meta["lng"] = _parse_gps(exif)
                meta["camera_model"] = _parse_camera(exif)
    except Exception:
        pass
    return meta


# ---------------------------------------------------------------------------
# Qt worker
# ---------------------------------------------------------------------------

class ImportWorker(QObject):
    """
    Run in a QThread.  Call start_import() from the thread's started signal.
    """
    progress = pyqtSignal(int, int)          # (completed, total)
    photo_imported = pyqtSignal(int, str)    # (photo_id, file_path)
    finished = pyqtSignal(int, int)          # (imported, skipped)
    error = pyqtSignal(str)

    def __init__(self, folder: str, parent=None):
        super().__init__(parent)
        self.folder = folder
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def start_import(self):
        try:
            self._run()
        except Exception as exc:
            self.error.emit(str(exc))

    def _run(self):
        folder = Path(self.folder)
        files = [
            p for p in folder.rglob("*")
            if p.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        total = len(files)
        imported = skipped = 0

        session = get_session()
        try:
            existing = {r[0] for r in session.query(Photo.file_path).all()}

            for i, file_path in enumerate(files):
                if self._cancelled:
                    break

                abs_path = str(file_path.resolve())
                if abs_path in existing:
                    skipped += 1
                    self.progress.emit(i + 1, total)
                    continue

                meta = extract_metadata(abs_path)
                photo = Photo(**{k: meta[k] for k in (
                    "file_path", "filename", "date_taken",
                    "lat", "lng", "camera_model",
                    "width", "height", "file_size"
                )})
                session.add(photo)
                session.flush()  # get photo.id

                # Auto-tag with date category
                if photo.date_taken:
                    session.add(Tag(
                        photo_id=photo.id,
                        label=str(photo.date_taken.year),
                        category="Date",
                        is_manual=False,
                    ))
                    session.add(Tag(
                        photo_id=photo.id,
                        label=photo.date_taken.strftime("%B %Y"),
                        category="Date",
                        is_manual=False,
                    ))

                # Store GPS in locations table
                if photo.lat is not None and photo.lng is not None:
                    session.add(Location(
                        photo_id=photo.id,
                        lat=photo.lat,
                        lng=photo.lng,
                    ))

                session.commit()
                imported += 1
                self.photo_imported.emit(photo.id, abs_path)
                self.progress.emit(i + 1, total)

        finally:
            session.close()

        self.finished.emit(imported, skipped)
