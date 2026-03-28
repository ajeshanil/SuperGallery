"""YOLOv8 object detection wrapper."""
import logging
from pathlib import Path
from typing import Optional

from models.config import DEFAULT_CONFIDENCE, MODELS_DIR

logger = logging.getLogger(__name__)

try:
    from ultralytics import YOLO as _YOLO
    _ULTRALYTICS_AVAILABLE = True
except (ImportError, OSError, Exception) as _e:
    _ULTRALYTICS_AVAILABLE = False
    logger.warning(
        "ultralytics/torch unavailable (%s). Object detection will return empty results. "
        "Install with: pip install ultralytics",
        _e,
    )


class ObjectDetector:
    """YOLOv8-based object detector with lazy model loading."""

    def __init__(self, confidence: float = DEFAULT_CONFIDENCE) -> None:
        self.confidence = confidence
        self._model = None

    def _load(self) -> None:
        """Lazy-load the YOLOv8 model. Downloads yolov8n.pt on first use."""
        if self._model is not None:
            return
        if not _ULTRALYTICS_AVAILABLE:
            return
        print("Loading YOLOv8...")
        model_path = MODELS_DIR / "yolov8n.pt"
        self._model = _YOLO(str(model_path))

    def detect(self, image_path: str) -> list[dict]:
        """
        Run object detection on the given image.

        Returns a list of dicts:
            {"label": str, "confidence": float, "bbox": (x, y, w, h)}
        where bbox coordinates are fractional (0.0–1.0) relative to image size.
        """
        if not _ULTRALYTICS_AVAILABLE:
            return []

        self._load()
        if self._model is None:
            return []

        try:
            results = self._model(
                image_path,
                conf=self.confidence,
                verbose=False,
            )
        except Exception as exc:
            logger.error("YOLOv8 inference failed for %s: %s", image_path, exc)
            return []

        detections: list[dict] = []
        for result in results:
            img_w = result.orig_shape[1]
            img_h = result.orig_shape[0]
            if img_w == 0 or img_h == 0:
                continue

            boxes = result.boxes
            if boxes is None:
                continue

            for box in boxes:
                conf = float(box.conf[0])
                if conf < self.confidence:
                    continue

                cls_id = int(box.cls[0])
                label = result.names.get(cls_id, str(cls_id))

                # xyxy absolute coords
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                x = x1 / img_w
                y = y1 / img_h
                w = (x2 - x1) / img_w
                h = (y2 - y1) / img_h

                detections.append({
                    "label": label,
                    "confidence": conf,
                    "bbox": (x, y, w, h),
                })

        return detections

    def infer_photo_type(self, detections: list[dict]) -> Optional[str]:
        """
        Infer a high-level photo type from detection results.

        Returns:
            "selfie"      if exactly 1 person with bounding-box area > 0.4
            "portrait"    if exactly 1 person
            "group photo" if 2 or more persons
            None          otherwise
        """
        persons = [d for d in detections if d["label"].lower() == "person"]

        if len(persons) == 0:
            return None

        if len(persons) >= 2:
            return "Group photo"

        # Exactly one person
        bbox = persons[0]["bbox"]
        area = bbox[2] * bbox[3]  # w * h
        if area > 0.4:
            return "Selfie"
        return "Portrait"
