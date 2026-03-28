"""Tag panel — shows AI and manual tags for the selected photo, allows add/delete."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QLineEdit, QComboBox, QSizePolicy
)

from database.db import get_session
from database.models import Tag, Photo


# ---------------------------------------------------------------------------
# Category colour palette  (bg, text)
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

_CHIP_BASE = """
    QWidget {{
        background: {bg};
        border-radius: 12px;
        padding: 1px 0px;
    }}
"""

_DARK_STYLESHEET = """
    QWidget#tagPanelRoot { background: #1a1a1a; }
    QLabel#panelHeader {
        font-size: 14px; font-weight: 700; color: #e0e0e0;
        padding: 12px 12px 8px 12px;
    }
    QLabel#categoryHeader {
        font-size: 11px; font-weight: 600; color: #888;
        padding: 6px 0 2px 0;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    QLabel#noTagsLabel {
        color: #555; font-size: 13px; padding: 16px;
    }
    QScrollArea { border: none; background: #1a1a1a; }
    QWidget#scrollContent { background: #1a1a1a; }
    QLineEdit {
        background: #2d2d2d; color: #e0e0e0;
        border: 1px solid #444; border-radius: 5px;
        padding: 5px 8px; font-size: 12px;
    }
    QLineEdit:focus { border-color: #1976d2; }
    QComboBox {
        background: #2d2d2d; color: #e0e0e0;
        border: 1px solid #444; border-radius: 5px;
        padding: 5px 8px; font-size: 12px; min-width: 90px;
    }
    QComboBox QAbstractItemView { background: #2d2d2d; color: #e0e0e0; }
    QPushButton#addTagBtn {
        background: #1565c0; color: #e0e0e0;
        border: none; border-radius: 5px;
        padding: 6px 12px; font-size: 12px;
    }
    QPushButton#addTagBtn:hover { background: #1976d2; }
    QWidget#addTagForm {
        background: #141414;
        border-top: 1px solid #2a2a2a;
    }
"""


def _load_thumbnail(file_path: str, size: int) -> QPixmap:
    pix = QPixmap(file_path)
    if pix.isNull():
        pix = QPixmap(size, size)
        pix.fill(QColor("#2a2a2a"))
    return pix.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class TagChip(QWidget):
    """A single coloured tag chip with an optional × delete button."""

    delete_requested = pyqtSignal(int)  # tag_id

    def __init__(
        self,
        tag: Tag,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        bg, fg = CATEGORY_COLORS.get(tag.category, ("#2d2d2d", "#e0e0e0"))

        self.setObjectName("tagChip")
        self.setStyleSheet(f"background:{bg}; border-radius:12px;")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 6, 4)
        row.setSpacing(4)

        label_text = tag.label
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"color:{fg}; font-size:12px; font-weight:600; background:transparent;")
        row.addWidget(lbl)

        # Confidence badge (AI tags)
        if not tag.is_manual and tag.confidence is not None:
            pct = int(tag.confidence * 100)
            conf_lbl = QLabel(f"{pct}%")
            conf_lbl.setStyleSheet(
                f"color:{fg}; opacity:0.7; font-size:10px; background:transparent;"
            )
            row.addWidget(conf_lbl)

        # "manual" badge
        if tag.is_manual:
            manual_lbl = QLabel("manual")
            manual_lbl.setStyleSheet(
                f"color:{fg}; font-size:9px; font-style:italic; background:transparent;"
            )
            row.addWidget(manual_lbl)

        # Delete button
        del_btn = QPushButton("×")
        del_btn.setFixedSize(16, 16)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{fg}; border:none;"
            f" font-size:14px; font-weight:700; padding:0; }}"
            f"QPushButton:hover {{ color:#e53935; }}"
        )
        del_btn.clicked.connect(lambda: self.delete_requested.emit(tag.id))
        row.addWidget(del_btn)


class TagPanel(QWidget):
    """Right-side panel for viewing and editing tags on a selected photo."""

    tags_changed = pyqtSignal(int)  # emits photo_id

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("tagPanelRoot")
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self.setStyleSheet(_DARK_STYLESHEET)
        self._photo_id: int | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QLabel("Tags")
        header.setObjectName("panelHeader")
        root.addWidget(header)

        # Thumbnail preview
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(100, 100)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(
            "background:#0d0d0d; border-radius:6px; margin: 0 auto;"
        )
        thumb_container = QWidget()
        thumb_container.setStyleSheet("background:transparent;")
        tc_layout = QHBoxLayout(thumb_container)
        tc_layout.setContentsMargins(12, 0, 12, 8)
        tc_layout.addWidget(self.thumb_label, alignment=Qt.AlignmentFlag.AlignCenter)
        root.addWidget(thumb_container)

        # Scroll area for tags
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("scrollContent")
        self.tags_layout = QVBoxLayout(self.scroll_content)
        self.tags_layout.setContentsMargins(12, 4, 12, 8)
        self.tags_layout.setSpacing(4)
        self.tags_layout.addStretch()

        self.scroll.setWidget(self.scroll_content)
        root.addWidget(self.scroll, stretch=1)

        # Add Tag form at the bottom
        form_widget = QWidget()
        form_widget.setObjectName("addTagForm")
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setSpacing(6)

        form_row = QHBoxLayout()
        form_row.setSpacing(6)

        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("Tag label…")
        self.tag_input.returnPressed.connect(self._add_tag)
        form_row.addWidget(self.tag_input, stretch=2)

        self.cat_combo = QComboBox()
        for cat in CATEGORIES:
            self.cat_combo.addItem(cat)
        form_row.addWidget(self.cat_combo, stretch=1)

        form_layout.addLayout(form_row)

        add_btn = QPushButton("Add Tag")
        add_btn.setObjectName("addTagBtn")
        add_btn.clicked.connect(self._add_tag)
        form_layout.addWidget(add_btn)

        root.addWidget(form_widget)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_photo(self, photo_id: int) -> None:
        """Query tags from DB, clear and rebuild the tag list."""
        self._photo_id = photo_id

        # Update thumbnail
        session = get_session()
        try:
            photo = session.get(Photo, photo_id)
            if photo and Path(photo.file_path).exists():
                pix = _load_thumbnail(photo.file_path, 100)
                self.thumb_label.setPixmap(pix)
            else:
                pix = QPixmap(100, 100)
                pix.fill(QColor("#2a2a2a"))
                self.thumb_label.setPixmap(pix)

            tags = (
                session.query(Tag)
                .filter(Tag.photo_id == photo_id)
                .order_by(Tag.category, Tag.label)
                .all()
            )
        finally:
            session.close()

        self._rebuild_tag_list(tags)

    def _rebuild_tag_list(self, tags: list[Tag]) -> None:
        """Clear the tag list widget and repopulate it."""
        # Remove all items except the trailing stretch
        while self.tags_layout.count() > 1:
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not tags:
            no_tags = QLabel("No tags")
            no_tags.setObjectName("noTagsLabel")
            no_tags.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tags_layout.insertWidget(0, no_tags)
            return

        # Group by category preserving display order
        groups: dict[str, list[Tag]] = {}
        for cat in CATEGORIES:
            groups[cat] = []
        for tag in tags:
            bucket = groups.setdefault(tag.category, [])
            bucket.append(tag)

        insert_pos = 0
        for cat, cat_tags in groups.items():
            if not cat_tags:
                continue

            # Category section header
            cat_header = QLabel(cat)
            cat_header.setObjectName("categoryHeader")
            bg, fg = CATEGORY_COLORS.get(cat, ("#2d2d2d", "#e0e0e0"))
            cat_header.setStyleSheet(
                f"font-size:11px; font-weight:600; color:{fg};"
                f" background:{bg}; border-radius:4px;"
                f" padding:2px 8px; margin-top:4px;"
            )
            self.tags_layout.insertWidget(insert_pos, cat_header)
            insert_pos += 1

            # Chip row — wrap chips in a flow-like widget
            chips_widget = QWidget()
            chips_widget.setStyleSheet("background:transparent;")
            chips_layout = QHBoxLayout(chips_widget)
            chips_layout.setContentsMargins(0, 2, 0, 2)
            chips_layout.setSpacing(4)

            for tag in cat_tags:
                chip = TagChip(tag)
                chip.delete_requested.connect(self._delete_tag)
                chips_layout.addWidget(chip)

            chips_layout.addStretch()
            self.tags_layout.insertWidget(insert_pos, chips_widget)
            insert_pos += 1

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _add_tag(self) -> None:
        if self._photo_id is None:
            return

        label = self.tag_input.text().strip()
        if not label:
            return

        category = self.cat_combo.currentText()

        session = get_session()
        try:
            tag = Tag(
                photo_id=self._photo_id,
                label=label,
                category=category,
                is_manual=True,
            )
            session.add(tag)
            session.commit()
        finally:
            session.close()

        self.tag_input.clear()
        self.load_photo(self._photo_id)
        self.tags_changed.emit(self._photo_id)

    def _delete_tag(self, tag_id: int) -> None:
        session = get_session()
        try:
            tag = session.get(Tag, tag_id)
            if tag:
                session.delete(tag)
                session.commit()
        finally:
            session.close()

        if self._photo_id is not None:
            self.load_photo(self._photo_id)
            self.tags_changed.emit(self._photo_id)
