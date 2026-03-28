"""Photo detail dialog — full-size photo viewer with object bbox overlay."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QLabel,
    QScrollArea, QSizePolicy,
)

from database.db import get_session
from database.models import ObjectDetection, Photo


# Colour cycle for bbox labels (one per unique label)
_BBOX_COLOURS = [
    "#FF5252", "#448AFF", "#69F0AE", "#FFD740", "#E040FB",
    "#40C4FF", "#FF6D00", "#00E5FF", "#76FF03", "#FF4081",
]


def _colour_for(label: str, _cache: dict = {}) -> str:
    if label not in _cache:
        _cache[label] = _BBOX_COLOURS[len(_cache) % len(_BBOX_COLOURS)]
    return _cache[label]


class _PhotoCanvas(QWidget):
    """Renders a photo and optionally draws YOLO bounding boxes on top."""

    def __init__(
        self,
        pixmap: QPixmap,
        detections: list,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pixmap = pixmap
        self._detections = detections  # list of ObjectDetection ORM objects
        self._show_bboxes = True
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_show_bboxes(self, visible: bool) -> None:
        self._show_bboxes = visible
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._pixmap.isNull():
            painter.fillRect(self.rect(), QColor("#1a1a1a"))
            return

        # Scale to fit widget keeping aspect ratio, centred
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        ox = (self.width() - scaled.width()) // 2
        oy = (self.height() - scaled.height()) // 2
        painter.drawPixmap(ox, oy, scaled)

        if not self._show_bboxes or not self._detections:
            return

        pw, ph = scaled.width(), scaled.height()
        font = QFont()
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)

        for det in self._detections:
            colour = QColor(_colour_for(det.label))
            pen = QPen(colour, 2)
            painter.setPen(pen)

            rx = int(ox + det.bbox_x * pw)
            ry = int(oy + det.bbox_y * ph)
            rw = int(det.bbox_w * pw)
            rh = int(det.bbox_h * ph)
            painter.drawRect(rx, ry, rw, rh)

            conf_pct = f"{int(det.confidence * 100)}%" if det.confidence else ""
            label_text = f" {det.label} {conf_pct} "
            # Semi-transparent label background
            fm = painter.fontMetrics()
            lw = fm.horizontalAdvance(label_text)
            lh = fm.height()
            label_y = max(oy, ry - lh - 2)
            painter.fillRect(rx, label_y, lw, lh + 2, QColor(colour.red(), colour.green(), colour.blue(), 200))
            painter.setPen(QColor("#000000"))
            painter.drawText(rx, label_y + lh, label_text)


class PhotoDetailDialog(QDialog):
    """
    Modal dialog showing a photo at full resolution with an optional
    object-detection bounding-box overlay.

    Usage::
        dlg = PhotoDetailDialog(photo_id, parent=self)
        dlg.exec()
    """

    def __init__(self, photo_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.photo_id = photo_id
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumSize(800, 600)
        self.setStyleSheet("QDialog { background:#121212; } QLabel { color:#e0e0e0; }")

        session = get_session()
        try:
            photo = session.get(Photo, photo_id)
            self._photo_path = photo.file_path if photo else ""
            self._filename = photo.filename if photo else "Photo"
            detections = (
                session.query(ObjectDetection)
                .filter(ObjectDetection.photo_id == photo_id)
                .all()
            )
            # Detach from session for use after close
            self._detections = list(detections)
        finally:
            session.close()

        self.setWindowTitle(self._filename)
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ──────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(44)
        toolbar.setStyleSheet("background:#1a1a1a; border-bottom:1px solid #252525;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(12, 0, 12, 0)
        tb_layout.setSpacing(8)

        name_lbl = QLabel(self._filename)
        name_lbl.setStyleSheet("font-size:13px; font-weight:600; color:#e0e0e0;")
        tb_layout.addWidget(name_lbl)
        tb_layout.addStretch()

        det_count = len(self._detections)
        if det_count:
            self._eye_btn = QPushButton(f"Hide object boxes ({det_count})")
            self._eye_btn.setCheckable(True)
            self._eye_btn.setChecked(False)  # bboxes ON by default
            self._eye_btn.setStyleSheet(
                "QPushButton { background:#1565c0; color:#e0e0e0; border:none;"
                " border-radius:5px; padding:6px 14px; font-size:12px; }"
                "QPushButton:checked { background:#2d2d2d; color:#888; }"
                "QPushButton:hover { background:#1976d2; }"
            )
            self._eye_btn.clicked.connect(self._toggle_bboxes)
            tb_layout.addWidget(self._eye_btn)
        else:
            no_det_lbl = QLabel("No object detections")
            no_det_lbl.setStyleSheet("color:#555; font-size:12px;")
            tb_layout.addWidget(no_det_lbl)

        root.addWidget(toolbar)

        # ── Photo canvas ──────────────────────────────────────────────────
        pixmap = QPixmap(self._photo_path) if self._photo_path and Path(self._photo_path).exists() else QPixmap()
        self._canvas = _PhotoCanvas(pixmap, self._detections)
        self._canvas.setStyleSheet("background:#121212;")
        root.addWidget(self._canvas, stretch=1)

    def _toggle_bboxes(self) -> None:
        hidden = self._eye_btn.isChecked()
        self._canvas.set_show_bboxes(not hidden)
        self._eye_btn.setText(
            f"Show object boxes ({len(self._detections)})" if hidden
            else f"Hide object boxes ({len(self._detections)})"
        )
