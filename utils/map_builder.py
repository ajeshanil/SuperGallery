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

    # Clustered marker layer — each marker IS the photo thumbnail (DivIcon),
    # not a generic pin.  At low zoom the cluster shows a count badge; when
    # zoomed in enough the individual thumbnail tiles appear.
    marker_cluster = MarkerCluster(
        name="Photos",
        options={
            "disableClusteringAtZoom": 14,   # show individual thumbs from zoom 14+
            "maxClusterRadius": 60,
        },
    ).add_to(fmap)

    for photo in photos_with_coords:
        filename = Path(photo["file_path"]).name
        date_str = str(photo.get("date", ""))[:10]  # YYYY-MM-DD
        photo_id = photo["id"]

        # ── Marker icon: 64×64 thumbnail tile ──
        icon_html = (
            f'<div onclick="window.parent.postMessage({{photoId:{photo_id}}},\'*\')" '
            f'     style="width:60px;height:60px;overflow:hidden;border-radius:6px;'
            f'            border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.55);'
            f'            cursor:pointer;background:#1a1a1a">'
            f'  <img src="/api/photos/{photo_id}/thumb" '
            f'       style="width:100%;height:100%;object-fit:cover">'
            f'</div>'
        )
        icon = folium.DivIcon(
            html=icon_html,
            icon_size=(64, 64),
            icon_anchor=(32, 32),   # centre anchor so thumb is over the coord
            class_name="photo-thumb-marker",
        )

        # ── Popup: larger preview + metadata ──
        popup_html = (
            f'<div style="text-align:center;font-family:sans-serif;padding:4px">'
            f'<img src="/api/photos/{photo_id}/thumb" '
            f'     style="max-width:200px;max-height:180px;border-radius:6px;'
            f'            display:block;margin:0 auto 8px;cursor:pointer" '
            f'     onclick="window.parent.postMessage({{photoId:{photo_id}}},\'*\')">'
            f'<div style="font-size:12px;color:#555">{date_str}</div>'
            f'<div style="font-size:11px;color:#888;word-break:break-all">{filename}</div>'
            f'</div>'
        )
        folium.Marker(
            location=[photo["lat"], photo["lng"]],
            icon=icon,
            popup=folium.Popup(popup_html, max_width=240),
            tooltip=date_str,
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
