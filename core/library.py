"""本地翻译库：SQLite 术语库 + 翻译记忆库。

- 术语库（glossary）：用户维护的专有名词，优先生效。
- 记忆库（memory）：每一条确认过的译文都会沉淀下来，下次同文或近似文本
  （模糊匹配）可直接复用。它既是“自己的翻译库”，也是离线缓存。
"""

from __future__ import annotations

import csv
import difflib
import json
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import LIBRARY_PATH


def normalize_text(text: str) -> str:
    text = (text or "").replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Lookup:
    target: str
    kind: str               # glossary / memory / fuzzy / demo
    score: float = 1.0
    engine: str = ""
    source: str = ""

    @property
    def label(self) -> str:
        return {
            "glossary": "术语库",
            "memory": "记忆库",
            "fuzzy": "模糊匹配",
            "demo": "演示库",
        }.get(self.kind, self.kind)


class DemoMemory:
    """随应用附带的只读演示语料，用于无网络时展示完整效果。"""

    def __init__(self, path: str):
        self.path = path
        self.entries: List[Dict[str, str]] = []
        self._exact: Dict[str, str] = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.entries = list(data.get("entries", []))
        except Exception:
            self.entries = []
        self._exact = {
            normalize_text(item.get("source", "")): item.get("target", "")
            for item in self.entries
            if item.get("source") and item.get("target")
        }

    def lookup(self, text: str) -> Optional[Lookup]:
        target = self._exact.get(normalize_text(text))
        if target:
            return Lookup(target=target, kind="demo", score=1.0, engine="demo", source=text)
        return None

    def __len__(self) -> int:
        return len(self._exact)


