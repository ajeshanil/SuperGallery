"""
SuperGallery — main window (Phases 1–5 integrated).

Layout
──────
┌─ Toolbar ────────────────────────────────────────────────────────────────┐
│ Title  │  SearchBar  │  Sort ▾  │ Import  │ Analyse  │ Restructure…      │
├─ progress bar (4 px, hidden) ────────────────────────────────────────────┤
│                                                                           │
│  ┌─ Left sidebar 200px ─┐  ┌─ Center (stacked) ──────┐  ┌─ Tag panel ─┐ │
│  │  ● All Photos        │  │  Gallery grid  / Map     │  │  Tags for   │ │
│  │  ● Map               │  │  / People / Albums       │  │  selected   │ │
│  │  ● People            │  │                          │  │  photo      │ │
│  │  ● Albums            │  │                          │  │             │ │
│  │  ─────────────────── │  │                          │  │             │ │
│  │  [people / album     │  │                          │  │             │ │
│  │   detail panels]     │  │                          │  │             │ │
│  └──────────────────────┘  └──────────────────────────┘  └─────────────┘ │
└───────────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

from collections import defaultdict

from PyQt6.QtCore import Qt, QThread, pyqtSlot
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QScrollArea, QLabel, QPushButton, QComboBox, QFileDialog,
    QProgressBar, QFrame, QGridLayout, QMessageBox, QStatusBar,
    QStackedWidget, QSizePolicy,
)

from database.db import get_session
from database.models import Photo, Person
from utils.importer import ImportWorker
from utils.tagger import TagWorker
from utils.face_processor import FaceWorker
from utils.search import search_photos
from utils.album_manager import get_album_photos
from .photo_tile import PhotoTile, TILE_SIZE
from .tag_panel import TagPanel
from .people_panel import PeoplePanel
from .album_panel import AlbumPanel
from .map_view import MapView
from .search_bar import SearchBar
from .restructure_dialog import RestructureDialog


SORT_OPTIONS = [
    ("Month (newest first)", "month_desc"),
    ("Month (oldest first)", "month_asc"),
    ("Year (newest first)", "year_desc"),
    ("Year (oldest first)", "year_asc"),
]

# Left nav page indices
_NAV_GALLERY  = 0
_NAV_MAP      = 1
_NAV_PEOPLE   = 2
_NAV_ALBUMS   = 3

# Center stack page indices
_CENTER_GALLERY = 0
_CENTER_MAP     = 1


class GalleryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SuperGallery")
        self.setMinimumSize(1100, 680)

        # active worker threads
        self._import_thread: QThread | None = None
        self._import_worker: ImportWorker | None = None
        self._tag_thread: QThread | None = None
        self._tag_worker: TagWorker | None = None
        self._face_thread: QThread | None = None
        self._face_worker: FaceWorker | None = None

        self._sort_mode = "month_desc"
        self._active_filters: dict = {}
        self._selected_photo_id: int | None = None
        self._active_nav = _NAV_GALLERY

        # Debounce resize so we don't re-render on every pixel
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(250)
        self._resize_timer.timeout.connect(self._do_deferred_render)

        self._setup_styles()
        self._setup_ui()
        self._load_photos()

    # ──────────────────────────────────────────────────────────────────────────
    # Style
    # ──────────────────────────────────────────────────────────────────────────

    def _setup_styles(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #121212; color: #e0e0e0; }
            QPushButton {
                background: #2d2d2d; color: #e0e0e0; border: 1px solid #3a3a3a;
                border-radius: 5px; padding: 6px 14px; font-size: 13px;
            }
            QPushButton:hover { background: #3a3a3a; }
            QPushButton:disabled { color: #555; border-color: #2a2a2a; }
            QPushButton#importBtn  { background: #1565c0; border-color: #1976d2; }
            QPushButton#importBtn:hover  { background: #1976d2; }
            QPushButton#analyseBtn { background: #1b5e20; border-color: #2e7d32; }
            QPushButton#analyseBtn:hover { background: #2e7d32; }
            QPushButton#navBtn {
                background: transparent; border: none; border-radius: 6px;
                text-align: left; padding: 8px 12px; font-size: 13px; color: #aaa;
            }
            QPushButton#navBtn:hover  { background: #2a2a2a; color: #e0e0e0; }
            QPushButton#navBtn[active="true"] {
                background: #1e2a3a; color: #4fc3f7; font-weight: 600;
            }
            QComboBox {
                background: #2d2d2d; color: #e0e0e0; border: 1px solid #3a3a3a;
                border-radius: 5px; padding: 5px 10px; font-size: 13px; min-width: 160px;
            }
            QComboBox QAbstractItemView { background: #2d2d2d; color: #e0e0e0; selection-background-color: #1976d2; }
            QScrollArea { border: none; }
            QLabel#groupHeader {
                font-size: 12px; font-weight: 600; color: #888;
                padding: 10px 0 4px 4px; letter-spacing: 0.05em;
            }
            QProgressBar {
                background: #2d2d2d; border: none; border-radius: 2px; height: 4px;
            }
            QProgressBar::chunk { background: #1976d2; border-radius: 2px; }
            QSplitter::handle { background: #2a2a2a; width: 1px; }
        """)

    # ──────────────────────────────────────────────────────────────────────────
    # UI build
    # ──────────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.hide()
        root.addWidget(self.progress_bar)

        root.addWidget(self._build_search_bar())
        root.addWidget(self._build_main_splitter(), 1)

        self.status = QStatusBar()
        self.status.setStyleSheet("background:#1a1a1a; color:#666; font-size:12px; padding: 0 8px;")
        self.setStatusBar(self.status)

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setFixedHeight(52)
        toolbar.setStyleSheet("background:#1a1a1a; border-bottom:1px solid #252525;")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(8)

        title = QLabel("SuperGallery")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#e0e0e0; margin-right:8px;")
        layout.addWidget(title)
        layout.addStretch()

        sort_lbl = QLabel("Sort:")
        sort_lbl.setStyleSheet("color:#666; font-size:12px;")
        layout.addWidget(sort_lbl)

        self.sort_combo = QComboBox()
        for label, value in SORT_OPTIONS:
            self.sort_combo.addItem(label, value)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        layout.addWidget(self.sort_combo)

        import_btn = QPushButton("Import Folder")
        import_btn.setObjectName("importBtn")
        import_btn.clicked.connect(self._on_import)
        layout.addWidget(import_btn)

        self.analyse_btn = QPushButton("Analyse Library")
        self.analyse_btn.setObjectName("analyseBtn")
        self.analyse_btn.clicked.connect(self._on_analyse)
        layout.addWidget(self.analyse_btn)

        restructure_btn = QPushButton("Restructure…")
        restructure_btn.clicked.connect(self._on_restructure)
        layout.addWidget(restructure_btn)

        return toolbar

    def _build_search_bar(self) -> QWidget:
        self.search_bar = SearchBar()
        self.search_bar.search_changed.connect(self._on_search_changed)
        wrapper = QWidget()
        wrapper.setFixedHeight(44)
        wrapper.setStyleSheet("background:#161616; border-bottom:1px solid #252525;")
        lay = QHBoxLayout(wrapper)
        lay.setContentsMargins(16, 4, 16, 4)
        lay.addWidget(self.search_bar)
        return wrapper

    def _build_main_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # ── Left sidebar ──────────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet("background:#161616; border-right:1px solid #252525;")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(8, 12, 8, 12)
        sb_layout.setSpacing(2)

        self._nav_buttons: dict[int, QPushButton] = {}
        for nav_id, label, icon in [
            (_NAV_GALLERY, "  All Photos", ""),
            (_NAV_MAP,     "  Map", ""),
            (_NAV_PEOPLE,  "  People", ""),
            (_NAV_ALBUMS,  "  Albums", ""),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("navBtn")
            btn.setProperty("active", nav_id == _NAV_GALLERY)
            btn.clicked.connect(lambda checked, n=nav_id: self._on_nav(n))
            sb_layout.addWidget(btn)
            self._nav_buttons[nav_id] = btn

        sb_layout.addSpacing(8)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#2a2a2a;")
        sb_layout.addWidget(sep)
        sb_layout.addSpacing(8)

        # Detail panels (people / albums) inside the sidebar
        self._sidebar_stack = QStackedWidget()
        self._sidebar_stack.addWidget(QWidget())         # placeholder for gallery + map

        self.people_panel = PeoplePanel()
        self.people_panel.person_selected.connect(self._on_person_selected)
        self.people_panel.person_renamed.connect(self._on_person_renamed)
        self.people_panel.run_face_processing.connect(self._on_run_faces)
        self._sidebar_stack.addWidget(self.people_panel)

        self.album_panel = AlbumPanel()
        self.album_panel.album_selected.connect(self._on_album_selected)
        self._sidebar_stack.addWidget(self.album_panel)

        sb_layout.addWidget(self._sidebar_stack, 1)
        splitter.addWidget(sidebar)

        # ── Center stack ──────────────────────────────────────────────────────
        self.center_stack = QStackedWidget()

        # Page 0 — gallery grid
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_container = QWidget()
        self.grid_layout = QVBoxLayout(self.grid_container)
        self.grid_layout.setContentsMargins(16, 12, 16, 16)
        self.grid_layout.setSpacing(0)
        self.grid_layout.addStretch()
        self.scroll.setWidget(self.grid_container)
        self.center_stack.addWidget(self.scroll)

        # Page 1 — map
        self.map_view = MapView()
        self.center_stack.addWidget(self.map_view)

        splitter.addWidget(self.center_stack)

        # ── Right tag panel ───────────────────────────────────────────────────
        self.tag_panel = TagPanel()
        self.tag_panel.setFixedWidth(280)
        self.tag_panel.tags_changed.connect(self._on_tags_changed)
        splitter.addWidget(self.tag_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        return splitter

    # ──────────────────────────────────────────────────────────────────────────
    # Navigation
    # ──────────────────────────────────────────────────────────────────────────

    def _on_nav(self, nav_id: int):
        self._active_nav = nav_id
        for n, btn in self._nav_buttons.items():
            btn.setProperty("active", n == nav_id)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if nav_id == _NAV_GALLERY:
            self.center_stack.setCurrentIndex(_CENTER_GALLERY)
            self._sidebar_stack.setCurrentIndex(0)
            self._load_photos()

        elif nav_id == _NAV_MAP:
            self.center_stack.setCurrentIndex(_CENTER_MAP)
            self._sidebar_stack.setCurrentIndex(0)
            session = get_session()
            try:
                self.map_view.refresh(session)
            finally:
                session.close()

        elif nav_id == _NAV_PEOPLE:
            self.center_stack.setCurrentIndex(_CENTER_GALLERY)
            self._sidebar_stack.setCurrentIndex(1)
            self.people_panel.load_people()

        elif nav_id == _NAV_ALBUMS:
            self.center_stack.setCurrentIndex(_CENTER_GALLERY)
            self._sidebar_stack.setCurrentIndex(2)
            self.album_panel.load_albums()

    # ──────────────────────────────────────────────────────────────────────────
    # Gallery grid
    # ──────────────────────────────────────────────────────────────────────────

    def _load_photos(self, filters: dict | None = None):
        session = get_session()
        try:
            if filters:
                photos = search_photos(session, filters)
            else:
                photos = session.query(Photo).all()
            self._render_grid(photos)
            self.status.showMessage(f"{len(photos)} photo(s)")
        finally:
            session.close()

    def _render_grid(self, photos: list[Photo]):
        while self.grid_layout.count() > 1:
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not photos:
            placeholder = QLabel("No photos found.\nUse 'Import Folder' to add photos.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color:#444; font-size:15px; padding:60px;")
            self.grid_layout.insertWidget(0, placeholder)
            return

        groups = self._group_photos(photos)
        pos = 0
        for group_label, group_photos in groups:
            header = QLabel(group_label.upper())
            header.setObjectName("groupHeader")
            self.grid_layout.insertWidget(pos, header)
            pos += 1

            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("background:#252525; max-height:1px; margin-bottom:6px;")
            self.grid_layout.insertWidget(pos, sep)
            pos += 1

            grid_widget = QWidget()
            grid = QGridLayout(grid_widget)
            grid.setContentsMargins(0, 4, 0, 16)
            grid.setSpacing(6)
            cols = max(1, (self.grid_container.width() - 32) // (TILE_SIZE + 6))
            for idx, photo in enumerate(group_photos):
                date_str = photo.date_taken.strftime("%d %b %Y") if photo.date_taken else ""
                tile = PhotoTile(photo.id, photo.file_path, date_str)
                tile.clicked.connect(self._on_photo_clicked)
                grid.addWidget(tile, idx // cols, idx % cols)

            self.grid_layout.insertWidget(pos, grid_widget)
            pos += 1

    def _group_photos(self, photos: list[Photo]) -> list[tuple[str, list[Photo]]]:
        reverse = "desc" in self._sort_mode
        by_year = "year" in self._sort_mode
        groups: dict[str, list[Photo]] = defaultdict(list)
        no_date: list[Photo] = []

        for photo in photos:
            if photo.date_taken:
                key = str(photo.date_taken.year) if by_year else photo.date_taken.strftime("%B %Y")
                groups[key].append(photo)
            else:
                no_date.append(photo)

        def _key(item):
            from datetime import datetime as dt
            try:
                return dt.strptime(item[0], "%Y" if by_year else "%B %Y")
            except ValueError:
                return item[0]

        sorted_groups = sorted(groups.items(), key=_key, reverse=reverse)
        if no_date:
            sorted_groups.append(("No date", no_date))
        return sorted_groups

    # ──────────────────────────────────────────────────────────────────────────
    # Photo selection
    # ──────────────────────────────────────────────────────────────────────────

    def _on_photo_clicked(self, photo_id: int):
        self._selected_photo_id = photo_id
        self.tag_panel.load_photo(photo_id)
        session = get_session()
        try:
            photo = session.get(Photo, photo_id)
            if photo:
                dims = f"{photo.width}×{photo.height}" if photo.width else ""
                gps = "  📍GPS" if photo.lat else ""
                self.status.showMessage(f"{photo.filename}  {dims}{gps}  —  {photo.file_path}")
        finally:
            session.close()

    def _on_tags_changed(self, photo_id: int):
        # Re-load tags panel (already done internally), update status
        self.status.showMessage(f"Tags updated for photo {photo_id}")

    # ──────────────────────────────────────────────────────────────────────────
    # People
    # ──────────────────────────────────────────────────────────────────────────

    def _on_person_selected(self, person_id: int):
        """Filter gallery to photos containing this person."""
        session = get_session()
        try:
            person = session.get(Person, person_id)
            if person:
                filters = {"People": [person.name]}
                photos = search_photos(session, filters)
                self.center_stack.setCurrentIndex(_CENTER_GALLERY)
                self._render_grid(photos)
                self.status.showMessage(f"{len(photos)} photo(s) with {person.name}")
        finally:
            session.close()

    def _on_person_renamed(self, person_id: int, new_name: str):
        self.status.showMessage(f'Renamed to "{new_name}"')

    def _on_run_faces(self):
        self._start_face_processing()

    # ──────────────────────────────────────────────────────────────────────────
    # Albums
    # ──────────────────────────────────────────────────────────────────────────

    def _on_album_selected(self, album_id: int):
        session = get_session()
        try:
            photos = get_album_photos(session, album_id)
            self.center_stack.setCurrentIndex(_CENTER_GALLERY)
            self._render_grid(photos)
            self.status.showMessage(f"{len(photos)} photo(s) in album")
        finally:
            session.close()

    # ──────────────────────────────────────────────────────────────────────────
    # Search
    # ──────────────────────────────────────────────────────────────────────────

    def _on_search_changed(self, filters: dict):
        self._active_filters = filters
        if self._active_nav != _NAV_GALLERY:
            self._on_nav(_NAV_GALLERY)
        else:
            self._load_photos(filters if any(filters.values()) else None)

    def _on_sort_changed(self, index: int):
        self._sort_mode = self.sort_combo.itemData(index)
        self._load_photos(self._active_filters or None)

    # ──────────────────────────────────────────────────────────────────────────
    # Import
    # ──────────────────────────────────────────────────────────────────────────

    def _on_import(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Photo Folder")
        if folder:
            self._start_import(folder)

    def _start_import(self, folder: str):
        if self._import_thread and self._import_thread.isRunning():
            self.status.showMessage("Import already in progress — please wait…")
            return
        if self._tag_thread and self._tag_thread.isRunning():
            self.status.showMessage("Cannot import while AI tagging is running — please wait…")
            return
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self._import_thread = QThread()
        self._import_worker = ImportWorker(folder)
        self._import_worker.moveToThread(self._import_thread)
        self._import_thread.started.connect(self._import_worker.start_import)
        self._import_worker.progress.connect(self._on_import_progress)
        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.error.connect(self._on_worker_error)
        self._import_worker.finished.connect(self._import_thread.quit)
        self._import_worker.error.connect(self._import_thread.quit)
        self._import_thread.finished.connect(lambda: self.findChild(QPushButton, "importBtn") and
                                              self.findChild(QPushButton, "importBtn").setEnabled(True))
        # Disable import button while running
        for btn in self.findChildren(QPushButton):
            if btn.objectName() == "importBtn":
                btn.setEnabled(False)
        self._import_thread.start()

    def _on_import_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
        self.status.showMessage(f"Importing… {done}/{total}")

    def _on_import_finished(self, imported: int, skipped: int):
        self.progress_bar.hide()
        self.status.showMessage(f"Import done — {imported} new photo(s) added, {skipped} already in library")
        self._load_photos()

    # ──────────────────────────────────────────────────────────────────────────
    # AI Tagging (Phase 2)
    # ──────────────────────────────────────────────────────────────────────────

    def _on_analyse(self):
        if self._tag_thread and self._tag_thread.isRunning():
            self.status.showMessage("Analysis already running…")
            return
        self.analyse_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status.showMessage("Running AI tagging…")

        self._tag_thread = QThread()
        self._tag_worker = TagWorker()
        self._tag_worker.moveToThread(self._tag_thread)
        self._tag_thread.started.connect(self._tag_worker.start_tagging)
        self._tag_worker.progress.connect(self._on_tag_progress)
        self._tag_worker.finished.connect(self._on_tag_finished)
        self._tag_worker.error.connect(self._on_worker_error)
        self._tag_worker.finished.connect(self._tag_thread.quit)
        self._tag_worker.error.connect(self._tag_thread.quit)
        self._tag_thread.finished.connect(lambda: self.analyse_btn.setEnabled(True))
        self._tag_thread.start()

    def _on_tag_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
        self.status.showMessage(f"Tagging… {done}/{total}")

    def _on_tag_finished(self, count: int):
        self.progress_bar.hide()
        self.status.showMessage(f"Tagged {count} photo(s)")
        if self._selected_photo_id is not None:
            self.tag_panel.load_photo(self._selected_photo_id)

    # ──────────────────────────────────────────────────────────────────────────
    # Face Processing (Phase 3)
    # ──────────────────────────────────────────────────────────────────────────

    def _start_face_processing(self):
        if self._face_thread and self._face_thread.isRunning():
            self.status.showMessage("Face processing already running — please wait…")
            return
        if self._import_thread and self._import_thread.isRunning():
            self.status.showMessage("Cannot process faces while import is running — please wait…")
            return
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status.showMessage("Processing faces…")

        self._face_thread = QThread()
        self._face_worker = FaceWorker()
        self._face_worker.moveToThread(self._face_thread)
        self._face_thread.started.connect(self._face_worker.start_processing)
        self._face_worker.progress.connect(self._on_face_progress)
        self._face_worker.finished.connect(self._on_face_finished)
        self._face_worker.error.connect(self._on_worker_error)
        self._face_worker.finished.connect(self._face_thread.quit)
        self._face_worker.error.connect(self._face_thread.quit)
        self._face_thread.start()

    def _on_face_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
        self.status.showMessage(f"Processing faces… {done}/{total}")

    def _on_face_finished(self, people_count: int):
        self.progress_bar.hide()
        self.status.showMessage(f"Face processing done — {people_count} person(s) identified")
        self.people_panel.load_people()

    # ──────────────────────────────────────────────────────────────────────────
    # Restructure (Phase 5)
    # ──────────────────────────────────────────────────────────────────────────

    def _on_restructure(self):
        dlg = RestructureDialog(self)
        dlg.exec()

    # ──────────────────────────────────────────────────────────────────────────
    # Shared
    # ──────────────────────────────────────────────────────────────────────────

    def _on_worker_error(self, msg: str):
        self.progress_bar.hide()
        QMessageBox.critical(self, "Error", msg)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    def _do_deferred_render(self):
        session = get_session()
        try:
            if self._active_filters and any(self._active_filters.values()):
                photos = search_photos(session, self._active_filters)
            else:
                photos = session.query(Photo).all()
            self._render_grid(photos)
        finally:
            session.close()
