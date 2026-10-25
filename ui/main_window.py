"""主窗口：左右对照、翻译流水线、导出与设置。"""

from __future__ import annotations

import csv
import logging
import os
import tempfile
import time
from typing import List, Optional

from PySide6.QtCore import QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction, QCloseEvent, QDesktopServices, QFontMetrics, QIcon, QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSplitter,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from core.config import AppConfig, resource_path
from core.extract import DocInfo, cleanup_font_files, extract_document
from core.library import DemoMemory, TranslationLibrary
from core.pipeline import TranslationPipeline, TranslationSummary
from core.providers import ENGINE_ORDER, PROVIDER_SPECS
from core.render import export_side_by_side, render_document

from . import icons
from . import theme as T
from .library_dialog import LibraryDialog
from .pdf_view import PdfView
from .segment_dialog import SegmentDialog
from .settings_dialog import SettingsDialog
from .widgets import (
    ComboBox, EmptyState, IconButton, PageBadge, PaneCard, Toast,
)


log = logging.getLogger(__name__)


TARGET_OPTIONS = [
    ("简体中文", "zh-CN"),
    ("繁体中文", "zh-TW"),
    ("英语", "en"),
    ("日语", "ja"),
    ("韩语", "ko"),
    ("法语", "fr"),
    ("德语", "de"),
    ("西班牙语", "es"),
    ("俄语", "ru"),
    ("葡萄牙语", "pt"),
    ("意大利语", "it"),
    ("阿拉伯语", "ar"),
]


# --------------------------------------------------------------------------- #
# 工作线程
# --------------------------------------------------------------------------- #
class DocumentLoadWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, target: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.target = target

    def run(self) -> None:
        try:
            doc = extract_document(self.path, self.target)
        except Exception as exc:
            log.exception("Failed to extract PDF")
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        if not doc.pages:
            self.failed.emit("这份 PDF 没有可读取的页面。")
            return
        self.loaded.emit(doc)


