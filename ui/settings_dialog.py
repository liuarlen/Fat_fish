"""设置对话框：翻译服务、本地库、排版与关于。"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QUrl

from core.config import AppConfig, LIBRARY_PATH, resource_path
from core.library import DemoMemory, TranslationLibrary
from core.providers import (
    ENGINE_ORDER, LLM_PRESETS, PROVIDER_SPECS, ProviderError, create_provider,
)

from . import icons
from . import theme as T
from .library_dialog import LibraryDialog
from .widgets import (
    ComboBox, DialogHeader, IconButton, StatCard, SwitchRow,
)


LANGUAGE_OPTIONS = [
    ("自动检测", "auto"),
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


class _ProviderTestWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, engine: str, options: Dict, source: str, target: str,
                 demo_path: str, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.options = options
        self.source = source
        self.target = target
        self.demo_path = demo_path

    def run(self) -> None:
        try:
            provider = create_provider(
                self.engine, self.options, self.source, self.target,
                demo_path=self.demo_path,
            )
            try:
                text = provider.translate("Good morning. This is a connection test.")
            finally:
                provider.close()
            if not text:
                self.done.emit(False, "服务返回了空译文。")
            else:
                self.done.emit(True, text)
        except Exception as exc:
            self.done.emit(False, str(exc))


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, library: TranslationLibrary,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self.library = library
        self.setWindowTitle("设置 · 肥鱼译文")
        self.setModal(True)
        self.resize(920, 690)
        self.setMinimumSize(840, 600)
        self.provider_values: Dict[str, Dict] = {
            engine: config.provider_config(engine) for engine in ENGINE_ORDER
        }
        self.engine_edits: Dict[str, Dict[str, QLineEdit]] = {}
        self._test_worker: Optional[_ProviderTestWorker] = None
        self._close_after_test = False
        self._save_after_test = False
        self._loading = True
        self.demo = DemoMemory(resource_path("demo", "demo_library.json"))
        self._library_dir = os.path.dirname(os.path.abspath(library.path))
        self._library_switch_mode = ""
        self.new_library: Optional[TranslationLibrary] = None
        self._build_ui()
        self._load_values()
        self._refresh_library_path()
        self._loading = False

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = DialogHeader(
            "设置", "翻译服务、本地翻译库与导出偏好 · 所有配置只保存在本机"
        )
        header.close_requested.connect(self.reject)
        outer.addWidget(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        nav = QFrame()
        nav.setObjectName("SettingsNav")
        nav.setFixedWidth(194)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(12, 16, 12, 14)
        nav_layout.setSpacing(4)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        entries = [
            ("翻译服务", "languages"),
            ("本地翻译库", "book"),
            ("排版与导出", "fit"),
            ("关于肥鱼译文", "info"),
        ]
        self.stack = QStackedWidget()
        for index, (label, icon_name) in enumerate(entries):
            button = QPushButton("  " + label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setIcon(icons.icon(icon_name, T.TEXT_SECONDARY, 16))
            button.setIconSize(button.iconSize())
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav_group.addButton(button, index)
            nav_layout.addWidget(button)
            button.clicked.connect(lambda _checked=False, i=index: self.stack.setCurrentIndex(i))
        self.nav_group.button(0).setChecked(True)
        nav_layout.addStretch(1)
        version = QLabel("肥鱼译文  v1.2.1\n免费在线 · 可离线")
        version.setObjectName("Muted")
        nav_layout.addWidget(version)
        body.addWidget(nav)

        content_wrap = QWidget()
        content_layout = QVBoxLayout(content_wrap)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.stack.addWidget(self._wrap_page(self._build_translation_page()))
        self.stack.addWidget(self._wrap_page(self._build_library_page()))
        self.stack.addWidget(self._wrap_page(self._build_layout_page()))
        self.stack.addWidget(self._wrap_page(self._build_about_page()))
        content_layout.addWidget(self.stack)
        body.addWidget(content_wrap, 1)
        outer.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("DialogHeader")
        footer.setStyleSheet(
            "QFrame#DialogHeader { border-top: 1px solid %s; border-bottom: none; }" % T.BORDER
        )
        footer.setFixedHeight(64)
        f = QHBoxLayout(footer)
        f.setContentsMargins(20, 0, 20, 0)
        f.setSpacing(9)
        hint = QLabel("设置保存后立即生效")
        hint.setObjectName("Muted")
        f.addWidget(hint)
        f.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Secondary")
        cancel.setFixedHeight(34)
        cancel.clicked.connect(self.reject)
        f.addWidget(cancel)
        self.save_button = QPushButton("保存设置")
        self.save_button.setObjectName("Primary")
        self.save_button.setFixedHeight(34)
        self.save_button.setMinimumWidth(104)
        self.save_button.clicked.connect(self._save)
        f.addWidget(self.save_button)
        outer.addWidget(footer)

    @staticmethod
    def _wrap_page(page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        area.setWidget(page)
        return area

    @staticmethod
    def _section(title: str, description: str = "") -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(title)
        label.setObjectName("DialogSection")
        layout.addWidget(label)
        if description:
            desc = QLabel(description)
            desc.setObjectName("Muted")
            desc.setWordWrap(True)
            layout.addWidget(desc)
        return layout

    # ------------------------------------------------------------------ #
    def _build_translation_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 32, 30)
        layout.setSpacing(14)

        layout.addLayout(self._section(
            "翻译服务",
            "选择免费在线、国内云服务，或完全离线的本地演示库。API 密钥会加密存储在本机。",
        ))

        self.engine_combo = ComboBox()
        for engine in ENGINE_ORDER:
            spec = PROVIDER_SPECS[engine]
            suffix = f"  ·  {spec.badge}" if spec.badge and engine not in ("demo", "llm", "bilibili", "google") else ""
            self.engine_combo.addItem(spec.label + suffix, engine)
        self.engine_combo.setMinimumHeight(38)
        layout.addWidget(self.engine_combo)

        card = QFrame()
        card.setObjectName("SoftCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(10)
        self.provider_subtitle = QLabel()
        self.provider_subtitle.setObjectName("Muted")
        self.provider_subtitle.setWordWrap(True)
        card_layout.addWidget(self.provider_subtitle)
        self.engine_stack = QStackedWidget()
        self.engine_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        for engine in ENGINE_ORDER:
            self.engine_stack.addWidget(self._build_provider_form(engine))
        card_layout.addWidget(self.engine_stack)
        self.docs_button = QPushButton("查看服务控制台")
        self.docs_button.setObjectName("LinkButton")
        self.docs_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.docs_button.clicked.connect(self._open_provider_docs)
        self._docs_url = ""
        self.docs_button.hide()
        card_layout.addWidget(self.docs_button, 0, Qt.AlignmentFlag.AlignLeft)
        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        self.test_button = QPushButton("测试连接")
        self.test_button.setObjectName("Secondary")
        self.test_button.setFixedHeight(32)
        self.test_button.setIcon(icons.icon("sparkles", T.ACCENT, 15))
        self.test_button.clicked.connect(self._test_connection)
        test_row.addWidget(self.test_button)
        self.test_status = QLabel("")
        self.test_status.setObjectName("Muted")
        self.test_status.setWordWrap(True)
        test_row.addWidget(self.test_status, 1)
        card_layout.addLayout(test_row)
        layout.addWidget(card)

        layout.addSpacing(2)
        layout.addLayout(self._section("语言", "源语言可自动检测；修改目标语言后，建议重新翻译。"))
        lang_row = QHBoxLayout()
        lang_row.setSpacing(12)
        source_box = QVBoxLayout()
        source_box.setSpacing(5)
        source_box.addWidget(QLabel("源语言"))
        self.source_combo = ComboBox()
        for label, code in LANGUAGE_OPTIONS:
            self.source_combo.addItem(label, code)
        source_box.addWidget(self.source_combo)
        target_box = QVBoxLayout()
        target_box.setSpacing(5)
        target_box.addWidget(QLabel("目标语言"))
        self.target_combo = ComboBox()
        for label, code in LANGUAGE_OPTIONS[1:]:
            self.target_combo.addItem(label, code)
        target_box.addWidget(self.target_combo)
        lang_row.addLayout(source_box, 1)
        lang_row.addLayout(target_box, 1)
        layout.addLayout(lang_row)

        privacy = QFrame()
        privacy.setObjectName("SoftCard")
        pl = QHBoxLayout(privacy)
        pl.setContentsMargins(14, 11, 14, 11)
        pl.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(icons.svg_pixmap("info", T.ACCENT, 16))
        pl.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        note = QLabel(
            "隐私说明：选择在线服务时，只有待翻译的文本段落会发送到对应服务商；"
            "PDF 文件本身不会上传。选择「本地演示库」则全程不联网。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        pl.addWidget(note, 1)
        layout.addWidget(privacy)
        layout.addStretch(1)

        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        return page

    def _build_provider_form(self, engine: str) -> QWidget:
        spec = PROVIDER_SPECS[engine]
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if engine == "demo":
            demo_note = QLabel(
                f"内置 {len(self.demo)} 条示例译文，可直接打开示例 PDF 体验。"
                "它也会优先读取你的术语库和记忆库，全程不需要网络。"
            )
            demo_note.setWordWrap(True)
            demo_note.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 12px;")
            layout.addWidget(demo_note)
            return wrapper
        if engine == "bilibili":
            free_note = QLabel(
                "B站开源的 Index-Translate 模型，官方免费接口，不需要 API Key。\n"
                "公共免费服务可能限流或临时不可用；重要文档建议配置付费服务或大模型。"
            )
            free_note.setWordWrap(True)
            free_note.setFixedHeight(44)
            free_note.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 12px;")
            layout.addWidget(free_note)
            return wrapper
        if engine == "google":
            google_note = QLabel(
                "Google 网页免费接口，不需要 API Key。\n"
                "中国大陆网络通常无法直连；若提示网络失败，请改用 B站免费翻译或国内云服务。"
            )
            google_note.setWordWrap(True)
            google_note.setFixedHeight(44)
            google_note.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 12px;")
            layout.addWidget(google_note)
            return wrapper

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(9)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        edits: Dict[str, QLineEdit] = {}

        if engine == "llm":
            self.llm_preset_combo = ComboBox()
            for key, preset in LLM_PRESETS.items():
                self.llm_preset_combo.addItem(preset["label"], key)
            self.llm_preset_combo.currentIndexChanged.connect(self._on_llm_preset_changed)
            form.addRow("服务预设", self.llm_preset_combo)

        for field in spec.fields:
            edit = QLineEdit()
            edit.setPlaceholderText(field.placeholder)
            edit.setMinimumWidth(380)
            if field.secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
                action = edit.addAction(
                    icons.icon("eye", T.TEXT_MUTED, 16),
                    QLineEdit.ActionPosition.TrailingPosition,
                )
                action.setToolTip("显示 / 隐藏")

                def toggle(checked=False, line=edit, act=action):
                    visible = line.echoMode() == QLineEdit.EchoMode.Normal
                    line.setEchoMode(
                        QLineEdit.EchoMode.Password if visible
                        else QLineEdit.EchoMode.Normal
                    )
                    act.setIcon(icons.icon(
                        "eye" if visible else "eye_off", T.TEXT_MUTED, 16
                    ))

                action.triggered.connect(toggle)
            edits[field.key] = edit
            label = QLabel(field.label)
            form.addRow(label, edit)
        layout.addLayout(form)
        self.engine_edits[engine] = edits

        if engine == "llm":
            tip = QLabel(
                "推荐 DeepSeek / 通义千问：整页一次请求，能保留上下文，译文更连贯。"
            )
            tip.setObjectName("Muted")
            tip.setWordWrap(True)
            layout.addWidget(tip)
        return wrapper

    def _build_library_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 32, 30)
        layout.setSpacing(16)
        layout.addLayout(self._section(
            "本地翻译库",
            "术语库保证专有名词一致；记忆库会沉淀已经翻译过的句子，重复出现时零成本复用。",
        ))
        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.stat_glossary = StatCard("术语条目")
        self.stat_memory = StatCard("记忆条目")
        self.stat_hits = StatCard("累计命中")
        for card in (self.stat_glossary, self.stat_memory, self.stat_hits):
            stats.addWidget(card, 1)
        layout.addLayout(stats)

        location_card = QFrame()
        location_card.setObjectName("SoftCard")
        location_layout = QVBoxLayout(location_card)
        location_layout.setContentsMargins(18, 14, 18, 14)
        location_layout.setSpacing(7)
        location_head = QHBoxLayout()
        location_head.setSpacing(8)
        location_title = QLabel("翻译库文件位置")
        location_title.setStyleSheet("font-size: 13px; font-weight: 500;")
        location_head.addWidget(location_title)
        location_head.addStretch(1)
        change_dir = QPushButton("更改位置…")
        change_dir.setObjectName("Secondary")
        change_dir.setFixedHeight(30)
        change_dir.clicked.connect(self._choose_library_dir)
        location_head.addWidget(change_dir)
        reset_dir = QPushButton("恢复默认")
        reset_dir.setObjectName("Secondary")
        reset_dir.setFixedHeight(30)
        reset_dir.clicked.connect(self._reset_library_dir)
        location_head.addWidget(reset_dir)
        location_layout.addLayout(location_head)
        self.library_path_edit = QLineEdit()
        self.library_path_edit.setReadOnly(True)
        self.library_path_edit.setMinimumHeight(32)
        location_layout.addWidget(self.library_path_edit)
        self.library_path_note = QLabel()
        self.library_path_note.setObjectName("Muted")
        self.library_path_note.setWordWrap(True)
        location_layout.addWidget(self.library_path_note)
        layout.addWidget(location_card)

        card = QFrame()
        card.setObjectName("SoftCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 14, 18, 14)
        card_layout.setSpacing(12)
        self.use_library_switch = SwitchRow(
            "优先使用本地翻译库",
            "命中术语或记忆库时直接使用本地译文，不再请求在线服务。",
        )
        self.auto_save_switch = SwitchRow(
            "自动积累翻译记忆",
            "在线服务返回的译文自动写入记忆库，下次相同或近似原文自动复用。",
        )
        card_layout.addWidget(self.use_library_switch)
        card_layout.addWidget(self._divider())
        card_layout.addWidget(self.auto_save_switch)
        card_layout.addWidget(self._divider())
        fuzzy_row = QHBoxLayout()
        fuzzy_text = QVBoxLayout()
        fuzzy_text.setSpacing(3)
        fuzzy_title = QLabel("模糊匹配阈值")
        fuzzy_title.setStyleSheet("font-size: 13px; font-weight: 500;")
        fuzzy_desc = QLabel("原文相似度高于该值时，复用记忆库中的译文。越接近 1 越严格。")
        fuzzy_desc.setObjectName("Muted")
        fuzzy_desc.setWordWrap(True)
        fuzzy_text.addWidget(fuzzy_title)
        fuzzy_text.addWidget(fuzzy_desc)
        fuzzy_row.addLayout(fuzzy_text, 1)
        self.fuzzy_spin = QDoubleSpinBox()
        self.fuzzy_spin.setRange(0.60, 0.99)
        self.fuzzy_spin.setSingleStep(0.01)
        self.fuzzy_spin.setDecimals(2)
        self.fuzzy_spin.setFixedWidth(90)
        fuzzy_row.addWidget(self.fuzzy_spin)
        card_layout.addLayout(fuzzy_row)
        layout.addWidget(card)

        buttons = QHBoxLayout()
        buttons.setSpacing(9)
        manage = QPushButton("打开翻译库管理")
        manage.setObjectName("Secondary")
        manage.setFixedHeight(34)
        manage.setIcon(icons.icon("book", T.TEXT_SECONDARY, 16))
        manage.clicked.connect(self._open_library)
        buttons.addWidget(manage)
        note = QLabel("支持导入 / 导出 CSV，可自行准备术语表。")
        note.setObjectName("Muted")
        buttons.addWidget(note)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        demo_card = QFrame()
        demo_card.setObjectName("SoftCard")
        dl = QHBoxLayout(demo_card)
        dl.setContentsMargins(14, 11, 14, 11)
        dl.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(icons.svg_pixmap("sparkles", T.ORANGE, 16))
        dl.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        demo_note = QLabel(
            f"演示语料 {len(self.demo)} 条：仅在「本地演示库」模式下参与查询，不会混入你的正式记忆库。"
        )
        demo_note.setObjectName("Muted")
        demo_note.setWordWrap(True)
        dl.addWidget(demo_note, 1)
        layout.addWidget(demo_card)
        layout.addStretch(1)
        return page

    def _refresh_library_path(self) -> None:
        directory = os.path.abspath(self._library_dir)
        target = os.path.join(directory, "library.sqlite")
        self.library_path_edit.setText(directory)
        self.library_path_edit.setCursorPosition(0)
        current = os.path.abspath(self.library.path)
        if os.path.normcase(target) == os.path.normcase(current):
            detail = "当前使用中"
        elif self._library_switch_mode == "use":
            detail = "保存后使用目标位置已有的翻译库；当前库文件会保留在原处"
        else:
            detail = "保存后迁移当前翻译库到该位置；原文件会保留为备份"
        size_text = ""
        if os.path.isfile(target):
            try:
                size_text = f" · {os.path.getsize(target) / 1024:.0f} KB"
            except OSError:
                pass
        self.library_path_note.setText(
            f"实际文件：{target}{size_text}\n{detail}。"
        )

    def _choose_library_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "选择翻译库保存目录", self._library_dir
        )
        if directory:
            self._set_library_dir(directory)

    def _reset_library_dir(self) -> None:
        self._set_library_dir(os.path.dirname(LIBRARY_PATH))

    def _set_library_dir(self, directory: str) -> None:
        target_dir = os.path.abspath(os.path.expanduser(directory))
        target_file = os.path.join(target_dir, "library.sqlite")
        current_file = os.path.abspath(self.library.path)
        if os.path.normcase(target_file) == os.path.normcase(current_file):
            self._library_dir = target_dir
            self._library_switch_mode = ""
            self._refresh_library_path()
            return
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "目录不可用", f"无法创建目录：\n{exc}")
            return
        probe = os.path.join(target_dir, ".yipage_write_test")
        try:
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write("ok")
            os.remove(probe)
        except OSError as exc:
            QMessageBox.warning(
                self, "目录不可写", f"这个目录没有写入权限：\n{target_dir}\n\n{exc}"
            )
            return
        mode = "copy"
        if os.path.isfile(target_file):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("目标位置已有翻译库")
            box.setText(f"目标目录中已经存在翻译库：\n{target_file}")
            box.setInformativeText(
                "“迁移当前库”会用当前数据覆盖目标文件；\n"
                "“使用目标库”会直接切换到已有文件，当前库保留在原处。"
            )
            migrate = box.addButton(
                "迁移当前库并覆盖", QMessageBox.ButtonRole.AcceptRole
            )
            use = box.addButton("使用目标库", QMessageBox.ButtonRole.ActionRole)
            box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(use)
            box.exec()
            clicked = box.clickedButton()
            if clicked is migrate:
                mode = "copy"
            elif clicked is use:
                mode = "use"
            else:
                return
        self._library_dir = target_dir
        self._library_switch_mode = mode
        self._refresh_library_path()

    def _switch_library_if_needed(self) -> Optional[TranslationLibrary]:
        target_dir = os.path.abspath(self._library_dir)
        target_file = os.path.join(target_dir, "library.sqlite")
        current_file = os.path.abspath(self.library.path)
        if os.path.normcase(target_file) == os.path.normcase(current_file):
            return None
        os.makedirs(target_dir, exist_ok=True)
        if (
            self._library_switch_mode == "use"
            and os.path.isfile(target_file)
        ):
            new_library = TranslationLibrary(target_file)
        else:
            self.library.backup_to(target_file)
            new_library = TranslationLibrary(target_file)
        try:
            new_library.stats()
        except Exception:
            new_library.close()
            raise
        return new_library

    def _build_layout_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 32, 30)
        layout.setSpacing(16)
        layout.addLayout(self._section(
            "排版与导出",
            "原位覆盖的默认策略是删除原文后写入译文；图片、线条和表格结构都会被保留。",
        ))
        card = QFrame()
        card.setObjectName("SoftCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 14, 18, 14)
        card_layout.setSpacing(12)
        size_row = QHBoxLayout()
        size_text = QVBoxLayout()
        size_text.setSpacing(3)
        size_title = QLabel("译文字号")
        size_title.setStyleSheet("font-size: 13px; font-weight: 500;")
        size_desc = QLabel("中文通常比英文紧凑；1.0× 为原文字号，遇到挤压可调小。")
        size_desc.setObjectName("Muted")
        size_desc.setWordWrap(True)
        size_text.addWidget(size_title)
        size_text.addWidget(size_desc)
        size_row.addLayout(size_text, 1)
        self.font_scale_spin = QDoubleSpinBox()
        self.font_scale_spin.setRange(0.75, 1.25)
        self.font_scale_spin.setSingleStep(0.05)
        self.font_scale_spin.setDecimals(2)
        self.font_scale_spin.setSuffix(" ×")
        self.font_scale_spin.setFixedWidth(100)
        size_row.addWidget(self.font_scale_spin)
        card_layout.addLayout(size_row)
        card_layout.addWidget(self._divider())
        self.auto_shrink_switch = SwitchRow(
            "放不下时自动缩小字号",
            "译文比原区域长时自动收紧到最小 62%，避免压到相邻段落。",
        )
        card_layout.addWidget(self.auto_shrink_switch)
        card_layout.addWidget(self._divider())
        mode_row = QHBoxLayout()
        mode_text = QVBoxLayout()
        mode_text.setSpacing(3)
        mode_title = QLabel("原文处理方式")
        mode_title.setStyleSheet("font-size: 13px; font-weight: 500;")
        mode_desc = QLabel("推荐删除原文：导出后文字可搜索、可复制；覆盖底色适合保留底图的特殊文档。")
        mode_desc.setObjectName("Muted")
        mode_desc.setWordWrap(True)
        mode_text.addWidget(mode_title)
        mode_text.addWidget(mode_desc)
        mode_row.addLayout(mode_text, 1)
        self.mode_combo = ComboBox()
        self.mode_combo.addItem("删除原文（推荐）", "redact")
        self.mode_combo.addItem("底色覆盖", "cover")
        self.mode_combo.setFixedWidth(160)
        mode_row.addWidget(self.mode_combo)
        card_layout.addLayout(mode_row)
        layout.addWidget(card)

        note = QLabel(
            "界面右栏是实时原位预览；导出的 PDF 由 PyMuPDF 重新写入文字并做字体子集化，"
            "因此同一份文件里既能保留版面，也能选中、搜索译文。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_about_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 32, 30)
        layout.setSpacing(16)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.brand_pixmap(54))
        top.addWidget(logo)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel("肥鱼译文")
        title.setStyleSheet("font-size: 21px; font-weight: 700;")
        sub = QLabel("原位对照翻译 · 版式不变")
        sub.setObjectName("Muted")
        text.addWidget(title)
        text.addWidget(sub)
        top.addLayout(text)
        top.addStretch(1)
        layout.addLayout(top)

        about = QLabel(
            "肥鱼译文是一个本地运行的桌面工具：把英文 PDF 的每个段落翻译成中文，"
            "并在原位置覆盖写回。左侧保留原文，右侧实时查看译文，拖拽、缩放与翻页同步。"
        )
        about.setWordWrap(True)
        about.setStyleSheet(f"color: {T.TEXT_SECONDARY}; line-height: 1.7;")
        layout.addWidget(about)

        card = QFrame()
        card.setObjectName("SoftCard")
        form = QFormLayout(card)
        form.setContentsMargins(18, 14, 18, 14)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(10)
        for label, value in (
            ("界面框架", "Qt 6 / PySide6"),
            ("PDF 引擎", "PyMuPDF（MuPDF）"),
            ("本地数据", "SQLite 术语库 + 记忆库"),
            ("配置文件", os.path.dirname(LIBRARY_PATH)),
            ("版本", "1.2.1"),
        ):
            key = QLabel(label)
            key.setObjectName("Muted")
            val = QLabel(value)
            val.setWordWrap(True)
            form.addRow(key, val)
        layout.addWidget(card)

        open_dir = QPushButton("打开数据目录")
        open_dir.setObjectName("Secondary")
        open_dir.setFixedHeight(34)
        open_dir.setIcon(icons.icon("folder", T.TEXT_SECONDARY, 16))
        open_dir.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.dirname(LIBRARY_PATH))
            )
        )
        layout.addWidget(open_dir, 0, Qt.AlignmentFlag.AlignLeft)
        note = QLabel(
            "说明：术语库与记忆库完全属于你。删除数据目录下的 library.sqlite 即可清空；"
            "API 密钥经 Windows DPAPI 加密后保存在 settings.json 中。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setObjectName("Divider")
        line.setFrameShape(QFrame.Shape.HLine)
        return line

    # ------------------------------------------------------------------ #
    def _load_values(self) -> None:
        engine = self.config.get("engine", "demo")
        index = self.engine_combo.findData(engine)
        self.engine_combo.setCurrentIndex(index if index >= 0 else 0)
        self.engine_stack.setCurrentIndex(max(0, self.engine_combo.currentIndex()))
        self.source_combo.setCurrentIndex(
            max(0, self.source_combo.findData(self.config.get("source_lang", "auto")))
        )
        self.target_combo.setCurrentIndex(
            max(0, self.target_combo.findData(self.config.get("target_lang", "zh-CN")))
        )
        for engine_key, edits in self.engine_edits.items():
            values = self.provider_values.get(engine_key, {})
            for key, edit in edits.items():
                edit.setText(str(values.get(key, "")))
        # LLM 预设
        if hasattr(self, "llm_preset_combo"):
            llm = self.provider_values.get("llm", {})
            preset = llm.get("preset", "")
            if preset not in LLM_PRESETS:
                preset = "custom"
            idx = self.llm_preset_combo.findData(preset)
            self.llm_preset_combo.setCurrentIndex(max(0, idx))
        self.use_library_switch.switch.setChecked(bool(self.config.get("use_library", True)))
        self.auto_save_switch.switch.setChecked(bool(self.config.get("auto_save_memory", True)))
        self.fuzzy_spin.setValue(float(self.config.get("fuzzy_threshold", 0.84)))
        self.font_scale_spin.setValue(float(self.config.get("font_scale", 1.0)))
        self.auto_shrink_switch.switch.setChecked(bool(self.config.get("auto_shrink", True)))
        idx = self.mode_combo.findData(self.config.get("mode", "redact"))
        self.mode_combo.setCurrentIndex(max(0, idx))
        self._refresh_stats()
        self._update_provider_meta()
        self._fit_provider_height()
        QTimer.singleShot(0, self._fit_provider_height)

    def _fit_provider_height(self) -> None:
        widget = self.engine_stack.currentWidget()
        if widget is None:
            return
        height = max(56, widget.sizeHint().height() + 6)
        self.engine_stack.setFixedHeight(height)

    def _refresh_stats(self) -> None:
        stats = self.library.stats()
        self.stat_glossary.set_value(stats["glossary"])
        self.stat_memory.set_value(stats["memory"])
        self.stat_hits.set_value(stats["hits"])

    def _on_engine_changed(self, index: int) -> None:
        if index < 0 or index >= len(ENGINE_ORDER):
            return
        engine = self.engine_combo.itemData(index)
        self.engine_stack.setCurrentIndex(index)
        self._fit_provider_height()
        QTimer.singleShot(0, self._fit_provider_height)
        self.test_status.setText("")
        self._update_provider_meta()
        if engine == "demo":
            self.test_status.setText(f"离线库已就绪：{len(self.demo)} 条演示语料")
            self.test_status.setStyleSheet(f"color: {T.GREEN};")
        else:
            self.test_status.setStyleSheet(f"color: {T.TEXT_MUTED};")

    def _update_provider_meta(self) -> None:
        engine = self.engine_combo.currentData()
        spec = PROVIDER_SPECS.get(engine, PROVIDER_SPECS["demo"])
        self.provider_subtitle.setText(spec.subtitle)
        self._docs_url = spec.docs_url
        self.docs_button.setVisible(bool(spec.docs_url))

    def _open_provider_docs(self) -> None:
        if self._docs_url:
            QDesktopServices.openUrl(QUrl(self._docs_url))

    def _on_llm_preset_changed(self, index: int) -> None:
        if self._loading:
            return
        key = self.llm_preset_combo.itemData(index)
        preset = LLM_PRESETS.get(key, {})
        if key == "custom":
            return
        edits = self.engine_edits.get("llm", {})
        if "base_url" in edits and preset.get("base_url"):
            edits["base_url"].setText(preset["base_url"])
        if "model" in edits and preset.get("model"):
            edits["model"].setText(preset["model"])

    def _values_for(self, engine: str) -> Dict:
        values = {key: edit.text().strip()
                  for key, edit in self.engine_edits.get(engine, {}).items()}
        if engine in ("tencent", "aliyun") and not values.get("region"):
            values["region"] = "ap-guangzhou" if engine == "tencent" else "cn-hangzhou"
        if engine == "llm":
            values["preset"] = self.llm_preset_combo.currentData()
        return values

    def _test_connection(self) -> None:
        if self._test_worker is not None and self._test_worker.isRunning():
            return
        engine = self.engine_combo.currentData()
        if engine == "demo":
            self.test_status.setText(f"离线演示库可用：{len(self.demo)} 条示例语料，无需联网。")
            self.test_status.setStyleSheet(f"color: {T.GREEN};")
            return
        options = self._values_for(engine)
        source = self.source_combo.currentData()
        target = self.target_combo.currentData()
        self.test_status.setText("正在连接服务…")
        self.test_status.setStyleSheet(f"color: {T.TEXT_SECONDARY};")
        self.test_button.setEnabled(False)
        self.save_button.setEnabled(False)
        worker = _ProviderTestWorker(
            engine, options, source, target,
            resource_path("demo", "demo_library.json"), self,
        )
        self._test_worker = worker
        worker.done.connect(self._on_test_done)
        worker.finished.connect(self._on_test_finished)
        worker.start()

    def _on_test_done(self, ok: bool, text: str) -> None:
        if ok:
            self.test_status.setText("连接成功：" + text.replace("\n", " ")[:80])
            self.test_status.setStyleSheet(f"color: {T.GREEN};")
        else:
            self.test_status.setText("连接失败：" + text[:180])
            self.test_status.setStyleSheet(f"color: {T.RED};")

    def _on_test_finished(self) -> None:
        self.test_button.setEnabled(True)
        self.save_button.setEnabled(True)
        worker = self._test_worker
        self._test_worker = None
        if worker is not None:
            worker.deleteLater()
        if self._close_after_test:
            self._close_after_test = False
            super().reject()
        elif self._save_after_test:
            self._save_after_test = False
            self._save()

    def _open_library(self) -> None:
        dialog = LibraryDialog(self.library, self.config, self)
        dialog.exec()
        self._refresh_stats()

    # ------------------------------------------------------------------ #
    def _save(self) -> None:
        if self._test_worker is not None and self._test_worker.isRunning():
            self._save_after_test = True
            self.test_status.setText("测试连接中，完成后会自动保存…")
            return
        new_library = None
        try:
            new_library = self._switch_library_if_needed()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "翻译库切换失败",
                f"无法切换翻译库：\n{type(exc).__name__}: {exc}\n\n"
                "请检查目录权限，或换一个位置。",
            )
            return
        engine = self.engine_combo.currentData()
        for engine_key in ENGINE_ORDER:
            values = self._values_for(engine_key)
            self.config.set_provider_config(engine_key, values)
        target_dir = os.path.abspath(self._library_dir)
        default_dir = os.path.abspath(os.path.dirname(LIBRARY_PATH))
        if os.path.normcase(target_dir) == os.path.normcase(default_dir):
            self.config.set("library_dir", "")
        else:
            self.config.set("library_dir", target_dir)
        self.config.set("engine", engine)
        self.config.set("source_lang", self.source_combo.currentData())
        self.config.set("target_lang", self.target_combo.currentData())
        self.config.set("use_library", self.use_library_switch.switch.isChecked())
        self.config.set("auto_save_memory", self.auto_save_switch.switch.isChecked())
        self.config.set("fuzzy_threshold", float(self.fuzzy_spin.value()))
        self.config.set("font_scale", float(self.font_scale_spin.value()))
        self.config.set("auto_shrink", self.auto_shrink_switch.switch.isChecked())
        self.config.set("mode", self.mode_combo.currentData())
        try:
            self.config.save()
        except Exception as exc:
            if new_library is not None:
                try:
                    new_library.close()
                except Exception:
                    pass
            QMessageBox.critical(self, "保存失败", f"设置保存失败：\n{exc}")
            return
        self.new_library = new_library
        self.accept()

    def reject(self) -> None:
        if self._test_worker is not None and self._test_worker.isRunning():
            self._close_after_test = True
            self.test_status.setText("正在等待测试请求结束…")
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._test_worker is not None and self._test_worker.isRunning():
            self._close_after_test = True
            self.test_status.setText("正在等待测试请求结束…")
            event.ignore()
            return
        super().closeEvent(event)
