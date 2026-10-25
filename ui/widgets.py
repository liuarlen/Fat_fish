"""可复用的界面组件。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    Property, QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt,
    QTimer, Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from . import icons
from . import theme as T

class ComboBox(QComboBox):
    """无原生小箭头的下拉框，右侧放一个自绘 chevron。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self._arrow = QLabel(self)
        self._arrow.setPixmap(icons.svg_pixmap("chevron_down", T.TEXT_MUTED, 14))
        self._arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._arrow.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrow.move(max(0, self.width() - 24), max(0, (self.height() - 14) // 2))


class IconButton(QToolButton):
    def __init__(self, name: str, tooltip: str = "", size: int = 18,
                 color: str = T.TEXT_SECONDARY, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("IconButton")
        self.setIcon(icons.icon(name, color, size))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(34, 34)
        self.setIconSize(QSize(18, 18))


class ToggleSwitch(QAbstractButton):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._position = 0.0
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    # animated property -------------------------------------------------- #
    def get_position(self) -> float:
        return self._position

    def set_position(self, value: float) -> None:
        self._position = float(value)
        self.update()

    position = Property(float, get_position, set_position)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(42, 24)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked = self.isChecked() or self._position > 0.5
        track = QRectF(1, 2, 40, 20)
        on_color = QColor(T.ACCENT)
        off_color = QColor("#D7DFEB")
        if self.isEnabled():
            color = on_color if checked else off_color
        else:
            color = QColor("#E4E9F1")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, 10, 10)
        x = 4 + (18 * self._position)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, 5, 14, 14))
        if not self.isEnabled():
            painter.setBrush(QColor(255, 255, 255, 110))
            painter.drawEllipse(QRectF(x, 5, 14, 14))


class SwitchRow(QWidget):
    def __init__(self, title: str, description: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-size: 13px; font-weight: 500;")
        text_layout.addWidget(self.title_label)
        if description:
            desc = QLabel(description)
            desc.setObjectName("Muted")
            desc.setWordWrap(True)
            text_layout.addWidget(desc)
        layout.addLayout(text_layout, 1)
        self.switch = ToggleSwitch()
        layout.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)


class DialogHeader(QFrame):
    close_requested = Signal()

    def __init__(self, title: str, subtitle: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("DialogHeader")
        self.setFixedHeight(76)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 16, 0)
        layout.setSpacing(14)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        text.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("Muted")
            text.addWidget(subtitle_label)
        layout.addLayout(text, 1)
        self.close_button = IconButton("close", "关闭")
        self.close_button.clicked.connect(self.close_requested.emit)
        layout.addWidget(self.close_button)


