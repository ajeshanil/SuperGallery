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
│  │  ● Map               │  │  / People grid           │  │  selected   │ │
│  │  ● People            │  │                          │  │  photo      │ │
│  │  ● Albums            │  │                          │  │             │ │
│  │  ─────────────────── │  │                          │  │             │ │
│  │  [people / album     │  │                          │  │             │ │
│  │   detail panels]     │  │                          │  │             │ │
│  └──────────────────────┘  └──────────────────────────┘  └─────────────┘ │
├─ "Same or different person?" bar (hidden) ───────────────────────────────┤
└───────────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

from collections import defaultdict

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSlot
from PyQt6.QtGui import QAction, QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QScrollArea, QLabel, QPushButton, QComboBox, QFileDialog,
    QProgressBar, QFrame, QGridLayout, QMessageBox, QStatusBar,
    QStackedWidget, QSizePolicy,
)
from sqlalchemy import func

from database.db import get_session
from database.models import Photo, Person, PhotoPerson, Tag, ObjectDetection
from utils.importer import ImportWorker
from utils.search import search_photos
from utils.album_manager import get_album_photos
from .photo_tile import PhotoTile, TILE_SIZE
from .tag_panel import TagPanel
from .people_panel import PeoplePanel
from .people_grid import PeopleGrid
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
_CENTER_PEOPLE  = 2


# ─── helper: circular pixmap ──────────────────────────────────────────────────

def _make_circular_pixmap(source: QPixmap, size: int) -> QPixmap:
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    p = QPainter(result)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    p.setClipPath(path)
    scaled = source.scaled(size, size,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    p.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    p.end()
    return result


def _placeholder_circle(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#3a3a3a"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.end()
    return pix


class GalleryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SuperGallery")
        self.setMinimumSize(1100, 680)

        # active worker threads
        self._import_thread: QThread | None = None
        self._import_worker: ImportWorker | None = None
        self._tag_thread: QThread | None = None
        self._tag_worker = None
        self._face_thread: QThread | None = None
        self._face_worker = None

        self._sort_mode = "month_desc"
        self._active_filters: dict = {}
        self._selected_photo_id: int | None = None
        self._active_nav = _NAV_GALLERY

        # Person-detail state
        self._current_person_id: int | None = None
        self._current_person_name: str = ""
        self._person_tag_filters: dict[str, list[str]] = {}   # active tag chip filters
        self._similar_pairs: list[tuple[int, int, float]] = []

        # Debounce resize
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(250)
        self._resize_timer.timeout.connect(self._do_deferred_render)

        self._pending_groups: list = []
        self._grid_pos: int = 0
        self._total_photos: int = 0

        self._setup_styles()
        self._setup_ui()
        QTimer.singleShot(0, self._load_photos)

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
            QPushButton#backBtn {
                background: transparent; border: none; color: #4fc3f7;
                font-size: 13px; padding: 4px 8px;
            }
            QPushButton#backBtn:hover { color: #81d4fa; }
            QPushButton#tagChipBtn {
                background: #2d2d2d; border: 1px solid #444; border-radius: 14px;
                color: #ccc; font-size: 11px; padding: 4px 12px;
            }
            QPushButton#tagChipBtn:checked {
                background: #1565c0; border-color: #1976d2; color: #fff;
            }
            QPushButton#tagChipBtn:hover { background: #3a3a3a; }
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
        root.addWidget(self._build_same_diff_bar())

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
        for nav_id, label in [
            (_NAV_GALLERY, "  All Photos"),
            (_NAV_MAP,     "  Map"),
            (_NAV_PEOPLE,  "  People"),
            (_NAV_ALBUMS,  "  Albums"),
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
        self._sidebar_stack.addWidget(QWidget())  # placeholder 0

        self.people_panel = PeoplePanel()
        self.people_panel.person_selected.connect(self._on_person_selected)
        self.people_panel.person_renamed.connect(self._on_person_renamed)
        self.people_panel.run_face_processing.connect(self._on_run_faces)
        self._sidebar_stack.addWidget(self.people_panel)   # index 1

        self.album_panel = AlbumPanel()
        self.album_panel.album_selected.connect(self._on_album_selected)
        self._sidebar_stack.addWidget(self.album_panel)    # index 2

        sb_layout.addWidget(self._sidebar_stack, 1)
        splitter.addWidget(sidebar)

        # ── Center stack ──────────────────────────────────────────────────────
        self.center_stack = QStackedWidget()

        # Page 0 — gallery page: person header + scroll area
        gallery_page = QWidget()
        gp_layout = QVBoxLayout(gallery_page)
        gp_layout.setContentsMargins(0, 0, 0, 0)
        gp_layout.setSpacing(0)

        self._person_header = self._build_person_header()
        gp_layout.addWidget(self._person_header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_container = QWidget()
        self.grid_layout = QVBoxLayout(self.grid_container)
        self.grid_layout.setContentsMargins(16, 12, 16, 16)
        self.grid_layout.setSpacing(0)
        self.grid_layout.addStretch()
        self.scroll.setWidget(self.grid_container)
        gp_layout.addWidget(self.scroll, stretch=1)

        self.center_stack.addWidget(gallery_page)   # page 0

        # Page 1 — map
        self.map_view = MapView()
        self.center_stack.addWidget(self.map_view)  # page 1

        # Page 2 — people grid (Google Photos-style)
        self.people_grid = PeopleGrid()
        self.people_grid.person_clicked.connect(self._on_people_grid_person_selected)
        self.center_stack.addWidget(self.people_grid)  # page 2

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

    def _build_person_header(self) -> QWidget:
        """Header bar shown when drilling into a person's photos."""
        header = QWidget()
        header.setStyleSheet(
            "QWidget { background:#161616; border-bottom:1px solid #252525; }"
        )
        header.hide()

        layout = QVBoxLayout(header)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        # Top row: back button + name + count
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        back_btn = QPushButton("← People")
        back_btn.setObjectName("backBtn")
        back_btn.clicked.connect(self._on_back_to_people)
        top_row.addWidget(back_btn)

        self._person_name_lbl = QLabel("")
        self._person_name_lbl.setStyleSheet(
            "font-size:15px; font-weight:700; color:#e0e0e0;"
        )
        top_row.addWidget(self._person_name_lbl)

        self._person_count_lbl = QLabel("")
        self._person_count_lbl.setStyleSheet("color:#888; font-size:12px;")
        top_row.addWidget(self._person_count_lbl)
        top_row.addStretch()

        layout.addLayout(top_row)

        # Tag filter chips row (scrollable horizontally)
        chips_area = QScrollArea()
        chips_area.setFixedHeight(36)
        chips_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        chips_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        chips_area.setStyleSheet("border:none; background:transparent;")

        self._chips_widget = QWidget()
        self._chips_widget.setStyleSheet("background:transparent;")
        self._chips_row = QHBoxLayout(self._chips_widget)
        self._chips_row.setContentsMargins(0, 0, 0, 0)
        self._chips_row.setSpacing(6)
        self._chips_row.addStretch()

        chips_area.setWidget(self._chips_widget)
        chips_area.setWidgetResizable(True)
        layout.addWidget(chips_area)

        return header

    def _build_same_diff_bar(self) -> QWidget:
        """Bottom bar for 'Same or different person?' suggestions."""
        self._same_diff_bar = QWidget()
        self._same_diff_bar.setFixedHeight(64)
        self._same_diff_bar.setStyleSheet(
            "background:#1a1a1a; border-top:1px solid #2e2e2e;"
        )
        self._same_diff_bar.hide()

        row = QHBoxLayout(self._same_diff_bar)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(12)

        self._sd_face_a = QLabel()
        self._sd_face_a.setFixedSize(40, 40)
        row.addWidget(self._sd_face_a)

        self._sd_face_b = QLabel()
        self._sd_face_b.setFixedSize(40, 40)
        row.addWidget(self._sd_face_b)

        self._sd_text = QLabel("Same or different person?")
        self._sd_text.setStyleSheet("color:#e0e0e0; font-size:13px;")
        row.addWidget(self._sd_text)

        self._sd_sub = QLabel("Improve face grouping results")
        self._sd_sub.setStyleSheet("color:#888; font-size:11px;")
        row.addWidget(self._sd_sub)
        row.addStretch()

        same_btn = QPushButton("Same person")
        same_btn.setStyleSheet(
            "background:#1565c0; color:#fff; border:none; border-radius:5px;"
            " padding:6px 14px; font-size:12px;"
        )
        same_btn.clicked.connect(self._on_same_person)
        row.addWidget(same_btn)

        diff_btn = QPushButton("Different")
        diff_btn.setStyleSheet(
            "background:#2d2d2d; color:#ccc; border:1px solid #444; border-radius:5px;"
            " padding:6px 14px; font-size:12px;"
        )
        diff_btn.clicked.connect(self._on_different_person)
        row.addWidget(diff_btn)

        dismiss_btn = QPushButton("×")
        dismiss_btn.setFixedSize(28, 28)
        dismiss_btn.setStyleSheet(
            "background:transparent; color:#666; border:none; font-size:18px;"
        )
        dismiss_btn.clicked.connect(self._same_diff_bar.hide)
        row.addWidget(dismiss_btn)

        return self._same_diff_bar

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
            self._person_header.hide()
            self._current_person_id = None
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
            self.center_stack.setCurrentIndex(_CENTER_PEOPLE)
            self._sidebar_stack.setCurrentIndex(1)   # keep process/rename panel
            self.people_grid.load_people()

        elif nav_id == _NAV_ALBUMS:
            self._person_header.hide()
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
        self._pending_groups = []

        while self.grid_layout.count() > 1:
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not photos:
            placeholder = QLabel("No photos found.\nUse 'Import Folder' to add photos.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color:#444; font-size:15px; padding:60px;")
            self.grid_layout.insertWidget(0, placeholder)
            self.status.showMessage("No photos found")
            return

        groups = self._group_photos(photos)
        self._pending_groups = list(groups)
        self._grid_pos = 0
        self._total_photos = len(photos)
        self.status.showMessage(f"Loading {len(photos)} photo(s)…")
        self._render_next_group()

    def _render_next_group(self):
        if not self._pending_groups:
            self.status.showMessage(f"{self._total_photos} photo(s)")
            return

        group_label, group_photos = self._pending_groups.pop(0)
        cols = max(1, (self.grid_container.width() - 32) // (TILE_SIZE + 6))

        header = QLabel(group_label.upper())
        header.setObjectName("groupHeader")
        self.grid_layout.insertWidget(self._grid_pos, header)
        self._grid_pos += 1

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#252525; max-height:1px; margin-bottom:6px;")
        self.grid_layout.insertWidget(self._grid_pos, sep)
        self._grid_pos += 1

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 4, 0, 16)
        grid.setSpacing(6)
        for idx, photo in enumerate(group_photos):
            date_str = photo.date_taken.strftime("%d %b %Y") if photo.date_taken else ""
            tile = PhotoTile(photo.id, photo.file_path, date_str)
            tile.clicked.connect(self._on_photo_clicked)
            grid.addWidget(tile, idx // cols, idx % cols)

        self.grid_layout.insertWidget(self._grid_pos, grid_widget)
        self._grid_pos += 1

        if self._pending_groups:
            QTimer.singleShot(0, self._render_next_group)

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
        self.status.showMessage(f"Tags updated for photo {photo_id}")

    # ──────────────────────────────────────────────────────────────────────────
    # People — grid view + person detail
    # ──────────────────────────────────────────────────────────────────────────

    def _on_people_grid_person_selected(self, person_id: int):
        """Called when a person circle is clicked in the center PeopleGrid."""
        session = get_session()
        try:
            person = session.get(Person, person_id)
            if not person:
                return

            self._current_person_id = person_id
            self._current_person_name = person.name
            self._person_tag_filters = {}

            # Photos for this person
            filters = {"People": [person.name]}
            photos = search_photos(session, filters)
            photo_ids = [p.id for p in photos]

            # Top 6 Objects/Scenes tags across their photos
            top_tags = (
                session.query(Tag.label, Tag.category, func.count().label("cnt"))
                .filter(Tag.photo_id.in_(photo_ids))
                .filter(Tag.category.in_(["Objects", "Scenes"]))
                .group_by(Tag.label, Tag.category)
                .order_by(func.count().desc())
                .limit(8)
                .all()
            ) if photo_ids else []

            # Update header
            self._person_name_lbl.setText(person.name)
            self._person_count_lbl.setText(f"   {len(photos)} photos")
            self._rebuild_tag_chips(top_tags)
            self._person_header.show()

            # Switch to gallery
            self.center_stack.setCurrentIndex(_CENTER_GALLERY)
            self._render_grid(photos)
            self.status.showMessage(f"{len(photos)} photo(s) with {person.name}")
        finally:
            session.close()

    def _on_back_to_people(self):
        """Back button in person detail header → return to people grid."""
        self._person_header.hide()
        self._current_person_id = None
        self._person_tag_filters = {}
        self.center_stack.setCurrentIndex(_CENTER_PEOPLE)
        self.people_grid.load_people()
        self._on_nav(_NAV_PEOPLE)

    def _rebuild_tag_chips(self, top_tags: list) -> None:
        """Clear and rebuild the tag chip row in the person header."""
        # Remove all chips (keep nothing — chips_row uses addStretch at end)
        while self._chips_row.count():
            item = self._chips_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for label, category, cnt in top_tags:
            chip = QPushButton(f"{label}  {cnt}")
            chip.setObjectName("tagChipBtn")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda checked, lbl=label, cat=category:
                                  self._on_tag_chip_toggled(lbl, cat, checked))
            self._chips_row.addWidget(chip)

        self._chips_row.addStretch()

    def _on_tag_chip_toggled(self, label: str, category: str, checked: bool) -> None:
        """A tag chip was toggled — apply combined filter."""
        if checked:
            self._person_tag_filters.setdefault(category, [])
            if label not in self._person_tag_filters[category]:
                self._person_tag_filters[category].append(label)
        else:
            if category in self._person_tag_filters:
                self._person_tag_filters[category] = [
                    l for l in self._person_tag_filters[category] if l != label
                ]
                if not self._person_tag_filters[category]:
                    del self._person_tag_filters[category]

        # Combined filter: person + active tag chips
        combined = {"People": [self._current_person_name]}
        combined.update(self._person_tag_filters)

        session = get_session()
        try:
            photos = search_photos(session, combined)
            self._render_grid(photos)
            self.status.showMessage(f"{len(photos)} photo(s)")
        finally:
            session.close()

    # ── Sidebar people panel (rename / process) ────────────────────────────

    def _on_person_selected(self, person_id: int):
        """Sidebar people panel card clicked → filter gallery."""
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
    # Same / Different person
    # ──────────────────────────────────────────────────────────────────────────

    def _check_similar_persons(self) -> None:
        """Find person pairs with similar embeddings and surface the first."""
        try:
            import numpy as np
        except ImportError:
            return

        session = get_session()
        try:
            people = (
                session.query(Person)
                .filter(Person.embedding_vector.isnot(None))
                .all()
            )
            if len(people) < 2:
                return

            pairs = []
            for i, p1 in enumerate(people):
                emb1 = np.frombuffer(p1.embedding_vector, dtype=np.float32)
                for p2 in people[i + 1:]:
                    emb2 = np.frombuffer(p2.embedding_vector, dtype=np.float32)
                    norm = np.linalg.norm(emb1) * np.linalg.norm(emb2)
                    sim = float(np.dot(emb1, emb2) / (norm + 1e-8)) if norm else 0.0
                    # Show pairs that are similar but below clustering merge threshold
                    if 0.45 < sim < 0.72:
                        pairs.append((p1.id, p2.id, sim))

            if not pairs:
                return

            self._similar_pairs = sorted(pairs, key=lambda t: -t[2])
            self._show_same_diff_suggestion()
        finally:
            session.close()

    def _show_same_diff_suggestion(self) -> None:
        if not self._similar_pairs:
            self._same_diff_bar.hide()
            return

        person_id_a, person_id_b, sim = self._similar_pairs[0]
        session = get_session()
        try:
            pa = session.get(Person, person_id_a)
            pb = session.get(Person, person_id_b)
            if not pa or not pb:
                return
            self._sd_text.setText(f"Same or different person?")
            self._sd_sub.setText(f"{pa.name}  ·  {pb.name}")
            self._set_face_thumb(self._sd_face_a, pa)
            self._set_face_thumb(self._sd_face_b, pb)
            self._same_diff_bar.show()
        finally:
            session.close()

    def _set_face_thumb(self, lbl: QLabel, person: Person) -> None:
        from pathlib import Path
        size = 40
        if person.thumbnail_path and Path(person.thumbnail_path).exists():
            src = QPixmap(person.thumbnail_path)
            pix = _make_circular_pixmap(src, size)
        else:
            pix = _placeholder_circle(size)
        lbl.setPixmap(pix)

    def _on_same_person(self) -> None:
        """Merge the two suggested persons into one."""
        if not self._similar_pairs:
            return
        person_id_a, person_id_b, _ = self._similar_pairs.pop(0)
        session = get_session()
        try:
            pa = session.get(Person, person_id_a)
            pb = session.get(Person, person_id_b)
            if not pa or not pb:
                return
            # Re-point all of pb's references to pa
            session.query(PhotoPerson).filter(PhotoPerson.person_id == pb.id).update(
                {"person_id": pa.id}
            )
            session.query(Tag).filter(
                Tag.category == "People", Tag.label == pb.name
            ).update({"label": pa.name})
            session.delete(pb)
            session.commit()
            self.status.showMessage(f"Merged '{pb.name}' into '{pa.name}'")
        except Exception as exc:
            session.rollback()
            QMessageBox.warning(self, "Merge failed", str(exc))
        finally:
            session.close()

        self.people_panel.load_people()
        self.people_grid.load_people()
        self._show_same_diff_suggestion()

    def _on_different_person(self) -> None:
        """Dismiss this suggestion and move to the next pair."""
        if self._similar_pairs:
            self._similar_pairs.pop(0)
        self._show_same_diff_suggestion()

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
        self._current_person_id = None
        self._person_header.hide()
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
        self._import_thread.finished.connect(
            lambda: self.findChild(QPushButton, "importBtn") and
                    self.findChild(QPushButton, "importBtn").setEnabled(True)
        )
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
        self.status.showMessage(
            f"Import done — {imported} new photo(s) added, {skipped} already in library"
        )
        self._load_photos()
        # Auto-run AI tagging on newly imported photos
        if imported > 0:
            QTimer.singleShot(200, self._on_analyse)

    # ──────────────────────────────────────────────────────────────────────────
    # AI Tagging
    # ──────────────────────────────────────────────────────────────────────────

    def _on_analyse(self):
        if self._tag_thread and self._tag_thread.isRunning():
            self.status.showMessage("Analysis already running…")
            return
        self.analyse_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status.showMessage("Running AI tagging…")

        from utils.tagger import TagWorker
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
        # Auto-start face processing if photos contain person detections
        # that haven't been through face recognition yet
        QTimer.singleShot(300, self._auto_face_if_needed)

    def _auto_face_if_needed(self) -> None:
        """Start face processing if YOLO found persons in photos not yet face-processed."""
        session = get_session()
        try:
            already_done = {r[0] for r in session.query(PhotoPerson.photo_id).distinct()}
            person_tagged = (
                session.query(Tag.photo_id)
                .filter(Tag.category == "Objects", Tag.label == "person")
                .filter(~Tag.photo_id.in_(already_done))
                .first()
            )
        finally:
            session.close()

        if person_tagged:
            self.status.showMessage("Persons detected — starting face recognition…")
            QTimer.singleShot(300, self._start_face_processing)

    # ──────────────────────────────────────────────────────────────────────────
    # Face Processing
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

        from utils.face_processor import FaceWorker
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
        self.people_grid.load_people()
        # Surface any possibly-same person pairs
        QTimer.singleShot(500, self._check_similar_persons)

    # ──────────────────────────────────────────────────────────────────────────
    # Restructure
    # ──────────────────────────────────────────────────────────────────────────

    def _on_restructure(self):
        dlg = RestructureDialog(self)
        dlg.exec()

    # ──────────────────────────────────────────────────────────────────────────
    # Shared helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _on_worker_error(self, msg: str):
        self.progress_bar.hide()
        QMessageBox.critical(self, "Error", msg)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    def _do_deferred_render(self):
        new_cols = max(1, (self.grid_container.width() - 32) // (TILE_SIZE + 6))
        if getattr(self, "_last_cols", None) == new_cols:
            return
        self._last_cols = new_cols
        session = get_session()
        try:
            if self._current_person_id is not None:
                # In person-detail view — re-apply combined filter
                combined = {"People": [self._current_person_name]}
                combined.update(self._person_tag_filters)
                photos = search_photos(session, combined)
            elif self._active_filters and any(self._active_filters.values()):
                photos = search_photos(session, self._active_filters)
            else:
                photos = session.query(Photo).all()
            self._render_grid(photos)
        finally:
            session.close()
