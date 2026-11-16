"""
gui.py - PyQt6 desktop GUI.

Layout (top → bottom):
  ┌─ Inputs (URL list) — legacy textarea for paste-many
  ├─ Script mode + custom script (single)
  ├─ Product list — each row: [URL | Product name | Script | ✕]
  │                     + [+ Thêm sản phẩm] button
  ├─ Run buttons
  ├─ Items table (status per item)
  └─ Log console
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional

from loguru import logger
from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal, QSize
from PyQt6.QtGui import QAction, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import settings
from src.pipeline import ItemState, process_batch
from src.voices import VoiceStore


# ---------------------------------------------------------------------------
# Loguru -> Qt signal bridge
# ---------------------------------------------------------------------------

class LogSignal(QObject):
    """Plain QObject carrying a pyqtSignal so it can be emitted from a thread."""
    message = pyqtSignal(str)


class QtLogHandler:
    """Capture loguru logs and emit them via a Qt signal."""
    def __init__(self):
        self.signal = LogSignal()
        self._handler_id = None

    def install(self):
        def sink(message):
            try:
                self.signal.message.emit(str(message).rstrip())
            except Exception:
                pass
        # No enqueue=True here — enqueue uses a multiprocessing queue which
        # breaks under PyInstaller (multiprocessing.resource_tracker gets
        # injected into argv and crashes argparse / module imports).
        self._handler_id = logger.add(sink, format="{message}", level="INFO")
        return self

    def uninstall(self):
        if self._handler_id is not None:
            logger.remove(self._handler_id)


# ---------------------------------------------------------------------------
# Pipeline worker thread
# ---------------------------------------------------------------------------

class PipelineWorker(QThread):
    item_updated = pyqtSignal(object)
    finished_all = pyqtSignal(list)
    progress_text = pyqtSignal(str)

    def __init__(self, items: List[ItemState], max_concurrent: int = 1, parent=None):
        super().__init__(parent)
        self.items = items
        self.max_concurrent = max_concurrent
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            results = self._loop.run_until_complete(
                process_batch(self.items, on_progress=self._on_progress,
                              max_concurrent=self.max_concurrent)
            )
            self.finished_all.emit(results)
        except Exception as e:
            logger.exception("pipeline crashed")
            self.progress_text.emit(f"Pipeline crashed: {e}")
        finally:
            self._loop.close()

    def _on_progress(self, state: ItemState):
        self.item_updated.emit(state)


# ---------------------------------------------------------------------------
# Product row widget — one row per item in the product list
# ---------------------------------------------------------------------------

class ProductRow(QFrame):
    """One row: [URL] [Product name] [Script] [✕ delete]"""

    removed = pyqtSignal(object)        # emits self when user clicks ✕

    def __init__(self, url: str = "", name: str = "", script: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background: #fafafa;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                margin: 2px 0;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # Row index label (filled by parent)
        self.index_label = QLabel("#?")
        self.index_label.setFixedWidth(28)
        self.index_label.setStyleSheet("color: #888; font-weight: bold;")
        layout.addWidget(self.index_label)

        # URL
        self.url_edit = QLineEdit(url)
        self.url_edit.setPlaceholderText("https://www.tiktok.com/@user/video/...")
        self.url_edit.setFixedWidth(280)
        layout.addWidget(self.url_edit)

        # Product name
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("Tên sản phẩm")
        self.name_edit.setFixedWidth(150)
        layout.addWidget(self.name_edit)

        # Script (multiline, takes remaining width)
        self.script_edit = QTextEdit(script)
        self.script_edit.setPlaceholderText(
            "Kịch bản tiếng Việt ~100 từ, 1 đoạn liền. "
            "Trời đất ơi ... haha. Mấy cưng ơi ... múc liền."
        )
        self.script_edit.setFixedHeight(70)
        layout.addWidget(self.script_edit, stretch=1)

        # Delete button
        self.delete_btn = QPushButton("✕")
        self.delete_btn.setFixedSize(28, 28)
        self.delete_btn.setToolTip("Xóa sản phẩm này")
        self.delete_btn.setStyleSheet("""
            QPushButton {
                background: #ff5252; color: white; border: none;
                border-radius: 14px; font-weight: bold; font-size: 14px;
            }
            QPushButton:hover { background: #d32f2f; }
        """)
        self.delete_btn.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(self.delete_btn)

    def values(self) -> tuple[str, str, str]:
        return (
            self.url_edit.text().strip(),
            self.name_edit.text().strip(),
            self.script_edit.toPlainText().strip(),
        )

    def set_index(self, idx: int):
        self.index_label.setText(f"#{idx:02d}")


class ProductListWidget(QWidget):
    """Scrollable container for ProductRow widgets with [+ Thêm] button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: List[ProductRow] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("""
            QScrollArea { border: 1px solid #ddd; border-radius: 6px; background: white; }
            QScrollBar:vertical { width: 10px; }
        """)
        self.scroll_inner = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_inner)
        self.scroll_layout.setContentsMargins(6, 6, 6, 6)
        self.scroll_layout.setSpacing(6)
        self.scroll_layout.addStretch(1)
        self.scroll.setWidget(self.scroll_inner)
        outer.addWidget(self.scroll, stretch=1)

        # Add row button
        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("+ Thêm sản phẩm")
        self.add_btn.setStyleSheet("""
            QPushButton {
                background: #4CAF50; color: white; padding: 8px 16px;
                border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background: #388E3C; }
        """)
        self.add_btn.clicked.connect(lambda: self.add_row())
        btn_row.addWidget(self.add_btn)
        btn_row.addStretch()
        self.count_label = QLabel("0 sản phẩm")
        self.count_label.setStyleSheet("color: #666;")
        btn_row.addWidget(self.count_label)
        outer.addLayout(btn_row)

    def add_row(self, url: str = "", name: str = "", script: str = "") -> ProductRow:
        row = ProductRow(url, name, script)
        row.removed.connect(self._remove_row)
        # Insert before the trailing stretch
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, row)
        self.rows.append(row)
        self._renumber()
        return row

    def _remove_row(self, row: ProductRow):
        if row in self.rows:
            self.rows.remove(row)
            self.scroll_layout.removeWidget(row)
            row.deleteLater()
            self._renumber()

    def _renumber(self):
        for i, row in enumerate(self.rows, start=1):
            row.set_index(i)
        self.count_label.setText(f"{len(self.rows)} sản phẩm")

    def values(self) -> List[tuple[str, str, str]]:
        return [r.values() for r in self.rows]

    def clear(self):
        for row in list(self.rows):
            self._remove_row(row)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TikTok Review Tool")
        self.resize(1280, 900)
        self.worker: Optional[PipelineWorker] = None

        self._build_ui()
        self._build_menu()

        # Start with one empty row
        self.product_list.add_row()

    # ----- UI construction -----
    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # --- Top: product list ---
        list_label = QLabel("📦 Danh sách sản phẩm (mỗi dòng = 1 sản phẩm)")
        list_label.setFont(QFont("", 12, QFont.Weight.Bold))
        layout.addWidget(list_label)

        self.product_list = ProductListWidget()
        self.product_list.setMinimumHeight(220)
        layout.addWidget(self.product_list, stretch=2)

        # --- Middle: action buttons ---
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("▶  Run Pipeline")
        self.run_btn.setFont(QFont("", 12, QFont.Weight.Bold))
        self.run_btn.setStyleSheet(
            "background: #1976D2; color: white; padding: 10px 20px; border-radius: 4px;"
        )
        self.run_btn.clicked.connect(self.start_pipeline)
        btn_row.addWidget(self.run_btn)

        self.open_out_btn = QPushButton("📁  Mở folder final")
        self.open_out_btn.clicked.connect(self.open_output_folder)
        btn_row.addWidget(self.open_out_btn)

        self.reveal_btn = QPushButton("🎬  Mở file mới nhất")
        self.reveal_btn.clicked.connect(self.reveal_latest)
        btn_row.addWidget(self.reveal_btn)

        self.clear_btn = QPushButton("🗑️  Xóa tất cả")
        self.clear_btn.clicked.connect(self.clear_all)
        btn_row.addWidget(self.clear_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Output folder selector
        folder_row = QHBoxLayout()
        folder_label = QLabel("📂 Folder lưu final video:")
        folder_label.setFont(QFont("", 9))
        folder_row.addWidget(folder_label)

        self.folder_edit = QLineEdit(str(settings.FINAL_OUTPUT_DIR))
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setStyleSheet("background: #f5f5f5;")
        folder_row.addWidget(self.folder_edit, stretch=1)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_output_folder)
        folder_row.addWidget(self.browse_btn)

        self.open_intermediate_btn = QPushButton("Mở folder tạm")
        self.open_intermediate_btn.clicked.connect(self.open_intermediate_folder)
        folder_row.addWidget(self.open_intermediate_btn)

        layout.addLayout(folder_row)

        # --- Voice management group ---
        self.voice_store = VoiceStore()
        self._build_voice_group(layout)

        # --- Items table ---

        # --- Items table ---
        self.status_label = QLabel("Trạng thái: Sẵn sàng")
        self.status_label.setFont(QFont("", 10))
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Sản phẩm", "Trạng thái", "Output"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, stretch=1)

        # --- Log console ---
        log_label = QLabel("📜 Log:")
        log_label.setFont(QFont("", 10))
        layout.addWidget(log_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setStyleSheet("background: #1e1e1e; color: #ddd; font-family: monospace;")
        layout.addWidget(self.log_view, stretch=1)

        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Sẵn sàng")

        self.log_handler = QtLogHandler()
        self.log_handler.signal.message.connect(self.log_view.appendPlainText)
        self.log_handler.install()

    def _build_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        open_act = QAction("Mở thư mục output", self)
        open_act.triggered.connect(self.open_output_folder)
        file_menu.addAction(open_act)
        quit_act = QAction("Thoát", self)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)
        help_menu = menubar.addMenu("&Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self.show_about)
        help_menu.addAction(about_act)

    # ----- Voice management UI -----
    def _build_voice_group(self, parent_layout: QVBoxLayout):
        """Group box: list of voices (left) + form to add/update/activate (right)."""
        group = QGroupBox("🎙️  Quản lý giọng đọc (LucyAI)")
        group.setFont(QFont("", 10, QFont.Weight.Bold))
        outer = QHBoxLayout(group)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(10)

        # ----- Left: list of voices -----
        left = QVBoxLayout()
        self.voice_list = QListWidget()
        self.voice_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ddd; border-radius: 4px;
                background: white; padding: 4px;
            }
            QListWidget::item { padding: 6px 8px; border-radius: 3px; }
            QListWidget::item:selected { background: #1976D2; color: white; }
            QListWidget::item:hover:!selected { background: #e3f2fd; }
        """)
        self.voice_list.itemSelectionChanged.connect(self._on_voice_selected)
        left.addWidget(self.voice_list, stretch=1)

        list_hint = QLabel("● = active (đang dùng cho pipeline)")
        list_hint.setStyleSheet("color: #888; font-size: 11px;")
        left.addWidget(list_hint)
        outer.addLayout(left, stretch=2)

        # ----- Right: form + buttons -----
        right = QVBoxLayout()
        right.setSpacing(6)

        right.addWidget(QLabel("Tên voice:"))
        self.voice_name_edit = QLineEdit()
        self.voice_name_edit.setPlaceholderText("VD: Adam - US Male, Hana - VN Female...")
        right.addWidget(self.voice_name_edit)

        right.addWidget(QLabel("Voice ID (từ vivibe.app):"))
        self.voice_id_edit = QLineEdit()
        self.voice_id_edit.setPlaceholderText("VD: 5r2MVjMfzwsSDzTpaLjbY9")
        right.addWidget(self.voice_id_edit)

        # Button grid
        btn_grid = QGridLayout()
        btn_grid.setSpacing(6)

        self.add_voice_btn = QPushButton("➕ Thêm")
        self.add_voice_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; padding: 6px 12px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #388E3C; }"
        )
        self.add_voice_btn.clicked.connect(self._add_voice)
        btn_grid.addWidget(self.add_voice_btn, 0, 0)

        self.update_voice_btn = QPushButton("✏️ Cập nhật")
        self.update_voice_btn.clicked.connect(self._update_voice)
        btn_grid.addWidget(self.update_voice_btn, 0, 1)

        self.delete_voice_btn = QPushButton("🗑️ Xóa")
        self.delete_voice_btn.setStyleSheet(
            "QPushButton { background: #EF5350; color: white; padding: 6px 12px; "
            "border-radius: 4px; }"
            "QPushButton:hover { background: #C62828; }"
        )
        self.delete_voice_btn.clicked.connect(self._delete_voice)
        btn_grid.addWidget(self.delete_voice_btn, 1, 0)

        self.activate_voice_btn = QPushButton("⭐ Set Active")
        self.activate_voice_btn.setStyleSheet(
            "QPushButton { background: #FFA726; color: white; padding: 6px 12px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #FB8C00; }"
        )
        self.activate_voice_btn.clicked.connect(self._activate_voice)
        btn_grid.addWidget(self.activate_voice_btn, 1, 1)

        right.addLayout(btn_grid)

        # Active voice indicator
        self.active_voice_label = QLabel()
        self.active_voice_label.setStyleSheet(
            "color: #1565C0; font-weight: bold; padding: 4px; "
            "background: #E3F2FD; border-radius: 4px;"
        )
        self.active_voice_label.setWordWrap(True)
        right.addWidget(self.active_voice_label)

        right.addStretch()
        outer.addLayout(right, stretch=3)

        parent_layout.addWidget(group)

        # Initial population
        self._refresh_voice_list()

    def _refresh_voice_list(self, select_index: int = -1):
        """Reload the QListWidget from voice_store. Selects given index if valid."""
        self.voice_list.blockSignals(True)
        self.voice_list.clear()
        for i, v in enumerate(self.voice_store.voices):
            label = ("● " if v.active else "   ") + f"{v.name}  ({v.voice_id[:10]}…)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.voice_list.addItem(item)
        self.voice_list.blockSignals(False)
        if select_index >= 0 and select_index < self.voice_list.count():
            self.voice_list.setCurrentRow(select_index)
        self._update_active_voice_label()

    def _update_active_voice_label(self):
        active = self.voice_store.active
        if active:
            self.active_voice_label.setText(
                f"Active: {active.name}  →  {active.voice_id}"
            )
        else:
            self.active_voice_label.setText("Chưa có voice nào active.")

    def _on_voice_selected(self):
        """Populate the form with the selected voice's data."""
        items = self.voice_list.selectedItems()
        if not items:
            return
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        v = self.voice_store.voices[idx]
        self.voice_name_edit.setText(v.name)
        self.voice_id_edit.setText(v.voice_id)

    def _add_voice(self):
        name = self.voice_name_edit.text().strip()
        vid = self.voice_id_edit.text().strip()
        if not name or not vid:
            QMessageBox.warning(
                self, "Thiếu thông tin",
                "Vui lòng nhập cả Tên voice và Voice ID."
            )
            return
        try:
            v = self.voice_store.add(name, vid)
        except ValueError as e:
            QMessageBox.warning(self, "Lỗi", str(e))
            return
        self._refresh_voice_list(select_index=len(self.voice_store.voices) - 1)
        self.voice_name_edit.clear()
        self.voice_id_edit.clear()
        logger.info(f"Đã thêm voice: {v.name} ({v.voice_id})")
        if v.active:
            self._sync_active_to_env(v)
        self.statusBar().showMessage(f"Đã thêm voice: {v.name}", 3000)

    def _update_voice(self):
        items = self.voice_list.selectedItems()
        if not items:
            QMessageBox.information(self, "Chưa chọn", "Chọn 1 voice trong danh sách trước.")
            return
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        name = self.voice_name_edit.text().strip()
        vid = self.voice_id_edit.text().strip()
        try:
            v = self.voice_store.update(idx, name, vid)
        except (ValueError, IndexError) as e:
            QMessageBox.warning(self, "Lỗi", str(e))
            return
        self._refresh_voice_list(select_index=idx)
        logger.info(f"Đã cập nhật voice #{idx+1}: {v.name} ({v.voice_id})")
        if v.active:
            self._sync_active_to_env(v)
        self.statusBar().showMessage(f"Đã cập nhật voice #{idx+1}", 3000)

    def _delete_voice(self):
        items = self.voice_list.selectedItems()
        if not items:
            QMessageBox.information(self, "Chưa chọn", "Chọn 1 voice trong danh sách trước.")
            return
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        v = self.voice_store.voices[idx]
        ans = QMessageBox.question(
            self, "Xác nhận xóa",
            f"Xóa voice \"{v.name}\" ({v.voice_id})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.voice_store.remove(idx)
        new_idx = min(idx, len(self.voice_store.voices) - 1)
        self._refresh_voice_list(select_index=new_idx)
        # If active voice changed, sync .env
        active = self.voice_store.active
        if active:
            self._sync_active_to_env(active)
        logger.info(f"Đã xóa voice #{idx+1}. Active hiện tại: {active.name if active else 'none'}")
        self.statusBar().showMessage(f"Đã xóa voice #{idx+1}", 3000)

    def _activate_voice(self):
        items = self.voice_list.selectedItems()
        if not items:
            QMessageBox.information(self, "Chưa chọn", "Chọn 1 voice trong danh sách trước.")
            return
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        try:
            v = self.voice_store.set_active(idx)
        except IndexError as e:
            QMessageBox.warning(self, "Lỗi", str(e))
            return
        # Mirror to settings + .env so the pipeline picks it up next run
        self._sync_active_to_env(v)
        self._refresh_voice_list(select_index=idx)
        logger.info(f"Active voice: {v.name} ({v.voice_id})")
        self.statusBar().showMessage(f"Active: {v.name}", 4000)

    def _sync_active_to_env(self, v):
        """Mirror active voice into settings.LUCY_VOICE_ID + .env."""
        settings.LUCY_VOICE_ID = v.voice_id
        self._save_env_value("LUCY_VOICE_ID", v.voice_id)

    # ----- Actions -----
    def _parse_inputs(self) -> List[ItemState]:
        items: List[ItemState] = []
        for idx, (url, name, script) in enumerate(self.product_list.values(), start=1):
            if not url:
                continue  # skip empty rows
            items.append(ItemState(
                index=idx,
                url=url,
                product_name_hint=name or None,
                custom_script=script or None,
            ))
        return items

    def _populate_table(self, items: List[ItemState]):
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(str(item.index)))
            self.table.setItem(row, 1, QTableWidgetItem(item.product_name_hint or "(auto)"))
            self.table.setItem(row, 2, QTableWidgetItem("pending"))
            self.table.setItem(row, 3, QTableWidgetItem("—"))

    def _update_table_row(self, state: ItemState):
        row = state.index - 1
        if row < 0 or row >= self.table.rowCount():
            return
        status_colors = {
            "pending": "#888",
            "downloading": "#1976D2",
            "scripting": "#7B1FA2",
            "tts": "#F57C00",
            "merging": "#00796B",
            "done": "#388E3C",
            "error": "#D32F2F",
        }
        status_item = self.table.item(row, 2)
        if status_item is None:
            status_item = QTableWidgetItem()
            self.table.setItem(row, 2, status_item)
        status_item.setText(state.status.upper())
        status_item.setForeground(Qt.GlobalColor.white)
        from PyQt6.QtGui import QBrush, QColor
        status_item.setBackground(QBrush(QColor(status_colors.get(state.status, "#888"))))

        if state.product_name_hint and self.table.item(row, 1) is not None:
            self.table.item(row, 1).setText(state.product_name_hint)

        out_text = "—"
        if state.final_video_path:
            out_text = Path(state.final_video_path).name
        if state.error:
            out_text = f"❌ {state.error[:80]}"
        out_item = self.table.item(row, 3)
        if out_item is None:
            out_item = QTableWidgetItem()
            self.table.setItem(row, 3, out_item)
        out_item.setText(out_text)

    def start_pipeline(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Đang chạy", "Pipeline đang chạy, vui lòng đợi.")
            return

        items = self._parse_inputs()
        if not items:
            QMessageBox.warning(self, "Chưa có sản phẩm", "Hãy thêm ít nhất 1 sản phẩm (URL + tên + kịch bản).")
            return

        logger.info(f"Bắt đầu pipeline cho {len(items)} sản phẩm")
        self._populate_table(items)
        self.run_btn.setEnabled(False)
        self.run_btn.setText("⏳ Đang chạy...")
        self.status_label.setText(f"Trạng thái: Đang xử lý {len(items)} sản phẩm...")

        max_concurrent = settings.MAX_CONCURRENT
        self.worker = PipelineWorker(items, max_concurrent=max_concurrent)
        self.worker.item_updated.connect(self._update_table_row)
        self.worker.finished_all.connect(self._on_pipeline_finished)
        self.worker.start()

    def _on_pipeline_finished(self, results: List[ItemState]):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶  Run Pipeline")
        n_done = sum(1 for r in results if r.status == "done")
        n_err = sum(1 for r in results if r.status == "error")
        self.status_label.setText(
            f"Trạng thái: Xong — {n_done} thành công, {n_err} lỗi"
        )
        self.statusBar().showMessage("Pipeline hoàn tất", 5000)
        logger.info(f"Pipeline xong: {n_done} OK, {n_err} lỗi")

        if n_err > 0:
            QMessageBox.warning(
                self, "Pipeline xong (có lỗi)",
                f"{n_done} thành công, {n_err} thất bại. Xem bảng để biết chi tiết.",
            )

    def open_output_folder(self):
        import subprocess
        target = Path(settings.FINAL_OUTPUT_DIR)
        target.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])

    def open_intermediate_folder(self):
        """Open the intermediate artifacts folder (sources, voice, scripts)."""
        import subprocess
        target = Path(settings.OUTPUT_DIR)
        target.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])

    def browse_output_folder(self):
        """Open a directory picker and remember the choice in .env."""
        chosen = QFileDialog.getExistingDirectory(
            self, "Chọn folder lưu final video", str(settings.FINAL_OUTPUT_DIR)
        )
        if not chosen:
            return
        self.folder_edit.setText(chosen)
        # Save to .env (live edit)
        self._save_final_output_dir(chosen)
        # Update in-memory settings
        settings.FINAL_OUTPUT_DIR = Path(chosen)
        logger.info(f"Final output folder set to: {chosen}")

    def _save_final_output_dir(self, path: str):
        """Persist the chosen folder to .env (preserves other lines)."""
        env_path = settings.PROJECT_ROOT / ".env"
        if not env_path.exists():
            env_path = settings.PROJECT_ROOT / ".env.example"
        try:
            text = env_path.read_text(encoding="utf-8")
            import re
            if re.search(r"^FINAL_OUTPUT_DIR=", text, re.M):
                text = re.sub(
                    r"^FINAL_OUTPUT_DIR=.*$",
                    f"FINAL_OUTPUT_DIR={path}",
                    text,
                    flags=re.M,
                )
            else:
                # Insert near the OUTPUT_DIR line
                text = re.sub(
                    r"^(OUTPUT_DIR=.*$)",
                    rf"\1\nFINAL_OUTPUT_DIR={path}",
                    text,
                    count=1,
                    flags=re.M,
                )
            env_path.write_text(text, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not save FINAL_OUTPUT_DIR to .env: {e}")

    def _save_env_value(self, key: str, value: str):
        """Generic .env writer: update KEY=value, or append if missing.
        Used for LUCY_VOICE_ID, FINAL_OUTPUT_DIR, etc."""
        env_path = settings.PROJECT_ROOT / ".env"
        if not env_path.exists():
            env_path = settings.PROJECT_ROOT / ".env.example"
        try:
            text = env_path.read_text(encoding="utf-8")
            import re
            pattern = rf"^{re.escape(key)}="
            if re.search(pattern, text, re.M):
                text = re.sub(
                    rf"^{re.escape(key)}=.*$",
                    f"{key}={value}",
                    text,
                    flags=re.M,
                )
            else:
                # Append at end of file
                if not text.endswith("\n"):
                    text += "\n"
                text += f"{key}={value}\n"
            env_path.write_text(text, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not save {key} to .env: {e}")

    def reveal_latest(self):
        target = Path(settings.FINAL_OUTPUT_DIR)
        target.mkdir(parents=True, exist_ok=True)
        finals = sorted(target.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not finals:
            QMessageBox.information(self, "Chưa có file", "Chưa có file MP3/MP4 nào trong folder final.")
            return
        latest = finals[0]
        import subprocess
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(latest)])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", f"/select,{latest}"])

    def clear_all(self):
        if self.product_list.rows:
            self.product_list.clear()
        self.product_list.add_row()
        self.log_view.clear()
        self.status_label.setText("Trạng thái: Sẵn sàng")

    def show_about(self):
        QMessageBox.about(
            self,
            "About TikTok Review Tool",
            "<h3>TikTok Review Tool</h3>"
            "<p>Pipeline: TikWM download → Script (manual) → TTS ADAM2 → FFmpeg merge</p>"
            "<p>Output: <code>outputs/&lt;index&gt;_&lt;product&gt;/final_video.mp4</code></p>"
            f"<p>Output folder: <code>{settings.OUTPUT_DIR}</code></p>"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("TikTok Review Tool")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()