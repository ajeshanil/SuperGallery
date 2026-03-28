"""Map view — renders Folium HTML map in an embedded browser."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    _WEB_ENGINE_AVAILABLE = True
except ImportError:
    _WEB_ENGINE_AVAILABLE = False


_DARK_STYLESHEET = """
    QWidget#mapViewRoot { background: #121212; }
    QLabel#fallbackLabel {
        color: #888; font-size: 13px;
        padding: 40px; background: #1a1a1a;
        border-radius: 8px;
    }
"""


class MapView(QWidget):
    """
    Embeds a Folium-generated HTML map using QWebEngineView.

    If PyQt6-WebEngine is not installed, a fallback label is shown instead.
    Users can install it with:  pip install PyQt6-WebEngine
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("mapViewRoot")
        self.setStyleSheet(_DARK_STYLESHEET)
        self._web_view: "QWebEngineView | None" = None
        self._current_html_path: str | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if _WEB_ENGINE_AVAILABLE:
            self._web_view = QWebEngineView()
            self._web_view.settings().setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
            )
            self._web_view.setStyleSheet("background:#121212;")
            # Show a neutral dark background while no map is loaded
            self._web_view.setHtml(
                "<html><body style='background:#121212;margin:0;padding:0;'>"
                "<p style='color:#555;font-family:sans-serif;padding:40px;font-size:14px;'>"
                "No map loaded yet."
                "</p></body></html>"
            )
            layout.addWidget(self._web_view)
        else:
            fallback = QLabel(
                "Map view is unavailable.\n\n"
                "Install PyQt6-WebEngine to enable the map view:\n"
                "    pip install PyQt6-WebEngine"
            )
            fallback.setObjectName("fallbackLabel")
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setWordWrap(True)
            layout.addWidget(fallback, alignment=Qt.AlignmentFlag.AlignCenter)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_map(self, html_path: str) -> None:
        """Load a Folium HTML file into the web view."""
        if not _WEB_ENGINE_AVAILABLE or self._web_view is None:
            return

        path = Path(html_path)
        if not path.exists():
            return

        self._current_html_path = html_path
        url = QUrl.fromLocalFile(str(path.resolve()))
        self._web_view.load(url)

    def refresh(self, session) -> None:
        """
        Regenerate the map HTML from the database and reload the view.

        Requires utils.map_builder.get_map_html(session) to exist.
        """
        if not _WEB_ENGINE_AVAILABLE or self._web_view is None:
            return

        try:
            from utils.map_builder import get_map_html
        except ImportError:
            self._web_view.setHtml(
                "<html><body style='background:#121212;'>"
                "<p style='color:#c62828;font-family:sans-serif;padding:40px;'>"
                "utils.map_builder module not found."
                "</p></body></html>"
            )
            return

        try:
            html_path = get_map_html(session)
            if html_path:
                self.load_map(html_path)
            else:
                self._web_view.setHtml(
                    "<html><body style='background:#121212;'>"
                    "<p style='color:#555;font-family:sans-serif;padding:40px;font-size:14px;'>"
                    "No location data available to display on the map."
                    "</p></body></html>"
                )
        except Exception as exc:
            self._web_view.setHtml(
                f"<html><body style='background:#121212;'>"
                f"<p style='color:#c62828;font-family:sans-serif;padding:40px;'>"
                f"Error generating map: {exc}"
                f"</p></body></html>"
            )
