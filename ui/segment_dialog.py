"""单段译文的校对与修正。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout,
    QWidget,
)

from . import theme as T
from .widgets import DialogHeader


class SegmentDialog(QDialog):
    def __init__(self, page_no: int, block_index: int, source_text: str,
                 translation: str, source_lang: str = "auto",
                 target_lang: str = "zh-CN", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.page_no = page_no
        self.block_index = block_index
        self.setWindowTitle("校对译文 · 肥鱼译文")
        self.setModal(True)
        self.resize(720, 540)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = DialogHeader(
            "校对与修正",
            f"第 {page_no + 1} 页 · 第 {block_index + 1} 段 · 保存后会写入本地记忆库",
        )
        header.close_requested.connect(self.reject)
        outer.addWidget(header)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)

        layout.addWidget(self._label("原文"))
        original_card = QFrame()
        original_card.setObjectName("SoftCard")
        ol = QVBoxLayout(original_card)
        ol.setContentsMargins(14, 11, 14, 11)
        self.source_view = QLabel(source_text)
        self.source_view.setWordWrap(True)
        self.source_view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.source_view.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 12px;")
        ol.addWidget(self.source_view)
        layout.addWidget(original_card)

        layout.addSpacing(2)
        row = QHBoxLayout()
        row.addWidget(self._label("译文"))
        row.addStretch(1)
        lang_names = {
            "auto": "自动检测", "en": "英语", "zh-CN": "简体中文",
            "zh-TW": "繁体中文", "ja": "日语", "ko": "韩语", "fr": "法语",
            "de": "德语", "es": "西班牙语", "ru": "俄语", "pt": "葡萄牙语",
            "it": "意大利语", "ar": "阿拉伯语",
        }
        quality = QLabel(
            f"{lang_names.get(source_lang, source_lang)} → "
            f"{lang_names.get(target_lang, target_lang)}"
        )
        quality.setObjectName("Pill")
        row.addWidget(quality)
        layout.addLayout(row)
        self.translation_edit = QTextEdit()
        self.translation_edit.setPlainText(translation or "")
        self.translation_edit.setPlaceholderText("在这里输入或修正译文…")
        self.translation_edit.setMinimumHeight(170)
        layout.addWidget(self.translation_edit, 1)

        note = QLabel(
            "提示：保存后当前段落会立即更新，并写入记忆库（quality=manual）。"
            "以后遇到相同原文会优先使用这次修正。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Secondary")
        cancel.setFixedHeight(34)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("保存并应用")
        save.setObjectName("Primary")
        save.setFixedHeight(34)
        save.setMinimumWidth(110)
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        outer.addWidget(body, 1)
        QTimer.singleShot(40, self.translation_edit.setFocus)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 12px; font-weight: 600; color: #5C6B82;")
        return label

    def _save(self) -> None:
        text = self.translation_edit.toPlainText().strip()
        if not text:
            self.translation_edit.setFocus()
            return
        self.accept()

    def translation(self) -> str:
        return self.translation_edit.toPlainText().strip()
