"""内联 SVG 图标与品牌图形（不依赖外部资源/字体图标）。"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer

from . import theme as T


PATHS = {
    "folder": (
        "M3 6.5A2.5 2.5 0 0 1 5.5 4H9l2 2h7.5A2.5 2.5 0 0 1 21 8.5v9"
        "A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5z"
    ),
    "languages": (
        "M5 8l6 6M4 14l6-6 2-3M2 5h12M7 2h1M22 22l-5-10-5 10M14 18h6"
    ),
    "play": "M8 5v14l11-7z",
    "stop": "M7 7h10v10H7z",
    "download": (
        "M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
    ),
    "settings": (
        "M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0"
        "l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 "
        "1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 "
        "2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44"
        "a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 "
        "2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.1a2 2 0 0 1-1-1.72v-.51a2 2 0 0 1 "
        "1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 "
        "1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"
        "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"
    ),
    "book": (
        "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20"
        "V2H6.5A2.5 2.5 0 0 0 4 4.5v15z"
    ),
    "close": "M6 6l12 12M18 6L6 18",
    "chevron_down": "M6 9l6 6 6-6",
    "chevron_up": "M6 15l6-6 6 6",
    "chevron_left": "M15 6l-6 6 6 6",
    "chevron_right": "M9 6l6 6-6 6",
    "plus": "M12 5v14M5 12h14",
    "minus": "M5 12h14",
    "fit": (
        "M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4"
        "M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4"
    ),
    "search": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
    "trash": (
        "M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"
        "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6"
    ),
    "edit": "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
    "refresh": "M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6",
    "check": "M20 6L9 17l-5-5",
    "warning": (
        "M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9"
        "a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01"
    ),
    "info": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
    "eye": "M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "eye_off": (
        "M17.9 17.9A10.3 10.3 0 0 1 12 20C5 20 1 12 1 12a19 19 0 0 1 5.1-5.9"
        "M9.9 4.2A10.8 10.8 0 0 1 12 4c7 0 11 8 11 8a19 19 0 0 1-2.2 3.2"
        "M1 1l22 22M9.9 9.9a3 3 0 0 0 4.2 4.2"
    ),
    "external": (
        "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"
        "M15 3h6v6M10 14L21 3"
    ),
    "file": (
        "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"
        "M14 2v6h6M9 13h6M9 17h6"
    ),
    "sparkles": (
        "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"
        "M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z"
    ),
    "arrow_right": "M5 12h14M13 6l6 6-6 6",
    "more": "M5 12h.01M12 12h.01M19 12h.01",
    "copy": "M9 9h10v10H9zM5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1",
    "zoom_in": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3M8 11h6M11 8v6",
    "zoom_out": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3M8 11h6",
    "globe": (
        "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM2 12h20"
        "M12 2a15.3 15.3 0 0 1 0 20M12 2a15.3 15.3 0 0 0 0 20"
    ),
    "panel_left": "M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM9 3v18",
    "translate": (
        "M4 4h8M8 4v2c0 4-1.5 7-4 9M6 9c1.5 2.8 4 5 7 6"
        "M13 20l4-10 4 10M14.5 16h5"
    ),
}


def svg_data(name: str, color: str = T.TEXT_SECONDARY, stroke_width: float = 1.8) -> str:
    path = PATHS.get(name, PATHS["info"])
    fill = "none"
    stroke = color
    width = stroke_width
    if name in ("play", "stop"):
        fill = color
        stroke = "none"
    if name == "more":
        width = 3.4
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24">'
        f'<path d="{path}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" '
        'stroke-linecap="round" stroke-linejoin="round" />'
        '</svg>'
    )


def icon(name: str, color: str = T.TEXT_SECONDARY, size: int = 18) -> QIcon:
    renderer = QSvgRenderer(QByteArray(svg_data(name, color).encode("utf-8")))
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


def svg_pixmap(name: str, color: str, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_data(name, color).encode("utf-8")))
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def brand_pixmap(size: int = 42) -> QPixmap:
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    rect = QRectF(0.5, 0.5, size - 1, size - 1)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor("#2F6BFF"))
    gradient.setColorAt(0.55, QColor("#3157E8"))
    gradient.setColorAt(1.0, QColor("#6C4BE8"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, size * 0.28, size * 0.28)
    # soft highlight
    painter.setBrush(QColor(255, 255, 255, 28))
    painter.drawEllipse(QRectF(-size * 0.2, -size * 0.45, size * 0.95, size * 1.1))
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"])
    font.setPixelSize(int(size * 0.54))
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(QRectF(0, -size * 0.035, size, size), Qt.AlignmentFlag.AlignCenter, "译")
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def empty_illustration(width: int = 380, height: int = 220) -> QPixmap:
    """欢迎页插画：左原文 / 右译文，一支箭头把版面“换”成中文。"""
    scale = 2
    pixmap = QPixmap(width * scale, height * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#EDF3FF"))
    painter.drawEllipse(QRectF(55, 20, 270, 180))

    def page(x: float, y: float, translated: bool) -> None:
        rect = QRectF(x, y, 126, 160)
        painter.setBrush(QColor(25, 38, 64, 22))
        painter.drawRoundedRect(rect.translated(2, 5), 10, 10)
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#DCE4F0"), 1))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        if translated:
            painter.setBrush(QColor("#EAF1FF"))
            painter.drawRoundedRect(QRectF(x + 13, y + 14, 42, 7), 3, 3)
            line_color = QColor("#7C9DE6")
        else:
            painter.setBrush(QColor("#CAD4E2"))
            painter.drawRoundedRect(QRectF(x + 13, y + 14, 42, 7), 3, 3)
            line_color = QColor("#C4CEDD")
        rng = [0.82, 0.95, 0.72, 0.88, 0.6]
        for i, factor in enumerate(rng):
            w = 92 * factor
            painter.setBrush(QColor("#D6DEEA") if not translated else QColor("#AFC5F3"))
            painter.drawRoundedRect(QRectF(x + 13, y + 36 + i * 12, w, 5), 2.5, 2.5)
        # image block
        painter.setBrush(QColor("#EDF1F7"))
        painter.drawRoundedRect(QRectF(x + 13, y + 108, 100, 36), 5, 5)
        if translated:
            painter.setPen(QColor("#2563EB"))
            font = QFont()
            font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei"])
            font.setPixelSize(13)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.drawText(QRectF(x + 13, y + 108, 100, 36),
                             Qt.AlignmentFlag.AlignCenter, "原位译文")
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#D6DEEA"))
            painter.drawRoundedRect(QRectF(x + 22, y + 118, 26, 16), 3, 3)
            painter.setBrush(QColor("#E4EAF2"))
            painter.drawRoundedRect(QRectF(x + 55, y + 116, 48, 4), 2, 2)
            painter.drawRoundedRect(QRectF(x + 55, y + 124, 40, 4), 2, 2)

    page(78, 30, False)
    page(238, 30, True)

    # arrow badge
    painter.setBrush(QColor("#2563EB"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(221, 111), 19, 19)
    pen = QPen(QColor("white"), 2.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(212, 111), QPointF(230, 111))
    painter.drawLine(QPointF(224, 105), QPointF(230, 111))
    painter.drawLine(QPointF(224, 117), QPointF(230, 111))

    # small floating chip
    painter.setPen(QPen(QColor("#D7E3FA"), 1))
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawRoundedRect(QRectF(130, 183, 120, 24), 12, 12)
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei"])
    font.setPixelSize(10)
    painter.setFont(font)
    painter.setPen(QColor("#2563EB"))
    painter.drawText(QRectF(130, 183, 120, 24), Qt.AlignmentFlag.AlignCenter,
                     "版式不变 · 原位覆盖")
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap
