"""AI tagging worker — runs object detection and scene classification in a QThread."""
import logging
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from database.db import get_session
from database.models import Photo, Tag
from models.object_detector import ObjectDetector
from models.scene_classifier import SceneClassifier
from models.config import DEFAULT_CONFIDENCE

logger = logging.getLogger(__name__)

# Categories written by the AI tagger — used to detect "already tagged" photos.
_AI_CATEGORIES = ("Objects", "Scenes", "PhotoType")


class TagWorker(QObject):
    """
    QObject that performs AI tagging and is meant to be moved to a QThread.

    Signals
    -------
    progress(done, total)   emitted after each photo is processed
    photo_tagged(photo_id)  emitted after tags are committed for a photo
    finished(count)         emitted when all work is done; count = photos tagged
    error(message)          emitted on unexpected exceptions
    """

    progress = pyqtSignal(int, int)    # done, total
    photo_tagged = pyqtSignal(int)     # photo_id
    finished = pyqtSignal(int)         # count tagged
    error = pyqtSignal(str)

    def __init__(
        self,
        confidence: float = DEFAULT_CONFIDENCE,
        photo_ids: Optional[list[int]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.confidence = confidence
        self.photo_ids = photo_ids
        self._cancelled = False

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Request graceful cancellation. The worker checks this flag between photos."""
        self._cancelled = True

    def start_tagging(self) -> None:
        """Entry point — connect this to QThread.started."""
        try:
            self._run()
        except Exception as exc:
            logger.exception("TagWorker encountered an unhandled error")
            self.error.emit(str(exc))

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    def _run(self) -> None:
        session = get_session()
        try:
            # --- 1. Determine which photos need tagging ---
            # A photo is considered untagged if it has no tags in any AI category.
            tagged_photo_ids_subq = (
                session.query(Tag.photo_id)
                .filter(Tag.category.in_(_AI_CATEGORIES))
                .subquery()
            )
            query = session.query(Photo).filter(
                ~Photo.id.in_(tagged_photo_ids_subq)
            )
            if self.photo_ids is not None:
                query = query.filter(Photo.id.in_(self.photo_ids))

            photos: list[Photo] = query.all()
            total = len(photos)
            done = 0

            # --- 2. Lazy-initialise models once ---
            detector = ObjectDetector(confidence=self.confidence)
            classifier = SceneClassifier(confidence=self.confidence)

            for photo in photos:
                if self._cancelled:
                    break

                file_path = photo.file_path

                # --- 3. Object detection ---
                try:
                    detections = detector.detect(file_path)
                except Exception as exc:
                    logger.error("Object detection failed for photo %d: %s", photo.id, exc)
                    detections = []

                for det in detections:
                    tag = Tag(
                        photo_id=photo.id,
                        label=det["label"],
                        category="Objects",
                        confidence=det["confidence"],
                        is_manual=False,
                    )
                    session.add(tag)

                # --- 4. Scene classification ---
                try:
                    scenes = classifier.classify(file_path)
                except Exception as exc:
                    logger.error("Scene classification failed for photo %d: %s", photo.id, exc)
                    scenes = []

                for scene in scenes:
                    tag = Tag(
                        photo_id=photo.id,
                        label=scene["label"],
                        category="Scenes",
                        confidence=scene["confidence"],
                        is_manual=False,
                    )
                    session.add(tag)

                # --- 5. Photo type inference ---
                try:
                    photo_type = detector.infer_photo_type(detections)
                except Exception as exc:
                    logger.error("Photo type inference failed for photo %d: %s", photo.id, exc)
                    photo_type = None

                if photo_type is not None:
                    tag = Tag(
                        photo_id=photo.id,
                        label=photo_type,
                        category="PhotoType",
                        confidence=None,
                        is_manual=False,
                    )
                    session.add(tag)

                # --- 6. Commit after each photo ---
                session.commit()

                done += 1
                self.photo_tagged.emit(photo.id)
                self.progress.emit(done, total)

            self.finished.emit(done)

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
