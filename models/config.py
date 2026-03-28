"""Shared model configuration."""
from pathlib import Path

MODELS_DIR = Path.home() / ".supergallery" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Confidence threshold for AI tags (0.0–1.0)
DEFAULT_CONFIDENCE = 0.75

# YOLOv8 model size: n=nano, s=small, m=medium
YOLO_MODEL_SIZE = "n"
