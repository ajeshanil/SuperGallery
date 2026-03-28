"""Shared model configuration."""
from pathlib import Path

MODELS_DIR = Path.home() / ".supergallery" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Confidence threshold for object detection (0.0–1.0)
# 0.35 catches phones, food, cameras etc. without too many false positives
DEFAULT_CONFIDENCE = 0.35

# Confidence threshold for scene classification
# Places365 softmax probs are low; 0.25 keeps only reasonably confident scene labels
SCENE_CONFIDENCE = 0.25

# Minimum MTCNN face detection probability to accept as a real face (0.0–1.0)
# MTCNN probs are very high (0.999+) for genuine faces; 0.95 aggressively rejects
# non-face detections like text, logos, or blurry background patches.
FACE_CONFIDENCE = 0.95

# Minimum face size as a fraction of the shorter image dimension.
# Faces smaller than this are usually background artefacts, not people.
FACE_MIN_FRACTION = 0.04   # 4 % of shorter image dimension

# Face clustering: maximum cosine distance to merge two faces into the same cluster.
# InceptionResnetV1(vggface2) genuine pairs ~0.2–0.4; impostors ~0.5–1.0.
# 0.45 keeps most same-person variations while preventing different-person merges.
FACE_CLUSTER_THRESHOLD = 0.45

# Incremental face matching: maximum cosine distance to accept an existing Person
# as the identity for a new face embedding.
FACE_MATCH_THRESHOLD = 0.40

# YOLOv8 model size: n=nano, s=small, m=medium
YOLO_MODEL_SIZE = "n"
