"""SuperGallery — entry point."""
import os
import sys
import logging
from pathlib import Path

# Ensure repo root is on sys.path when running as `python app/main.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Suppress Qt's CSS parser warnings about unsupported properties (e.g. overflow)
# Must be set before Qt is imported.
os.environ.setdefault("QT_LOGGING_RULES", "qt.gui.styleparser.warning=false")

_LOG_DIR = Path.home() / ".supergallery"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "app.log", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
# Suppress verbose PIL/pillow debug noise
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("PIL.TiffImagePlugin").setLevel(logging.WARNING)

# Pre-load torch before Qt to avoid DLL search path conflicts on Windows.
# Qt loads its own native DLLs at import time, which can disrupt torch's
# c10.dll resolution when ultralytics imports torch later.
try:
    import torch as _torch  # noqa: F401
except Exception:
    pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from database.db import init_db
from ui.gallery_window import GalleryWindow


def main():
    init_db()
    app = QApplication(sys.argv)
    app.setApplicationName("SuperGallery")
    app.setOrganizationName("SuperGallery")

    window = GalleryWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
