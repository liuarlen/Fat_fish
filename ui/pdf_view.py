"""左右双栏 PDF 视图：连续页面、异步栅格化、译文原位覆盖。"""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Sequence, Tuple

import fitz
from PySide6.QtCore import (
    QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsScene, QGraphicsView, QStyleOptionGraphicsItem, QWidget,
)

from core.extract import Block, DocInfo, PageInfo

from . import theme as T
from .widgets import ComboBox


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u303f]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9@._/:%+\-]+")
_BREAKABLE = set("，。；：！？、）】》」』,.;:!?)]}")


def _qrect(rect) -> QRectF:
    """fitz.Rect(x0, y0, x1, y1) -> QRectF(x, y, width, height)。

    注意不能直接 QRectF(*rect)：QRectF 的第三、四个参数是宽高，不是右下角。
    """
    x0, y0, x1, y1 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
    return QRectF(x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0))


# --------------------------------------------------------------------------- #
# 异步渲染
# --------------------------------------------------------------------------- #
class _RenderSignals(QObject):
    ready = Signal(int, str, object)    # generation, key, {page: QImage}


class _RenderTask(QRunnable):
    def __init__(self, path: str, pages: Sequence[int], scale: float,
                 dpr: float, generation: int, key: str,
                 signals: _RenderSignals):
        super().__init__()
        self.path = path
        self.pages = list(pages)
        self.scale = max(0.05, scale)
        self.dpr = max(1.0, dpr)
        self.generation = generation
        self.key = key
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        images: Dict[int, QImage] = {}
        try:
            doc = fitz.open(self.path)
            try:
                for number in self.pages:
                    if not 0 <= number < doc.page_count:
                        continue
                    page = doc[number]
                    # 限制超大位图，避免高倍缩放时内存失控
                    max_px = 3600
                    scale = min(
                        self.scale,
                        max_px / max(page.rect.width, page.rect.height, 1.0),
                    )
                    matrix = fitz.Matrix(scale, scale)
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    fmt = (QImage.Format.Format_RGB888 if pix.n == 3
                           else QImage.Format.Format_RGBA8888)
                    image = QImage(
                        pix.samples, pix.width, pix.height, pix.stride, fmt
                    ).copy()
                    image.setDevicePixelRatio(self.dpr)
                    images[number] = image
            finally:
                doc.close()
        except Exception:
            images = {}
        try:
            self.signals.ready.emit(self.generation, self.key, images)
        except RuntimeError:
            pass


