"""Single photo thumbnail tile for the gallery grid."""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel


TILE_SIZE = 160
THUMB_SIZE = 150


def _load_thumbnail(file_path: str, size: int) -> QPixmap:
    pix = QPixmap(file_path)
    if pix.isNull():
        pix = QPixmap(size, size)
        pix.fill(QColor("#2a2a2a"))
    return pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


class PhotoTile(QWidget):
    clicked = pyqtSignal(int)   # emits photo_id

    def __init__(self, photo_id: int, file_path: str, date_label: str = "", parent=None):
        super().__init__(parent)
        self.photo_id = photo_id
        self._file_path = file_path
        self._thumb_loaded = False
        self.setFixedSize(TILE_SIZE, TILE_SIZE + 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build(date_label)

    def _build(self, date_label: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(2)

        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet("background:#1e1e1e; border-radius:4px;")
        # Placeholder — real image loads lazily on showEvent
        placeholder = QPixmap(THUMB_SIZE, THUMB_SIZE)
        placeholder.fill(QColor("#2a2a2a"))
        self._thumb_label.setPixmap(placeholder)
        layout.addWidget(self._thumb_label)

        if date_label:
            lbl = QLabel(date_label)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color:#888; font-size:10px;")
            lbl.setMaximumHeight(18)
            layout.addWidget(lbl)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._thumb_loaded:
            self._thumb_loaded = True
            QTimer.singleShot(0, self._load_thumb)

    def _load_thumb(self):
        pix = _load_thumbnail(self._file_path, THUMB_SIZE)
        self._thumb_label.setPixmap(pix)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.photo_id)
        super().mousePressEvent(event)