class TranslationWorker(QThread):
    blockDone = Signal(int, int, str, str, str, str)
    pageDone = Signal(int, int, int)
    progressChanged = Signal(int, int, int, int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, pipeline: TranslationPipeline, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.pipeline.on_block = self.blockDone.emit
        self.pipeline.on_page = self.pageDone.emit
        self.pipeline.on_progress = self.progressChanged.emit

    def cancel(self) -> None:
        self.pipeline.cancel_event.set()

    def run(self) -> None:
        try:
            summary = self.pipeline.run()
        except Exception as exc:
            log.exception("Translation failed")
            self.failed.emit(str(exc) or "翻译失败")
            return
        self.succeeded.emit(summary)


class ExportWorker(QThread):
    done = Signal(str, list)
    failed = Signal(str)

    def __init__(self, doc: DocInfo, output: str, kind: str,
                 font_scale: float, auto_shrink: bool, mode: str,
                 target_lang: str, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.output = output
        self.kind = kind
        self.font_scale = font_scale
        self.auto_shrink = auto_shrink
        self.mode = mode
        self.target_lang = target_lang

    def run(self) -> None:
        tmp = ""
        try:
            parent = os.path.dirname(os.path.abspath(self.output))
            if parent:
                os.makedirs(parent, exist_ok=True)
            if self.kind == "bilingual":
                fd, tmp = tempfile.mkstemp(suffix=".pdf", prefix="yipage_")
                os.close(fd)
                result = render_document(
                    self.doc, tmp, mode=self.mode, font_scale=self.font_scale,
                    target_lang=self.target_lang, auto_shrink=self.auto_shrink,
                )
                export_side_by_side(self.doc, tmp, self.output)
                warnings = list(result.warnings)
            else:
                result = render_document(
                    self.doc, self.output, mode=self.mode,
                    font_scale=self.font_scale, target_lang=self.target_lang,
                    auto_shrink=self.auto_shrink,
                )
                warnings = list(result.warnings)
        except Exception as exc:
            log.exception("Export failed")
            self.failed.emit(str(exc))
            return
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        self.done.emit(self.output, warnings)


# --------------------------------------------------------------------------- #
# 主窗口
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, library: TranslationLibrary):
        super().__init__()
        self.config = config
        self.library = library
        self.demo = DemoMemory(resource_path("demo", "demo_library.json"))
        self.doc: Optional[DocInfo] = None
        self._load_worker: Optional[DocumentLoadWorker] = None
        self._translation_worker: Optional[TranslationWorker] = None
        self._export_worker: Optional[ExportWorker] = None
        self._load_error = ""
        self._auto_start_pending = False
        self._pending_close = False
        self._syncing_scroll = False
        self._syncing_zoom = False
        self._loading_config = False
        self._total_blocks = 0
        self._done_blocks = 0
        self._error_blocks = 0
        self._current_scope = "all"
        self._last_summary: Optional[TranslationSummary] = None
        self._last_error = ""
        self._last_export_path = ""
        self._skip_close_prompt = False
        self._shortcuts: List[QShortcut] = []
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(90)
        self._fit_timer.timeout.connect(self._apply_fit_width)

        # Windows 自动在标题后追加应用名，因此这里不再重复“肥鱼译文”
        self.setWindowTitle("原位对照翻译")
        self.setWindowIcon(QIcon(resource_path("app.ico")))
        screen = QApplication.primaryScreen()
        width, height = 1420, 900
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, max(1320, available.width() - 48))
            height = min(height, max(680, available.height() - 48))
        self.resize(width, height)
        self.setMinimumSize(1320, 680)
        self.setAcceptDrops(True)
        self._build_ui()
        self._bind_shortcuts()
        self._apply_config()
        self._update_library_status()
        self._set_status("准备就绪 · 打开一份 PDF，或查看示例文档", "idle")
        self.toast = Toast(self.content)
        self.toast.hide()

    # ------------------------------------------------------------------ #
    # 构建界面
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_topbar())
        root_layout.addWidget(self._build_toolbar())

        self.content = QWidget()
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(16, 12, 16, 10)
        content_layout.setSpacing(10)
        self.content_stack = QStackedWidget()
        self.empty_state = EmptyState()
        self.empty_state.open_requested.connect(self.open_pdf)
        self.empty_state.sample_requested.connect(self.open_sample)
        self.content_stack.addWidget(self.empty_state)
        self.content_stack.addWidget(self._build_splitter())
        content_layout.addWidget(self.content_stack, 1)
        root_layout.addWidget(self.content, 1)
        root_layout.addWidget(self._build_statusbar())
        self.setCentralWidget(root)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(72)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 18, 0)
        layout.setSpacing(11)

        logo = QLabel()
        logo.setPixmap(QIcon(resource_path("app.ico")).pixmap(40, 40))
        logo.setFixedSize(40, 40)
        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
        brand = QVBoxLayout()
        brand.setContentsMargins(0, 4, 0, 0)
        brand.setSpacing(1)
        title = QLabel("肥鱼译文")
        title.setObjectName("BrandTitle")
        brand.addWidget(title)
        layout.addLayout(brand)
        layout.addSpacing(16)

        self.file_chip = QFrame()
        self.file_chip.setObjectName("FileChip")
        self.file_chip.setFixedHeight(44)
        self.file_chip.setMaximumWidth(470)
        chip = QHBoxLayout(self.file_chip)
        chip.setContentsMargins(11, 0, 14, 0)
        chip.setSpacing(9)
        file_icon = QLabel()
        file_icon.setPixmap(icons.svg_pixmap("file", T.ACCENT, 19))
        chip.addWidget(file_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        chip_text = QVBoxLayout()
        chip_text.setContentsMargins(0, 0, 0, 0)
        chip_text.setSpacing(0)
        self.file_name_label = QLabel("")
        self.file_name_label.setStyleSheet("font-size: 12px; font-weight: 600;")
        self.file_meta_label = QLabel("")
        self.file_meta_label.setObjectName("Muted")
        self.file_meta_label.setStyleSheet("font-size: 10px;")
        chip_text.addWidget(self.file_name_label)
        chip_text.addWidget(self.file_meta_label)
        chip.addLayout(chip_text)
        self.file_chip.hide()
        layout.addWidget(self.file_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)

        self.service_chip = PageBadge("本地演示库", "Pill")
        self.service_chip.setToolTip("当前翻译服务")
        layout.addWidget(self.service_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        self.settings_button = IconButton("settings", "设置（Ctrl+,）")
        self.settings_button.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignVCenter)
        return bar

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("ToolBar")
        bar.setFixedHeight(58)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 0, 16, 0)
        layout.setSpacing(8)

        self.open_button = QPushButton(" 打开 PDF")
        self.open_button.setObjectName("Secondary")
        self.open_button.setIcon(icons.icon("folder", T.TEXT_SECONDARY, 16))
        self.open_button.setFixedHeight(34)
        self.open_button.setMinimumWidth(100)
        self.open_button.clicked.connect(self.open_pdf)
        layout.addWidget(self.open_button)

        self.start_button = QPushButton(" 开始翻译")
        self.start_button.setObjectName("Primary")
        self.start_button.setIcon(icons.icon("play", "#FFFFFF", 14))
        self.start_button.setFixedHeight(34)
        self.start_button.setMinimumWidth(112)
        self.start_button.clicked.connect(self.start_translation)
        self.start_button.setEnabled(False)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton(" 停止")
        self.stop_button.setObjectName("Ghost")
        self.stop_button.setIcon(icons.icon("stop", T.TEXT_SECONDARY, 12))
        self.stop_button.setFixedHeight(34)
        self.stop_button.setMinimumWidth(68)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_translation)
        layout.addWidget(self.stop_button)

        self.export_button = QPushButton(" 导出")
        self.export_button.setObjectName("Secondary")
        self.export_button.setIcon(icons.icon("download", T.TEXT_SECONDARY, 16))
        self.export_button.setFixedHeight(34)
        self.export_button.setMinimumWidth(86)
        self.export_button.setEnabled(False)
        export_menu = QMenu(self.export_button)
        export_pdf = export_menu.addAction("译文 PDF（原位覆盖）")
        export_pdf.triggered.connect(lambda: self.export_document("pdf"))
        export_bilingual = export_menu.addAction("左右对照 PDF")
        export_bilingual.triggered.connect(lambda: self.export_document("bilingual"))
        export_menu.addSeparator()
        export_csv = export_menu.addAction("中英对照 CSV")
        export_csv.triggered.connect(lambda: self.export_document("csv"))
        self.export_button.setMenu(export_menu)
        layout.addWidget(self.export_button)
        layout.addWidget(self._vline())

        engine_label = QLabel("引擎")
        engine_label.setObjectName("Muted")
        layout.addWidget(engine_label)
        self.engine_combo = ComboBox()
        for key in ENGINE_ORDER:
            self.engine_combo.addItem(PROVIDER_SPECS[key].short_label, key)
        self.engine_combo.setFixedWidth(142)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_combo_changed)
        layout.addWidget(self.engine_combo)

        target_label = QLabel("译为")
        target_label.setObjectName("Muted")
        layout.addWidget(target_label)
        self.target_combo = ComboBox()
        for label, code in TARGET_OPTIONS:
            self.target_combo.addItem(label, code)
        self.target_combo.setFixedWidth(100)
        self.target_combo.currentIndexChanged.connect(self._on_target_combo_changed)
        layout.addWidget(self.target_combo)

        self.scope_combo = ComboBox()
        self.scope_combo.addItem("全部页面", "all")
        self.scope_combo.addItem("当前页", "page")
        self.scope_combo.setFixedWidth(96)
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        layout.addWidget(self.scope_combo)

        self.library_button = QPushButton(" 翻译库")
        self.library_button.setObjectName("Secondary")
        self.library_button.setIcon(icons.icon("book", T.TEXT_SECONDARY, 15))
        self.library_button.setFixedHeight(34)
        self.library_button.setMinimumWidth(90)
        self.library_button.clicked.connect(self.open_library)
        layout.addWidget(self.library_button)

        layout.addStretch(1)
        self.prev_button = IconButton("chevron_left", "上一页 / PageUp")
        self.prev_button.clicked.connect(lambda: self.go_page(-1))
        layout.addWidget(self.prev_button)
        self.page_label = QLabel("—")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setStyleSheet(
            f"color: {T.TEXT_SECONDARY}; font-size: 11px; min-width: 46px;"
        )
        layout.addWidget(self.page_label)
        self.next_button = IconButton("chevron_right", "下一页 / PageDown")
        self.next_button.clicked.connect(lambda: self.go_page(1))
        layout.addWidget(self.next_button)
        layout.addWidget(self._vline())
        self.zoom_out_button = IconButton("minus", "缩小（Ctrl+-）")
        self.zoom_out_button.clicked.connect(lambda: self.zoom_by(1 / 1.15))
        layout.addWidget(self.zoom_out_button)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setStyleSheet(
            f"color: {T.TEXT_SECONDARY}; font-size: 11px; min-width: 44px;"
        )
        self.zoom_label.setToolTip("当前缩放比例")
        layout.addWidget(self.zoom_label)
        self.zoom_in_button = IconButton("plus", "放大（Ctrl+=）")
        self.zoom_in_button.clicked.connect(lambda: self.zoom_by(1.15))
        layout.addWidget(self.zoom_in_button)
        self.fit_button = IconButton("fit", "适应宽度（Ctrl+0）")
        self.fit_button.clicked.connect(self._apply_fit_width)
        layout.addWidget(self.fit_button)
        return bar

    @staticmethod
    def _vline() -> QFrame:
        line = QFrame()
        line.setFixedSize(1, 22)
        line.setStyleSheet(f"background: {T.BORDER};")
        return line

    def _build_splitter(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(10)
        self.left_card = PaneCard("原文", "PDF", T.ACCENT)
        self.right_card = PaneCard("译文", "原位覆盖", T.GREEN)
        self.left_view = PdfView(translated=False)
        self.right_view = PdfView(translated=True)
        self.right_view.setToolTip("双击右栏任意译文段落，可校对并自动写入本地记忆库。")
        self.left_card.set_view(self.left_view)
        self.right_card.set_view(self.right_view)
        self.splitter.addWidget(self.left_card)
        self.splitter.addWidget(self.right_card)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([700, 700])
        layout.addWidget(self.splitter, 1)
        self.left_view.currentPageChanged.connect(self._on_page_changed)
        self.right_view.currentPageChanged.connect(self._on_page_changed)
        self.right_view.blockActivated.connect(self.edit_block)
        self.left_view.zoomChanged.connect(self._on_view_zoom_changed)
        self.right_view.zoomChanged.connect(self._on_view_zoom_changed)
        self.left_view.verticalScrollBar().valueChanged.connect(
            lambda _v: self._sync_scroll(self.left_view, self.right_view)
        )
        self.right_view.verticalScrollBar().valueChanged.connect(
            lambda _v: self._sync_scroll(self.right_view, self.left_view)
        )
        self.splitter.splitterMoved.connect(lambda *_: self._fit_timer.start())
        return wrap

    def _build_statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(36)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 0, 16, 0)
        layout.setSpacing(9)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(7, 7)
        self.status_dot.setStyleSheet(
            f"background: {T.GREEN}; border-radius: 3px;"
        )
        layout.addWidget(self.status_dot)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("Muted")
        self.progress_label.setStyleSheet("font-size: 10px;")
        self.progress_label.hide()
        layout.addWidget(self.progress_label)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(140)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.library_status = QLabel("")
        self.library_status.setObjectName("Muted")
        self.library_status.setStyleSheet("font-size: 10px;")
        layout.addWidget(self.library_status)
        return bar

    # ------------------------------------------------------------------ #
    # 快捷键 / 拖拽
    # ------------------------------------------------------------------ #
    def _bind_shortcuts(self) -> None:
        mapping = [
            ("Ctrl+O", self.open_pdf),
            ("Ctrl+Return", self.start_translation),
            ("Ctrl+Enter", self.start_translation),
            ("Ctrl+S", lambda: self.export_document("pdf")),
            ("Ctrl+L", self.open_library),
            ("Ctrl+,", self.open_settings),
            ("Ctrl+=", lambda: self.zoom_by(1.15)),
            ("Ctrl++", lambda: self.zoom_by(1.15)),
            ("Ctrl+-", lambda: self.zoom_by(1 / 1.15)),
            ("Ctrl+0", self._apply_fit_width),
            ("PageDown", lambda: self.go_page(1)),
            ("PageUp", lambda: self.go_page(-1)),
        ]
        for sequence, callback in mapping:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path.lower().endswith(".pdf") and os.path.isfile(path):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pdf") and os.path.isfile(path):
                event.acceptProposedAction()
                self.load_document(path)
                return
        event.ignore()

    # ------------------------------------------------------------------ #
    # 配置
    # ------------------------------------------------------------------ #
    def _apply_config(self) -> None:
        self._loading_config = True
        engine = self.config.get("engine", "demo")
        index = self.engine_combo.findData(engine)
        self.engine_combo.setCurrentIndex(index if index >= 0 else 0)
        target = self.config.get("target_lang", "zh-CN")
        target_index = self.target_combo.findData(target)
        self.target_combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        self.left_view.set_font_scale(float(self.config.get("font_scale", 1.0)))
        self.right_view.set_font_scale(float(self.config.get("font_scale", 1.0)))
        self.left_view.set_show_marks(bool(self.config.get("show_quality_marks", True)))
        self.right_view.set_show_marks(bool(self.config.get("show_quality_marks", True)))
        self._loading_config = False
        self._update_service_chip()
        self._refresh_target_tooltip()

    def _update_service_chip(self) -> None:
        engine = self.config.get("engine", "demo")
        spec = PROVIDER_SPECS.get(engine, PROVIDER_SPECS["demo"])
        missing = self._missing_fields(engine)
        if engine == "demo":
            text = "本地演示库"
            style = "GreenPill"
            tip = spec.subtitle + "\n完全离线，不会产生网络请求。"
        elif engine in ("bilibili", "google"):
            text = spec.short_label
            style = "GreenPill"
            tip = spec.subtitle + "\n无需 API Key · 公共免费接口，可能限流。"
            if engine == "google":
                tip += "\n大陆网络通常需要代理。"
        elif missing:
            text = f"{spec.short_label} · 待配置"
            style = "OrangePill"
            tip = spec.subtitle + "\n缺少：" + "、".join(missing)
        else:
            text = spec.short_label
            style = "Pill"
            tip = spec.subtitle + "\n点击右上角设置可修改密钥。"
        self.service_chip.setText(text)
        self.service_chip.set_style(style)
        self.service_chip.setToolTip(tip)

    def _missing_fields(self, engine: str) -> List[str]:
        spec = PROVIDER_SPECS.get(engine)
        if not spec or engine == "demo":
            return []
        options = self.config.provider_config(engine, decrypt=True)
        return [
            field.label for field in spec.fields
            if not str(options.get(field.key, "")).strip()
        ]

    def _refresh_target_tooltip(self) -> None:
        label = self.target_combo.currentText()
        self.target_combo.setToolTip(f"目标语言：{label}")

    def _on_engine_combo_changed(self, _index: int) -> None:
        if self._loading_config:
            return
        engine = self.engine_combo.currentData()
        if not engine:
            return
        old = self.config.get("engine", "demo")
        if engine == old:
            return
        self.config.set("engine", engine)
        self.config.save()
        self._update_service_chip()
        missing = self._missing_fields(engine)
        if engine != "demo" and missing:
            self.toast.show_message(
                f"已切换到{PROVIDER_SPECS[engine].short_label}，请先在设置中填写："
                + "、".join(missing),
                "warning", 4600,
            )
        else:
            self.toast.show_message(
                f"翻译服务：{PROVIDER_SPECS[engine].short_label}", "info", 2400
            )

    def _on_target_combo_changed(self, _index: int) -> None:
        if self._loading_config:
            return
        target = self.target_combo.currentData()
        old = self.config.get("target_lang", "zh-CN")
        if not target or target == old:
            return
        if self._done_blocks > 0 and self.doc is not None:
            reply = QMessageBox.question(
                self, "切换目标语言",
                f"切换为「{self.target_combo.currentText()}」会清除当前译文，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._loading_config = True
                index = self.target_combo.findData(old)
                self.target_combo.setCurrentIndex(max(0, index))
                self._loading_config = False
                return
            self.clear_translations()
        self.config.set("target_lang", target)
        self.config.save()
        self._refresh_target_tooltip()
        self.toast.show_message(
            f"目标语言已切换为{self.target_combo.currentText()}", "info", 2200
        )

    def _on_scope_changed(self, _index: int) -> None:
        self._current_scope = self.scope_combo.currentData() or "all"
        if self._current_scope == "page":
            self.toast.show_message("只翻译当前页；滚动到目标页后再开始。", "info", 2600)

    def open_settings(self) -> None:
        if self._is_busy():
            return
        old_target = self.config.get("target_lang", "zh-CN")
        dialog = SettingsDialog(self.config, self.library, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._apply_config()
            return
        new_library = getattr(dialog, "new_library", None)
        library_switched = new_library is not None
        if library_switched:
            old_library = self.library
            self.library = new_library
            try:
                old_library.close()
            except Exception:
                pass
        new_target = self.config.get("target_lang", "zh-CN")
        if new_target != old_target and self._done_blocks > 0:
            reply = QMessageBox.question(
                self, "目标语言已更改",
                "目标语言已更改，是否清除当前译文并使用新语言重新开始？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.clear_translations()
            else:
                self.config.set("target_lang", old_target)
                self.config.save()
        self._apply_config()
        self._update_library_status()
        self._update_right_header()
        self.toast.show_message(
            "设置已保存 · 翻译库已切换" if library_switched else "设置已保存",
            "success", 2600,
        )

    def open_library(self) -> None:
        if self._is_busy():
            return
        dialog = LibraryDialog(self.library, self.config, self)
        dialog.exec()
        self._update_library_status()

    def _update_library_status(self) -> None:
        try:
            stats = self.library.stats()
            self.library_status.setText(
                f"本地库 {stats['glossary']} 术语 · {stats['memory']} 记忆"
            )
            self.library_status.setToolTip(
                f"累计命中 {stats['hits']} 次；管理翻译库（Ctrl+L）"
            )
        except Exception:
            self.library_status.setText("本地库不可用")

    # ------------------------------------------------------------------ #
    # 打开文档
    # ------------------------------------------------------------------ #
    def open_pdf(self) -> None:
        if self._is_busy():
            return
        start_dir = self.config.get("last_dir") or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 PDF", start_dir, "PDF 文件 (*.pdf);;所有文件 (*)"
        )
        if path:
            self.load_document(path)

    def open_sample(self) -> None:
        path = resource_path("demo", "sample.pdf")
        if not os.path.isfile(path):
            QMessageBox.warning(self, "示例缺失", "示例 PDF 不存在，请重新安装应用。")
            return
        engine = self.config.get("engine", "bilibili")
        autostart = engine in ("demo", "bilibili")
        if engine not in ("demo", "bilibili") and self._missing_fields(engine):
            self._loading_config = True
            idx = self.engine_combo.findData("demo")
            self.engine_combo.setCurrentIndex(max(0, idx))
            self._loading_config = False
            self.config.set("engine", "demo")
            self.config.save()
            self._update_service_chip()
            autostart = True
            self.toast.show_message("示例使用本地演示库，全程离线。", "info", 2600)
        self.load_document(path, autostart=autostart)

    def load_document(self, path: str, autostart: bool = False) -> None:
        if self._is_busy():
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "文件不存在", f"找不到文件：\n{path}")
            return
        if not path.lower().endswith(".pdf"):
            QMessageBox.warning(self, "格式不支持", "请选择 PDF 文件。")
            return
        if self.doc is not None and self._done_blocks > 0:
            reply = QMessageBox.question(
                self, "打开新文档",
                f"当前文档有 {self._done_blocks} 段译文尚未导出，仍要打开新文档吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._load_error = ""
        self._auto_start_pending = autostart
        self._show_file_loading(path)
        self._set_actions_loading()
        self._show_indeterminate("正在解析 PDF 页面与文字块…")
        self._set_status("正在解析 PDF…", "working")
        worker = DocumentLoadWorker(
            path, self.config.get("target_lang", "zh-CN"), self
        )
        self._load_worker = worker
        worker.loaded.connect(self._on_document_loaded)
        worker.failed.connect(self._on_document_failed)
        worker.finished.connect(self._on_load_finished)
        worker.start()

    def _on_document_loaded(self, doc: DocInfo) -> None:
        old_doc = self.doc
        if old_doc is not None:
            try:
                cleanup_font_files(old_doc.all_blocks())
            except Exception:
                pass
        self.doc = doc
        self.left_view.set_document(doc)
        self.right_view.set_document(doc)
        self.left_view.set_font_scale(float(self.config.get("font_scale", 1.0)))
        self.right_view.set_font_scale(float(self.config.get("font_scale", 1.0)))
        self.left_view.set_show_marks(bool(self.config.get("show_quality_marks", True)))
        self.right_view.set_show_marks(bool(self.config.get("show_quality_marks", True)))
        self._recount()
        self._error_blocks = 0
        self._last_summary = None
        self._last_error = ""
        self._last_export_path = ""
        self.content_stack.setCurrentIndex(1)
        self.left_card.set_hint(f"PDF · {len(doc.pages)} 页")
        self.right_card.set_badge("待翻译", "OrangePill")
        self._update_right_header()
        self._update_file_chip()
        self.left_card.set_page(1, len(doc.pages))
        self.right_card.set_page(1, len(doc.pages))
        self.page_label.setText(f"1 / {len(doc.pages)}")
        self.setWindowTitle(os.path.basename(doc.path))
        self.config.remember_file(doc.path)
        self._hide_progress()
        self._set_status(
            f"已载入 · {len(doc.pages)} 页 · {self._total_blocks} 个文本块 · 点击「开始翻译」",
            "ok",
        )
        self.start_button.setText(" 开始翻译")
        self.start_button.setIcon(icons.icon("play", "#FFFFFF", 14))
        self._update_library_status()
        QTimer.singleShot(40, self._reset_and_fit)

    def _on_document_failed(self, error: str) -> None:
        self._load_error = error
        self._hide_progress()
        self._set_status("PDF 解析失败 · " + error[:120], "error")
        if self.doc is None:
            self.content_stack.setCurrentIndex(0)
            self.file_chip.hide()
        self._toast("打开失败：" + error[:220], "error", 6000)

    def _on_load_finished(self) -> None:
        worker = self._load_worker
        self._load_worker = None
        if worker is not None:
            worker.deleteLater()
        self._hide_progress()
        if self._load_error:
            self._set_actions_idle()
            if self.doc is not None:
                self._update_file_chip()
            else:
                self.file_chip.hide()
            self._load_error = ""
            self._auto_start_pending = False
            self._hide_progress()
            if self._pending_close:
                self._pending_close = False
                self.close()
            return
        self._set_actions_idle()
        if self._pending_close:
            self._pending_close = False
            self.close()
            return
        if self._auto_start_pending:
            self._auto_start_pending = False
            QTimer.singleShot(260, self.start_translation)

    def _reset_and_fit(self) -> None:
        if self.doc is None:
            return
        self._syncing_scroll = True
        self.left_view.verticalScrollBar().setValue(0)
        self.right_view.verticalScrollBar().setValue(0)
        self._syncing_scroll = False
        self._apply_fit_width()
        page = self.left_view.current_page()
        self._on_page_changed(page)

    def _show_file_loading(self, path: str) -> None:
        self.file_chip.show()
        self.file_name_label.setText(self._elide(os.path.basename(path), 260))
        self.file_name_label.setToolTip(path)
        self.file_meta_label.setText("正在解析…")

    def _update_file_chip(self) -> None:
        if self.doc is None:
            self.file_chip.hide()
            return
        self.file_chip.show()
        name = os.path.basename(self.doc.path)
        self.file_name_label.setText(self._elide(name, 260))
        self.file_name_label.setToolTip(self.doc.path)
        self.file_meta_label.setText(
            f"{len(self.doc.pages)} 页 · {self._total_blocks} 个文本块"
        )

    @staticmethod
    def _elide(text: str, width: int) -> str:
        label = QLabel()
        metrics = QFontMetrics(label.font())
        return metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, width)

    # ------------------------------------------------------------------ #
    # 页面 / 缩放
    # ------------------------------------------------------------------ #
    def _on_page_changed(self, page: int) -> None:
        if self.doc is None:
            self.page_label.setText("—")
            return
        total = len(self.doc.pages)
        if total <= 0:
            return
        page = max(0, min(total - 1, page))
        self.left_card.set_page(page + 1, total)
        self.right_card.set_page(page + 1, total)
        self.page_label.setText(f"{page + 1} / {total}")

    def go_page(self, delta: int) -> None:
        if self.doc is None:
            return
        current = self.left_view.current_page()
        target = max(0, min(len(self.doc.pages) - 1, current + delta))
        if target == current:
            return
        self._syncing_scroll = True
        self.left_view.scroll_to_page(target)
        self.right_view.scroll_to_page(target)
        self._syncing_scroll = False
        self._on_page_changed(target)

    def _sync_scroll(self, source: PdfView, target: PdfView) -> None:
        if self._syncing_scroll or self.doc is None:
            return
        self._syncing_scroll = True
        target.verticalScrollBar().setValue(source.verticalScrollBar().value())
        self._syncing_scroll = False

    def _apply_fit_width(self) -> None:
        if self.doc is None or self.content_stack.currentIndex() == 0:
            return
        left_scale = self.left_view.fit_width_scale()
        right_scale = self.right_view.fit_width_scale()
        scale = max(self.left_view.MIN_ZOOM, min(left_scale, right_scale))
        self._syncing_zoom = True
        try:
            self.left_view.apply_zoom(scale, True)
            self.right_view.apply_zoom(scale, True)
        finally:
            self._syncing_zoom = False
        self._syncing_scroll = True
        self.right_view.verticalScrollBar().setValue(
            self.left_view.verticalScrollBar().value()
        )
        self._syncing_scroll = False
        self._update_zoom_label(scale)

    def _on_view_zoom_changed(self, zoom: float) -> None:
        if self._syncing_zoom:
            return
        source = self.sender()
        target = self.right_view if source is self.left_view else self.left_view
        self._syncing_zoom = True
        try:
            target.apply_zoom(zoom, source.fit_mode)
        finally:
            self._syncing_zoom = False
        self._syncing_scroll = True
        self.right_view.verticalScrollBar().setValue(
            self.left_view.verticalScrollBar().value()
        )
        self._syncing_scroll = False
        self._update_zoom_label(zoom)

    def _update_zoom_label(self, zoom: float) -> None:
        self.zoom_label.setText(f"{int(round(zoom * 100))}%")
        self.zoom_label.setToolTip("适应宽度" if self.left_view.fit_mode and self.right_view.fit_mode
                                   else "手动缩放")

    def zoom_by(self, factor: float) -> None:
        if self.doc is None:
            return
        base = min(self.left_view.zoom, self.right_view.zoom)
        zoom = max(PdfView.MIN_ZOOM, min(PdfView.MAX_ZOOM, base * factor))
        self._syncing_zoom = True
        try:
            self.left_view.apply_zoom(zoom, False)
            self.right_view.apply_zoom(zoom, False)
        finally:
            self._syncing_zoom = False
        self._syncing_scroll = True
        self.right_view.verticalScrollBar().setValue(
            self.left_view.verticalScrollBar().value()
        )
        self._syncing_scroll = False
        self._update_zoom_label(zoom)

    # ------------------------------------------------------------------ #
    # 翻译
    # ------------------------------------------------------------------ #
    def start_translation(self) -> None:
        if self.doc is None or self._is_busy():
            return
        engine = self.config.get("engine", "demo")
        if engine != "demo":
            missing = self._missing_fields(engine)
            if missing:
                self._set_status("翻译服务尚未配置 · " + "、".join(missing), "warn")
                self._toast(
                    "请先在设置中填写 " + "、".join(missing) + "，再开始翻译。",
                    "warning", 4200,
                )
                self.open_settings()
                return
        pages = self._page_scope()
        if not pages:
            QMessageBox.information(self, "没有可翻译页面", "当前范围内没有页面。")
            return
        selected_blocks = [
            block for number in pages for block in self.doc.pages[number].blocks
            if not block.rotation
        ]
        if not selected_blocks:
            QMessageBox.information(
                self, "没有可翻译文字",
                "所选页面没有可编辑文字层。扫描件需要先做 OCR。",
            )
            return
        provider_options = self.config.provider_config(engine, decrypt=True)
        pipeline = TranslationPipeline(
            self.doc, self.library, self.demo, engine,
            self.config.get("source_lang", "auto"),
            self.config.get("target_lang", "zh-CN"),
            provider_options,
            use_library=bool(self.config.get("use_library", True)),
            auto_save=bool(self.config.get("auto_save_memory", True)),
            fuzzy_threshold=float(self.config.get("fuzzy_threshold", 0.84)),
            page_numbers=pages,
            demo_path=resource_path("demo", "demo_library.json"),
        )
        worker = TranslationWorker(pipeline, self)
        self._translation_worker = worker
        worker.blockDone.connect(self._on_block_translated)
        worker.pageDone.connect(self._on_page_translated)
        worker.progressChanged.connect(self._on_translation_progress)
        worker.succeeded.connect(self._on_translation_succeeded)
        worker.failed.connect(self._on_translation_failed)
        worker.finished.connect(self._on_translation_finished)
        self._last_export_path = ""
        self._set_actions_translating()
        self.start_button.setText(" 正在翻译…")
        self.right_card.set_badge("翻译中", "SoftPill")
        self._last_summary = None
        self._last_error = ""
        total = len(selected_blocks)
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self.progress_label.setText(f"0 / {total} 段")
        self.progress_label.show()
        self.progress.show()
        self._set_status(
            f"正在使用{PROVIDER_SPECS[engine].short_label}翻译 · 0/{total} 段",
            "working",
        )
        worker.start()

    def stop_translation(self) -> None:
        if self._translation_worker is None:
            return
        self._translation_worker.cancel()
        self.stop_button.setEnabled(False)
        self._set_status("正在停止翻译，当前请求完成后会保存进度…", "working")

    def _page_scope(self) -> List[int]:
        if self.doc is None:
            return []
        if self._current_scope == "page":
            return [self.left_view.current_page()]
        return [page.number for page in self.doc.pages]

    def _on_block_translated(self, page: int, index: int, translation: str,
                             status: str, quality: str, error: str) -> None:
        if self.doc is None or not 0 <= page < len(self.doc.pages):
            return
        blocks = self.doc.pages[page].blocks
        if not 0 <= index < len(blocks):
            return
        block = blocks[index]
        old_done = block.status in ("done", "skipped") and bool(block.translation)
        new_done = status in ("done", "skipped") and bool(translation)
        if old_done and not new_done:
            self._done_blocks -= 1
        elif not old_done and new_done:
            self._done_blocks += 1
        if status == "error" and block.status != "error":
            self._error_blocks += 1
        elif status != "error" and block.status == "error":
            self._error_blocks = max(0, self._error_blocks - 1)
        block.translation = translation
        block.status = status
        block.quality = quality
        block.error = error
        self.right_view.update_page(page)
        self._update_right_header()
        if self._translation_worker is not None:
            self.right_card.set_badge(
                f"翻译中 · {self._done_blocks}/{self._total_blocks}", "SoftPill"
            )

    def _on_page_translated(self, page: int, processed: int, total: int) -> None:
        if self.doc is None:
            return
        page_info = self.doc.pages[page]
        self.right_view.update_page(page)
        self._set_status(
            f"第 {page + 1} / {len(self.doc.pages)} 页已处理 · "
            f"{processed}/{total} 段 · 已译 {self._done_blocks}/{self._total_blocks}",
            "working",
        )

    def _on_translation_progress(self, done: int, total: int, pages_done: int,
                                 pages_total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, total))
        self.progress_label.setText(f"{done} / {total} 段")
        self.progress_label.show()
        self.progress.show()
        self._set_status(
            f"正在翻译 · {done}/{total} 段 · 第 {max(1, pages_done)}/{max(1, pages_total)} 页",
            "working",
        )

    def _on_translation_succeeded(self, summary: TranslationSummary) -> None:
        self._last_summary = summary
        self._recount()
        self._error_blocks = summary.errors
        self._update_right_header()
        self._update_library_status()
        elapsed = max(0.1, summary.elapsed)
        duration = f"{elapsed:.1f}s" if elapsed < 60 else f"{int(elapsed // 60)}m{int(elapsed % 60):02d}s"
        done = self._done_blocks
        total = self._total_blocks
        current_engine = self.config.get("engine")
        online_label = "B站免费" if current_engine == "bilibili" else "机器翻译"
        source_parts = []
        if summary.library_hits:
            source_parts.append(f"本地库 {summary.library_hits} 段")
        if summary.demo_hits:
            source_parts.append(f"演示库 {summary.demo_hits} 段")
        if summary.machine:
            source_parts.append(f"{online_label} {summary.machine} 段")
        source_detail = " / ".join(source_parts) or "0 段"
        if summary.cancelled:
            self._set_status(
                f"已停止 · 已保留进度 {done}/{total} 段 · 再次点击「开始翻译」可继续",
                "warn",
            )
            self.right_card.set_badge("已停止", "OrangePill")
            self._toast(f"已停止，当前进度已保留（{done}/{total} 段）。", "warning", 3600)
            self.start_button.setText(" 继续翻译")
        elif summary.errors:
            message = summary.last_error or "部分段落翻译失败"
            self._set_status(
                f"完成，但有 {summary.errors} 段失败 · {message[:100]}", "error"
            )
            self.right_card.set_badge("部分完成", "OrangePill")
            self._toast(f"{summary.errors} 段翻译失败：{message[:160]}", "error", 6500)
            self.start_button.setText(" 重试翻译")
        elif summary.misses:
            self._set_status(
                f"完成 · {done}/{total} 段有译文 · {summary.misses} 段未收录",
                "warn",
            )
            self.right_card.set_badge("部分完成", "OrangePill")
            self._toast(
                f"已有译文 {done}/{total} 段；未收录的 {summary.misses} 段可改用免费在线、"
                "本地库或其它翻译服务重试。",
                "warning", 5200,
            )
            self.start_button.setText(" 重新翻译")
        else:
            self._set_status(
                f"翻译完成 · {summary.translated} 段 · 用时 {duration} · {source_detail}",
                "ok",
            )
            self.right_card.set_badge("已完成", "GreenPill")
            self._toast(f"翻译完成 · {summary.translated} 段 · 用时 {duration}", "success", 3600)
            self.start_button.setText(" 重新翻译")
        if not summary.cancelled:
            self.progress.setRange(0, max(1, summary.total))
            self.progress.setValue(max(1, summary.total))
            self.progress_label.setText(f"{summary.total} / {summary.total} 段")
        self._update_zoom_label(self.left_view.zoom)

    def _on_translation_failed(self, error: str) -> None:
        self._last_error = error
        self._set_status("翻译失败 · " + error[:140], "error")
        self.right_card.set_badge("翻译失败", "OrangePill")
        self._toast(
            "翻译失败：" + error[:200]
            + "；可在引擎下拉更换服务，或切换到本地演示库。",
            "error", 7000,
        )
        log.error("Translation error: %s", error)
        self.start_button.setText(" 重试翻译" if self._done_blocks == 0 else " 重新翻译")

    def _on_translation_finished(self) -> None:
        worker = self._translation_worker
        self._translation_worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_actions_idle()
        if self._last_summary is None and self._last_error:
            self.stop_button.setEnabled(False)
        else:
            self.stop_button.setEnabled(False)
        if self._pending_close:
            self._pending_close = False
            self.close()

    def clear_translations(self) -> None:
        if self.doc is None:
            return
        for page in self.doc.pages:
            for block in page.blocks:
                block.translation = ""
                block.status = "pending"
                block.quality = ""
                block.error = ""
        self._done_blocks = 0
        self._error_blocks = 0
        self._last_summary = None
        self._last_export_path = ""
        self.left_view.update_all()
        self.right_view.update_all()
        self._update_right_header()
        self.progress.hide()
        self.progress_label.hide()
        self.export_button.setEnabled(False)
        self.start_button.setText(" 开始翻译")
        self._set_status("译文已清除 · 可以重新开始翻译", "idle")

    def _recount(self) -> None:
        total = 0
        done = 0
        errors = 0
        if self.doc is not None:
            for page in self.doc.pages:
                for block in page.blocks:
                    if block.rotation:
                        continue
                    total += 1
                    if block.status in ("done", "skipped") and block.translation:
                        done += 1
                    if block.status == "error":
                        errors += 1
        self._total_blocks = total
        self._done_blocks = done
        self._error_blocks = errors

    def _update_right_header(self) -> None:
        if self.doc is None:
            self.right_card.set_badge("", "Pill")
            return
        self.right_card.set_hint(f"原位覆盖 · {self._done_blocks} / {self._total_blocks} 段")
        if self._translation_worker is not None:
            style = "SoftPill"
            text = f"翻译中 · {self._done_blocks}/{self._total_blocks}"
        elif self._error_blocks:
            style = "OrangePill"
            text = "部分完成"
        elif self._done_blocks >= self._total_blocks and self._total_blocks > 0:
            style = "GreenPill"
            text = "已完成"
        elif self._done_blocks > 0:
            style = "OrangePill"
            text = "部分完成"
        else:
            style = "OrangePill"
            text = "待翻译"
        self.right_card.set_badge(text, style)

    # ------------------------------------------------------------------ #
    # 校对
    # ------------------------------------------------------------------ #
    def edit_block(self, page: int, index: int) -> None:
        if self.doc is None or not 0 <= page < len(self.doc.pages):
            return
        blocks = self.doc.pages[page].blocks
        if not 0 <= index < len(blocks):
            return
        block = blocks[index]
        dialog = SegmentDialog(
            page, index, block.text, block.translation or "",
            self.config.get("source_lang", "auto"),
            self.config.get("target_lang", "zh-CN"), self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        text = dialog.translation()
        if not text:
            return
        old_done = block.status in ("done", "skipped") and bool(block.translation)
        block.translation = text
        block.status = "done"
        block.quality = "manual"
        block.error = ""
        if not old_done:
            self._done_blocks += 1
            if self._error_blocks:
                self._error_blocks = max(0, self._error_blocks - 1)
        try:
            self.library.remember(
                block.text, text,
                self.config.get("source_lang", "auto"),
                self.config.get("target_lang", "zh-CN"),
                engine="manual", quality="manual", overwrite=True,
            )
        except Exception:
            pass
        self._last_export_path = ""
        self.right_view.update_page(page)
        self._update_right_header()
        self._update_library_status()
        self.export_button.setEnabled(self._done_blocks > 0)
        self._set_status(
            f"已保存第 {page + 1} 页第 {index + 1} 段译文，并写入记忆库", "ok"
        )

    # ------------------------------------------------------------------ #
    # 导出
    # ------------------------------------------------------------------ #
    def export_document(self, kind: str) -> None:
        if self.doc is None:
            QMessageBox.information(self, "没有文档", "请先打开并翻译一份 PDF。")
            return
        if self._is_busy():
            return
        if self._done_blocks == 0:
            QMessageBox.information(self, "还没有译文", "请先开始翻译，再导出。")
            return
        if kind == "csv":
            self._export_csv()
            return
        if self._done_blocks < self._total_blocks:
            reply = QMessageBox.question(
                self, "仍有未翻译段落",
                f"还有 {self._total_blocks - self._done_blocks} 段没有译文，"
                "导出后这些位置会保留原文。继续导出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        base = os.path.splitext(os.path.basename(self.doc.path))[0]
        suffix = "_译文.pdf" if kind == "pdf" else "_左右对照.pdf"
        default = os.path.join(
            self.config.get("last_dir") or os.path.dirname(self.doc.path),
            base + suffix,
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 PDF", default, "PDF 文件 (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        worker = ExportWorker(
            self.doc, path, kind,
            float(self.config.get("font_scale", 1.0)),
            bool(self.config.get("auto_shrink", True)),
            str(self.config.get("mode", "redact")),
            self.config.get("target_lang", "zh-CN"),
            self,
        )
        self._export_worker = worker
        worker.done.connect(self._on_export_done)
        worker.failed.connect(self._on_export_failed)
        worker.finished.connect(self._on_export_finished)
        self._set_actions_exporting()
        self._show_indeterminate("正在写入译文 PDF…")
        self._set_status("正在生成 PDF，请勿关闭窗口…", "working")
        worker.start()

    def _export_csv(self) -> None:
        if self.doc is None:
            return
        base = os.path.splitext(os.path.basename(self.doc.path))[0]
        default = os.path.join(
            self.config.get("last_dir") or os.path.dirname(self.doc.path),
            base + "_对照.csv",
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "导出对照 CSV", default, "CSV 文件 (*.csv)"
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["页码", "段号", "原文", "译文", "状态"])
                for page in self.doc.pages:
                    for block in page.blocks:
                        if block.rotation:
                            continue
                        writer.writerow([
                            page.number + 1, block.index + 1, block.text,
                            block.translation or "", block.status,
                        ])
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self._last_export_path = path
        self._set_status("已导出对照 CSV · " + path, "ok")
        self._toast("对照 CSV 已导出", "success", 2600)
        self._offer_open(path)

    def _on_export_done(self, path: str, warnings: list) -> None:
        self._last_export_path = path
        self._hide_progress()
        self._set_status("已导出 · " + path, "ok")
        warning_text = ""
        if warnings:
            warning_text = "\n\n提示：" + "；".join(str(item) for item in warnings[:3])
        self._toast("PDF 导出完成", "success", 3200)
        QTimer.singleShot(10, lambda: self._offer_open(path, warning_text))

    def _on_export_failed(self, error: str) -> None:
        self._hide_progress()
        self._set_status("导出失败 · " + error[:140], "error")
        QMessageBox.warning(self, "导出失败", error)

    def _on_export_finished(self) -> None:
        worker = self._export_worker
        self._export_worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_actions_idle()
        if self._pending_close:
            self._pending_close = False
            self.close()

    def _offer_open(self, path: str, extra: str = "") -> None:
        box = QMessageBox(self)
        box.setWindowTitle("导出完成")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("文件已保存：\n" + path + extra)
        open_button = box.addButton("打开文件", QMessageBox.ButtonRole.ActionRole)
        box.addButton("完成", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------ #
    # 状态与动作
    # ------------------------------------------------------------------ #
    def _is_busy(self) -> bool:
        return (
            self._load_worker is not None
            or self._translation_worker is not None
            or self._export_worker is not None
        )

    def _set_actions_loading(self) -> None:
        self.open_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.engine_combo.setEnabled(False)
        self.target_combo.setEnabled(False)
        self.scope_combo.setEnabled(False)
        self.library_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.empty_state.open_button.setEnabled(False)
        self.empty_state.sample_button.setEnabled(False)
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.fit_button.setEnabled(False)

    def _set_actions_translating(self) -> None:
        self.open_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.export_button.setEnabled(False)
        self.engine_combo.setEnabled(False)
        self.target_combo.setEnabled(False)
        self.scope_combo.setEnabled(False)
        self.library_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.empty_state.open_button.setEnabled(False)
        self.empty_state.sample_button.setEnabled(False)
        self.prev_button.setEnabled(True)
        self.next_button.setEnabled(True)
        self.fit_button.setEnabled(True)

    def _set_actions_exporting(self) -> None:
        self.open_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.engine_combo.setEnabled(False)
        self.target_combo.setEnabled(False)
        self.scope_combo.setEnabled(False)
        self.library_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.empty_state.open_button.setEnabled(False)
        self.empty_state.sample_button.setEnabled(False)

    def _set_actions_idle(self) -> None:
        self.open_button.setEnabled(True)
        self.start_button.setEnabled(self.doc is not None)
        self.stop_button.setEnabled(False)
        self.export_button.setEnabled(self.doc is not None and self._done_blocks > 0)
        self.engine_combo.setEnabled(True)
        self.target_combo.setEnabled(True)
        self.scope_combo.setEnabled(True)
        self.library_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.empty_state.open_button.setEnabled(True)
        self.empty_state.sample_button.setEnabled(True)
        self.prev_button.setEnabled(self.doc is not None)
        self.next_button.setEnabled(self.doc is not None)
        self.fit_button.setEnabled(self.doc is not None)
        if self.doc is None:
            self.start_button.setText(" 开始翻译")
            self.export_button.setEnabled(False)

    def _set_status(self, text: str, kind: str = "idle") -> None:
        self.status_label.setText(text)
        color = {
            "idle": T.GREEN, "ok": T.GREEN, "working": T.ACCENT,
            "warn": T.ORANGE, "error": T.RED,
        }.get(kind, T.GREEN)
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 3px;")
        if kind == "error":
            self.status_label.setStyleSheet(f"font-size: 11px; color: {T.RED};")
        else:
            self.status_label.setStyleSheet("font-size: 11px;")
        self.toast.reposition() if hasattr(self, "toast") else None

    def _show_indeterminate(self, label: str) -> None:
        self.progress.setRange(0, 0)
        self.progress_label.setText(label)
        self.progress_label.show()
        self.progress.show()

    def _hide_progress(self) -> None:
        self.progress.hide()
        self.progress_label.hide()

    def _toast(self, message: str, kind: str = "info", duration: int = 3600) -> None:
        if hasattr(self, "toast") and self.toast is not None:
            self.toast.show_message(message, kind, duration)

    # ------------------------------------------------------------------ #
    # 事件
    # ------------------------------------------------------------------ #
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "toast"):
            self.toast.reposition()
        if self.doc is not None and self.left_view.fit_mode and self.right_view.fit_mode:
            self._fit_timer.start()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._translation_worker is not None:
            if not self._pending_close:
                reply = QMessageBox.question(
                    self, "翻译尚未完成",
                    "翻译尚未完成，退出会丢失尚未写入记忆库的结果。确定退出吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
                self._skip_close_prompt = True
                self._pending_close = True
                self._translation_worker.cancel()
                self._set_status("正在停止翻译，完成后自动退出…", "working")
            event.ignore()
            return
        if self._load_worker is not None or self._export_worker is not None:
            self._pending_close = True
            self._skip_close_prompt = True
            self._set_status("当前任务完成后会自动退出…", "working")
            event.ignore()
            return
        if (
            not self._skip_close_prompt
            and self.doc is not None
            and self._done_blocks > 0
            and not self._last_export_path
        ):
            reply = QMessageBox.question(
                self, "译文尚未导出",
                f"当前文档有 {self._done_blocks} 段译文尚未导出，确定退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        try:
            if self.doc is not None:
                cleanup_font_files(self.doc.all_blocks())
        except Exception:
            pass
        try:
            self.library.close()
        except Exception:
            pass
        event.accept()
