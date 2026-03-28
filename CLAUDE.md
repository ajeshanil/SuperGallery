# SuperGallery — Claude Project Context

## What this is
Offline-first personal photo gallery with AI tagging, face recognition, and map view.
FastAPI backend + vanilla JS SPA frontend. Designed to run locally and be wrapped as a mobile app (Capacitor/PWA) later.

## Run the app
```bash
.venv/Scripts/python.exe app/server.py   # opens http://localhost:8432
```

## Architecture
```
app/
  api.py          FastAPI backend — all REST endpoints + SSE progress stream
  server.py       uvicorn entry point (opens browser automatically)
  static/
    index.html    SPA shell (single HTML file, no build step)
    style.css     Mobile-first dark theme, CSS variables for theming
    app.js        Vanilla JS SPA — all interactivity, no framework

database/
  models.py       SQLAlchemy ORM: Photo, Tag, Person, PhotoPerson, ObjectDetection, Location
  db.py           Engine + session factory, DB at ~/.supergallery/gallery.db

models/
  object_detector.py    YOLOv8 object detection
  scene_classifier.py   MobileNetV3 scene classification
  face_recognizer.py    MTCNN + InceptionResnetV1 face embedding + clustering

utils/
  importer.py     Scan folder → extract EXIF → create Photo + metadata Tags
  tagger.py       Run object/scene AI → create Tags + ObjectDetection rows
  face_processor.py     Face detection → embedding → cluster → Person + face thumbnail
  search.py       Multi-category filter logic used by /api/photos
  map_builder.py  folium map HTML from Location rows

ui/               Legacy PyQt6 UI — superseded, kept for reference
```

## Data flow
1. **Import** → scans folder, extracts EXIF, creates `Photo` + `Tag` (Date/Camera/PhotoType/Location) rows
2. **Auto-thumbnail** → pre-generates `~/.supergallery/thumbs/{id}_220.jpg` for all photos
3. **AI Analysis** → YOLOv8 objects + MobileNet scenes → `Tag` + `ObjectDetection` rows
4. **Face Processing** → MTCNN detect → InceptionResnet embed → AgglomerativeClustering → `Person` + `PhotoPerson` + face thumbnail at `~/.supergallery/face_thumbs/{id}.jpg`

Import auto-chains: Import → Thumbnails → AI Analysis → Face Processing (if person objects found)

## Key API endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/photos` | Paginated photo list; `filters` param is JSON `{category: [labels]}` |
| GET | `/api/photos/{id}/thumb` | On-demand thumbnail (cached to disk) |
| GET | `/api/photos/{id}/detections` | Bounding boxes `[{label, confidence, bbox:[x,y,w,h]}]` |
| GET | `/api/people` | All persons with `has_thumb`, `photo_count` |
| GET | `/api/people/similar` | Similar-face pairs (only when both have thumbnails) |
| POST | `/api/people/merge` | Merge two Person records |
| POST | `/api/people/{id}/rename` | Rename person + update all their Tags |
| GET | `/api/map` | Returns folium HTML → loaded in `<iframe>` |
| GET | `/api/status/stream` | SSE: `{running, operation, op_label, done, total, message}` |
| POST | `/api/import` | Start import `{folder: "C:\\..."}` |
| POST | `/api/analyze` | Start AI tagging |
| POST | `/api/faces` | Start face processing |
| POST | `/api/admin/gen-thumbs` | Pre-generate all thumbnails |

## UI conventions
- CSS variable `--tile-size` controls photo grid tile size (slider 80–300px, saved to localStorage)
- `body.progress-active` shifts `#layout` down by 28px to make room for progress info bar
- Tags use `label` field (not `value`). Categories: People, Objects, Scenes, Camera, PhotoType, Date, Location
- `/api/people/similar` returns `{person_a: id, name_a, person_b: id, name_b, similarity}`
- Detections `bbox` is `[x, y, w, h]` as fraction of image dimensions (0–1)
- Same/diff bar only shows when both persons have face thumbnails on disk

## Important behaviours
- `setAutoDelete(False)` on Qt QRunnable prevents GC crash (legacy UI, kept for reference)
- `/api/people/similar` route MUST be defined before `/api/people/{person_id}/...` in FastAPI
- Face thumbnails at `~/.supergallery/face_thumbs/{person_id}.jpg`; `has_thumb` in `/api/people` checks file existence
- Tile-size slider persists to `localStorage('tileSize')`

## Dev notes
- No build step — edit HTML/CSS/JS directly, browser reload is instant
- DB is SQLite at `~/.supergallery/gallery.db`; delete to reset
- Thumbs cache at `~/.supergallery/thumbs/`; safe to delete (regenerated on demand)
- All AI models are downloaded on first use to `~/.supergallery/models/`
