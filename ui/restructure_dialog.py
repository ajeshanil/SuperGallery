"""Folder restructure dialog — preview virtual structure and optionally export."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTreeWidget, QTreeWidgetItem, QFileDialog,
    QDialogButtonBox, QProgressBar, QCheckBox
)

from database.db import get_session
from utils.folder_restructurer import get_virtual_structure, export_structure


_DARK_STYLESHEET = """
    QDialog { background: #121212; color: #e0e0e0; }
    QLabel { color: #e0e0e0; background: transparent; }
    QLabel#dialogTitle {
        font-size: 15px; font-weight: 700; color: #e0e0e0; padding-bottom: 4px;
    }
    QLabel#statusLabel {
        color: #888; font-size: 12px; padding: 4px 0;
    }
    QComboBox {
        background: #2d2d2d; color: #e0e0e0;
        border: 1px solid #444; border-radius: 5px;
        padding: 6px 10px; font-size: 13px; min-width: 160px;
    }
    QComboBox QAbstractItemView {
        background: #2d2d2d; color: #e0e0e0; selection-background-color: #1976d2;
    }
    QTreeWidget {
        background: #1a1a1a; color: #e0e0e0;
        border: 1px solid #2a2a2a; border-radius: 6px;
        font-size: 12px;
    }
    QTreeWidget::item { padding: 3px 6px; }
    QTreeWidget::item:selected { background: #1976d2; color: #fff; }
    QTreeWidget::item:hover { background: #2d2d2d; }
    QTreeWidget::branch { background: #1a1a1a; }
    QCheckBox { color: #e0e0e0; font-size: 12px; background: transparent; }
    QCheckBox::indicator {
        width: 16px; height: 16px;
        border: 1px solid #555; border-radius: 3px;
        background: #2d2d2d;
    }
    QCheckBox::indicator:checked {
        background: #1976d2; border-color: #1976d2;
    }
    QPushButton {
        background: #2d2d2d; color: #e0e0e0;
        border: 1px solid #444; border-radius: 5px;
        padding: 7px 14px; font-size: 13px;
    }
    QPushButton:hover { background: #3a3a3a; }
    QPushButton#exportBtn {
        background: #1565c0; color: #e0e0e0; border: none;
    }
    QPushButton#exportBtn:hover { background: #1976d2; }
    QPushButton#previewBtn {
        background: #2d2d2d; color: #aaa; border-color: #555;
    }
    QPushButton#previewBtn:hover { background: #3a3a3a; color: #e0e0e0; }
    QProgressBar {
        background: #2d2d2d; border: none; border-radius: 3px; height: 6px;
    }
    QProgressBar::chunk { background: #1976d2; border-radius: 3px; }
    QDialogButtonBox { background: transparent; }
"""

GROUP_BY_OPTIONS = [
    ("Year",     "year"),
    ("Month",    "month"),
    ("Location", "location"),
    ("Person",   "person"),
]


class RestructureDialog(QDialog):
    """Preview a virtual folder structure and optionally export/copy photos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Restructure / Export Photos")
        self.setMinimumSize(560, 480)
        self.setStyleSheet(_DARK_STYLESHEET)
        self._dest_folder: str | None = None
        self._setup_ui()
        # Auto-preview on open
        self._preview()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("Restructure / Export")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        # Group-by row
        group_row = QHBoxLayout()
        group_row.setSpacing(10)

        group_lbl = QLabel("Group by:")
        group_lbl.setStyleSheet("font-size:12px; color:#aaa; background:transparent;")
        group_row.addWidget(group_lbl)

        self.group_combo = QComboBox()
        for label, value in GROUP_BY_OPTIONS:
            self.group_combo.addItem(label, value)
        self.group_combo.currentIndexChanged.connect(self._preview)
        group_row.addWidget(self.group_combo)

        preview_btn = QPushButton("Refresh Preview")
        preview_btn.setObjectName("previewBtn")
        preview_btn.clicked.connect(self._preview)
        group_row.addWidget(preview_btn)

        group_row.addStretch()
        layout.addLayout(group_row)

        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Virtual Structure"])
        self.tree.setColumnCount(1)
        self.tree.header().setStyleSheet(
            "QHeaderView::section { background:#1a1a1a; color:#666;"
            " font-size:11px; border:none; padding:4px 6px; }"
        )
        layout.addWidget(self.tree, stretch=1)

        # Export options row
        opts_row = QHBoxLayout()
        opts_row.setSpacing(12)

        self.symlink_check = QCheckBox("Use symlinks (instead of copy)")
        opts_row.addWidget(self.symlink_check)
        opts_row.addStretch()
        layout.addLayout(opts_row)

        # Destination folder row
        dest_row = QHBoxLayout()
        dest_row.setSpacing(8)

        self.dest_label = QLabel("No destination selected")
        self.dest_label.setObjectName("statusLabel")
        dest_row.addWidget(self.dest_label, stretch=1)

        choose_dest_btn = QPushButton("Choose Folder\u2026")
        choose_dest_btn.clicked.connect(self._choose_dest)
        dest_row.addWidget(choose_dest_btn)

        export_btn = QPushButton("Export")
        export_btn.setObjectName("exportBtn")
        export_btn.clicked.connect(self._export)
        dest_row.addWidget(export_btn)

        layout.addLayout(dest_row)

        # Progress bar (hidden initially)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Close button
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_group_mode(self) -> str:
        return self.group_combo.currentData()

    def _preview(self) -> None:
        """Call get_virtual_structure and populate the tree widget."""
        self.tree.clear()
        mode = self._get_group_mode()

        session = get_session()
        try:
            structure = get_virtual_structure(session, mode)
        except Exception as exc:
            self.status_label.setText(f"Preview error: {exc}")
            return
        finally:
            session.close()

        if not structure:
            item = QTreeWidgetItem(self.tree, ["(No photos found)"])
            from PyQt6.QtGui import QColor
            item.setForeground(0, QColor("#555"))
            return

        from PyQt6.QtGui import QFont, QColor, QBrush
        for group_label, photos in structure.items():
            parent_item = QTreeWidgetItem(self.tree, [f"{group_label}  ({len(photos)})"])
            parent_item.setExpanded(False)
            font = QFont()
            font.setBold(True)
            parent_item.setFont(0, font)
            parent_item.setForeground(0, QBrush(QColor("#1976d2")))

            for photo in photos:
                child_item = QTreeWidgetItem(parent_item, [photo.filename])
                child_item.setForeground(0, QBrush(QColor("#b0b0b0")))

        self.tree.resizeColumnToContents(0)
        total_photos = sum(len(v) for v in structure.values())
        self.status_label.setText(
            f"Preview: {len(structure)} group(s), {total_photos} photo(s) total"
        )

    def _choose_dest(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if folder:
            self._dest_folder = folder
            self.dest_label.setText(f"Destination: {folder}")

    def _export(self) -> None:
        """Ask for destination folder, call export_structure, show results."""
        if not self._dest_folder:
            self._choose_dest()
        if not self._dest_folder:
            self.status_label.setText("No destination folder selected.")
            return

        mode = self._get_group_mode()
        use_symlinks = self.symlink_check.isChecked()

        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.show()
        self.status_label.setText("Exporting\u2026")

        session = get_session()
        try:
            result = export_structure(
                session,
                mode=mode,
                dest_folder=self._dest_folder,
                copy=not use_symlinks,
            )
        except Exception as exc:
            self.status_label.setText(f"Export error: {exc}")
            return
        finally:
            session.close()
            self.progress_bar.hide()

        copied = result.get("files_copied", 0)
        err_list = result.get("errors", [])
        self.status_label.setText(
            f"Done — {copied} file(s) exported, {len(err_list)} error(s).  "
            f"→ {self._dest_folder}"
        )
