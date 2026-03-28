"""SuperGallery web server — run with:  python app/server.py [--test [N]]

Flags
-----
--test [N]   Test mode: limit AI analysis and face processing to the first N
             photos (default 30). Useful for quick iteration without waiting
             for the full library to be processed.
"""
import os
import sys
import argparse
import webbrowser
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Suppress Qt CSS warnings that may appear from any remaining Qt imports
os.environ.setdefault("QT_LOGGING_RULES", "qt.gui.styleparser.warning=false")

# Pre-load AI libraries in the main thread before uvicorn spins up worker threads.
# On Windows, DLL initialisation fails when a DLL is first loaded from a non-main
# thread — importing here ensures all torch/ultralytics/facenet DLLs are resident
# in the process before any background task tries to use them.
try:
    import torch as _torch  # noqa: F401
except Exception:
    pass
try:
    from ultralytics import YOLO as _YOLO  # noqa: F401
except Exception:
    pass
try:
    import torchvision as _tv  # noqa: F401
except Exception:
    pass
try:
    from facenet_pytorch import MTCNN as _MTCNN  # noqa: F401
except Exception:
    pass

import uvicorn

PORT = 8432
URL  = f"http://localhost:{PORT}"


def _open_browser():
    import time
    time.sleep(1.2)          # wait for uvicorn to be ready
    webbrowser.open(URL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SuperGallery server")
    parser.add_argument(
        "--test", nargs="?", const=30, type=int, metavar="N",
        help="Test mode: limit AI analysis to first N photos (default 30)",
    )
    args = parser.parse_args()

    if args.test is not None:
        os.environ["SG_TEST_LIMIT"] = str(args.test)
        print(f"\n  ⚠  TEST MODE — AI analysis limited to first {args.test} photos\n")

    threading.Thread(target=_open_browser, daemon=True).start()
    print(f"\n  SuperGallery running at {URL}\n")
    uvicorn.run(
        "app.api:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="warning",
    )
