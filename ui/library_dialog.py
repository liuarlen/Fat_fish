"""本地翻译库管理：术语、记忆、导入导出。"""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.config import AppConfig, LIBRARY_PATH
from core.library import TranslationLibrary

from . import icons
from . import theme as T
from .widgets import ComboBox, DialogHeader, StatCard


LANG_LABELS = {
    "auto": "自动", "en": "英语", "zh-CN": "简体中文", "zh-TW": "繁体中文",
    "ja": "日语", "ko": "韩语", "fr": "法语", "de": "德语", "es": "西班牙语",
    "ru": "俄语", "pt": "葡萄牙语", "it": "意大利语", "ar": "阿拉伯语",
}


class GlossaryEditDialog(QDialog):
    def __init__(self, library: TranslationLibrary, config: AppConfig,
                 entry: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.library = library
        self.config = config
        self.entry = entry
        self.setWindowTitle("编辑术语 · 肥鱼译文")
        self.setModal(True)
        self.resize(620, 440)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = DialogHeader(
            "编辑术语" if entry else "新增术语",
            "术语会在本地库中大显身手：整个段落精确匹配时直接复用。",
        )
        header.close_requested.connect(self.reject)
        outer.addWidget(header)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(13)
        form = QVBoxLayout()
        form.setSpacing(6)
        form.addWidget(self._label("原文"))
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("例如：calm technology")
        form.addWidget(self.source_edit)
        form.addWidget(self._label("译文"))
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText("例如：安静的技术")
        form.addWidget(self.target_edit)
        pair = QHBoxLayout()
        pair.setSpacing(12)
        src_box = QVBoxLayout()
        src_box.setSpacing(6)
        src_box.addWidget(self._label("源语言"))
        self.source_lang = ComboBox()
        for code, label in LANG_LABELS.items():
            if code == "auto":
                continue
            self.source_lang.addItem(label, code)
        src_box.addWidget(self.source_lang)
        dst_box = QVBoxLayout()
        dst_box.setSpacing(6)
        dst_box.addWidget(self._label("目标语言"))
        self.target_lang = ComboBox()
        for code, label in LANG_LABELS.items():
            if code == "auto":
                continue
            self.target_lang.addItem(label, code)
        dst_box.addWidget(self.target_lang)
        pair.addLayout(src_box, 1)
        pair.addLayout(dst_box, 1)
        form.addLayout(pair)
        form.addWidget(self._label("备注（可选）"))
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("例如：产品名，不翻译 / 统一译法")
        form.addWidget(self.note_edit)
        layout.addLayout(form)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet(f"color: {T.RED}; font-size: 12px;")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Secondary")
        cancel.setFixedHeight(34)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("保存术语")
        save.setObjectName("Primary")
        save.setFixedHeight(34)
        save.setMinimumWidth(96)
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        outer.addWidget(body, 1)
        self._fill()

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 12px; font-weight: 600; color: #5C6B82;")
        return label

    def _fill(self) -> None:
        source_lang = self.config.get("source_lang", "en")
        target_lang = self.config.get("target_lang", "zh-CN")
        if source_lang == "auto":
            source_lang = "en"
        self.source_lang.setCurrentIndex(max(0, self.source_lang.findData(source_lang)))
        self.target_lang.setCurrentIndex(max(0, self.target_lang.findData(target_lang)))
        if self.entry:
            self.source_edit.setText(self.entry.get("source", ""))
            self.target_edit.setText(self.entry.get("target", ""))
            self.note_edit.setText(self.entry.get("note", ""))
            self.source_lang.setCurrentIndex(
                max(0, self.source_lang.findData(self.entry.get("source_lang", source_lang)))
            )
            self.target_lang.setCurrentIndex(
                max(0, self.target_lang.findData(self.entry.get("target_lang", target_lang)))
            )
        QTimer.singleShot(20, self.source_edit.setFocus)

    def _save(self) -> None:
        source = self.source_edit.text().strip()
        target = self.target_edit.text().strip()
        if not source or not target:
            self.error_label.setText("原文和译文都不能为空。")
            self.error_label.show()
            return
        try:
            self.library.upsert_glossary(
                source, target,
                self.source_lang.currentData(), self.target_lang.currentData(),
                self.note_edit.text().strip(),
            )
        except Exception as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        self.accept()


class LibraryDialog(QDialog):
    def __init__(self, library: TranslationLibrary, config: AppConfig, parent=None):
        super().__init__(parent)
        self.library = library
        self.config = config
        self.mode = "glossary"
        self.setWindowTitle("翻译库 · 肥鱼译文")
        self.setModal(True)
        self.resize(980, 680)
        self.setMinimumSize(840, 560)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self.refresh)
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = DialogHeader(
            "翻译库",
            "你的术语与译文会沉淀在这里；它们优先于在线翻译，也可以完全离线使用。",
        )
        header.close_requested.connect(self.accept)
        outer.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 14)
        body_layout.setSpacing(13)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.stat_glossary = StatCard("术语条目")
        self.stat_memory = StatCard("记忆条目")
        self.stat_hits = StatCard("累计命中")
        self.stat_size = StatCard("本地库大小")
        for card in (self.stat_glossary, self.stat_memory, self.stat_hits, self.stat_size):
            stats.addWidget(card, 1)
        body_layout.addLayout(stats)

        tools = QHBoxLayout()
        tools.setSpacing(9)
        seg_wrap = QFrame()
        seg_wrap.setStyleSheet(
            f"QFrame {{ background: #EEF3FA; border-radius: 9px; }}"
        )
        seg = QHBoxLayout(seg_wrap)
        seg.setContentsMargins(3, 3, 3, 3)
        seg.setSpacing(2)
        self.seg_group = QButtonGroup(self)
        self.seg_group.setExclusive(True)
        self.glossary_button = QPushButton("术语库")
        self.memory_button = QPushButton("记忆库")
        for index, button in enumerate((self.glossary_button, self.memory_button)):
            button.setObjectName("SegButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.seg_group.addButton(button, index)
            seg.addWidget(button)
            button.clicked.connect(lambda _c=False, i=index: self._set_mode(
                "glossary" if i == 0 else "memory"
            ))
        self.glossary_button.setChecked(True)
        tools.addWidget(seg_wrap)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索原文或译文…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.addAction(
            icons.icon("search", T.TEXT_MUTED, 16), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search_edit.setFixedWidth(280)
        self.search_edit.textChanged.connect(lambda _t: self._search_timer.start())
        tools.addWidget(self.search_edit)
        tools.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        tools.addWidget(self.count_label)
        body_layout.addLayout(tools)

        self.table = QTableWidget(0, 5)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.doubleClicked.connect(self._edit_or_copy)
        body_layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(9)
        self.add_button = QPushButton("新增术语")
        self.add_button.setObjectName("Primary")
        self.add_button.setFixedHeight(34)
        self.add_button.setIcon(icons.icon("plus", "#FFFFFF", 15))
        self.add_button.clicked.connect(self._add_glossary)
        actions.addWidget(self.add_button)
        self.import_button = QPushButton("导入 CSV")
        self.import_button.setObjectName("Secondary")
        self.import_button.setFixedHeight(34)
        self.import_button.setIcon(icons.icon("download", T.TEXT_SECONDARY, 15))
        self.import_button.clicked.connect(self._import_csv)
        actions.addWidget(self.import_button)
        self.export_button = QPushButton("导出 CSV")
        self.export_button.setObjectName("Secondary")
        self.export_button.setFixedHeight(34)
        self.export_button.setIcon(icons.icon("external", T.TEXT_SECONDARY, 15))
        self.export_button.clicked.connect(self._export_csv)
        actions.addWidget(self.export_button)
        actions.addStretch(1)
        self.delete_button = QPushButton("删除选中")
        self.delete_button.setObjectName("DangerGhost")
        self.delete_button.setFixedHeight(34)
        self.delete_button.setIcon(icons.icon("trash", T.RED, 15))
        self.delete_button.clicked.connect(self._delete_selected)
        actions.addWidget(self.delete_button)
        body_layout.addLayout(actions)
        outer.addWidget(body, 1)

        footer = QFrame()
        footer.setObjectName("StatusBar")
        footer.setFixedHeight(48)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 0, 16, 0)
        fl.setSpacing(8)
        path_label = QLabel(f"数据库：{LIBRARY_PATH}")
        path_label.setObjectName("Muted")
        fl.addWidget(path_label)
        fl.addStretch(1)
        close = QPushButton("完成")
        close.setObjectName("Secondary")
        close.setFixedHeight(32)
        close.setMinimumWidth(84)
        close.clicked.connect(self.accept)
        fl.addWidget(close)
        outer.addWidget(footer)

    # ------------------------------------------------------------------ #
    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self.glossary_button.setChecked(mode == "glossary")
        self.memory_button.setChecked(mode == "memory")
        self.add_button.setEnabled(mode == "glossary")
        self.import_button.setEnabled(mode == "glossary")
        self.refresh()

    def _selected_ids(self) -> List[int]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        ids = []
        for row in rows:
            item = self.table.item(row, 0)
            if item is not None:
                value = item.data(Qt.ItemDataRole.UserRole)
                if value is not None:
                    ids.append(int(value))
        return ids

    def _edit_or_copy(self, index) -> None:
        if self.mode == "glossary":
            item = self.table.item(index.row(), 0)
            if item is None:
                return
            entry_id = item.data(Qt.ItemDataRole.UserRole)
            entry = next(
                (row for row in self.library.list_glossary(limit=100000)
                 if int(row["id"]) == int(entry_id)),
                None,
            )
            if entry is None:
                return
            dialog = GlossaryEditDialog(self.library, self.config, entry, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.refresh()

    def _add_glossary(self) -> None:
        dialog = GlossaryEditDialog(self.library, self.config, None, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _delete_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(self, "未选择条目", "请先在表格中选择要删除的条目。")
            return
        kind = "术语" if self.mode == "glossary" else "记忆"
        reply = QMessageBox.question(
            self, f"删除{kind}",
            f"确定删除选中的 {len(ids)} 条{kind}吗？此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for entry_id in ids:
            if self.mode == "glossary":
                self.library.delete_glossary(entry_id)
            else:
                self.library.delete_memory(entry_id)
        self.refresh()

    def _import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入术语 CSV", self.config.get("last_dir", ""),
            "CSV 文件 (*.csv);;所有文件 (*)",
        )
        if not path:
            return
        try:
            count = self.library.import_glossary_csv(
                path,
                self.config.get("source_lang", "en"),
                self.config.get("target_lang", "zh-CN"),
            )
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        QMessageBox.information(self, "导入完成", f"已导入 {count} 条术语。")
        self.refresh()

    def _export_csv(self) -> None:
        default_name = "术语库.csv" if self.mode == "glossary" else "翻译记忆库.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", os.path.join(self.config.get("last_dir", ""), default_name),
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            if self.mode == "glossary":
                count = self.library.export_glossary_csv(path)
            else:
                count = self.library.export_memory_csv(path)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"已导出 {count} 条记录到：\n{path}")

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        query = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        stats = self.library.stats()
        self.stat_glossary.set_value(stats["glossary"])
        self.stat_memory.set_value(stats["memory"])
        self.stat_hits.set_value(stats["hits"])
        size = stats["size"]
        self.stat_size.set_value(
            f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
        )
        if self.mode == "glossary":
            rows = self.library.list_glossary(search=query, limit=2000)
            headers = ["原文", "译文", "语向", "备注", "更新时间"]
        else:
            rows = self.library.list_memory(search=query, limit=2000)
            headers = ["原文", "译文", "来源", "命中", "更新时间"]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            source_item = QTableWidgetItem(row.get("source", ""))
            source_item.setData(Qt.ItemDataRole.UserRole, int(row.get("id", 0)))
            source_item.setToolTip(row.get("source", ""))
            target_item = QTableWidgetItem(row.get("target", ""))
            target_item.setToolTip(row.get("target", ""))
            updated = str(row.get("updated_at", "")).replace("T", " ")[:16]
            if self.mode == "glossary":
                pair = (
                    f"{LANG_LABELS.get(row.get('source_lang', ''), row.get('source_lang', ''))}"
                    f" → {LANG_LABELS.get(row.get('target_lang', ''), row.get('target_lang', ''))}"
                )
                values = [source_item, target_item, QTableWidgetItem(pair),
                          QTableWidgetItem(row.get("note", "")), QTableWidgetItem(updated)]
            else:
                engine = row.get("engine", "") or "本地"
                values = [source_item, target_item, QTableWidgetItem(engine),
                          QTableWidgetItem(str(row.get("hits", 0))),
                          QTableWidgetItem(updated)]
            for col, item in enumerate(values):
                if col == 3 and self.mode == "glossary":
                    item.setToolTip(row.get("note", ""))
                self.table.setItem(row_index, col, item)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        if self.mode == "glossary":
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(2, 148)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(3, 140)
        else:
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(2, 96)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(3, 70)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 152)
        noun = "术语" if self.mode == "glossary" else "记忆"
        self.count_label.setText(f"共 {len(rows)} 条{noun}")
        self.delete_button.setEnabled(bool(rows))
