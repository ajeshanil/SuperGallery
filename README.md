# SuperGallery

Fully offline, privacy-first photo gallery desktop app for Windows. All AI processing and data storage happens locally — no cloud, no account required.

## Features

| Feature | Status | Notes |
|---|---|---|
| Photo import + EXIF | ✅ | Date, GPS, camera model, dimensions |
| Gallery grid (sort by month/year) | ✅ | Lazy thumbnail loading |
| Date tags | ✅ | Auto-tagged on import |
| Multi-category search | ✅ | AND across categories, OR within |
| Smart albums | ✅ | Filter-based, stored in DB |
| Object detection | ✅* | YOLOv8 — requires `ultralytics torch` |
| Scene classification | ✅* | MobileNetV3 — requires `torch torchvision` |
| Photo type detection | ✅* | selfie / portrait / group — requires `ultralytics` |
| Face recognition | ✅* | FaceNet clustering — requires `facenet-pytorch scikit-learn` |
| Location map | ✅* | Folium heatmap — requires `folium PyQt6-WebEngine` |
| Folder restructuring | ✅ | By year / month / location / person (virtual + export) |
| Manual tag add/delete | ✅ | Any category, any photo |

*Gracefully disabled if optional deps not installed — app still runs.

## Setup

**Requires Python 3.11–3.13.** Python 3.14 is not yet supported by torch/ultralytics.

```powershell
# Create virtualenv (Python 3.13 recommended)
py -3.13 -m venv .venv
.venv\Scripts\activate

# Core (required)
pip install PyQt6 SQLAlchemy Pillow exifread numpy scikit-learn

# AI features (large downloads — install separately as needed)
pip install ultralytics torch torchvision   # object + scene detection (~2–4 GB)
pip install facenet-pytorch                 # face recognition
pip install folium PyQt6-WebEngine          # interactive map
```

## Running

```powershell
.venv\Scripts\python.exe app\main.py
```

Logs are written to `~/.supergallery/app.log`.

## Usage

1. **Import Folder** — scan a local folder recursively, extract EXIF metadata
2. **Analyse Library** — run YOLOv8 + MobileNetV3 AI tagging on untagged photos
3. **People → Process Faces** — detect and cluster faces across all photos
4. **Map** (left nav) — view GPS heatmap of your library
5. **Albums** (left nav) — create smart albums with tag-based filters
6. **Restructure…** — preview and export folder structure by year/month/location/person
7. Click any photo → edit tags in the right panel

## Data storage

- Database: `~/.supergallery/gallery.db` (SQLite)
- Logs: `~/.supergallery/app.log`
- AI model cache: `~/.supergallery/models/`
- Original photos are **never modified**

## Project structure

```
app/            Entry point (main.py)
database/       SQLAlchemy models + DB connection
models/         AI model wrappers (YOLOv8, MobileNetV3, FaceNet)
ui/             PyQt6 widgets (gallery, tag panel, map, people, albums)
utils/          Business logic (importer, tagger, search, albums, restructure)
tests/          Test suite
```

## Phases

- **Phase 1** — Core gallery, EXIF import, SQLite schema, grid UI
- **Phase 2** — YOLOv8 object detection, MobileNetV3 scene classification, tag panel
- **Phase 3** — FaceNet face recognition, clustering, people panel with rename
- **Phase 4** — Folium interactive map with GPS heatmap
- **Phase 5** — Multi-category search, smart albums, folder restructuring
