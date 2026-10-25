"""翻译流水线：本地库优先 → 国内翻译服务 → 自动沉淀记忆库。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from .extract import Block, DocInfo
from .library import DemoMemory, Lookup, TranslationLibrary
from .providers import BaseProvider, ProviderError, create_provider


@dataclass
class TranslationSummary:
    total: int = 0
    translated: int = 0
    library_hits: int = 0
    demo_hits: int = 0
    machine: int = 0
    misses: int = 0
    errors: int = 0
    skipped: int = 0
    pages_total: int = 0
    pages_done: int = 0
    cancelled: bool = False
    last_error: str = ""
    elapsed: float = 0.0

    @property
    def processed(self) -> int:
        return self.translated + self.misses + self.errors


BlockCallback = Callable[[int, int, str, str, str, str], None]
PageCallback = Callable[[int, int, int], None]
ProgressCallback = Callable[[int, int, int, int], None]


class TranslationPipeline:
    """可取消的同步翻译流水线，由工作线程调用。

    on_block(page, index, translation, status, quality, error)
        status: done / error / miss
        quality: glossary / memory / fuzzy / demo / mt
    on_page(page, processed, total)
    on_progress(processed_blocks, total_blocks, pages_done, total_pages)
    """

    def __init__(
        self,
        doc: DocInfo,
        library: TranslationLibrary,
        demo: DemoMemory,
        engine: str,
        source_lang: str,
        target_lang: str,
        provider_options: Dict,
        use_library: bool = True,
        auto_save: bool = True,
        fuzzy_threshold: float = 0.84,
        page_numbers: Optional[Sequence[int]] = None,
        demo_path: str = "",
        on_block: Optional[BlockCallback] = None,
        on_page: Optional[PageCallback] = None,
        on_progress: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        self.doc = doc
        self.library = library
        self.demo = demo
        self.engine = engine
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.provider_options = provider_options
        self.use_library = use_library
        self.auto_save = auto_save
        self.fuzzy_threshold = fuzzy_threshold
        self.demo_path = demo_path
        self.on_block = on_block
        self.on_page = on_page
        self.on_progress = on_progress
        self.cancel_event = cancel_event or threading.Event()
        self.page_numbers = set(page_numbers) if page_numbers else None
        self.summary = TranslationSummary()
        self.provider: Optional[BaseProvider] = None
        self._processed = 0
        self._total_blocks = 0

    # ------------------------------------------------------------------ #
    def _cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def _selected_pages(self):
        for page in self.doc.pages:
            if self.page_numbers is None or page.number in self.page_numbers:
                yield page

    def _notify_progress(self) -> None:
        if self.on_progress:
            try:
                self.on_progress(
                    self._processed, self._total_blocks,
                    self.summary.pages_done, self.summary.pages_total,
                )
            except Exception:
                pass

    def _emit(self, page_no: int, block: Block, translation: str, status: str,
              quality: str = "", error: str = "") -> None:
        if self.on_block:
            try:
                self.on_block(page_no, block.index, translation, status, quality, error)
            except Exception:
                pass
        self._processed += 1
        if status == "done":
            self.summary.translated += 1
            if quality == "demo":
                self.summary.demo_hits += 1
            elif quality == "mt":
                self.summary.machine += 1
            else:
                self.summary.library_hits += 1
        elif status == "miss":
            self.summary.misses += 1
        elif status == "error":
            self.summary.errors += 1
            self.summary.last_error = error
        self._notify_progress()

    # ------------------------------------------------------------------ #
    def run(self) -> TranslationSummary:
        started = time.time()
        pages = list(self._selected_pages())
        all_blocks = [b for page in pages for b in page.blocks]
        translatable = [b for b in all_blocks if not b.rotation]
        self._total_blocks = len(translatable)
        self.summary = TranslationSummary(
            total=self._total_blocks,
            pages_total=len(pages),
            skipped=len(all_blocks) - len(translatable),
        )
        self._processed = 0

        glossary: List = []
        if self.engine in ("llm", "bilibili") and translatable:
            try:
                glossary = self.library.glossary_hints(
                    [b.text for b in translatable], self.source_lang, self.target_lang
                )
            except Exception:
                glossary = []
        if self.engine != "demo" and translatable:
            self.provider = create_provider(
                self.engine, self.provider_options, self.source_lang,
                self.target_lang, glossary=glossary, demo_path=self.demo_path,
            )
        try:
            for page in pages:
                if self._cancelled():
                    self.summary.cancelled = True
                    break
                page_processed_before = self._processed
                page_total = len([b for b in page.blocks if not b.rotation])
                self._translate_page(page)
                self.summary.pages_done += 1
                if self.on_page:
                    try:
                        self.on_page(
                            page.number, self._processed - page_processed_before,
                            page_total,
                        )
                    except Exception:
                        pass
                self._notify_progress()
                if self._cancelled():
                    self.summary.cancelled = True
                    break
        finally:
            if self.provider is not None:
                self.provider.close()
            self.summary.elapsed = time.time() - started
        return self.summary

    # ------------------------------------------------------------------ #
    def _lookup_library(self, block: Block) -> Optional[Lookup]:
        if not self.use_library:
            return None
        try:
            return self.library.lookup(
                block.text, self.source_lang, self.target_lang,
                fuzzy_threshold=self.fuzzy_threshold,
            )
        except Exception:
            return None

    def _translate_page(self, page) -> None:
        pending: List[Block] = []
        for block in page.blocks:
            if self._cancelled():
                return
            if block.rotation:
                continue
            hit = self._lookup_library(block)
            if hit is None and self.engine == "demo":
                hit = self.demo.lookup(block.text)
            if hit is not None:
                self._emit(
                    page.number, block, hit.target, "done",
                    hit.kind if hit.kind != "memory" else "memory",
                )
                continue
            if self.engine == "demo":
                self._emit(
                    page.number, block, "", "miss", "",
                    "本地库暂无这段译文",
                )
                continue
            pending.append(block)

        if not pending or self._cancelled():
            return

        texts = [block.text for block in pending]
        try:
            assert self.provider is not None
            results = self.provider.translate_many(texts)
        except ProviderError as exc:
            self._mark_pending(page.number, pending, str(exc))
            return
        except Exception as exc:
            self._mark_pending(page.number, pending, f"翻译失败：{exc}")
            return

        if len(results) != len(pending):
            self._mark_pending(page.number, pending, "翻译服务返回数量异常")
            return

        for block, translated in zip(pending, results):
            if self._cancelled():
                return
            translated = (translated or "").strip()
            if not translated:
                self._emit(
                    page.number, block, "", "miss", "",
                    "翻译服务返回空译文",
                )
                continue
            self._emit(page.number, block, translated, "done", "mt")
            if self.auto_save:
                try:
                    self.library.remember(
                        block.text, translated, self.source_lang,
                        self.target_lang, engine=self.engine, quality="mt",
                    )
                except Exception:
                    pass

    def _mark_pending(self, page_no: int, blocks: Sequence[Block], error: str) -> None:
        for block in blocks:
            self._emit(page_no, block, "", "error", "", error)
