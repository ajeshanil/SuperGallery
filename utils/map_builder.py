"""Folium-based interactive map builder for geotagged photos."""
import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import folium
    from folium.plugins import HeatMap, MarkerCluster
    _FOLIUM_AVAILABLE = True
except ImportError:
    _FOLIUM_AVAILABLE = False
    logger.warning(
        "folium is not installed. Map features will be unavailable. "
        "Install with: pip install folium"
    )

_DEFAULT_OUTPUT = str(Path(tempfile.gettempdir()) / "supergallery_map.html")


def build_map(photos_with_coords: list[dict], output_path: str) -> Optional[str]:
    """
    Build an interactive HTML map from a list of geotagged photos.

    Parameters
    ----------
    photos_with_coords
        List of dicts with keys: "id", "lat", "lng", "file_path", "date".
    output_path
        File path where the HTML file will be saved.

    Returns
    -------
    str
        Absolute path to the generated HTML file.
    """
    if not _FOLIUM_AVAILABLE:
        return None

    if not photos_with_coords:
        return None

    lats = [p["lat"] for p in photos_with_coords]
    lngs = [p["lng"] for p in photos_with_coords]
    center_lat = sum(lats) / len(lats)
    center_lng = sum(lngs) / len(lngs)

    fmap = folium.Map(location=[center_lat, center_lng], zoom_start=5)

    # Heat map layer
    heat_data = [[p["lat"], p["lng"]] for p in photos_with_coords]
    HeatMap(heat_data, name="Photo Density").add_to(fmap)

    # Clustered marker layer
    marker_cluster = MarkerCluster(name="Photos").add_to(fmap)
    for photo in photos_with_coords:
        filename = Path(photo["file_path"]).name
        date_str = str(photo.get("date", ""))
        popup_html = f"<b>{filename}</b><br>{date_str}"
        folium.Marker(
            location=[photo["lat"], photo["lng"]],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=filename,
        ).add_to(marker_cluster)

    folium.LayerControl().add_to(fmap)

    output_path = str(Path(output_path).resolve())
    fmap.save(output_path)
    return output_path


def get_map_html(session) -> Optional[str]:
    """
    Query all photos that have GPS coordinates, build a map, and return the
    path to the generated HTML file.

    Parameters
    ----------
    session : SQLAlchemy Session

    Returns
    -------
    str
        Path to the generated HTML file.
    """
    from database.models import Location, Photo

    rows = (
        session.query(Photo, Location)
        .join(Location, Location.photo_id == Photo.id)
        .filter(Location.lat.isnot(None), Location.lng.isnot(None))
        .all()
    )

    photos_with_coords: list[dict] = []
    for photo, location in rows:
        photos_with_coords.append({
            "id": photo.id,
            "lat": location.lat,
            "lng": location.lng,
            "file_path": photo.file_path,
            "date": str(photo.date_taken) if photo.date_taken else "",
        })

    if not photos_with_coords:
        return None
    output_path = _DEFAULT_OUTPUT
    return build_map(photos_with_coords, output_path)
