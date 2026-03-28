"""Face detection and recognition using facenet-pytorch."""
import logging
from typing import Optional

import numpy as np

from models.config import DEFAULT_CONFIDENCE

logger = logging.getLogger(__name__)

try:
    from facenet_pytorch import MTCNN, InceptionResnetV1
    import torch
    from PIL import Image as _PILImage
    _FACENET_AVAILABLE = True
except ImportError:
    _FACENET_AVAILABLE = False
    logger.warning(
        "facenet-pytorch is not installed. Face recognition will return empty results. "
        "Install with: pip install facenet-pytorch"
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

    def __init__(self, confidence: float = DEFAULT_CONFIDENCE) -> None:
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
        except Exception as exc:
            logger.error("Failed to open image %s: %s", image_path, exc)
            return []

        img_w, img_h = img.size

        try:
            boxes, probs = self._mtcnn.detect(img)
        except Exception as exc:
            logger.error("MTCNN detection failed for %s: %s", image_path, exc)
            return []

        if boxes is None or probs is None:
            return []

        results: list[dict] = []
        for box, prob in zip(boxes, probs):
            if prob is None or float(prob) < self.confidence:
                continue

            x1, y1, x2, y2 = [float(v) for v in box]

            # Fractional bounding box
            fx = x1 / img_w
            fy = y1 / img_h
            fw = (x2 - x1) / img_w
            fh = (y2 - y1) / img_h

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
    threshold: float = 0.7,
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
