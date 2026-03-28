"""Album panel — lists albums, allows create/delete/click."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QInputDialog, QDialog, QFormLayout, QLineEdit,
    QComboBox, QDialogButtonBox, QFrame, QSizePolicy
)

from database.db import get_session
from database.models import Album
from utils.album_manager import create_album, list_albums, delete_album


# ---------------------------------------------------------------------------
# Category colour palette — mirrors tag_panel.py
# ---------------------------------------------------------------------------

CATEGORY_COLORS: dict[str, tuple[str, str]] = {
    "People":    ("#EEEDFE", "#3C3489"),
    "Objects":   ("#E6F1FB", "#0C447C"),
    "Scenes":    ("#E1F5EE", "#085041"),
    "PhotoType": ("#FAEEDA", "#633806"),
    "Location":  ("#FAECE7", "#712B13"),
    "Date":      ("#F1EFE8", "#444441"),
}

CATEGORIES = list(CATEGORY_COLORS.keys())

_DARK_STYLESHEET = """
    QWidget#albumPanelRoot { background: #1a1a1a; }
    QLabel#panelHeader {
        font-size: 14px; font-weight: 700; color: #e0e0e0;
        padding: 12px 12px 8px 12px;
    }
    QScrollArea { border: none; background: #1a1a1a; }
    QWidget#scrollContent { background: #1a1a1a; }
    QLabel#noAlbumLabel {
        color: #555; font-size: 13px; padding: 16px;
    }
    QPushButton#newAlbumBtn {
        background: #1565c0; color: #e0e0e0;
        border: none; border-radius: 5px;
        padding: 6px 14px; font-size: 12px; margin: 8px 12px;
    }
    QPushButton#newAlbumBtn:hover { background: #1976d2; }
    QWidget#albumRow { background: #2d2d2d; border-radius: 6px; }
    QWidget#albumRow:hover { background: #3a3a3a; }
    QPushButton#deleteBtn {
        background: transparent; color: #666;
        border: none; padding: 2px 6px; font-size: 14px;
    }
    QPushButton#deleteBtn:hover { color: #e53935; }
    QLabel#smartBadge {
        background: #1565c0; color: #e0e0e0;
        border-radius: 8px; padding: 1px 6px;
        font-size: 10px; font-weight: 600;
    }
"""


class AlbumRow(QFrame):
    """A clickable row representing a single album."""

    row_clicked = pyqtSignal(int)    # album_id
    delete_clicked = pyqtSignal(int) # album_id

    def __init__(self, album: Album, parent: QWidget | None = None):
        super().__init__(parent)
        self.album_id = album.id
        self.setObjectName("albumRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#albumRow { background:#2d2d2d; border-radius:6px; }"
            "QFrame#albumRow:hover { background:#3a3a3a; }"
        )
        self._build(album)

    def _build(self, album: Album) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(8)

        name_lbl = QLabel(album.name)
        name_lbl.setStyleSheet(
            "color:#e0e0e0; font-size:13px; font-weight:500; background:transparent;"
        )
        layout.addWidget(name_lbl, stretch=1)

        if album.is_smart:
            smart_lbl = QLabel("smart")
            smart_lbl.setObjectName("smartBadge")
            smart_lbl.setStyleSheet(
                "background:#1565c0; color:#e0e0e0; border-radius:8px;"
                " padding:1px 6px; font-size:10px; font-weight:600;"
                " background:transparent;"  # override root
            )
            smart_lbl.setStyleSheet(
                "QLabel { background:#1565c0; color:#e0e0e0; border-radius:8px;"
                " padding:1px 6px; font-size:10px; font-weight:600; }"
            )
            layout.addWidget(smart_lbl)

        del_btn = QPushButton("\u2715")
        del_btn.setObjectName("deleteBtn")
        del_btn.setFixedSize(24, 24)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#666; border:none;"
            " font-size:13px; padding:0; }"
            "QPushButton:hover { color:#e53935; }"
        )
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.album_id))
        layout.addWidget(del_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.row_clicked.emit(self.album_id)
        super().mousePressEvent(event)


class FilterBuilderDialog(QDialog):
    """
    Dialog for creating a new album with optional smart filter definitions.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("New Album")
        self.setMinimumWidth(380)
        self.setStyleSheet("""
            QDialog { background: #1a1a1a; }
            QLabel {
                color: #e0e0e0; font-size: 12px; background: transparent;
            }
            QLabel#dialogTitle {
                font-size: 14px; font-weight: 700; color: #e0e0e0;
            }
            QLineEdit {
                background: #2d2d2d; color: #e0e0e0;
                border: 1px solid #444; border-radius: 5px;
                padding: 6px 10px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #1976d2; }
            QComboBox {
                background: #2d2d2d; color: #e0e0e0;
                border: 1px solid #444; border-radius: 5px;
                padding: 5px 8px; font-size: 12px;
            }
            QComboBox QAbstractItemView { background: #2d2d2d; color: #e0e0e0; }
            QPushButton {
                background: #2d2d2d; color: #e0e0e0;
                border: 1px solid #444; border-radius: 5px;
                padding: 6px 12px; font-size: 12px;
            }
            QPushButton:hover { background: #3a3a3a; }
            QPushButton#addFilterRowBtn {
                background: transparent; color: #1976d2;
                border: 1px dashed #1976d2; border-radius: 5px;
                padding: 4px 10px; font-size: 11px;
            }
            QPushButton#addFilterRowBtn:hover {
                background: #1a2a3a;
            }
            QPushButton#okBtn {
                background: #1565c0; color: #e0e0e0; border: none;
            }
            QPushButton#okBtn:hover { background: #1976d2; }
            QDialogButtonBox { background: transparent; }
            QFrame#filterRow { background: #2a2a2a; border-radius: 5px; }
        """)
        # Accumulated filter rows: list of (category, value) tuples
        self._filter_rows: list[tuple[str, str]] = []
        self._filter_widgets: list[QWidget] = []
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)

        title = QLabel("New Album")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        # Name input
        name_label = QLabel("Album name")
        layout.addWidget(name_label)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Summer 2024")
        layout.addWidget(self.name_input)

        # Filter builder section
        filter_label = QLabel("Filters  (optional — creates a smart album)")
        filter_label.setStyleSheet("color:#888; font-size:11px; background:transparent;")
        layout.addWidget(filter_label)

        self.filters_container = QWidget()
        self.filters_container.setStyleSheet("background:transparent;")
        self.filters_vbox = QVBoxLayout(self.filters_container)
        self.filters_vbox.setContentsMargins(0, 0, 0, 0)
        self.filters_vbox.setSpacing(6)
        layout.addWidget(self.filters_container)

        # Add filter row
        add_filter_btn = QPushButton("+ Add Filter")
        add_filter_btn.setObjectName("addFilterRowBtn")
        add_filter_btn.clicked.connect(self._add_filter_row)
        layout.addWidget(add_filter_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addStretch()

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = btn_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setObjectName("okBtn")
        ok_btn.setText("Create Album")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _add_filter_row(self) -> None:
        """Add a dynamic filter row (category combo + value input + remove button)."""
        row_widget = QFrame()
        row_widget.setObjectName("filterRow")
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(8, 6, 8, 6)
        row_layout.setSpacing(8)

        cat_combo = QComboBox()
        for cat in CATEGORIES:
            cat_combo.addItem(cat)
        row_layout.addWidget(cat_combo, stretch=1)

        val_input = QLineEdit()
        val_input.setPlaceholderText("Value…")
        row_layout.addWidget(val_input, stretch=2)

        remove_btn = QPushButton("\u00d7")
        remove_btn.setFixedSize(24, 24)
        remove_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#666; border:none; font-size:15px; }"
            "QPushButton:hover { color:#e53935; }"
        )
        remove_btn.clicked.connect(lambda: self._remove_filter_row(row_widget))
        row_layout.addWidget(remove_btn)

        self.filters_vbox.addWidget(row_widget)
        self._filter_widgets.append(row_widget)

    def _remove_filter_row(self, row_widget: QWidget) -> None:
        self.filters_vbox.removeWidget(row_widget)
        row_widget.deleteLater()
        if row_widget in self._filter_widgets:
            self._filter_widgets.remove(row_widget)

    def get_album_data(self) -> tuple[str, list[dict]]:
        """Return (name, [{'category': ..., 'value': ...}, ...])."""
        name = self.name_input.text().strip()
        filters: list[dict] = []
        for row_widget in self._filter_widgets:
            layout = row_widget.layout()
            cat_combo: QComboBox = layout.itemAt(0).widget()
            val_input: QLineEdit = layout.itemAt(1).widget()
            value = val_input.text().strip()
            if value:
                filters.append({"category": cat_combo.currentText(), "value": value})
        return name, filters