# --------------------------------------------------------------------------- #
# 页面
# --------------------------------------------------------------------------- #
class PageItem(QGraphicsItem):
    def __init__(self, page_info: PageInfo, view: "PdfView", translated: bool):
        super().__init__()
        self.page = page_info
        self.view = view
        self.translated = translated
        self.image: Optional[QImage] = None
        self.image_key = ""
        self.hover_index = -1
        self.show_marks = True
        self._bg_cache: Dict[int, QColor] = {}
        self.setAcceptHoverEvents(translated)
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton if translated else Qt.MouseButton.NoButton
        )
        self.setZValue(1)

    # -- geometry -------------------------------------------------------- #
    def boundingRect(self) -> QRectF:
        pad = 8.0
        return QRectF(-pad, -pad, self.page.width + pad * 2,
                      self.page.height + 30 + pad)

    def set_image(self, image: QImage, key: str) -> None:
        self.image = image
        self.image_key = key
        self._bg_cache.clear()
        self.update()

    def clear_image(self) -> None:
        self.image = None
        self.image_key = ""
        self._bg_cache.clear()
        self.update()

    # -- painting -------------------------------------------------------- #
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem,
              widget: Optional[QWidget] = None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        zoom = max(self.view.zoom, 0.05)
        page_rect = QRectF(0, 0, self.page.width, self.page.height)

        # 阴影
        for i, alpha in ((3.0, 10), (1.5, 16)):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(24, 38, 64, alpha))
            painter.drawRoundedRect(
                page_rect.translated(0, 2.5 / zoom + i / zoom), 4 / zoom, 4 / zoom
            )
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#DCE3ED"), 1.0 / zoom))
        painter.drawRect(page_rect)

        if self.image is not None:
            painter.drawImage(page_rect, self.image)
        else:
            self._paint_placeholder(painter, page_rect, zoom)

        if self.translated:
            for block in self.page.blocks:
                if self._has_translation(block):
                    self._paint_block(painter, block, zoom)
            if 0 <= self.hover_index < len(self.page.blocks):
                block = self.page.blocks[self.hover_index]
                rect = _qrect(block.rect)
                painter.setPen(QPen(QColor(37, 99, 235, 160), 1.0 / zoom,
                                    Qt.PenStyle.DashLine))
                painter.setBrush(QColor(37, 99, 235, 14))
                painter.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5),
                                        3 / zoom, 3 / zoom)

        # 页脚页码
        font = QFont(T.font_family())
        font.setPixelSize(max(7, int(round(9.5 / zoom))))
        painter.setFont(font)
        painter.setPen(QColor(T.TEXT_MUTED))
        painter.drawText(
            QRectF(0, self.page.height + 5 / zoom, self.page.width, 16 / zoom),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            f"{self.page.number + 1}",
        )

    def _paint_placeholder(self, painter: QPainter, page_rect: QRectF,
                           zoom: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#F7F9FC"))
        painter.drawRect(page_rect.adjusted(1, 1, -1, -1))
        painter.setPen(QColor(T.TEXT_MUTED))
        font = QFont(T.font_family())
        font.setPixelSize(max(8, int(round(11 / zoom))))
        painter.setFont(font)
        painter.drawText(page_rect, Qt.AlignmentFlag.AlignCenter, "正在载入页面…")

    @staticmethod
    def _has_translation(block: Block) -> bool:
        return bool(block.translation and block.status in ("done", "skipped"))

    # -- text overlay ---------------------------------------------------- #
    def _background_for(self, block: Block) -> QColor:
        if block.index in self._bg_cache:
            return self._bg_cache[block.index]
        color = QColor("#FFFFFF")
        if self.image is not None and self.page.width > 0 and self.page.height > 0:
            sx = self.image.width() / self.page.width
            sy = self.image.height() / self.page.height
            rect = _qrect(block.rect)
            points = [
                (rect.left() - 2, rect.top() - 2), (rect.right() + 2, rect.top() - 2),
                (rect.left() - 2, rect.bottom() + 2), (rect.right() + 2, rect.bottom() + 2),
                ((rect.left() + rect.right()) / 2, rect.top() - 3),
                ((rect.left() + rect.right()) / 2, rect.bottom() + 3),
            ]
            samples: List[Tuple[int, int, int]] = []
            for px, py in points:
                ix = int(min(max(px * sx, 0), self.image.width() - 1))
                iy = int(min(max(py * sy, 0), self.image.height() - 1))
                sample = QColor(self.image.pixel(ix, iy))
                samples.append((sample.red(), sample.green(), sample.blue()))
            if samples:
                r = sum(s[0] for s in samples) // len(samples)
                g = sum(s[1] for s in samples) // len(samples)
                b = sum(s[2] for s in samples) // len(samples)
                color = QColor(r, g, b)
        self._bg_cache[block.index] = color
        return color

    @staticmethod
    def _break_point(line: str) -> int:
        for i in range(len(line) - 1, 0, -1):
            prev = line[i - 1]
            if prev.isspace() or prev in _BREAKABLE:
                return i
            if _CJK_RE.match(prev):
                return i
        return 0

    def _wrap(self, text: str, metrics: QFontMetricsF, max_width: float) -> List[str]:
        lines: List[str] = []
        for paragraph in (text or "").replace("\r", "").split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            current = ""
            for ch in paragraph:
                trial = current + ch
                if current and metrics.horizontalAdvance(trial) > max_width:
                    cut = self._break_point(current)
                    if cut > 0:
                        line = current[:cut].rstrip()
                        if line:
                            lines.append(line)
                        current = current[cut:].lstrip() + ch
                    else:
                        lines.append(current.rstrip())
                        current = ch
                else:
                    current = trial
            if current.strip():
                lines.append(current.rstrip())
        while lines and not lines[-1]:
            lines.pop()
        # 中文禁则：避免逗号、句号等标点出现在行首
        for index in range(1, len(lines)):
            while lines[index] and lines[index][0] in _BREAKABLE and len(lines[index - 1]) > 1:
                lines[index - 1] += lines[index][0]
                lines[index] = lines[index][1:]
        return lines

    def _paint_block(self, painter: QPainter, block: Block, zoom: float) -> None:
        text = (block.translation or "").strip()
        if not text:
            return
        rect = _qrect(block.rect)
        if rect.width() < 2 or rect.height() < 2:
            return
        base_size = max(3.0, block.size * self.view.font_scale)
        min_size = max(4.0, block.size * 0.62)
        family = T.font_family()
        chosen = None
        lines: List[str] = []
        size = base_size
        while True:
            font = QFont(family)
            font.setPixelSize(max(4, int(round(size))))
            font.setWeight(QFont.Weight.Normal)
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            metrics = QFontMetricsF(font)
            wrapped = self._wrap(text, metrics, max(4.0, rect.width()))
            line_gap = max(
                block.lineheight * size / max(block.size, 0.1),
                size * 1.12,
            )
            total = metrics.ascent() + metrics.descent()
            if len(wrapped) > 1:
                total += (len(wrapped) - 1) * line_gap
            if total <= rect.height() + 1.2 or size <= min_size:
                chosen = (font, metrics, wrapped, line_gap, total)
                break
            size = max(min_size, size - max(0.4, size * 0.055))
        if chosen is None:
            return
        font, metrics, lines, line_gap, total_h = chosen

        painter.save()
        painter.setClipRect(rect.adjusted(-1.5, -1.5, 1.5, 2.0))
        # 覆盖原文：从页面位图里采样背景色，避免在浅色卡片上盖出白块
        bg = self._background_for(block)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRect(rect.adjusted(-1.0, -1.0, 1.0, 1.0))

        color = QColor.fromRgbF(
            max(0.0, min(1.0, block.color[0])),
            max(0.0, min(1.0, block.color[1])),
            max(0.0, min(1.0, block.color[2])),
        )
        if color.lightness() > 232:
            color = QColor(T.TEXT)
        painter.setFont(font)
        painter.setPen(color)
        top = rect.top() + max(0.0, (rect.height() - total_h) / 2.0)
        baseline = top + metrics.ascent()
        for line in lines:
            width = metrics.horizontalAdvance(line)
            if block.align == 1:
                x = rect.left() + max(0.0, (rect.width() - width) / 2.0)
            elif block.align == 2:
                x = rect.right() - width
            else:
                x = rect.left()
            painter.drawText(QPointF(x, baseline), line)
            baseline += line_gap
        painter.restore()

    # -- interaction ----------------------------------------------------- #
    def _block_at(self, point: QPointF) -> int:
        for block in self.page.blocks:
            if _qrect(block.rect).contains(point):
                return block.index
        return -1

    def hoverMoveEvent(self, event) -> None:
        if not self.translated:
            return
        index = self._block_at(event.pos())
        if index != self.hover_index:
            self.hover_index = index
            self.update()
        if index >= 0:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            block = self.page.blocks[index]
            self.setToolTip(
                "双击校对这段译文\n\n原文：" + block.text[:180]
            )
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setToolTip("")
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        if self.hover_index != -1:
            self.hover_index = -1
            self.update()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self.translated:
            return
        index = self._block_at(event.pos())
        if index >= 0:
            self.view.blockActivated.emit(self.page.number, index)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


# --------------------------------------------------------------------------- #
# 视图
# --------------------------------------------------------------------------- #
class PdfView(QGraphicsView):
    currentPageChanged = Signal(int)
    blockActivated = Signal(int, int)
    zoomChanged = Signal(float)

    MIN_ZOOM = 0.30
    MAX_ZOOM = 3.50

    def __init__(self, translated: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.translated = translated
        self.doc: Optional[DocInfo] = None
        self.zoom = 1.0
        self.fit_mode = True
        self.font_scale = 1.0
        self.show_marks = True
        self._page_items: List[PageItem] = []
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate
        )
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QColor(T.CANVAS))
        self.setAcceptDrops(False)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._generation = 0
        self._inflight_generation = 0
        self._refresh_pending = False
        self._key = ""
        self._lru: "OrderedDict[int, str]" = OrderedDict()
        self._signal_refs: List[_RenderSignals] = []
        self._current_page = -1
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(35)
        self._scroll_timer.timeout.connect(self._on_settled)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(90)
        self._render_timer.timeout.connect(self._refresh_visible)

        self.verticalScrollBar().valueChanged.connect(self._schedule_scroll)
        self.horizontalScrollBar().valueChanged.connect(self._schedule_scroll)

    # -- document -------------------------------------------------------- #
    def set_document(self, doc: Optional[DocInfo]) -> None:
        self.doc = doc
        self._generation += 1
        self._inflight_generation = 0
        self._pool.clear()
        self._lru.clear()
        self._page_items = []
        self._scene.clear()
        if doc is None:
            self.setSceneRect(QRectF())
            return
        max_width = max((page.width for page in doc.pages), default=595.0)
        max_width = max(1.0, max_width)
        y = 16.0
        for page in doc.pages:
            item = PageItem(page, self, self.translated)
            item.show_marks = self.show_marks
            item.setPos((max_width - page.width) / 2.0, y)
            self._scene.addItem(item)
            self._page_items.append(item)
            y += page.height + 28.0
        self._scene.setSceneRect(QRectF(0, 0, max_width, max(1.0, y + 20)))
        self._current_page = -1
        self.verticalScrollBar().setValue(0)
        self._schedule_render(0)

    # -- zoom ------------------------------------------------------------ #
    def fit_width_scale(self) -> float:
        if not self.doc:
            return 1.0
        max_width = max((page.width for page in self.doc.pages), default=595.0)
        available = max(100, self.viewport().width() - 34)
        return max(self.MIN_ZOOM, min(self.MAX_ZOOM, available / max(max_width, 1.0)))

    def apply_zoom(self, zoom: float, fit_mode: bool = False) -> None:
        zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, zoom))
        if abs(zoom - self.zoom) < 0.0005 and fit_mode == self.fit_mode:
            return
        center = self.mapToScene(self.viewport().rect().center())
        self.zoom = zoom
        self.fit_mode = fit_mode
        self.resetTransform()
        self.scale(zoom, zoom)
        self.centerOn(center)
        self._generation += 1
        self._pool.clear()
        self._schedule_render(20)
        self.zoomChanged.emit(zoom)

    def set_font_scale(self, scale: float) -> None:
        self.font_scale = max(0.5, min(1.5, scale))
        for item in self._page_items:
            item.update()

    def set_show_marks(self, show: bool) -> None:
        self.show_marks = show
        for item in self._page_items:
            item.show_marks = show
            item.update()

    def update_page(self, index: int) -> None:
        if 0 <= index < len(self._page_items):
            self._page_items[index].update()

    def update_all(self) -> None:
        for item in self._page_items:
            item.update()

    # -- navigation ------------------------------------------------------ #
    def page_count(self) -> int:
        return len(self._page_items)

    def current_page(self) -> int:
        return max(0, min(len(self._page_items) - 1, self._current_page))

    def scroll_to_page(self, index: int) -> None:
        if not self._page_items:
            return
        index = max(0, min(len(self._page_items) - 1, index))
        item = self._page_items[index]
        top = item.pos().y() * self.zoom
        self.verticalScrollBar().setValue(int(max(0, top - 12)))
        self._current_page = index
        self.currentPageChanged.emit(index)

    def maybe_refit(self) -> None:
        if self.fit_mode:
            self.apply_zoom(self.fit_width_scale(), True)

    # -- rendering ------------------------------------------------------- #
    def _visible_pages(self, buffer_pages: int = 1) -> List[int]:
        if not self._page_items:
            return []
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        visible.adjust(0, -visible.height() * 0.25, 0, visible.height() * 0.25)
        pages = [i for i, item in enumerate(self._page_items)
                 if item.sceneBoundingRect().intersects(visible)]
        if not pages:
            center = visible.center().y()
            best, best_dist = 0, 1e18
            for i, item in enumerate(self._page_items):
                dist = abs(item.sceneBoundingRect().center().y() - center)
                if dist < best_dist:
                    best, best_dist = i, dist
            pages = [best]
        low = max(0, min(pages) - buffer_pages)
        high = min(len(self._page_items) - 1, max(pages) + buffer_pages)
        return list(range(low, high + 1))

    def _render_key(self) -> str:
        dpr = max(1.0, self.devicePixelRatioF())
        return f"{self.zoom:.4f}@{dpr:.2f}"

    def _schedule_render(self, delay: int = 80) -> None:
        if self.doc is None:
            return
        self._render_timer.start(delay)

    def _refresh_visible(self) -> None:
        if self.doc is None or not self._page_items:
            return
        if self._inflight_generation == self._generation:
            self._refresh_pending = True
            return
        key = self._render_key()
        pages = self._visible_pages()
        missing = []
        for number in pages:
            item = self._page_items[number]
            if item.image is not None and item.image_key == key:
                continue
            missing.append(number)
        if not missing:
            return
        self._key = key
        self._generation += 1
        generation = self._generation
        self._inflight_generation = generation
        self._refresh_pending = False
        dpr = max(1.0, self.devicePixelRatioF())
        signals = _RenderSignals(self)
        signals.ready.connect(self._on_images_ready)
        self._signal_refs.append(signals)
        if len(self._signal_refs) > 6:
            self._signal_refs = self._signal_refs[-6:]
        task = _RenderTask(
            self.doc.path, missing, self.zoom * dpr, dpr, generation, key, signals
        )
        self._pool.start(task)

    def _on_images_ready(self, generation: int, key: str, images: dict) -> None:
        if generation != self._generation:
            # 迟到的旧请求：只有它仍是“当前请求”时才清标记并补一次；
            # 若已有更新请求在飞，忽略即可，避免重复渲染/抖动。
            if self._inflight_generation == generation:
                self._inflight_generation = 0
                self._refresh_pending = True
                self._refresh_visible()
            return
        self._inflight_generation = 0
        visible = set(self._visible_pages())
        for number, image in images.items():
            if 0 <= number < len(self._page_items):
                item = self._page_items[number]
                item.set_image(image, key)
                self._lru[number] = key
                self._lru.move_to_end(number)
        # 只保留当前视口附近与最近看过的页面位图，避免大文档内存膨胀
        if len(self._lru) > 12:
            removable = [
                number for number in self._lru
                if number not in visible and number != self.current_page()
            ]
            for old_number in removable:
                if len(self._lru) <= 12:
                    break
                self._lru.pop(old_number, None)
                if 0 <= old_number < len(self._page_items):
                    self._page_items[old_number].clear_image()
        if self._refresh_pending:
            self._refresh_pending = False
            self._schedule_render(20)

    # -- events ---------------------------------------------------------- #
    def _schedule_scroll(self, *_args) -> None:
        self._scroll_timer.start()
        self._schedule_render(100)

    def _on_settled(self) -> None:
        page = self._page_at_center()
        if page != self._current_page:
            self._current_page = page
            self.currentPageChanged.emit(page)
        self._refresh_visible()

    def _page_at_center(self) -> int:
        if not self._page_items:
            return 0
        center = self.mapToScene(self.viewport().rect().center())
        for i, item in enumerate(self._page_items):
            rect = item.sceneBoundingRect()
            if rect.top() - 10 <= center.y() <= rect.bottom() + 10:
                return i
        best, best_dist = 0, 1e18
        for i, item in enumerate(self._page_items):
            dist = abs(item.sceneBoundingRect().center().y() - center.y())
            if dist < best_dist:
                best, best_dist = i, dist
        return best

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.12 if delta > 0 else 1 / 1.12
            self.apply_zoom(self.zoom * factor, False)
            event.accept()
            return
        super().wheelEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_render(120)


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def make_combo(items: Sequence[Tuple[str, object]], current: object = None) -> ComboBox:
    combo = ComboBox()
    for label, value in items:
        combo.addItem(label, value)
    if current is not None:
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)
    return combo
