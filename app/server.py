"""SuperGallery web server — run with:  python app/server.py"""
import os
import sys
import webbrowser
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Suppress Qt CSS warnings that may appear from any remaining Qt imports
os.environ.setdefault("QT_LOGGING_RULES", "qt.gui.styleparser.warning=false")

# Pre-load torch before anything Qt-related to avoid DLL conflicts on Windows
try:
    import torch as _torch  # noqa: F401
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
    threading.Thread(target=_open_browser, daemon=True).start()
    print(f"\n  SuperGallery running at {URL}\n")
    uvicorn.run(
        "app.api:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="warning",
    )
