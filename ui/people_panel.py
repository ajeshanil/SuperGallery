"""People panel — shows all identified people, allows renaming."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QInputDialog, QSizePolicy, QFrame
)

from database.db import get_session
from database.models import Person, PhotoPerson


_DARK_STYLESHEET = """
    QWidget#peoplePanelRoot { background: #1a1a1a; }
    QLabel#panelHeader {
        font-size: 14px; font-weight: 700; color: #e0e0e0;
        padding: 12px 12px 8px 12px;
    }
    QScrollArea { border: none; background: #1a1a1a; }
    QWidget#scrollContent { background: #1a1a1a; }
    QLabel#noPersonLabel {
        color: #555; font-size: 13px; padding: 16px;
    }
    QPushButton#processFacesBtn {
        background: #1565c0; color: #e0e0e0;
        border: none; border-radius: 5px;
        padding: 6px 14px; font-size: 12px; margin: 8px 12px;
    }
    QPushButton#processFacesBtn:hover { background: #1976d2; }
    QWidget#personCard {
        background: #2d2d2d;
        border-radius: 8px;
    }
    QWidget#personCard:hover { background: #3a3a3a; }
    QPushButton#renameBtn {
        background: transparent; color: #888;
        border: 1px solid #444; border-radius: 4px;
        padding: 2px 8px; font-size: 11px;
    }
    QPushButton#renameBtn:hover { background: #444; color: #e0e0e0; }
"""


def _load_thumbnail(file_path: str, size: int) -> QPixmap:
    pix = QPixmap(file_path)
    if pix.isNull():
        pix = QPixmap(size, size)
        pix.fill(QColor("#3a3a3a"))
    return pix.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )


def _placeholder_pixmap(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(QColor("#3a3a3a"))
    return pix


class PersonCard(QFrame):
    """Card widget showing a person thumbnail, name and photo count."""

    card_clicked = pyqtSignal(int)    # person_id
    rename_clicked = pyqtSignal(int, str)  # person_id, current_name

    def __init__(self, person: Person, photo_count: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.person_id = person.id
        self.current_name = person.name
        self.setObjectName("personCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QFrame#personCard { background:#2d2d2d; border-radius:8px; }"
                           "QFrame#personCard:hover { background:#3a3a3a; }")
        self._build(person, photo_count)

    def _build(self, person: Person, photo_count: int) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        # Thumbnail
        thumb = QLabel()
        thumb.setFixedSize(52, 52)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet("border-radius:26px; background:#1a1a1a;")
        if person.thumbnail_path and Path(person.thumbnail_path).exists():
            pix = _load_thumbnail(person.thumbnail_path, 52)
        else:
            pix = _placeholder_pixmap(52)
        thumb.setPixmap(pix)
        layout.addWidget(thumb)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        name_lbl = QLabel(person.name)
        name_lbl.setStyleSheet("color:#e0e0e0; font-size:13px; font-weight:600; background:transparent;")
        text_col.addWidget(name_lbl)

        count_lbl = QLabel(f"{photo_count} photo{'s' if photo_count != 1 else ''}")
        count_lbl.setStyleSheet("color:#888; font-size:11px; background:transparent;")
        text_col.addWidget(count_lbl)

        layout.addLayout(text_col, stretch=1)

        # Rename button
        rename_btn = QPushButton("Rename")
        rename_btn.setObjectName("renameBtn")
        rename_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rename_btn.clicked.connect(lambda: self.rename_clicked.emit(self.person_id, self.current_name))
        layout.addWidget(rename_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.card_clicked.emit(self.person_id)
        super().mousePressEvent(event)


class PeoplePanel(QWidget):
    """Left-panel section for people management."""

    person_selected = pyqtSignal(int)       # person_id
    person_renamed = pyqtSignal(int, str)   # person_id, new_name
    run_face_processing = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("peoplePanelRoot")
        self.setStyleSheet(_DARK_STYLESHEET)
        self.setMinimumWidth(200)
        self._setup_ui()
        self.load_people()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QLabel("People")
        header.setObjectName("panelHeader")
        root.addWidget(header)

        # Process Faces button
        process_btn = QPushButton("Process Faces")
        process_btn.setObjectName("processFacesBtn")
        process_btn.clicked.connect(self.run_face_processing.emit)
        root.addWidget(process_btn)

        # Scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("scrollContent")
        self.people_layout = QVBoxLayout(self.scroll_content)
        self.people_layout.setContentsMargins(10, 6, 10, 10)
        self.people_layout.setSpacing(6)
        self.people_layout.addStretch()

        self.scroll.setWidget(self.scroll_content)
        root.addWidget(self.scroll, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_people(self) -> None:
        """Query all Person records from DB and display as cards."""
        # Clear existing cards (keep trailing stretch)
        while self.people_layout.count() > 1:
            item = self.people_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        session = get_session()
        try:
            people = session.query(Person).order_by(Person.name).all()

            if not people:
                no_lbl = QLabel("No people identified yet.\nRun face processing to get started.")
                no_lbl.setObjectName("noPersonLabel")
                no_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                no_lbl.setWordWrap(True)
                self.people_layout.insertWidget(0, no_lbl)
                return

            for i, person in enumerate(people):
                photo_count = (
                    session.query(PhotoPerson)
                    .filter(PhotoPerson.person_id == person.id)
                    .count()
                )
                card = PersonCard(person, photo_count)
                card.card_clicked.connect(self.person_selected.emit)
                card.rename_clicked.connect(self._rename_dialog)
                self.people_layout.insertWidget(i, card)
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _rename_dialog(self, person_id: int, current_name: str) -> None:
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Person",
            "Enter new name:",
            text=current_name,
        )
        if not ok or not new_name.strip():
            return

        new_name = new_name.strip()
        session = get_session()
        try:
            person = session.get(Person, person_id)
            if person:
                person.name = new_name
                session.commit()
        finally:
            session.close()

        self.person_renamed.emit(person_id, new_name)
        self.load_people()
