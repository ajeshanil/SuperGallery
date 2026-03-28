"""Face detection and recognition using facenet-pytorch.

Key quality controls
--------------------
* EXIF orientation is corrected before detection so portrait-mode photos are
  processed upright — preventing rotated faces from getting different embeddings.
* MTCNN thresholds are tightened ([0.8, 0.9, 0.9]) to suppress false positives
  such as logos, text, or background patches.
* A minimum face-size filter (FACE_MIN_FRACTION of the shorter image dimension)
  skips tiny, probably-spurious detections.
* A minimum face probability (FACE_CONFIDENCE) is applied after MTCNN detection.
"""
import logging
from typing import Optional

import numpy as np

from models.config import FACE_CONFIDENCE, FACE_MIN_FRACTION, FACE_CLUSTER_THRESHOLD

logger = logging.getLogger(__name__)

try:
    from facenet_pytorch import MTCNN, InceptionResnetV1
    import torch
    from PIL import Image as _PILImage, ImageOps as _ImageOps
    _FACENET_AVAILABLE = True
except (ImportError, OSError, Exception) as _e:
    _FACENET_AVAILABLE = False
    logger.warning(
        "facenet-pytorch/torch unavailable (%s). Face recognition will return empty results. "
        "Install with: pip install facenet-pytorch",
        _e,
    )

try:
    from sklearn.cluster import AgglomerativeClustering
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    logger.warning(
        "scikit-learn is not installed. Clustering will fall back to assigning each "
        "face its own cluster. Install with: pip install scikit-learn"
    )


class FaceRecognizer:
    """Face detector and embedder with lazy model loading."""

    def __init__(self, confidence: float = FACE_CONFIDENCE) -> None:
        self.confidence = confidence
        self._mtcnn = None
        self._resnet = None

    def _load(self) -> None:
        """Lazy-load MTCNN and InceptionResnetV1 (vggface2 pretrained)."""
        if self._mtcnn is not None:
            return
        if not _FACENET_AVAILABLE:
            return

        self._mtcnn = MTCNN(
            keep_all=True,
            post_process=False,
            select_largest=False,
            # Larger minimum face size (pixels) avoids tiny artefact detections.
            # At 60 px a face must be at least 60x60 pixels to be considered.
            min_face_size=60,
            # Tighter three-stage thresholds: P-Net, R-Net, O-Net.
            # Default is [0.6, 0.7, 0.7]; raising to [0.8, 0.9, 0.9] cuts false positives
            # like logos, backgrounds, and reflections.
            thresholds=[0.8, 0.9, 0.9],
        )
        self._resnet = InceptionResnetV1(pretrained="vggface2").eval()

    def detect_and_embed(self, image_path: str) -> list[dict]:
        """
        Detect faces and compute 512-d embeddings.

        Returns a list of dicts:
            {
                "bbox": (x, y, w, h),   # fractional 0.0–1.0
                "embedding": np.ndarray, # shape (512,)
                "confidence": float,
            }
        """
        if not _FACENET_AVAILABLE:
            return []

        self._load()
        if self._mtcnn is None or self._resnet is None:
            return []

        try:
            img = _PILImage.open(image_path).convert("RGB")
            # Apply EXIF orientation so portrait-mode shots are upright before
            # detection — otherwise MTCNN sees a rotated face and produces a
            # different embedding than the same face shot in landscape mode,
            # causing the same person to appear as two separate people.
            img = _ImageOps.exif_transpose(img)
        except Exception as exc:
            logger.error("Failed to open image %s: %s", image_path, exc)
            return []

        img_w, img_h = img.size
        # Minimum face dimension: FACE_MIN_FRACTION of shorter image side
        min_dim = min(img_w, img_h) * FACE_MIN_FRACTION

        try:
            boxes, probs = self._mtcnn.detect(img)
        except Exception as exc:
            logger.error("MTCNN detection failed for %s: %s", image_path, exc)
            return []

        if boxes is None or probs is None:
            return []

        results: list[dict] = []
        for box, prob in zip(boxes, probs):
            # ── Quality gate 1: minimum MTCNN probability ──
            if prob is None or float(prob) < self.confidence:
                continue

            x1, y1, x2, y2 = [float(v) for v in box]
            face_w = x2 - x1
            face_h = y2 - y1

            # ── Quality gate 2: minimum face size ──
            if face_w < min_dim or face_h < min_dim:
                logger.debug(
                    "Skipping tiny face %.0fx%.0f (min %.0f) in %s",
                    face_w, face_h, min_dim, image_path,
                )
                continue

            # Fractional bounding box
            fx = x1 / img_w
            fy = y1 / img_h
            fw = face_w / img_w
            fh = face_h / img_h

            # Crop and embed
            try:
                x1_c = max(0, int(x1))
                y1_c = max(0, int(y1))
                x2_c = min(img_w, int(x2))
                y2_c = min(img_h, int(y2))
                face_crop = img.crop((x1_c, y1_c, x2_c, y2_c)).resize((160, 160))

                import torchvision.transforms.functional as TF
                face_tensor = TF.to_tensor(face_crop).unsqueeze(0)
                # Normalize to [-1, 1] as expected by InceptionResnetV1
                face_tensor = (face_tensor - 0.5) / 0.5

                with torch.no_grad():
                    embedding = self._resnet(face_tensor)[0].cpu().numpy()
            except Exception as exc:
                logger.error("Embedding failed for face in %s: %s", image_path, exc)
                continue

            results.append({
                "bbox": (fx, fy, fw, fh),
                "embedding": embedding,
                "confidence": float(prob),
            })

        return results


def cluster_embeddings(
    embeddings: list[np.ndarray],
    threshold: float = FACE_CLUSTER_THRESHOLD,
) -> list[int]:
    """
    Cluster face embeddings using AgglomerativeClustering with cosine distance.

    Parameters
    ----------
    embeddings : list of np.ndarray, each shape (512,)
    threshold  : cosine distance threshold for merging clusters

    Returns
    -------
    list[int] — cluster label (0-based) for each embedding
    """
    if not embeddings:
        return []

    if len(embeddings) == 1:
        return [0]

    if not _SKLEARN_AVAILABLE:
        # Fallback: each face gets its own cluster
        logger.warning(
            "scikit-learn unavailable; assigning each face to its own cluster."
        )
        return list(range(len(embeddings)))

    matrix = np.stack(embeddings)

    try:
        clusterer = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=threshold,
        )
        labels = clusterer.fit_predict(matrix)
        return [int(lbl) for lbl in labels]
    except Exception as exc:
        logger.error("Clustering failed: %s", exc)
        return list(range(len(embeddings)))
