"""PDF 文本块抽取与排版信息分析。

目标：把 PDF 里的英文按“可读段落 / 行块”切出来，同时保留
位置(rect)、字号(size)、字体(font)、行距(lineheight)、旋转(rotation)等信息，
以便翻译后可以原位写回，版式不变。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Block:
    """页面上一个待翻译的文本块。"""

    page: int                 # 0 基页码
    index: int                # 页内序号
    rect: fitz.Rect           # 原始包围盒
    text: str                 # 原始英文文本
    font: str = "helv"        # 写回时使用的字体名（回退默认）
    fontname: str = ""        # 原 PDF 中的字体名，用于展示
    fontfile: Optional[str] = None   # 原 PDF 内嵌字体文件（若抽取成功）
    size: float = 10.0
    lineheight: float = 12.0
    rotation: int = 0
    color: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    lines: List[str] = field(default_factory=list)      # 原始各行文本
    line_rects: List[Tuple[float, float, float, float]] = field(default_factory=list)
    align: int = 0            # 0=左对齐 1=居中 2=右对齐 3=两端对齐
    first_baseline: Optional[float] = None   # 首行基线 y
    left: Optional[float] = None             # 文本左边界

    translation: Optional[str] = None
    status: str = "pending"   # pending / translating / done / error / skipped
    quality: str = ""         # glossary / memory / fuzzy / demo / mt / manual
    error: str = ""

    @property
    def key(self) -> str:
        return f"{self.page}:{self.index}"

    @property
    def display_original(self) -> str:
        return self.text

    @property
    def display_translation(self) -> str:
        return self.translation if self.translation else ""


@dataclass
class PageInfo:
    number: int
    width: float
    height: float
    blocks: List[Block] = field(default_factory=list)


@dataclass
class DocInfo:
    path: str
    pages: List[PageInfo] = field(default_factory=list)

    @property
    def total_blocks(self) -> int:
        return sum(len(p.blocks) for p in self.pages)

    @property
    def translated_blocks(self) -> int:
        return sum(
            1
            for p in self.pages
            for b in p.blocks
            if b.status in ("done", "skipped")
        )

    def all_blocks(self) -> Iterable[Block]:
        for page in self.pages:
            for block in page.blocks:
                yield block


# --------------------------------------------------------------------------- #
# 过滤规则
# --------------------------------------------------------------------------- #
# 只有数字/符号/公式片段的内容不值得翻译
_MEANINGLESS = re.compile(r"^[\W\d_]+$", re.UNICODE)
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_LETTERS = re.compile(r"[A-Za-z]")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")

# 不需要翻译的短标签
_SKIP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "by", "for",
    "figure", "fig", "table", "page", "eq", "equation", "http", "https", "www",
}


def contains_cjk(text: str) -> bool:
    return bool(_CJK.search(text))


def cjk_ratio(text: str) -> float:
    letters = [ch for ch in text if not ch.isspace()]
    if not letters:
        return 0.0
    return len(_CJK.findall(text)) / len(letters)


_CJK_TARGETS = {"zh-CN", "zh-TW", "ja", "ko"}


def is_translatable(text: str, target_lang: str = "zh-CN") -> bool:
    """判断一段文本是否值得送去翻译。

    默认产品路径是拉丁文字 → 中文；如果目标语言不是 CJK，则保留中文原文，
    这样也支持带文字层的中文 PDF 翻译成英文（需在设置里指定源语言）。
    """
    t = (text or "").strip()
    if len(t) < 2:
        return False
    if _MEANINGLESS.match(t):
        return False
    cjk_chars = _CJK.findall(t)
    if cjk_ratio(t) >= 0.35:
        if target_lang in _CJK_TARGETS:
            return False
        return len(cjk_chars) >= 2
    letters = _LETTERS.findall(t)
    # 至少要有两个字母（如 "H. R. Rocha" 这类作者行也要翻译）
    if len(letters) < 2:
        return False
    if not _LATIN_WORD.search(t) and len(letters) < 6:
        return False
    if t.lower() in _SKIP_WORDS:
        return False
    return True


# --------------------------------------------------------------------------- #
# 抽取
# --------------------------------------------------------------------------- #
_FONT_SUBSET = re.compile(r"^[A-Z]{6}\+")


def _clean_font_name(name: str) -> str:
    return _FONT_SUBSET.sub("", name or "").strip()


def resolve_builtin_font(name: str) -> str:
    """把 PDF 里的字体名映射成 PyMuPDF 的内置字体名，失败则回退 helv。"""
    if not name:
        return "helv"
    try:
        return fitz.Font(name).name
    except Exception:
        pass
    lowered = name.lower()
    family_map = (
        (("times", "serif", "georgia", "cambria", "garamond", "minion", "charis", "book"),
         ("times-roman", "times-bold", "times-italic", "times-bolditalic")),
        (("courier", "mono", "consol", "menlo"), ("cour", "cobo", "coit", "cobi")),
        (("symbol",), ("symb",)),
    )
    for keys, candidates in family_map:
        if any(key in lowered for key in keys):
            for candidate in candidates:
                try:
                    return fitz.Font(candidate).name
                except Exception:
                    continue
    return "helv"


def _dominant_font(spans: Sequence[dict]) -> Tuple[str, float, Tuple[float, float, float]]:
    """按字符数加权，取出现最多的字体与字号、颜色。"""
    weight: dict = {}
    size_w: dict = {}
    color_w: dict = {}
    for span in spans:
        text = span.get("text", "")
        n = max(len(text.strip()), 1)
        fname = span.get("font", "")
        weight[fname] = weight.get(fname, 0) + n
        size_w[fname] = size_w.get(fname, 0.0) + float(span.get("size", 0.0)) * n
        color_w[fname] = span.get("color", 0)
    if not weight:
        return "", 0.0, (0, 0, 0)
    fname = max(weight, key=lambda k: weight[k])
    size = size_w[fname] / max(weight[fname], 1)
    color_int = color_w[fname]
    color = (
        ((color_int >> 16) & 255) / 255.0,
        ((color_int >> 8) & 255) / 255.0,
        (color_int & 255) / 255.0,
    )
    return _clean_font_name(fname), size, color


def _join_line_texts(line_texts: Sequence[str]) -> str:
    """把换行拼接成段落：英文行尾缺空格时补空格，中文直接连。"""
    parts: List[str] = []
    for raw in line_texts:
        text = raw.strip()
        if not text:
            continue
        if not parts:
            parts.append(text)
            continue
        prev = parts[-1]
        prev_ch = prev[-1]
        cur_ch = text[0]
        prev_cjk = bool(_CJK.match(prev_ch))
        cur_cjk = bool(_CJK.match(cur_ch))
        # 拉丁 ↔ 拉丁：补空格；中文 ↔ 中文：不补；跨语种：补空格跑偏概率低，统一补
        if prev.endswith("-") and cur_ch.islower() and not prev_cjk:
            parts[-1] = prev[:-1] + text          # 断词连字符还原
        elif prev_cjk and cur_cjk:
            parts.append(text)
        else:
            parts.append(" " + text if not prev.endswith(" ") else text)
    return re.sub(r"[ \t]{2,}", " ", "".join(parts)).strip()


def _join_spans(spans: Sequence[dict]) -> str:
    """把同一行的多个 span 拼成一句话，智能补空格。"""
    out = ""
    prev_end: Optional[float] = None
    prev_size = 10.0
    for span in spans:
        text = span.get("text", "")
        if not text:
            continue
        x0 = float(span.get("bbox", (0, 0, 0, 0))[0])
        size = float(span.get("size", 10.0)) or 10.0
        if out and not out.endswith(" ") and not text.startswith(" "):
            gap = x0 - (prev_end if prev_end is not None else x0)
            # 字距间隙大于约半个字符宽度时，认为中间应有空格
            if gap > max(prev_size, size) * 0.18:
                out += " "
        out += text
        prev_end = float(span.get("bbox", (0, 0, 0, 0))[2])
        prev_size = size
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def _rotation_of(line: dict, span: dict) -> int:
    direction = line.get("dir", (1.0, 0.0))
    angle = 0
    try:
        import math

        angle = int(round(math.degrees(math.atan2(-direction[1], direction[0]))))
    except Exception:
        angle = 0
    if angle == 0:
        return 0
    # 归一到{0,90,180,270}
    for candidate in (0, 90, 180, 270):
        if abs(((angle - candidate + 180) % 360) - 180) <= 15:
            return candidate
    return 0


def _align_of(block_rect: fitz.Rect, line_rects: Sequence[fitz.Rect], page_width: float) -> int:
    """粗略判断对齐方式：居中 / 右对齐 / 左对齐。"""
    centers = [(r.x0 + r.x1) / 2 for r in line_rects]
    if len(centers) >= 2:
        spread = max(centers) - min(centers)
        tolerance = max(2.0, block_rect.width * 0.03)
        if spread <= tolerance:
            return 1
    if abs(block_rect.x1 - page_width) < page_width * 0.06 and block_rect.x0 > page_width * 0.25:
        return 2
    return 0


def _try_extract_font_file(doc: "fitz.Document", xref: int, cache: dict) -> Optional[str]:
    """尝试把 PDF 内嵌字体抽成临时文件，用于原位写回时保持字形一致。"""
    if xref in cache:
        return cache[xref]
    path: Optional[str] = None
    try:
        name, ext, _type, content = doc.extract_font(xref)
        if content and ext in ("ttf", "otf", "cff"):
            import os
            import tempfile

            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name or "font")
            fd, path = tempfile.mkstemp(prefix="pdftr_", suffix="." + ext)
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
            cache[xref] = path
    except Exception:
        path = None
    cache.setdefault(xref, path)
    return path


@dataclass
class _Candidate:
    """抽取过程中的一行 / 一组行，稍后会按版面合并成段落。"""

    rect: fitz.Rect
    line_texts: List[str]
    line_rects: List[fitz.Rect]
    font: str
    fontname: str
    fontfile: Optional[str]
    size: float
    color: Tuple[float, float, float]
    rotation: int
    first_baseline: Optional[float]
    left: Optional[float]
    weight: int
    block_id: int = 0

    @property
    def text(self) -> str:
        return _join_line_texts(self.line_texts)


def _candidates_from_block(
    doc: "fitz.Document", blk: dict, font_cache: dict, block_id: int = 0
) -> List[_Candidate]:
    """把原始 block 拆到“行”粒度。

    PDF 的 dict block 有时会把左右两栏的标题塞进同一个 block，直接按 block
    翻译会串栏。先统一拆成行，再按几何关系重新拼段落，能得到更可靠的段落边界。
    """
    result: List[_Candidate] = []
    for line in blk.get("lines", []):
        spans = line.get("spans", [])
        ltext = _join_spans(spans)
        if not ltext.strip() or not spans:
            continue
        fname, size, color = _dominant_font(spans)
        if size <= 0:
            size = 10.0
        rect = fitz.Rect(line.get("bbox", (0, 0, 0, 0)))
        if rect.width < 0.5 or rect.height < 0.5:
            continue
        rotation = _rotation_of(line, spans[0])
        first_span = spans[0]
        origin = first_span.get("origin")
        fontfile = None
        if first_span.get("xref"):
            fontfile = _try_extract_font_file(doc, int(first_span["xref"]), font_cache)
        result.append(_Candidate(
            rect=rect,
            line_texts=[ltext],
            line_rects=[rect],
            font=resolve_builtin_font(fname),
            fontname=fname,
            fontfile=fontfile,
            size=size,
            color=color,
            rotation=rotation,
            first_baseline=float(origin[1]) if origin else None,
            left=float(origin[0]) if origin else None,
            weight=max(1, len(ltext)),
            block_id=block_id,
        ))
    return result


def _median_line_gap(candidate: _Candidate) -> Optional[float]:
    """一组行已经建立的典型行距；只有一行时还没有参考值。"""
    if len(candidate.line_rects) < 2:
        return None
    rects = sorted(candidate.line_rects, key=lambda r: r.y0)
    gaps = [
        max(0.0, rects[i + 1].y0 - rects[i].y1)
        for i in range(len(rects) - 1)
    ]
    gaps.sort()
    return gaps[len(gaps) // 2]


def _merge_line_candidates(candidates: Sequence[_Candidate]) -> List[_Candidate]:
    """把被 PDF 拆成一行一个 block 的正文重新拼成段落。

    很多导出工具（Word、InDesign、LaTeX）会把每一行文字写成独立的 text block，
    如果直接按 block 翻译，就会一句一断、上下文全丢。这里用几何位置把
    “同栏、同字号、行距连续”的行合并；跨栏、跨标题层级不会误合并。
    """
    normal = sorted(
        [c for c in candidates if c.rotation == 0],
        key=lambda c: (round(c.rect.y0, 1), c.rect.x0),
    )
    rotated = [c for c in candidates if c.rotation != 0]
    groups: List[_Candidate] = []

    for cand in normal:
        best: Optional[_Candidate] = None
        best_gap = 1e9
        for group in groups:
            group_size = group.size
            cand_size = cand.size
            min_size = min(group_size, cand_size)
            if max(group_size, cand_size) > min_size * 1.12 + 0.35:
                continue
            same_block = group.block_id == cand.block_id
            gap = cand.rect.y0 - group.rect.y1
            # 紧凑行距（leading < 1.0）时两行 bbox 会轻微重叠，不能因此拒绝合并。
            if gap < -max(1.8, min_size * 0.42):
                continue
            # PDF 的一个大 text block 里，行距可能很松；不能再按固定 0.66em 切碎。
            max_gap = max(4.0, min_size * (4.5 if same_block else 3.2))
            if gap > max_gap:
                continue
            typical = _median_line_gap(group)
            if typical is not None:
                # 用这一组已经建立的行距节奏判断“换段”：同一段内应基本一致。
                allowed = max(
                    typical * (1.9 if same_block else 1.6),
                    typical + min_size * (1.3 if same_block else 0.9),
                    4.0,
                )
                if gap > allowed:
                    continue
            overlap = min(group.rect.x1, cand.rect.x1) - max(group.rect.x0, cand.rect.x0)
            min_width = max(1.0, min(group.rect.width, cand.rect.width))
            if overlap / min_width < 0.55:
                continue
            left_diff = abs(cand.rect.x0 - group.rect.x0)
            center_diff = abs(
                (cand.rect.x0 + cand.rect.x1) / 2 - (group.rect.x0 + group.rect.x1) / 2
            )
            # 首行缩进、悬挂缩进、引文缩进不应把整段拆开。
            if left_diff > max(18.0, min_size * 3.2) and center_diff > max(
                14.0, min_size * 2.0
            ):
                continue
            if gap < best_gap:
                best_gap = gap
                best = group
        if best is None:
            groups.append(cand)
            continue

        total_weight = max(1, best.weight + cand.weight)
        best.rect |= cand.rect
        best.line_texts.extend(cand.line_texts)
        best.line_rects.extend(cand.line_rects)
        best.size = (
            best.size * best.weight + cand.size * cand.weight
        ) / total_weight
        best.weight = total_weight
        if cand.fontfile and not best.fontfile:
            best.fontfile = cand.fontfile
        if not best.fontname and cand.fontname:
            best.fontname = cand.fontname
            best.font = cand.font
        best.block_id = cand.block_id

    result: List[_Candidate] = []
    for group in groups + rotated:
        pairs = sorted(
            zip(group.line_rects, group.line_texts),
            key=lambda pair: (round(pair[0].y0, 1), pair[0].x0),
        )
        if not pairs:
            continue
        group.line_rects = [p[0] for p in pairs]
        group.line_texts = [p[1] for p in pairs]
        group.rect = fitz.Rect(group.line_rects[0])
        for rect in group.line_rects[1:]:
            group.rect |= rect
        result.append(group)
    result.sort(key=lambda c: (round(c.rect.y0, 1), c.rect.x0))
    return result


def extract_document(path: str, target_lang: str = "zh-CN") -> DocInfo:
    """抽取整份 PDF 的可翻译文本块（按版面把逐行 block 合并为段落）。"""
    doc = fitz.open(path)
    info = DocInfo(path=path)
    font_cache: dict = {}
    try:
        for pno in range(doc.page_count):
            page = doc[pno]
            page_rect = page.rect
            pinfo = PageInfo(number=pno, width=page_rect.width, height=page_rect.height)
            raw = page.get_text(
                "dict",
                flags=fitz.TEXTFLAGS_DICT | fitz.TEXT_PRESERVE_WHITESPACE,
            )
            candidates: List[_Candidate] = []
            for block_id, blk in enumerate(raw.get("blocks", [])):
                if blk.get("type", 0) != 0:
                    continue  # 图片块跳过
                candidates.extend(
                    _candidates_from_block(doc, blk, font_cache, block_id=block_id)
                )

            idx = 0
            for candidate in _merge_line_candidates(candidates):
                block_text = candidate.text
                if not is_translatable(block_text, target_lang):
                    continue
                line_rects = candidate.line_rects
                lineheight = candidate.size * 1.2
                if len(line_rects) >= 2:
                    gaps = [
                        abs(line_rects[i + 1].y0 - line_rects[i].y0)
                        for i in range(len(line_rects) - 1)
                    ]
                    gaps = [gap for gap in gaps if gap > 0.5]
                    if gaps:
                        gaps.sort()
                        lineheight = gaps[len(gaps) // 2]
                if lineheight < candidate.size * 0.9:
                    lineheight = candidate.size * 1.2
                block = Block(
                    page=pno,
                    index=idx,
                    rect=candidate.rect,
                    text=block_text,
                    font=candidate.font,
                    fontname=candidate.fontname,
                    fontfile=candidate.fontfile,
                    size=candidate.size,
                    lineheight=lineheight,
                    rotation=candidate.rotation,
                    color=candidate.color,
                    lines=candidate.line_texts,
                    line_rects=[tuple(rect) for rect in line_rects],
                    align=_align_of(candidate.rect, line_rects, page_rect.width),
                    first_baseline=candidate.first_baseline,
                    left=candidate.left,
                )
                pinfo.blocks.append(block)
                idx += 1
            info.pages.append(pinfo)
    finally:
        doc.close()
    return info


def cleanup_font_files(blocks: Iterable[Block]) -> None:
    """删除抽取字体时产生的临时文件。"""
    import os

    for block in blocks:
        if block.fontfile and os.path.exists(block.fontfile):
            try:
                os.remove(block.fontfile)
            except OSError:
                pass
