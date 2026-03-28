"""Search bar with multi-category tag filters."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton,
    QLabel, QScrollArea, QFrame, QSizePolicy, QMenu, QWidgetAction,
    QComboBox, QDialog, QFormLayout, QDialogButtonBox,
)


# ---------------------------------------------------------------------------
# Category colour palette — mirrors tag_panel.py
# ---------------------------------------------------------------------------

CATEGORY_COLORS: dict[str, tuple[str, str]] = {
    "People":    ("#EEEDFE", "#3C3489"),
    "Objects":   ("#E6F1FB", "#0C447C"),
    "Scenes":    ("#E1F5EE", "#085041"),
    "PhotoType": ("#FAEEDA", "#633806"),
    "Location":  ("#FAECE7", "#712B13"),
    "Date":      ("#F1EFE8", "#444441"),
}

CATEGORIES = list(CATEGORY_COLORS.keys())

_DARK_STYLESHEET = """
    QWidget#searchBarRoot { background: #1a1a1a; }
    QLineEdit#searchInput {
        background: #2d2d2d; color: #e0e0e0;
        border: 1px solid #444; border-radius: 6px;
        padding: 7px 12px; font-size: 13px; min-width: 200px;
    }
    QLineEdit#searchInput:focus { border-color: #1976d2; }
    QPushButton#addFilterBtn {
        background: #2d2d2d; color: #aaa;
        border: 1px solid #444; border-radius: 6px;
        padding: 7px 12px; font-size: 12px;
    }
    QPushButton#addFilterBtn:hover { background: #3a3a3a; color: #e0e0e0; }
    QPushButton#clearBtn {
        background: transparent; color: #666;
        border: none; padding: 4px 8px; font-size: 12px;
    }
    QPushButton#clearBtn:hover { color: #e0e0e0; }
    QScrollArea#chipsScroll { border: none; background: transparent; }
    QWidget#chipsContent { background: transparent; }
"""


class FilterChip(QWidget):
    """A removable coloured chip representing an active filter."""

    remove_requested = pyqtSignal(str, str)  # category, value

    def __init__(self, category: str, value: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.category = category
        self.value = value

        bg, fg = CATEGORY_COLORS.get(category, ("#2d2d2d", "#e0e0e0"))
        self.setStyleSheet(f"background:{bg}; border-radius:12px;")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 6, 4)
        row.setSpacing(4)

        cat_lbl = QLabel(f"{category}:")
        cat_lbl.setStyleSheet(
            f"color:{fg}; font-size:11px; font-weight:400; background:transparent;"
        )
        row.addWidget(cat_lbl)

        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(
            f"color:{fg}; font-size:12px; font-weight:600; background:transparent;"
        )
        row.addWidget(val_lbl)

        del_btn = QPushButton("×")
        del_btn.setFixedSize(16, 16)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{fg}; border:none;"
            f" font-size:14px; font-weight:700; padding:0; }}"
            f"QPushButton:hover {{ color:#e53935; }}"
        )
        del_btn.clicked.connect(lambda: self.remove_requested.emit(category, value))
        row.addWidget(del_btn)


class AddFilterDialog(QDialog):
    """Small popup dialog for picking category + value to add a filter."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add Filter")
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setStyleSheet("""
            QDialog {
                background: #2d2d2d;
                border: 1px solid #444;
                border-radius: 8px;
            }
            QLabel { color: #e0e0e0; font-size: 12px; background: transparent; }
            QComboBox {
                background: #3a3a3a; color: #e0e0e0;
                border: 1px solid #555; border-radius: 5px;
                padding: 5px 8px; font-size: 12px;
            }
            QComboBox QAbstractItemView { background: #2d2d2d; color: #e0e0e0; }
            QLineEdit {
                background: #3a3a3a; color: #e0e0e0;
                border: 1px solid #555; border-radius: 5px;
                padding: 5px 8px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #1976d2; }
            QPushButton {
                background: #1565c0; color: #e0e0e0;
                border: none; border-radius: 5px;
                padding: 6px 14px; font-size: 12px;
            }
            QPushButton:hover { background: #1976d2; }
            QPushButton[flat="true"] {
                background: #3a3a3a; color: #aaa;
            }
            QPushButton[flat="true"]:hover { background: #444; }
        """)
        self.setMinimumWidth(280)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("Add Filter")
        title.setStyleSheet("font-size:13px; font-weight:700; color:#e0e0e0; background:transparent;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(8)

        self.cat_combo = QComboBox()
        for cat in CATEGORIES:
            self.cat_combo.addItem(cat)
        form.addRow("Category:", self.cat_combo)

        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("Value…")
        self.value_input.returnPressed.connect(self.accept)
        form.addRow("Value:", self.value_input)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("flat", "true")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton("Add")
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)

    def get_filter(self) -> tuple[str, str]:
        return self.cat_combo.currentText(), self.value_input.text().strip()


