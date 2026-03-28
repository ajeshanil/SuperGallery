"""Scene classification using MIT Places365 ResNet18.

Downloads the ResNet18-Places365 checkpoint (~45 MB) and the category list on
first use, caching both to ~/.supergallery/models/.

Places365 was trained on 1.8 M images spanning 365 real-world scene categories
(beach, mountain, kitchen, street, forest, …) — a much better fit for a photo
gallery than ImageNet-based classifiers.

Reference: http://places2.csail.mit.edu
"""
from __future__ import annotations

import logging
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL_URL = (
    "http://places2.csail.mit.edu/models_places365/resnet18_places365.pth.tar"
)
_CATS_URL = (
    "https://raw.githubusercontent.com/CSAILVision/places365/master/"
    "categories_places365.txt"
)

_MODELS_DIR = Path.home() / ".supergallery" / "models"

try:
    import torch
    import torchvision.models as _tvm
    import torchvision.transforms as _tvt
    from PIL import Image as _PILImage
    _TORCH_AVAILABLE = True
except (ImportError, OSError, Exception) as _e:
    _TORCH_AVAILABLE = False
    logger.warning(
        "torch/torchvision unavailable (%s). Scene classification will return "
        "empty results. Install with: pip install torch torchvision pillow",
        _e,
    )


def _fetch(url: str, dest: Path) -> None:
    """Download *url* to *dest* with a simple progress log."""
    logger.info("Downloading %s → %s …", url, dest)
    urllib.request.urlretrieve(url, str(dest))
    logger.info("Download complete: %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)


def _load_categories(cats_path: Path) -> list[str]:
    """Parse Places365 category file into clean human-readable labels.

    The file format is::

        /a/airfield 0
        /a/alcove 1
        /a/airport_terminal 2
        ...

    We parse the numeric index explicitly and sort by it so the returned list is
    always correctly ordered regardless of line order in the file.
    """
    entries: list[tuple[int, str]] = []
    with open(cats_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ")
            if len(parts) < 2:
                continue
            try:
                idx = int(parts[-1])
            except ValueError:
                continue
            raw = parts[0]   # e.g. /a/airfield  or /f/forest/broadleaf
            # Strip leading /x/ letter-bucket prefix, keep meaningful parts
            path_parts = [p for p in raw.split("/") if p and len(p) > 1]
            label = path_parts[-1].replace("_", " ") if path_parts else raw
            entries.append((idx, label))

    # Sort by class index to guarantee correct model↔label alignment
    entries.sort(key=lambda t: t[0])
    return [label for _, label in entries]


class SceneClassifier:
    """MIT Places365 ResNet18 scene classifier with lazy model loading."""

    def __init__(
        self,
        confidence: float = 0.10,
        top_k: int = 3,
    ) -> None:
        self.confidence = confidence
        self.top_k = top_k
        self._model: Optional[object] = None
        self._transform: Optional[object] = None
        self._classes: list[str] = []

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if self._model is not None:
            return
        if not _TORCH_AVAILABLE:
            return

        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        model_path = _MODELS_DIR / "resnet18_places365.pth.tar"
        cats_path  = _MODELS_DIR / "categories_places365.txt"

        if not cats_path.exists():
            _fetch(_CATS_URL, cats_path)
        if not model_path.exists():
            _fetch(_MODEL_URL, model_path)

        self._classes = _load_categories(cats_path)

        import torch
        import torchvision.models as tvm
        import torchvision.transforms as tvt

        # ResNet18 with 365 output classes
        model = tvm.resnet18(weights=None)
        model.fc = torch.nn.Linear(model.fc.in_features, 365)

        checkpoint = torch.load(str(model_path), map_location="cpu", weights_only=False)
        state_dict = {
            k.replace("module.", ""): v
            for k, v in checkpoint["state_dict"].items()
        }
        model.load_state_dict(state_dict)
        model.eval()
        self._model = model

        self._transform = tvt.Compose([
            tvt.Resize((256, 256)),
            tvt.CenterCrop(224),
            tvt.ToTensor(),
            tvt.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

    # ------------------------------------------------------------------
    def classify(self, image_path: str) -> list[dict]:
        """Return up to *top_k* scene labels above *confidence* threshold."""
        if not _TORCH_AVAILABLE:
            return []

        self._load()
        if self._model is None:
            return []

        try:
            img = _PILImage.open(image_path).convert("RGB")
        except Exception as exc:
            logger.error("Failed to open %s: %s", image_path, exc)
            return []

        try:
            import torch
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
            results.append({
                "label":      self._classes[idx],
                "confidence": round(prob, 4),
            })
        return results
