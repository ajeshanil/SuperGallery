"""Multi-category photo search logic."""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import exists, and_

from database.models import Photo, Tag, PhotoPerson, Person, Location

logger = logging.getLogger(__name__)


def search_photos(session: Session, filters: dict) -> list[Photo]:
    """
    Search photos using a multi-category filter dict.

    Filter format::

        {
            "People":    ["Ajesh"],          # photo contains this person
            "Objects":   ["dog", "car"],     # photo has ALL of these object tags
            "Scenes":    ["beach"],
            "PhotoType": ["selfie"],
            "Date":      ["2024"],           # matches year in date_taken
            "Location":  ["Paris"],          # matches city or country
            "text":      "free text search across all tag labels",
        }

    Rules:
    - AND logic across different keys.
    - OR logic between values in the same category list.
    - An empty dict returns all photos.

    Returns
    -------
    list[Photo]
    """
    query = session.query(Photo)

    for key, value in filters.items():
        if not value:
            continue

        if key == "text":
            text_val = value if isinstance(value, str) else str(value)
            text_pattern = f"%{text_val}%"
            query = query.filter(
                exists().where(
                    and_(
                        Tag.photo_id == Photo.id,
                        Tag.label.ilike(text_pattern),
                    )
                )
            )

        elif key == "People":
            names = [value] if isinstance(value, str) else list(value)
            # OR within the People list: photo contains at least one of the named persons
            from sqlalchemy import or_
            name_conditions = [
                Person.name.ilike(f"%{name}%") for name in names
            ]
            query = query.filter(
                exists().where(
                    and_(
                        PhotoPerson.photo_id == Photo.id,
                        PhotoPerson.person_id == Person.id,
                        or_(*name_conditions),
                    )
                )
            )

        elif key == "Date":
            date_values = [value] if isinstance(value, str) else list(value)
            from sqlalchemy import or_, cast, String
            date_conditions = [
                cast(Photo.date_taken, String).ilike(f"%{dv}%")
                for dv in date_values
            ]
            # Also match month-name labels stored as Date tags (e.g. "April 2022")
            tag_date_conditions = [
                exists().where(
                    and_(
                        Tag.photo_id == Photo.id,
                        Tag.category == "Date",
                        Tag.label.ilike(f"%{dv}%"),
                    )
                )
                for dv in date_values
            ]
            query = query.filter(or_(*date_conditions, *tag_date_conditions))

        elif key == "Location":
            loc_values = [value] if isinstance(value, str) else list(value)
            from sqlalchemy import or_
            loc_conditions = []
            for lv in loc_values:
                pattern = f"%{lv}%"
                loc_conditions.append(
                    exists().where(
                        and_(
                            Location.photo_id == Photo.id,
                            or_(
                                Location.city.ilike(pattern),
                                Location.country.ilike(pattern),
                            ),
                        )
                    )
                )
            from sqlalchemy import or_ as _or
            query = query.filter(_or(*loc_conditions))

        else:
            # Tag-based categories: Objects, Scenes, PhotoType, or any custom
            category = key
            tag_values = [value] if isinstance(value, str) else list(value)
            # AND logic: photo must have ALL requested tag values for this category.
            for tag_label in tag_values:
                query = query.filter(
                    exists().where(
                        and_(
                            Tag.photo_id == Photo.id,
                            Tag.category == category,
                            Tag.label.ilike(f"%{tag_label}%"),
                        )
                    )
                )

    return query.all()


def get_all_tags_by_category(session: Session) -> dict[str, list[str]]:
    """
    Return all unique tag labels grouped by category.

    Returns
    -------
    dict[str, list[str]]
        Example: {"Objects": ["dog", "car"], "Scenes": ["beach"], ...}
    """
    rows = session.query(Tag.category, Tag.label).distinct().all()

    result: dict[str, list[str]] = {}
    for category, label in rows:
        result.setdefault(category, []).append(label)

    # Sort labels within each category for consistent UI presentation
    for cat in result:
        result[cat].sort()

    return result