class SearchBar(QWidget):
    """Search bar widget with category filter chips."""

    search_changed = pyqtSignal(dict)  # emits filter dict whenever search changes

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("searchBarRoot")
        self.setStyleSheet(_DARK_STYLESHEET)
        # {category: [value, ...]}
        self._filters: dict[str, list[str]] = {}
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        # Top row: text input + buttons
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Search photos\u2026")
        self.search_input.textChanged.connect(self._on_text_changed)
        top_row.addWidget(self.search_input, stretch=1)

        add_filter_btn = QPushButton("+ Filter")
        add_filter_btn.setObjectName("addFilterBtn")
        add_filter_btn.clicked.connect(self._open_add_filter)
        top_row.addWidget(add_filter_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("clearBtn")
        clear_btn.clicked.connect(self.clear)
        top_row.addWidget(clear_btn)

        root.addLayout(top_row)

        # Chips scroll area (hidden when no active filters)
        self.chips_scroll = QScrollArea()
        self.chips_scroll.setObjectName("chipsScroll")
        self.chips_scroll.setFixedHeight(36)
        self.chips_scroll.setWidgetResizable(True)
        self.chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chips_scroll.hide()

        self.chips_content = QWidget()
        self.chips_content.setObjectName("chipsContent")
        self.chips_layout = QHBoxLayout(self.chips_content)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(6)
        self.chips_layout.addStretch()

        self.chips_scroll.setWidget(self.chips_content)
        root.addWidget(self.chips_scroll)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_filter(self, category: str, value: str) -> None:
        """Add a filter chip and emit search_changed."""
        if not value:
            return
        bucket = self._filters.setdefault(category, [])
        if value not in bucket:
            bucket.append(value)
            self._rebuild_chips()
            self.search_changed.emit(self.get_filters())

    def remove_filter(self, category: str, value: str) -> None:
        """Remove a filter chip and emit search_changed."""
        bucket = self._filters.get(category, [])
        if value in bucket:
            bucket.remove(value)
            if not bucket:
                del self._filters[category]
            self._rebuild_chips()
            self.search_changed.emit(self.get_filters())

    def get_filters(self) -> dict:
        """Return current {category: [values]} plus 'text' key if non-empty."""
        result: dict = {k: list(v) for k, v in self._filters.items()}
        text = self.search_input.text().strip()
        if text:
            result["text"] = text
        return result

    def clear(self) -> None:
        """Clear all filters, clear text input, emit search_changed({})."""
        self._filters.clear()
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self._rebuild_chips()
        self.search_changed.emit({})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_chips(self) -> None:
        # Remove all chips (keep trailing stretch)
        while self.chips_layout.count() > 1:
            item = self.chips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        has_chips = False
        for category, values in self._filters.items():
            for value in values:
                chip = FilterChip(category, value)
                chip.remove_requested.connect(self.remove_filter)
                self.chips_layout.insertWidget(self.chips_layout.count() - 1, chip)
                has_chips = True

        if has_chips:
            self.chips_scroll.show()
        else:
            self.chips_scroll.hide()

    def _on_text_changed(self, _text: str) -> None:
        self.search_changed.emit(self.get_filters())

    def _open_add_filter(self) -> None:
        dialog = AddFilterDialog(self)
        # Position below the button
        btn = self.sender()
        if btn:
            pos = btn.mapToGlobal(btn.rect().bottomLeft())
            dialog.move(pos)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            category, value = dialog.get_filter()
            if value:
                self.add_filter(category, value)
