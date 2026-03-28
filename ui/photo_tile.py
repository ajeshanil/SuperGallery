"""Single photo thumbnail tile for the gallery grid."""
import io

from PyQt6.QtCore import Qt, QRunnable, QThreadPool, QObject, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor, QImage
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel


TILE_SIZE = 160
THUMB_SIZE = 150


class _ThumbSignals(QObject):
    loaded = pyqtSignal(QImage)


class _ThumbLoader(QRunnable):
    """Loads and resizes an image on a thread-pool thread using PIL."""

    def __init__(self, file_path: str, size: int):
        super().__init__()
        self.file_path = file_path
        self.size = size
        self.signals = _ThumbSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            from PIL import Image
            img = Image.open(self.file_path)
            # .draft() tells PIL to decode at a smaller size (big JPEG speed-up)
            img.draft("RGB", (self.size, self.size))
            img.thumbnail((self.size, self.size), Image.BILINEAR)
            if img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            qimg = QImage.fromData(buf.getvalue())
        except Exception:
            qimg = QImage()
        self.signals.loaded.emit(qimg)


class PhotoTile(QWidget):
    clicked = pyqtSignal(int)   # emits photo_id

    def __init__(self, photo_id: int, file_path: str, date_label: str = "", parent=None):
        super().__init__(parent)
        self.photo_id = photo_id
        self._file_path = file_path
        self._thumb_loaded = False
        self._loader = None  # holds Python ref to prevent GC while thread runs
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
            self._loader = _ThumbLoader(self._file_path, THUMB_SIZE)
            # setAutoDelete(False): Python owns the object; Qt won't delete it after run().
            # This prevents the GC from collecting _ThumbLoader (and its _ThumbSignals)
            # while the worker thread is still executing.
            self._loader.setAutoDelete(False)
            self._loader.signals.loaded.connect(self._on_thumb_loaded)
            QThreadPool.globalInstance().start(self._loader)

    def _on_thumb_loaded(self, qimg: QImage):
        self._loader = None  # safe to release now — run() has finished
        pix = QPixmap.fromImage(qimg) if not qimg.isNull() else _blank_pixmap()
        try:
            self._thumb_label.setPixmap(pix)
        except RuntimeError:
            pass  # widget was already deleted (grid re-rendered)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.photo_id)
        super().mousePressEvent(event)


def _blank_pixmap() -> QPixmap:
    pix = QPixmap(THUMB_SIZE, THUMB_SIZE)
    pix.fill(QColor("#2a2a2a"))
    return pix