class TranslationLibrary:
    def __init__(self, path: str = LIBRARY_PATH):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=20)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._create_schema()

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS glossary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    source_lang TEXT NOT NULL DEFAULT 'en',
                    target_lang TEXT NOT NULL DEFAULT 'zh-CN',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source, source_lang, target_lang)
                );

                CREATE TABLE IF NOT EXISTS memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    source_norm TEXT NOT NULL,
                    target TEXT NOT NULL,
                    source_lang TEXT NOT NULL DEFAULT 'en',
                    target_lang TEXT NOT NULL DEFAULT 'zh-CN',
                    engine TEXT NOT NULL DEFAULT '',
                    quality TEXT NOT NULL DEFAULT 'mt',
                    hits INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_norm, source_lang, target_lang)
                );

                CREATE INDEX IF NOT EXISTS idx_memory_pair
                    ON memory(source_lang, target_lang);
                CREATE INDEX IF NOT EXISTS idx_glossary_pair
                    ON glossary(source_lang, target_lang);
                """
            )

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def lookup(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        fuzzy_threshold: float = 0.0,
        mark_hit: bool = True,
    ) -> Optional[Lookup]:
        norm = normalize_text(text)
        if not norm:
            return None
        src = "auto" if not source_lang else source_lang
        memory_clause = "" if src == "auto" else "AND (source_lang=? OR source_lang='auto')"
        glossary_clause = "" if src == "auto" else "AND (source_lang=? OR source_lang='auto')"
        memory_params: Tuple[Any, ...] = (norm, target_lang)
        if src != "auto":
            memory_params += (src, src)
        glossary_params: Tuple[Any, ...] = (text.strip(), target_lang)
        if src != "auto":
            glossary_params += (src,)
        with self._lock:
            row = self._conn.execute(
                f"""
                SELECT target, note FROM glossary
                WHERE source=? COLLATE NOCASE AND target_lang=? {glossary_clause}
                ORDER BY length(source) DESC
                LIMIT 1
                """,
                glossary_params,
            ).fetchone()
            if row and row["target"]:
                return Lookup(target=row["target"], kind="glossary", engine="glossary",
                              source=text)

            row = self._conn.execute(
                f"""
                SELECT target, engine, quality FROM memory
                WHERE source_norm=? AND target_lang=? {memory_clause}
                ORDER BY quality='manual' DESC, updated_at DESC
                LIMIT 1
                """,
                memory_params,
            ).fetchone()
            if row and row["target"]:
                if mark_hit:
                    self._touch_memory(norm, src, target_lang)
                return Lookup(
                    target=row["target"], kind="memory", score=1.0,
                    engine=row["engine"] or "", source=text,
                )

            if fuzzy_threshold and fuzzy_threshold < 1.0:
                best = self._fuzzy_lookup(norm, src, target_lang, fuzzy_threshold)
                if best:
                    if mark_hit:
                        self._touch_memory(best[2], src, target_lang)
                    return Lookup(
                        target=best[1], kind="fuzzy", score=best[0],
                        engine=best[3] or "", source=text,
                    )
        return None

    def _fuzzy_lookup(
        self, norm: str, source_lang: str, target_lang: str, threshold: float
    ) -> Optional[Tuple[float, str, str, str]]:
        if len(norm) < 8:
            return None
        lang_clause = "" if source_lang == "auto" else "AND (source_lang=? OR source_lang='auto')"
        params: Tuple[Any, ...] = (target_lang,)
        if source_lang != "auto":
            params += (source_lang,)
        params += (int(len(norm) * 0.55), int(len(norm) * 1.8) + 1)
        rows = self._conn.execute(
            f"""
            SELECT source_norm, target, engine FROM memory
            WHERE target_lang=? {lang_clause}
              AND length(source_norm) BETWEEN ? AND ?
            ORDER BY updated_at DESC LIMIT 2500
            """,
            params,
        ).fetchall()
        best_score = 0.0
        best: Optional[Tuple[float, str, str, str]] = None
        for row in rows:
            candidate = row["source_norm"] or ""
            if not candidate:
                continue
            # 先用首字母和长度粗筛，避免大库做全量 SequenceMatcher
            if candidate[:1] != norm[:1]:
                continue
            score = difflib.SequenceMatcher(None, norm, candidate).ratio()
            if score > best_score:
                best_score = score
                best = (score, row["target"], candidate, row["engine"] or "")
        if best and best_score >= threshold:
            return best
        return None

    def _touch_memory(self, norm: str, source_lang: str, target_lang: str) -> None:
        lang_clause = "" if source_lang == "auto" else "AND (source_lang=? OR source_lang='auto')"
        params: Tuple[Any, ...] = (now_iso(), norm, target_lang)
        if source_lang != "auto":
            params += (source_lang,)
        with self._lock, self._conn:
            self._conn.execute(
                f"""
                UPDATE memory SET hits=hits+1, updated_at=?
                WHERE source_norm=? AND target_lang=? {lang_clause}
                """,
                params,
            )

    def glossary_hints(
        self, texts: Sequence[str], source_lang: str, target_lang: str, limit: int = 60
    ) -> List[Tuple[str, str]]:
        """挑出当前页面真正出现的术语，供大模型提示使用。"""
        joined = "\n".join(texts).casefold()
        lang_clause = "" if source_lang == "auto" else "AND (source_lang=? OR source_lang='auto')"
        params: Tuple[Any, ...] = (target_lang,)
        if source_lang != "auto":
            params += (source_lang,)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT source, target FROM glossary
                WHERE target_lang=? {lang_clause}
                ORDER BY length(source) DESC LIMIT 500
                """,
                params,
            ).fetchall()
        result = []
        for row in rows:
            source = row["source"]
            if source and source.casefold() in joined:
                result.append((source, row["target"]))
            if len(result) >= limit:
                break
        return result

    # ------------------------------------------------------------------ #
    # 写入
    # ------------------------------------------------------------------ #
    def remember(
        self,
        source: str,
        target: str,
        source_lang: str,
        target_lang: str,
        engine: str = "",
        quality: str = "mt",
        overwrite: bool = False,
    ) -> None:
        norm = normalize_text(source)
        if not norm or not (target or "").strip():
            return
        src = source_lang or "auto"
        with self._lock, self._conn:
            existing = self._conn.execute(
                """
                SELECT id, quality FROM memory
                WHERE source_norm=? AND source_lang=? AND target_lang=?
                """,
                (norm, src, target_lang),
            ).fetchone()
            if existing:
                if overwrite:
                    self._conn.execute(
                        """
                        UPDATE memory SET source=?, target=?, engine=?, quality=?,
                            hits=hits+1, updated_at=? WHERE id=?
                        """,
                        (source.strip(), target.strip(), engine, quality, now_iso(),
                         existing["id"]),
                    )
                else:
                    self._conn.execute(
                        "UPDATE memory SET hits=hits+1, updated_at=? WHERE id=?",
                        (now_iso(), existing["id"]),
                    )
            else:
                self._conn.execute(
                    """
                    INSERT INTO memory
                        (source, source_norm, target, source_lang, target_lang,
                         engine, quality, hits, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (source.strip(), norm, target.strip(), src, target_lang,
                     engine, quality, now_iso(), now_iso()),
                )

    def upsert_glossary(
        self,
        source: str,
        target: str,
        source_lang: str = "en",
        target_lang: str = "zh-CN",
        note: str = "",
    ) -> int:
        source = (source or "").strip()
        target = (target or "").strip()
        if not source or not target:
            raise ValueError("术语原文和译文不能为空")
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO glossary
                    (source, target, source_lang, target_lang, note,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, source_lang, target_lang) DO UPDATE SET
                    target=excluded.target, note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (source, target, source_lang, target_lang, note, now_iso(), now_iso()),
            )
            row = self._conn.execute(
                """
                SELECT id FROM glossary
                WHERE source=? AND source_lang=? AND target_lang=?
                """,
                (source, source_lang, target_lang),
            ).fetchone()
            return int(row["id"]) if row else 0

    def delete_glossary(self, entry_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM glossary WHERE id=?", (entry_id,))

    def delete_memory(self, entry_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM memory WHERE id=?", (entry_id,))

    def clear_memory(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM memory")

    # ------------------------------------------------------------------ #
    # 列表与导入导出
    # ------------------------------------------------------------------ #
    def list_glossary(
        self, search: str = "", source_lang: str = "", target_lang: str = "",
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if search:
            clauses.append("(source LIKE ? OR target LIKE ? OR note LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])
        if source_lang:
            clauses.append("source_lang=?")
            params.append(source_lang)
        if target_lang:
            clauses.append("target_lang=?")
            params.append(target_lang)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT * FROM glossary {where}
                    ORDER BY updated_at DESC LIMIT ?""",
                (*params, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_memory(
        self, search: str = "", target_lang: str = "", limit: int = 500
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if search:
            clauses.append("(source LIKE ? OR target LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])
        if target_lang:
            clauses.append("target_lang=?")
            params.append(target_lang)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT * FROM memory {where}
                    ORDER BY updated_at DESC LIMIT ?""",
                (*params, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            glossary = self._conn.execute("SELECT COUNT(*) c FROM glossary").fetchone()["c"]
            memory = self._conn.execute("SELECT COUNT(*) c FROM memory").fetchone()["c"]
            hits = self._conn.execute("SELECT COALESCE(SUM(hits),0) h FROM memory").fetchone()["h"]
        size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        return {"glossary": glossary, "memory": memory, "hits": hits, "size": size}

    def export_glossary_csv(self, path: str) -> int:
        rows = self.list_glossary(limit=100000)
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["source", "target", "source_lang", "target_lang", "note"])
            for row in rows:
                writer.writerow([
                    row["source"], row["target"], row["source_lang"],
                    row["target_lang"], row["note"],
                ])
        return len(rows)

    def export_memory_csv(self, path: str) -> int:
        rows = self.list_memory(limit=100000)
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["source", "target", "source_lang", "target_lang", "engine"])
            for row in rows:
                writer.writerow([
                    row["source"], row["target"], row["source_lang"],
                    row["target_lang"], row["engine"],
                ])
        return len(rows)

    def import_glossary_csv(self, path: str, source_lang: str = "en",
                            target_lang: str = "zh-CN") -> int:
        count = 0
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            first_line = sample.splitlines()[0].lower() if sample else ""
            has_header = "source" in first_line or "原文" in first_line
            reader = csv.reader(handle)
            if has_header:
                next(reader, None)
            for row in reader:
                if len(row) < 2 or not row[0].strip() or not row[1].strip():
                    continue
                src_lang = row[2].strip() if len(row) > 2 and row[2].strip() else source_lang
                dst_lang = row[3].strip() if len(row) > 3 and row[3].strip() else target_lang
                note = row[4].strip() if len(row) > 4 else ""
                self.upsert_glossary(row[0], row[1], src_lang, dst_lang, note)
                count += 1
        return count

    def backup_to(self, destination: str) -> str:
        """把当前库完整复制到目标文件，用于更换存储位置。"""
        destination = os.path.abspath(destination)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        temp = destination + ".tmp"
        try:
            if os.path.exists(temp):
                os.remove(temp)
        except OSError:
            pass
        target = sqlite3.connect(temp)
        try:
            with self._lock:
                self._conn.backup(target)
        finally:
            target.close()
        os.replace(temp, destination)
        return destination

    def close(self) -> None:
        with self._lock:
            self._conn.close()
