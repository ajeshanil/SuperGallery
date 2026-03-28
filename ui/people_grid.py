"""People grid — Google Photos-style circular face thumbnail grid."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QGridLayout,
    QSizePolicy,
)

from database.db import get_session
from database.models import Person, PhotoPerson


_CIRCLE_SIZE = 96


def _make_circular_pixmap(source_pix: QPixmap, size: int) -> QPixmap:
    """Crop source pixmap into a circle of the given diameter."""
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    scaled = source_pix.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    ox = (size - scaled.width()) // 2
    oy = (size - scaled.height()) // 2
    painter.drawPixmap(ox, oy, scaled)
    painter.end()
    return result


def _placeholder_circle(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#3a3a3a"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return pix


class PersonCircle(QWidget):
    """One person card: circular face + name + photo count."""

    clicked = pyqtSignal(int)  # person_id

    def __init__(self, person: Person, photo_count: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.person_id = person.id
        self.setFixedWidth(130)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build(person, photo_count)

    def _build(self, person: Person, photo_count: int) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 8)
        layout.setSpacing(6)

        # Circular thumbnail
        circle_lbl = QLabel()
        circle_lbl.setFixedSize(_CIRCLE_SIZE, _CIRCLE_SIZE)
        circle_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        circle_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if person.thumbnail_path and Path(person.thumbnail_path).exists():
            pix = _make_circular_pixmap(QPixmap(person.thumbnail_path), _CIRCLE_SIZE)
        else:
            pix = _placeholder_circle(_CIRCLE_SIZE)
        circle_lbl.setPixmap(pix)
        layout.addWidget(circle_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Name
        name_lbl = QLabel(person.name)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(
            "color:#e0e0e0; font-size:12px; font-weight:600; background:transparent;"
        )
        layout.addWidget(name_lbl)

        # Photo count
        count_lbl = QLabel(f"{photo_count} photo{'s' if photo_count != 1 else ''}")
        count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        count_lbl.setStyleSheet("color:#888; font-size:10px; background:transparent;")
        layout.addWidget(count_lbl)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.person_id)
        super().mousePressEvent(event)


class PeopleGrid(QWidget):
    """
    Full-center grid of circular person thumbnails.

    Signals
    -------
    person_clicked(person_id)  — user tapped a person card
    """

    person_clicked = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet("background:#121212;")
        self._cols = 5  # updated on resize
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        hdr = QWidget()
        hdr.setFixedHeight(48)
        hdr.setStyleSheet("background:#1a1a1a; border-bottom:1px solid #252525;")
        hdr_row = QHBoxLayout(hdr)
        hdr_row.setContentsMargins(16, 0, 16, 0)
        title = QLabel("People")
        title.setStyleSheet("font-size:15px; font-weight:700; color:#e0e0e0;")
        hdr_row.addWidget(title)
        hdr_row.addStretch()
        root.addWidget(hdr)

        # Scrollable grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("border:none; background:#121212;")

        self._content = QWidget()
        self._content.setStyleSheet("background:#121212;")
        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(24, 20, 24, 20)
        self._grid.setHorizontalSpacing(20)
        self._grid.setVerticalSpacing(20)

        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_people(self) -> None:
        """Rebuild the grid from the database."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        session = get_session()
        try:
            people = session.query(Person).order_by(Person.name).all()

            if not people:
                no_lbl = QLabel(
                    "No people identified yet.\n"
                    "Click 'Process Faces' in the People sidebar to get started."
                )
                no_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                no_lbl.setStyleSheet("color:#555; font-size:13px; padding:40px;")
                self._grid.addWidget(no_lbl, 0, 0, 1, self._cols)
                return

            cols = max(2, self.width() // 150) if self.width() > 0 else self._cols
            for idx, person in enumerate(people):
                photo_count = (
                    session.query(PhotoPerson)
                    .filter(PhotoPerson.person_id == person.id)
                    .count()
                )
                card = PersonCircle(person, photo_count)
                card.clicked.connect(self.person_clicked.emit)
                self._grid.addWidget(card, idx // cols, idx % cols)
        finally:
            session.close()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Re-layout on width change so cols adapt
        new_cols = max(2, self.width() // 150)
        if new_cols != self._cols:
            self._cols = new_cols
            self.load_people()
