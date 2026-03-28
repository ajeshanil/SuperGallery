"""Scene classification using torchvision MobileNetV3-Large (ImageNet pretrained)."""
import logging
from typing import Optional

from models.config import DEFAULT_CONFIDENCE

logger = logging.getLogger(__name__)

try:
    import torch
    from torchvision import models, transforms
    from torchvision.models import MobileNet_V3_Large_Weights
    from PIL import Image as _PILImage
    _TORCH_AVAILABLE = True
except (ImportError, OSError, Exception) as _e:
    _TORCH_AVAILABLE = False
    logger.warning(
        "torch/torchvision unavailable (%s). Scene classification will return empty results. "
        "Install with: pip install torch torchvision pillow",
        _e,
    )

# Maps substrings of ImageNet class names to human-readable scene categories.
_IMAGENET_TO_SCENE: dict[str, str] = {
    # nature / outdoor
    "seashore": "beach",
    "beach": "beach",
    "reef": "underwater",
    "alp": "mountain",
    "volcano": "mountain",
    "cliff": "mountain",
    "valley": "landscape",
    "lakeside": "waterside",
    "dock": "waterside",
    "tree": "forest",
    "jungle": "forest",
    "rainforest": "forest",
    "desert": "desert",
    "dune": "desert",
    "snowfield": "snowy",
    "ski": "snowy",
    "sky": "sky",
    "cloud": "sky",
    # urban / built
    "street": "urban",
    "traffic": "urban",
    "bridge": "urban",
    "building": "urban",
    "skyscraper": "urban",
    "restaurant": "indoor",
    "library": "indoor",
    "classroom": "indoor",
    "gym": "indoor",
    "kitchen": "indoor",
    "bedroom": "indoor",
    "office": "indoor",
    "bookcase": "indoor",
    # transport
    "airport": "transport",
    "train": "transport",
}


def _map_class_to_scene(class_name: str) -> str:
    """
    Map an ImageNet class name to a scene category.
    Checks whether any key in _IMAGENET_TO_SCENE is a substring of class_name
    (case-insensitive). Returns the first match or the raw class name.
    """
    lower = class_name.lower()
    for key, scene in _IMAGENET_TO_SCENE.items():
        if key in lower:
            return scene
    return class_name


class SceneClassifier:
    """MobileNetV3-Large scene classifier with lazy model loading."""

    def __init__(
        self,
        confidence: float = DEFAULT_CONFIDENCE,
        top_k: int = 3,
    ) -> None:
        self.confidence = confidence
        self.top_k = top_k
        self._model = None
        self._transform = None
        self._class_names: list[str] = []

    def _load(self) -> None:
        """Lazy-load the MobileNetV3-Large model in eval mode."""
        if self._model is not None:
            return
        if not _TORCH_AVAILABLE:
            return

        weights = MobileNet_V3_Large_Weights.IMAGENET1K_V2
        self._model = models.mobilenet_v3_large(weights=weights)
        self._model.eval()

        self._transform = weights.transforms()
        self._class_names = weights.meta["categories"]

    def classify(self, image_path: str) -> list[dict]:
        """
        Classify the scene in an image.

        Returns up to top_k results as:
            [{"label": str, "confidence": float}, ...]
        Only results meeting the confidence threshold are included.
        """
        if not _TORCH_AVAILABLE:
            return []

        self._load()
        if self._model is None:
            return []

        try:
            img = _PILImage.open(image_path).convert("RGB")
        except Exception as exc:
            logger.error("Failed to open image %s: %s", image_path, exc)
            return []

        try:
            tensor = self._transform(img).unsqueeze(0)
            with torch.no_grad():
                logits = self._model(tensor)
            probs = torch.softmax(logits, dim=1)[0]
        except Exception as exc:
            logger.error("Scene classification failed for %s: %s", image_path, exc)
            return []

        top_probs, top_indices = torch.topk(probs, k=min(self.top_k, len(probs)))

        results: list[dict] = []
        for prob, idx in zip(top_probs.tolist(), top_indices.tolist()):
            if prob < self.confidence:
                continue
            raw_name = self._class_names[idx]
            scene_label = _map_class_to_scene(raw_name)
            results.append({"label": scene_label, "confidence": round(prob, 4)})

        return results