class AlbumPanel(QWidget):
    """Left-panel section for album management."""

    album_selected = pyqtSignal(int)  # album_id

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("albumPanelRoot")
        self.setStyleSheet(_DARK_STYLESHEET)
        self.setMinimumWidth(200)
        self._setup_ui()
        self.load_albums()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QLabel("Albums")
        header.setObjectName("panelHeader")
        root.addWidget(header)

        # New Album button
        new_album_btn = QPushButton("New Album")
        new_album_btn.setObjectName("newAlbumBtn")
        new_album_btn.clicked.connect(self.new_album_dialog)
        root.addWidget(new_album_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("scrollContent")
        self.albums_layout = QVBoxLayout(self.scroll_content)
        self.albums_layout.setContentsMargins(10, 6, 10, 10)
        self.albums_layout.setSpacing(6)
        self.albums_layout.addStretch()

        self.scroll.setWidget(self.scroll_content)
        root.addWidget(self.scroll, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_albums(self) -> None:
        """Query and display albums as clickable rows."""
        # Clear existing rows (keep trailing stretch)
        while self.albums_layout.count() > 1:
            item = self.albums_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        session = get_session()
        try:
            albums = list_albums(session)
        finally:
            session.close()

        if not albums:
            no_lbl = QLabel("No albums yet.\nClick 'New Album' to create one.")
            no_lbl.setObjectName("noAlbumLabel")
            no_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_lbl.setWordWrap(True)
            self.albums_layout.insertWidget(0, no_lbl)
            return

        for i, album in enumerate(albums):
            row = AlbumRow(album)
            row.row_clicked.connect(self.album_selected.emit)
            row.delete_clicked.connect(self._delete_album)
            self.albums_layout.insertWidget(i, row)

    def new_album_dialog(self) -> None:
        """Open dialog to name the album and optionally define filters."""
        dialog = FilterBuilderDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        name, filters = dialog.get_album_data()
        if not name:
            return

        import json
        session = get_session()
        try:
            filter_query = json.dumps(filters) if filters else None
            create_album(session, name=name, filter_query=filter_query, is_smart=bool(filters))
        finally:
            session.close()

        self.load_albums()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _delete_album(self, album_id: int) -> None:
        session = get_session()
        try:
            delete_album(session, album_id)
        finally:
            session.close()
        self.load_albums()
