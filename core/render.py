"""把译文原位写回 PDF —— 版式不变，只把英文换成译文。

实现要点
--------
1. ``redact``（默认）：用 PyMuPDF 的“涂销”功能精确删除原文本字节，
   同时保留矢量图形与图片（``graphics=0, images=0``），
   再用 TextWriter 把译文写到原来的位置、保持原来的字号/行距/对齐。
2. ``cover``：不删原文，直接在原文区域上覆盖一层底色再写译文。
3. 中文等 CJK 文字使用系统 CJK 字体（微软雅黑等），
   拉丁语言使用系统拉丁字体；若能从原 PDF 抽出内嵌字体则优先复用。

注意：不修改原文件，始终生成新的 PDF。
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import fitz

from .extract import Block, DocInfo, contains_cjk

# --------------------------------------------------------------------------- #
# 字体
# --------------------------------------------------------------------------- #
_WINDIR = os.environ.get("WINDIR", r"C:\Windows")
FONT_DIRS = [
    os.path.join(_WINDIR, "Fonts"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
]

# (显示名, 文件名) 优先级从高到低
_CJK_FONTS: Sequence[Tuple[str, str]] = (
    ("Microsoft YaHei", "msyh.ttc"),
    ("Microsoft YaHei UI", "msyh.ttc"),
    ("SimHei", "simhei.ttf"),
    ("SimSun", "simsun.ttc"),
    ("DengXian", "Deng.ttf"),
    ("Noto Sans CJK SC", "NotoSansCJKsc-Regular.otf"),
    ("Source Han Sans SC", "SourceHanSansSC-Regular.otf"),
    ("Malgun Gothic", "malgun.ttf"),
    ("Meiryo", "meiryo.ttc"),
)

_LATIN_FONTS: Sequence[Tuple[str, str]] = (
    ("Arial", "arial.ttf"),
    ("Segoe UI", "segoeui.ttf"),
    ("Calibri", "calibri.ttf"),
    ("Tahoma", "tahoma.ttf"),
    ("Verdana", "verdana.ttf"),
    ("DejaVu Sans", "DejaVuSans.ttf"),
)

_BUILTIN = {"helv", "heit", "hebo", "cour", "cobo", "tiro", "tibo", "symb", "zadb"}

_CJK_LANGS = {"zh-CN", "zh-TW", "ja", "ko"}


def find_font_file(filename: str) -> Optional[str]:
    for folder in FONT_DIRS:
        if not folder:
            continue
        path = os.path.join(folder, filename)
        if os.path.exists(path):
            return path
    return None


def pick_system_font(need_cjk: bool) -> Tuple[str, str]:
    """返回 (显示名, 字体文件路径)；找不到时回退到内置 helv。"""
    order = _CJK_FONTS + _LATIN_FONTS if need_cjk else _LATIN_FONTS + _CJK_FONTS
    for name, filename in order:
        path = find_font_file(filename)
        if path:
            return name, path
    return "Helvetica", ""


@dataclass
class FontKey:
    family: str      # 显示名
    fontfile: str    # 字体文件路径，空表示内置字体
    builtin: str = "helv"

    def same_as(self, other: "FontKey") -> bool:
        return self.fontfile == other.fontfile and self.builtin == other.builtin


class FontBook:
    """按需加载并缓存 fitz.Font 对象。"""

    def __init__(self, target_lang: str = "zh-CN", prefer_embedded: bool = True):
        self.target_lang = target_lang
        self.prefer_embedded = prefer_embedded
        self._cache: Dict[str, fitz.Font] = {}
        self._cjk_key: Optional[FontKey] = None
        self._latin_key: Optional[FontKey] = None

    # -- 基础 ------------------------------------------------------------- #
    def _load(self, key: FontKey) -> fitz.Font:
        ck = key.fontfile or key.builtin
        if ck not in self._cache:
            try:
                if key.fontfile:
                    self._cache[ck] = fitz.Font(fontfile=key.fontfile)
                else:
                    self._cache[ck] = fitz.Font(key.builtin)
            except Exception:
                self._cache[ck] = fitz.Font("helv")
        return self._cache[ck]

    @property
    def cjk_key(self) -> FontKey:
        if self._cjk_key is None:
            name, path = pick_system_font(True)
            self._cjk_key = FontKey(name, path)
        return self._cjk_key

    @property
    def latin_key(self) -> FontKey:
        if self._latin_key is None:
            name, path = pick_system_font(False)
            self._latin_key = FontKey(name, path)
        return self._latin_key

    # -- 选择 ------------------------------------------------------------- #
    def key_for(self, block_block: Block, text: str, embed_ok: bool) -> FontKey:
        """为一段译文挑选字体。"""
        need_cjk = contains_cjk(text) or self.target_lang in _CJK_LANGS
        if need_cjk:
            return self.cjk_key
        if self.prefer_embedded and block_block.fontfile and embed_ok:
            return FontKey(block_block.fontname or "Embedded", block_block.fontfile or "")
        if not text:
            return self.latin_key
        # 拉丁文字：优先复用 PDF 内置标准字体（体积最小）
        base = (block_block.font or "").lower()
        if base in _BUILTIN:
            return FontKey(block_block.font, "", block_block.font)
        return self.latin_key

    def font(self, key: FontKey) -> fitz.Font:
        return self._load(key)


# --------------------------------------------------------------------------- #
# 文本换行 / 排版
# --------------------------------------------------------------------------- #
_TOKEN_RE = re.compile(r"\S+\s*")


def wrap_text(
    text: str,
    font: fitz.Font,
    fontsize: float,
    max_width: float,
) -> List[str]:
    """贪心换行。CJK 可任意字符断行；拉丁按单词断行。"""
    text = re.sub(r"[ \t]+", " ", (text or "").replace("\r", "")).strip()
    if not text:
        return []

    def width_of(s: str) -> float:
        try:
            return font.text_length(s, fontsize=fontsize)
        except Exception:
            return len(s) * fontsize * 0.5

    lines: List[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue
        if " " in paragraph:
            # 拉丁文本：按单词（含尾随空格）断行
            tokens = _TOKEN_RE.findall(paragraph)
        else:
            # 中文等无空格文本：逐字符断行
            tokens = list(paragraph)
        if not tokens:
            continue
        current = ""
        for token in tokens:
            if current and width_of(current.rstrip() + token.rstrip()) > max_width:
                lines.append(current.rstrip())
                current = token
            else:
                current += token
            # 单个 token 超长（例如超长网址）：强制按字符切
            while width_of(current.rstrip()) > max_width and len(current.rstrip()) > 1:
                body = current.rstrip()
                cut = max(1, int(len(body) * max_width / max(width_of(body), 1e-6)) or 1)
                cut = min(cut, len(body) - 1)
                while cut > 1 and width_of(body[:cut]) > max_width:
                    cut -= 1
                while cut < len(body) - 1 and width_of(body[: cut + 1]) <= max_width:
                    cut += 1
                lines.append(body[:cut].rstrip())
                current = body[cut:] + (" " if current.endswith(" ") else "")
        if current.strip():
            lines.append(current.rstrip())
    return lines


def _place_lines(
    x_left: float,
    x_right: float,
    lines: Sequence[str],
    font: fitz.Font,
    fontsize: float,
    baselines: Sequence[float],
    align: int,
    measure,
) -> List[Tuple[Tuple[float, float], str]]:
    """计算每行文本的插入点（TextWriter 的 append 参数）。"""
    placed: List[Tuple[Tuple[float, float], str]] = []
    for line, baseline in zip(lines, baselines):
        if not line.strip():
            continue
        w = measure(line)
        if align == 1:
            x = x_left + max(0.0, (x_right - x_left - w) / 2.0)
        elif align == 2:
            x = max(x_left, x_right - w)
        else:
            x = x_left
        placed.append(((x, baseline), line))
    return placed


def fit_block(
    block: Block,
    text: str,
    font: fitz.Font,
    base_size: float,
    scale: float,
    box: fitz.Rect,
    auto_shrink: bool = True,
    min_ratio: float = 0.62,
) -> Tuple[List[Tuple[Tuple[float, float], str]], float]:
    """选择字号并换行，返回 (待写入的行, 使用的字号)。"""
    ascender = getattr(font, "ascender", 0.8) or 0.8
    descender = getattr(font, "descender", -0.2) or -0.2

    def measure(s: str, size: float) -> float:
        try:
            return font.text_length(s, fontsize=size)
        except Exception:
            return len(s) * size * 0.5

    def layout(size: float):
        lines = wrap_text(text, font, size, box.width)
        if not lines:
            return [], [], 0.0
        line_gap = block.lineheight * (size / max(base_size, 1e-6))
        line_gap = max(line_gap, size * 1.05)
        n = len(lines)
        total_height = (n - 1) * line_gap + size * 1.25
        if block.first_baseline is None:
            top = box.y0 + ascender * size
            candidates = [top + i * line_gap for i in range(n)]
            return lines, candidates, total_height
        # 单行且空间够：保持原基线，位置最贴合原文
        if n == 1 and size <= (block.rect.height + 1.5) * 1.15:
            return lines, [block.first_baseline], total_height
        # 多行：最后一行基线贴原文底部，整体向上排；排不下则从原首行基线往下排
        bottom_baseline = block.rect.y1 + descender * size
        candidates = [bottom_baseline - (n - 1 - i) * line_gap for i in range(n)]
        if candidates[0] < block.first_baseline - line_gap * 0.6:
            candidates = [block.first_baseline + i * line_gap for i in range(n)]
        return lines, candidates, total_height

    size = max(3.0, base_size * max(scale, 0.2))
    lines, baselines, height = layout(size)
    if auto_shrink:
        min_size = max(3.5, base_size * min_ratio * min(scale, 1.0))
        best = (lines, baselines, size)
        lo, hi = min_size, size
        for _ in range(14):
            mid = (lo + hi) / 2.0
            l2, b2, h2 = layout(mid)
            if (not l2) or h2 <= box.height + max(1.0, box.height * 0.02):
                best = (l2, b2, mid)
                lo = mid
            else:
                hi = mid
            if hi - lo < 0.15:
                break
        lines, baselines, size = best
    placed = _place_lines(
        box.x0, box.x1, lines, font, size, baselines, block.align,
        lambda s: measure(s, size),
    )
    return placed, size


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
@dataclass
class RenderResult:
    output: str
    pages: int = 0
    blocks: int = 0
    rendered: int = 0
    skipped: int = 0
    warnings: List[str] = field(default_factory=list)


def _block_box(block: Block, pad: float = 1.0) -> fitz.Rect:
    box = fitz.Rect(block.rect)
    box.x0 -= pad
    box.y0 -= pad
    box.x1 += pad
    box.y1 += pad
    box.normalize()
    if box.width < 1:
        box.x1 = box.x0 + 1
    if box.height < 1:
        box.y1 = box.y0 + 1
    return box


def render_document(
    doc_info: DocInfo,
    output_path: str,
    mode: str = "redact",
    font_scale: float = 1.0,
    cover_color: Tuple[float, float, float] = (1, 1, 1),
    target_lang: str = "zh-CN",
    prefer_embedded: bool = True,
    auto_shrink: bool = True,
    progress=None,
) -> RenderResult:
    """生成“原位替换”后的 PDF。"""
    src = fitz.open(doc_info.path)
    result = RenderResult(output=output_path)
    book = FontBook(target_lang=target_lang, prefer_embedded=prefer_embedded)
    try:
        wanted = {page_info.number for page_info in doc_info.pages}
        for number in range(src.page_count - 1, -1, -1):
            if number not in wanted:                 # 只保留本次需要处理的页面
                src.delete_page(number)
        index_of = {number: i for i, number in enumerate(sorted(wanted))}
        result.pages = src.page_count
        parent = os.path.dirname(os.path.abspath(output_path))
        if parent:
            os.makedirs(parent, exist_ok=True)

        for page_info in doc_info.pages:
            page = src[index_of[page_info.number]]
            jobs: List[Tuple[Block, str]] = []
            for block in page_info.blocks:
                if block.rotation:
                    result.skipped += 1
                    result.warnings.append(
                        f"第 {block.page + 1} 页：旋转文本未替换（{block.text[:20]}…）"
                    )
                    continue
                if block.status in ("done", "skipped") and block.translation:
                    jobs.append((block, block.translation))
                else:
                    result.skipped += 1
            if not jobs:
                continue

            boxes = [_block_box(b) for b, _ in jobs]

            # 1) 删除原文 / 覆盖原文
            if mode == "redact":
                for box in boxes:
                    page.add_redact_annot(box)
                try:
                    # text=0：删除框内文字；images=0 / graphics=0：保留图片与矢量图形
                    page.apply_redactions(images=0, graphics=0, text=0)
                except TypeError:                       # 老版本参数不同
                    page.apply_redactions()
            else:
                for box in boxes:
                    page.draw_rect(
                        box, color=None, fill=cover_color, overlay=True, width=0
                    )

            # 2) 写入译文，按 (字体) 分组批量写入
            text_writer = fitz.TextWriter(page.rect)
            groups: Dict[Tuple[str, str], fitz.TextWriter] = {}
            for (block, text), box in zip(jobs, boxes):
                text = (text or "").strip()
                if not text:
                    continue
                font_key = book.key_for(block, text, embed_ok=True)
                font = book.font(font_key)
                placed, used_size = fit_block(
                    block, text, font, block.size, font_scale, box, auto_shrink
                )
                if not placed:
                    continue
                gkey = (font_key.fontfile, font_key.builtin)
                tw = groups.get(gkey)
                if tw is None:
                    tw = fitz.TextWriter(page.rect)
                    groups[gkey] = tw
                for point, line in placed:
                    try:
                        tw.append(
                            point, line,
                            font=font,
                            fontsize=used_size,
                            small_caps=False,
                        )
                    except Exception as exc:            # 字体缺字形等
                        result.warnings.append(f"第 {block.page + 1} 页写入失败：{exc}")
                result.rendered += 1
                result.blocks += 1

            for (fontfile, builtin), tw in groups.items():
                color = (0, 0, 0)
                try:
                    tw.write_text(page, color=color)
                except Exception as exc:
                    result.warnings.append(f"第 {page_info.number + 1} 页文字输出失败：{exc}")

            if progress:
                progress(page_info.number + 1, result.pages)

        try:
            # 把用到的字体子集化：否则整份中文字体（约 20MB）会被嵌进去
            src.subset_fonts(verbose=False)
        except Exception as exc:                    # 老版本或个别字体不支持
            result.warnings.append(f"字体子集化跳过：{exc}")
        src.save(output_path, garbage=4, deflate=True, clean=True)
    finally:
        src.close()
    return result


# --------------------------------------------------------------------------- #
# 双语对照导出（左原文 / 右译文）
# --------------------------------------------------------------------------- #
def export_side_by_side(
    doc_info: DocInfo,
    translated_pdf: str,
    output_path: str,
    gap: float = 12.0,
    progress=None,
) -> str:
    """把原文与译文并排拼到一个新 PDF：左页原文、右页译文。"""
    original = fitz.open(doc_info.path)
    translated = fitz.open(translated_pdf)
    out = fitz.open()
    try:
        for i in range(original.page_count):
            left = original[i]
            right = translated[i] if i < translated.page_count else None
            w = left.rect.width + gap + (right.rect.width if right else left.rect.width)
            h = max(left.rect.height, right.rect.height if right else left.rect.height)
            page = out.new_page(width=w, height=h)
            page.show_pdf_page(
                fitz.Rect(0, 0, left.rect.width, left.rect.height), original, i
            )
            if right is not None:
                page.show_pdf_page(
                    fitz.Rect(
                        left.rect.width + gap, 0,
                        left.rect.width + gap + right.rect.width,
                        right.rect.height,
                    ),
                    translated, i,
                )
            if progress:
                progress(i + 1, original.page_count)
        out.save(output_path, garbage=4, deflate=True)
    finally:
        original.close()
        translated.close()
        out.close()
    return output_path


def export_page_images(
    pdf_path: str,
    page_no: int,
    zoom: float,
    clip: Optional[fitz.Rect] = None,
) -> bytes:
    """把某一页渲染成 PNG 字节（白底），用于界面预览。"""
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_no]
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False, clip=clip)
        return pix.tobytes("png")
    finally:
        doc.close()


def render_pages_to_png(
    pdf_path: str,
    page_numbers: Sequence[int],
    zoom: float,
    cache: Optional[Dict[Tuple[int, ...], bytes]] = None,
    limit: int = 12,
    fit_sizes: Optional[Dict[int, Tuple[int, int]]] = None,
) -> Dict[int, bytes]:
    """一次性把多页渲染成白底 PNG（画布重绘时用，减少反复打开文件）。

    fit_sizes 给出每页期望的像素尺寸（已乘过系统缩放），
    这样在高 DPI 屏幕上不会因为缩小而发虚。
    """
    result: Dict[int, bytes] = {}
    matrix = fitz.Matrix(zoom, zoom)
    key_zoom = int(round(zoom * 1000))
    fit_key = tuple(sorted((n, w, h) for n, (w, h) in (fit_sizes or {}).items()))
    doc = fitz.open(pdf_path)
    try:
        for number in page_numbers:
            if not 0 <= number < doc.page_count:
                continue
            key = (number, key_zoom) + fit_key
            if cache is not None and key in cache:
                result[number] = cache[key]
                continue
            page = doc[number]
            size = (fit_sizes or {}).get(number)
            if size and size[0] > 0 and size[1] > 0:
                # 直接按目标像素渲染：矢量重采样，比位图缩放清晰得多
                one = page.rect
                use = fitz.Matrix(size[0] / max(one.width, 1e-6),
                                  size[1] / max(one.height, 1e-6))
            else:
                use = matrix
            pix = page.get_pixmap(matrix=use, alpha=False)
            data = pix.tobytes("png")
            if cache is not None:
                if len(cache) > limit:
                    cache.clear()
                cache[key] = data
            result[number] = data
    finally:
        doc.close()
    return result
