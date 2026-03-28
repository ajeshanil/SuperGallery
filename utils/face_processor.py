"""Face processing worker — detection, embedding, and clustering in a QThread."""
import logging
from typing import Optional

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from database.db import get_session
from database.models import Photo, Person, PhotoPerson, Tag
from models.face_recognizer import FaceRecognizer, cluster_embeddings

logger = logging.getLogger(__name__)


def _save_face_thumbnail(session, person: "Person", face_data: tuple) -> None:
    """Crop the best face detection and save it as person.thumbnail_path."""
    photo_id, bbox, _confidence = face_data
    try:
        from PIL import Image, ImageOps
        from pathlib import Path
        photo = session.get(Photo, photo_id)
        if not photo:
            return
        img = Image.open(photo.file_path).convert("RGB")
        # Apply EXIF orientation so saved thumbnails are always upright
        img = ImageOps.exif_transpose(img)
        img_w, img_h = img.size
        x, y, w, h = bbox
        x1 = int(x * img_w)
        y1 = int(y * img_h)
        x2 = int((x + w) * img_w)
        y2 = int((y + h) * img_h)
        # 20% padding so the face isn't cropped too tightly
        pad_x = int((x2 - x1) * 0.2)
        pad_y = int((y2 - y1) * 0.2)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(img_w, x2 + pad_x)
        y2 = min(img_h, y2 + pad_y)
        crop = img.crop((x1, y1, x2, y2)).resize((120, 120), Image.LANCZOS)
        thumb_dir = Path.home() / ".supergallery" / "face_thumbs"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = thumb_dir / f"{person.id}.jpg"
        crop.save(str(thumb_path), format="JPEG", quality=85)
        person.thumbnail_path = str(thumb_path)
    except Exception as exc:
        logger.warning("Could not save face thumbnail for person %d: %s", person.id, exc)


class FaceWorker(QObject):
    """
    QObject for face detection, embedding, and person clustering.
    Intended to be moved to a QThread.

    Signals
    -------
    progress(done, total)  emitted after each photo is processed
    finished(count)        emitted when done; count = number of distinct persons found
    error(message)         emitted on unexpected exceptions
    """

    progress = pyqtSignal(int, int)   # done, total
    finished = pyqtSignal(int)        # number of people identified
    error = pyqtSignal(str)

    def __init__(
        self,
        photo_ids: Optional[list[int]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.photo_ids = photo_ids
        self._cancelled = False

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Request graceful cancellation."""
        self._cancelled = True

    def start_processing(self) -> None:
        """Entry point — connect this to QThread.started."""
        try:
            self._run()
        except Exception as exc:
            logger.exception("FaceWorker encountered an unhandled error")
            self.error.emit(str(exc))

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    def _run(self) -> None:
        session = get_session()
        try:
            # --- 1. Build photo list — skip photos already processed ---
            already_done = {
                r[0] for r in session.query(PhotoPerson.photo_id).distinct()
            }
            query = session.query(Photo).filter(~Photo.id.in_(already_done))
            if self.photo_ids is not None:
                query = query.filter(Photo.id.in_(self.photo_ids))
            photos: list[Photo] = query.all()
            total = len(photos)

            recognizer = FaceRecognizer()

            # Accumulate all face data before clustering.
            # Each entry: (photo_id, bbox_tuple, embedding, confidence)
            all_faces: list[tuple[int, tuple, np.ndarray, float]] = []

            # --- 2. Detect and embed faces in every photo ---
            for done_count, photo in enumerate(photos, start=1):
                if self._cancelled:
                    break

                try:
                    face_results = recognizer.detect_and_embed(photo.file_path)
                except Exception as exc:
                    logger.error(
                        "Face detection failed for photo %d: %s", photo.id, exc
                    )
                    face_results = []

                for face in face_results:
                    all_faces.append((
                        photo.id,
                        face["bbox"],
                        face["embedding"],
                        face["confidence"],
                    ))

                self.progress.emit(done_count, total)

            if not all_faces or self._cancelled:
                self.finished.emit(0)
                return

            # --- 3. Cluster all embeddings ---
            embeddings = [f[2] for f in all_faces]
            labels = cluster_embeddings(embeddings)

            # --- 4. Find or create Person rows per cluster ---
            existing_count = session.query(Person).count()
            cluster_to_person: dict[int, Person] = {}
            person_index = existing_count + 1

            # Pre-compute the highest-confidence face per cluster for thumbnail
            best_face_per_cluster: dict[int, tuple] = {}
            for (pid, bbox, emb, conf), lbl in zip(all_faces, labels):
                if lbl not in best_face_per_cluster or conf > best_face_per_cluster[lbl][2]:
                    best_face_per_cluster[lbl] = (pid, bbox, conf)

            for face_data, cluster_label in zip(all_faces, labels):
                photo_id, bbox, embedding, confidence = face_data

                if cluster_label not in cluster_to_person:
                    person_name = f"Person {person_index}"
                    person_index += 1

                    # Compute mean embedding for faces already seen in this cluster
                    cluster_embeddings_list = [
                        all_faces[i][2]
                        for i, lbl in enumerate(labels)
                        if lbl == cluster_label
                    ]
                    mean_embedding = np.mean(
                        np.stack(cluster_embeddings_list), axis=0
                    )

                    person = Person(
                        name=person_name,
                        embedding_vector=mean_embedding.tobytes(),
                    )
                    session.add(person)
                    session.flush()  # get person.id
                    _save_face_thumbnail(session, person, best_face_per_cluster[cluster_label])
                    cluster_to_person[cluster_label] = person

                person = cluster_to_person[cluster_label]
                x, y, w, h = bbox

                photo_person = PhotoPerson(
                    photo_id=photo_id,
                    person_id=person.id,
                    confidence=confidence,
                    bbox_x=x,
                    bbox_y=y,
                    bbox_w=w,
                    bbox_h=h,
                )
                session.add(photo_person)

                # Mirror into tags table so the tag panel shows people
                session.add(Tag(
                    photo_id=photo_id,
                    label=person.name,
                    category="People",
                    confidence=confidence,
                    is_manual=False,
                ))

            session.commit()
            self.finished.emit(len(cluster_to_person))

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