class StatCard(QFrame):
    def __init__(self, label: str, value: str = "0", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatNumber")
        layout.addWidget(self.value_label)
        caption = QLabel(label)
        caption.setObjectName("Muted")
        layout.addWidget(caption)

    def set_value(self, value: object) -> None:
        self.value_label.setText(str(value))


class PageBadge(QLabel):
    def __init__(self, text: str = "", style: str = "Pill", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setObjectName(style)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_style(self, style: str) -> None:
        self.setObjectName(style)
        self.style().unpolish(self)
        self.style().polish(self)


class PaneCard(QFrame):
    def __init__(self, title: str, hint: str, dot_color: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("PaneCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        header = QWidget()
        header.setObjectName("PaneHeader")
        header.setFixedHeight(48)
        h = QHBoxLayout(header)
        h.setContentsMargins(15, 0, 13, 0)
        h.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f"background: {dot_color}; border-radius: 3px;")
        h.addWidget(dot)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        h.addWidget(self.title_label)
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("Muted")
        h.addWidget(self.hint_label)
        h.addStretch(1)
        self.badge = PageBadge("", "Pill")
        self.badge.hide()
        h.addWidget(self.badge)
        self.page_label = QLabel("—")
        self.page_label.setObjectName("Muted")
        h.addWidget(self.page_label)
        outer.addWidget(header)

        self.body = QWidget()
        self.body.setObjectName("ViewWrap")
        self._body_layout = QVBoxLayout(self.body)
        self._body_layout.setContentsMargins(8, 8, 8, 8)
        self._body_layout.setSpacing(0)
        outer.addWidget(self.body, 1)

    def set_view(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)

    def set_page(self, current: int, total: int) -> None:
        self.page_label.setText(f"第 {current} / {total} 页" if total else "—")

    def set_hint(self, text: str) -> None:
        self.hint_label.setText(text)

    def set_badge(self, text: str, style: str = "Pill") -> None:
        if not text:
            self.badge.hide()
            return
        self.badge.setText(text)
        self.badge.set_style(style)
        self.badge.show()


class EmptyState(QFrame):
    open_requested = Signal()
    sample_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("EmptyState")
        self.setAcceptDrops(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 26)
        layout.setSpacing(0)
        layout.addStretch(1)

        artwork = QLabel()
        artwork.setPixmap(icons.empty_illustration(380, 220))
        artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(artwork, 0, Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("把 PDF 拖进来，原位变成中文")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-size: 25px; font-weight: 700; color: {T.TEXT}; margin-top: 6px;"
        )
        layout.addWidget(title)

        subtitle = QLabel(
            "欢迎使用肥鱼译文喵！"
        )
        subtitle.setObjectName("PageSub")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setMaximumWidth(810)
        layout.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(22)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        self.open_button = QPushButton(" 打开 PDF")
        self.open_button.setObjectName("Primary")
        self.open_button.setIcon(icons.icon("folder", "#FFFFFF", 17))
        self.open_button.setFixedHeight(38)
        self.open_button.setMinimumWidth(130)
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(self.open_requested.emit)
        buttons.addWidget(self.open_button)
        self.sample_button = QPushButton("  查看示例文档")
        self.sample_button.setObjectName("Secondary")
        self.sample_button.setIcon(icons.icon("file", T.TEXT_SECONDARY, 17))
        self.sample_button.setFixedHeight(38)
        self.sample_button.setMinimumWidth(150)
        self.sample_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sample_button.clicked.connect(self.sample_requested.emit)
        buttons.addWidget(self.sample_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        layout.addSpacing(18)
        features = QHBoxLayout()
        features.setSpacing(8)
        features.addStretch(1)
        for text in ("B站免费在线", "百度 / 有道 / 腾讯 / 阿里", "本地术语库 + 记忆库", "导出原位译文 PDF"):
            pill = QLabel(text)
            pill.setObjectName("Pill")
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            features.addWidget(pill)
        features.addStretch(1)
        layout.addLayout(features)
        layout.addStretch(1)

        drop_hint = QLabel("也可以把文件拖到窗口任意位置")
        drop_hint.setObjectName("Muted")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(drop_hint)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setBrush(QColor(255, 255, 255, 216))
        pen = QPen(QColor("#D7E1EF"), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([5, 4])
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 14, 14)


class Toast(QFrame):
    """浮在内容区顶部的轻量提示。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setStyleSheet(
            "QFrame#Toast { background: #172033; border-radius: 10px; }"
            "QLabel { color: white; font-size: 12px; }"
        )
        self.setVisible(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 16, 10)
        layout.setSpacing(9)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(16, 16)
        layout.addWidget(self.icon_label)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.finished.connect(self._on_fade_finished)
        self._hiding = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide_animated)

    def show_message(self, text: str, kind: str = "info", duration: int = 3600) -> None:
        self.label.setText(text)
        color = {"info": "#8CB4FF", "success": "#5DD9AC", "error": "#FF9B9B",
                 "warning": "#FFC27A"}.get(kind, "#8CB4FF")
        name = {"info": "info", "success": "check", "error": "warning",
                "warning": "warning"}.get(kind, "info")
        self.icon_label.setPixmap(icons.svg_pixmap(name, color, 16))
        self.adjustSize()
        width = min(max(self.sizeHint().width(), 260), max(300, self.parentWidget().width() - 80))
        self.setFixedWidth(width)
        self.label.setFixedWidth(width - 58)
        self.layout().activate()
        self.adjustSize()
        self.reposition()
        self.raise_()
        self.setVisible(True)
        self._hiding = False
        self._effect.setOpacity(0.0)
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(duration)

    def hide_animated(self) -> None:
        self._hiding = True
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_finished(self) -> None:
        if self._hiding:
            self._hiding = False
            self.setVisible(False)

    def reposition(self) -> None:
        parent = self.parentWidget()
        if not parent:
            return
        self.move(
            max(20, (parent.width() - self.width()) // 2),
            max(18, parent.height() - self.height() - 16),
        )
