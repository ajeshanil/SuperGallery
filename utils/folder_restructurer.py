"""Virtual and physical folder restructuring for the photo library."""
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from database.models import Photo, Tag, Location

logger = logging.getLogger(__name__)

GroupByMode = str  # "year" | "month" | "location" | "person"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _group_by_year(photos: list[Photo]) -> dict[str, list[Photo]]:
    groups: dict[str, list[Photo]] = {}
    for photo in photos:
        if photo.date_taken:
            key = str(photo.date_taken.year)
        else:
            key = "Unknown Year"
        groups.setdefault(key, []).append(photo)
    return groups


def _group_by_month(photos: list[Photo]) -> dict[str, list[Photo]]:
    groups: dict[str, list[Photo]] = {}
    for photo in photos:
        if photo.date_taken:
            key = photo.date_taken.strftime("%Y-%m %B")  # e.g. "2024-07 July"
        else:
            key = "Unknown Month"
        groups.setdefault(key, []).append(photo)
    return groups


def _group_by_location(session: Session, photos: list[Photo]) -> dict[str, list[Photo]]:
    photo_ids = [p.id for p in photos]
    locations = (
        session.query(Location)
        .filter(Location.photo_id.in_(photo_ids))
        .all()
    )
    loc_map: dict[int, Location] = {loc.photo_id: loc for loc in locations}

    groups: dict[str, list[Photo]] = {}
    for photo in photos:
        loc = loc_map.get(photo.id)
        if loc:
            country = loc.country or "Unknown Country"
            city = loc.city or "Unknown City"
            key = f"{country}/{city}"
        else:
            key = "Unknown Location"
        groups.setdefault(key, []).append(photo)
    return groups


def _group_by_person(session: Session, photos: list[Photo]) -> dict[str, list[Photo]]:
    from database.models import PhotoPerson, Person

    photo_ids = [p.id for p in photos]
    rows = (
        session.query(PhotoPerson, Person)
        .join(Person, Person.id == PhotoPerson.person_id)
        .filter(PhotoPerson.photo_id.in_(photo_ids))
        .all()
    )

    # Build a mapping photo_id -> list of person names
    photo_to_persons: dict[int, list[str]] = {}
    for pp, person in rows:
        photo_to_persons.setdefault(pp.photo_id, []).append(person.name)

    # Index photos by ID for quick lookup
    photo_index: dict[int, Photo] = {p.id: p for p in photos}

    groups: dict[str, list[Photo]] = {}
    for photo in photos:
        person_names = photo_to_persons.get(photo.id)
        if person_names:
            # Assign photo to the first (most-tagged) person alphabetically
            key = sorted(person_names)[0]
        else:
            key = "Unknown Person"
        groups.setdefault(key, []).append(photo)
    return groups


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_virtual_structure(
    session: Session,
    mode: GroupByMode,
) -> dict[str, list[Photo]]:
    """
    Return {group_label: [Photo, ...]} without touching any files.

    Parameters
    ----------
    session : SQLAlchemy Session
    mode    : "year" | "month" | "location" | "person"

    Returns
    -------
    dict[str, list[Photo]]
    """
    photos: list[Photo] = session.query(Photo).all()

    if mode == "year":
        return _group_by_year(photos)
    elif mode == "month":
        return _group_by_month(photos)
    elif mode == "location":
        return _group_by_location(session, photos)
    elif mode == "person":
        return _group_by_person(session, photos)
    else:
        raise ValueError(
            f"Unknown GroupByMode '{mode}'. Choose from: year, month, location, person."
        )


def export_structure(
    session: Session,
    mode: GroupByMode,
    dest_folder: str,
    copy: bool = True,
) -> dict:
    """
    Create the folder structure at dest_folder, copying or symlinking photos.

    Parameters
    ----------
    session     : SQLAlchemy Session
    mode        : "year" | "month" | "location" | "person"
    dest_folder : Root directory for the exported structure.
    copy        : True  = copy files (originals untouched).
                  False = create symbolic links.

    Returns
    -------
    dict
        {"folders_created": int, "files_copied": int, "errors": list[str]}
    """
    groups = get_virtual_structure(session, mode)

    dest_root = Path(dest_folder)
    folders_created = 0
    files_processed = 0
    errors: list[str] = []

    for group_label, photos in groups.items():
        # Replace path separators that are part of the label (e.g. location mode)
        # with OS-safe separators.
        group_path = dest_root
        for part in group_label.split("/"):
            # Sanitise part: strip leading/trailing spaces and replace
            # characters that are illegal in directory names on most OSes.
            safe_part = part.strip().replace(":", "-").replace("\\", "-")
            if not safe_part:
                safe_part = "_"
            group_path = group_path / safe_part

        try:
            group_path.mkdir(parents=True, exist_ok=True)
            folders_created += 1
        except OSError as exc:
            errors.append(f"Could not create directory {group_path}: {exc}")
            continue

        for photo in photos:
            src = Path(photo.file_path)
            if not src.exists():
                errors.append(f"Source file not found: {src}")
                continue

            dest_file = group_path / src.name

            # Avoid collisions by appending photo ID when names clash.
            if dest_file.exists():
                dest_file = group_path / f"{src.stem}_{photo.id}{src.suffix}"

            try:
                if copy:
                    shutil.copy2(str(src), str(dest_file))
                else:
                    os.symlink(str(src.resolve()), str(dest_file))
                files_processed += 1
            except OSError as exc:
                errors.append(
                    f"Failed to {'copy' if copy else 'symlink'} {src} -> {dest_file}: {exc}"
                )

    return {
        "folders_created": folders_created,
        "files_copied": files_processed,
        "errors": errors,
    }
