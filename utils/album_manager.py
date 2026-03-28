"""Smart and manual album management."""
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from database.models import Album
from utils.search import search_photos

logger = logging.getLogger(__name__)


def create_album(
    session: Session,
    name: str,
    filters: dict,
    is_smart: bool = True,
) -> Album:
    """
    Create a new album and persist it.

    Parameters
    ----------
    name     : Display name for the album.
    filters  : Filter criteria dict (see search_photos). Serialised as JSON.
    is_smart : True for dynamic albums that re-run the query each time.

    Returns
    -------
    Album
        The newly created Album ORM object.
    """
    album = Album(
        name=name,
        filter_query=json.dumps(filters),
        is_smart=is_smart,
    )
    session.add(album)
    session.commit()
    return album


def get_album_photos(session: Session, album_id: int) -> list:
    """
    Return photos belonging to an album.

    For smart albums, the stored filter query is re-executed live.
    For non-smart albums, the filter_query field is expected to be an empty
    dict or None (manual curation would be implemented separately).

    Returns
    -------
    list[Photo]
    """
    album: Optional[Album] = session.get(Album, album_id)
    if album is None:
        logger.warning("Album %d not found.", album_id)
        return []

    if album.filter_query:
        try:
            filters = json.loads(album.filter_query)
        except json.JSONDecodeError:
            logger.error(
                "Album %d has invalid filter_query JSON: %r",
                album_id,
                album.filter_query,
            )
            filters = {}
    else:
        filters = {}

    return search_photos(session, filters)


def list_albums(session: Session) -> list[Album]:
    """
    Return all albums ordered by creation date, newest first.

    Returns
    -------
    list[Album]
    """
    return (
        session.query(Album)
        .order_by(Album.created_at.desc())
        .all()
    )


def delete_album(session: Session, album_id: int) -> None:
    """
    Permanently delete an album.

    Parameters
    ----------
    album_id : Primary key of the album to delete.
    """
    album: Optional[Album] = session.get(Album, album_id)
    if album is None:
        logger.warning("delete_album: Album %d not found.", album_id)
        return
    session.delete(album)
    session.commit()


def update_album_name(session: Session, album_id: int, new_name: str) -> None:
    """
    Rename an album.

    Parameters
    ----------
    album_id : Primary key of the album to rename.
    new_name : New display name.
    """
    album: Optional[Album] = session.get(Album, album_id)
    if album is None:
        logger.warning("update_album_name: Album %d not found.", album_id)
        return
    album.name = new_name
    session.commit()
