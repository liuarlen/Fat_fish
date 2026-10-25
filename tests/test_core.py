"""核心逻辑测试：抽取、本地库、流水线、写回、服务签名辅助。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import fitz

from core.config import AppConfig, LIBRARY_PATH
from core.extract import extract_document, is_translatable
from core.library import DemoMemory, TranslationLibrary, normalize_text
from core.pipeline import TranslationPipeline
from core.providers import (
    AliyunProvider, BilibiliProvider, GoogleProvider, LLMProvider,
    TencentProvider, YoudaoProvider, create_provider,
    translate_batch_resilient,
)
from core.render import render_document


SAMPLE = os.path.join(HERE, "resources", "demo", "sample.pdf")
DEMO = os.path.join(HERE, "resources", "demo", "demo_library.json")


class ExtractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = extract_document(SAMPLE)

    def test_pages_and_blocks(self):
        self.assertEqual(len(self.doc.pages), 2)
        self.assertEqual(self.doc.total_blocks, 30)
        # 标题的三行应该被合并成一个段落，而不是三个 block
        first = self.doc.pages[0].blocks[3]
        self.assertIn("Designing Calm Technology", first.text)
        self.assertEqual(len(first.lines), 3)

    def test_two_columns_not_merged(self):
        page = self.doc.pages[0]
        heads = [b.text for b in page.blocks if b.text in ("The attention tax", "A quieter interface")]
        self.assertEqual(len(heads), 2)

    def test_is_translatable(self):
        self.assertTrue(is_translatable("A city feels calm."))
        self.assertFalse(is_translatable("1234 / 5678"))
        self.assertFalse(is_translatable("这是中文内容，不需要再翻译。"))
        self.assertFalse(is_translatable("这是中文内容，目标也是中文。", "zh-CN"))
        self.assertTrue(is_translatable("这是中文内容，需要翻译成英文。", "en"))

    def test_large_line_spacing_stays_one_block(self):
        lines = [
            "This is the first line of one continuous paragraph.",
            "It continues on the second line with more details.",
            "A third line keeps the same paragraph going.",
            "The fourth line closes this block of text.",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "double_spaced.pdf")
            doc = fitz.open()
            page = doc.new_page(width=595, height=842)
            for index, line in enumerate(lines):
                # 24pt 行距远超 0.66em，但视觉上仍是同一个大段落。
                page.insert_text((72, 100 + index * 24), line, fontsize=10, fontname="helv")
            doc.save(path)
            doc.close()
            info = extract_document(path, "zh-CN")
        self.assertEqual(info.total_blocks, 1)
        self.assertEqual(len(info.pages[0].blocks[0].lines), 4)

    def test_blank_line_still_separates_paragraphs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "paragraphs.pdf")
            doc = fitz.open()
            page = doc.new_page(width=595, height=842)
            for index, line in enumerate(("First paragraph line one.", "First paragraph line two.")):
                page.insert_text((72, 100 + index * 13), line, fontsize=10, fontname="helv")
            for index, line in enumerate(("Second paragraph line one.", "Second paragraph line two.")):
                page.insert_text((72, 160 + index * 13), line, fontsize=10, fontname="helv")
            doc.save(path)
            doc.close()
            info = extract_document(path, "zh-CN")
        self.assertEqual(info.total_blocks, 2)

    def test_chinese_source_pdf(self):
        font = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyh.ttc")
        if not os.path.exists(font):
            self.skipTest("测试机没有微软雅黑")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "zh.pdf")
            doc = fitz.open()
            page = doc.new_page(width=595, height=842)
            page.insert_text((72, 100), "这是一个中文测试文档，用来验证逆向抽取。",
                             fontname="F0", fontfile=font, fontsize=16)
            doc.save(path)
            doc.close()
            to_zh = extract_document(path, "zh-CN")
            to_en = extract_document(path, "en")
        self.assertEqual(to_zh.total_blocks, 0)
        self.assertGreaterEqual(to_en.total_blocks, 1)
        self.assertIn("中文测试文档", to_en.pages[0].blocks[0].text)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = TranslationLibrary(os.path.join(self.tmp.name, "library.sqlite"))

    def tearDown(self):
        self.lib.close()
        self.tmp.cleanup()

    def test_glossary_and_memory(self):
        self.lib.upsert_glossary("calm technology", "安静的技术", "en", "zh-CN", "核心术语")
        hit = self.lib.lookup("calm technology", "auto", "zh-CN")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.target, "安静的技术")
        self.assertEqual(hit.kind, "glossary")

        self.lib.remember("The quick brown fox jumps over the lazy dog.",
                          "敏捷的棕色狐狸跳过懒狗。", "en", "zh-CN", "test")
        hit = self.lib.lookup("The quick brown fox jumps over the lazy dog.",
                              "auto", "zh-CN")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.kind, "memory")
        stats = self.lib.stats()
        self.assertEqual(stats["glossary"], 1)
        self.assertEqual(stats["memory"], 1)
        self.assertGreaterEqual(stats["hits"], 1)

    def test_fuzzy_match(self):
        self.lib.remember(
            "Designing calm technology for the cities of tomorrow.",
            "为未来城市设计安静的技术。", "en", "zh-CN", "test",
        )
        hit = self.lib.lookup(
            "Designing calm technology for the city of tomorrow.",
            "auto", "zh-CN", fuzzy_threshold=0.75,
        )
        self.assertIsNotNone(hit)
        self.assertIn(hit.kind, ("fuzzy", "memory"))

    def test_csv_roundtrip(self):
        self.lib.upsert_glossary("PDF", "PDF 文档", "en", "zh-CN", "保留缩写")
        path = os.path.join(self.tmp.name, "glossary.csv")
        self.assertEqual(self.lib.export_glossary_csv(path), 1)
        self.lib.delete_glossary(self.lib.list_glossary()[0]["id"])
        self.assertEqual(self.lib.stats()["glossary"], 0)
        self.assertEqual(self.lib.import_glossary_csv(path), 1)
        self.assertEqual(self.lib.stats()["glossary"], 1)

    def test_normalize(self):
        self.assertEqual(normalize_text("  A  B \n C "), "a b c")

    def test_backup_to_keeps_data(self):
        self.lib.upsert_glossary("PDF", "PDF 文档", "en", "zh-CN", "备份测试")
        destination = os.path.join(self.tmp.name, "moved", "library.sqlite")
        self.lib.backup_to(destination)
        moved = TranslationLibrary(destination)
        try:
            stats = moved.stats()
            self.assertEqual(stats["glossary"], 1)
            hit = moved.lookup("PDF", "en", "zh-CN")
            self.assertIsNotNone(hit)
            self.assertEqual(hit.target, "PDF 文档")
        finally:
            moved.close()


class ConfigTests(unittest.TestCase):
    def test_provider_secret_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            config = AppConfig(path)
            config.set_provider_config("baidu", {"appid": "123", "secret": "very-secret"})
            config.save()
            with open(path, "r", encoding="utf-8") as handle:
                raw = handle.read()
            self.assertNotIn("very-secret", raw)
            reloaded = AppConfig(path)
            options = reloaded.provider_config("baidu")
            self.assertEqual(options["appid"], "123")
            self.assertEqual(options["secret"], "very-secret")

    def test_default_engine_is_free_online(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(os.path.join(tmp, "settings.json"))
            self.assertEqual(config.get("engine"), "bilibili")

    def test_custom_library_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            config = AppConfig(path)
            self.assertEqual(
                config.library_file(),
                os.path.join(os.path.dirname(LIBRARY_PATH), "library.sqlite"),
            )
            custom = os.path.join(tmp, "my-library")
            config.set("library_dir", custom)
            config.save()
            reloaded = AppConfig(path)
            self.assertEqual(reloaded.library_dir(), os.path.abspath(custom))
            self.assertEqual(
                reloaded.library_file(), os.path.join(os.path.abspath(custom), "library.sqlite")
            )


class DemoMemoryTests(unittest.TestCase):
    def test_entries(self):
        demo = DemoMemory(DEMO)
        self.assertGreaterEqual(len(demo), 29)
        hit = demo.lookup("Designing Calm Technology for the Cities of Tomorrow")
        self.assertIsNotNone(hit)
        self.assertIn("未来城市", hit.target)


class FakeProvider:
    name = "fake"

    def __init__(self, *args, **kwargs):
        self.calls = 0

    def translate_many(self, texts):
        self.calls += 1
        return [f"机器译文 {i + 1}" for i, _ in enumerate(texts)]

    def close(self):
        pass


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = TranslationLibrary(os.path.join(self.tmp.name, "library.sqlite"))
        self.doc = extract_document(SAMPLE)

    def tearDown(self):
        self.lib.close()
        self.tmp.cleanup()

    def test_demo_pipeline_complete(self):
        demo = DemoMemory(DEMO)
        events = []

        def on_block(page, index, translation, status, quality, error):
            events.append((page, index, translation, status, quality, error))
            block = self.doc.pages[page].blocks[index]
            block.translation = translation
            block.status = status

        summary = TranslationPipeline(
            self.doc, self.lib, demo, "demo", "auto", "zh-CN", {},
            on_block=on_block,
        ).run()
        self.assertEqual(summary.total, 30)
        self.assertEqual(summary.translated, 30)
        self.assertEqual(summary.misses, 0)
        self.assertEqual(len(events), 30)
        self.assertEqual(self.lib.stats()["memory"], 0)  # 演示库不写入用户记忆

    def test_online_pipeline_saves_memory(self):
        demo = DemoMemory(DEMO)
        events = []
        with patch("core.pipeline.create_provider", return_value=FakeProvider()):
            summary = TranslationPipeline(
                self.doc, self.lib, demo, "baidu", "auto", "zh-CN", {},
                on_block=lambda p, i, t, s, q, e: events.append((p, i, t, s, q, e)),
                auto_save=True,
            ).run()
        # 第二页的 "URBAN SYSTEMS LAB" 与第一页重复，会被刚写入的记忆库命中
        self.assertEqual(summary.machine, 29)
        self.assertEqual(summary.library_hits, 1)
        self.assertEqual(summary.translated, 30)
        self.assertEqual(summary.errors, 0)
        self.assertEqual(len(events), 30)
        self.assertGreater(self.lib.stats()["memory"], 0)
        self.assertTrue(all(event[3] == "done" for event in events))

    def test_render_in_place(self):
        demo = DemoMemory(DEMO)

        def on_block(page, index, translation, status, quality, error):
            block = self.doc.pages[page].blocks[index]
            block.translation = translation
            block.status = status

        TranslationPipeline(
            self.doc, self.lib, demo, "demo", "auto", "zh-CN", {},
            on_block=on_block,
        ).run()
        output = os.path.join(self.tmp.name, "out.pdf")
        result = render_document(self.doc, output, target_lang="zh-CN")
        self.assertTrue(os.path.isfile(output))
        self.assertEqual(result.pages, 2)
        self.assertEqual(result.rendered, 30)
        doc = fitz.open(output)
        try:
            self.assertEqual(doc.page_count, 2)
            text = doc[0].get_text()
            self.assertIn("城市", text)
            self.assertNotIn("Designing Calm Technology", text)
        finally:
            doc.close()


class ProviderHelperTests(unittest.TestCase):
    def test_youdao_truncate(self):
        self.assertEqual(YoudaoProvider._truncate("short"), "short")
        text = "a" * 30
        self.assertEqual(YoudaoProvider._truncate(text), "a" * 10 + "30" + "a" * 10)

    def test_llm_parse_array(self):
        self.assertEqual(LLMProvider._parse_array('["甲", "乙"]'), ["甲", "乙"])
        fenced = '```json\n["甲", "乙"]\n```'
        self.assertEqual(LLMProvider._parse_array(fenced), ["甲", "乙"])
        obj = '{"translations": ["A", "B"]}'
        self.assertEqual(LLMProvider._parse_array(obj), ["A", "B"])

    def test_bilibili_free_batch_with_fake_response(self):
        provider = create_provider("bilibili", {}, "auto", "zh-CN")
        self.assertIsInstance(provider, BilibiliProvider)
        self.assertEqual(provider.missing_fields(), [])
        fake = {
            "choices": [{"message": {"content": '["城市设计", "公共交通"]'}}]
        }
        with patch.object(provider, "_request_json", return_value=fake) as request:
            result = provider.translate_many(
                ["Designing for cities.", "Public transport."]
            )
        self.assertEqual(result, ["城市设计", "公共交通"])
        self.assertEqual(request.call_count, 1)
        provider.close()

    def test_count_mismatch_splits_and_recovers(self):
        provider = create_provider(
            "llm",
            {
                "api_key": "test",
                "base_url": "https://example.com/v1",
                "model": "test-model",
            },
            "auto",
            "zh-CN",
        )
        texts = [f"paragraph {index}" for index in range(25)]
        calls = []

        def fake_batch(batch):
            calls.append(len(batch))
            if len(batch) == 25:
                return [f"译文 {index}" for index in range(23)]
            return [f"译文 {text}" for text in batch]

        with patch.object(provider, "_request_batch", side_effect=fake_batch):
            result = provider.translate_many(texts)
        self.assertEqual(len(result), 25)
        self.assertEqual(calls[:3], [25, 12, 13])
        self.assertEqual(result[0], "译文 paragraph 0")
        provider.close()

    def test_single_item_split_is_merged(self):
        result = translate_batch_resilient(
            lambda _texts: ["第一段", "第二段"],
            ["one source paragraph"],
        )
        self.assertEqual(result, ["第一段第二段"])

    def test_google_marker_batch(self):
        provider = create_provider("google", {}, "auto", "zh-CN")
        self.assertIsInstance(provider, GoogleProvider)
        self.assertEqual(provider.missing_fields(), [])
        with patch.object(
            provider,
            "_request_raw",
            return_value="[[1]] 甲\n[[2]] 乙\n[[3]] 丙",
        ) as request:
            result = provider.translate_many(["one", "two", "three"])
        self.assertEqual(result, ["甲", "乙", "丙"])
        self.assertEqual(request.call_count, 1)
        provider.close()

    def test_google_parse_primary_and_backup(self):
        provider = GoogleProvider({}, "auto", "zh-CN")
        self.assertEqual(
            provider._parse_payload(
                [[["城市设计", "Designing cities", None, None, 10]], None, "en"]
            ),
            "城市设计",
        )
        self.assertEqual(provider._parse_payload(["城市", "设计"]), "城市设计")
        provider.close()

    def test_tencent_auth_headers(self):
        provider = TencentProvider({
            "secret_id": "AKIDEXAMPLE",
            "secret_key": "SECRET",
            "region": "ap-guangzhou",
        }, "auto", "zh-CN")
        headers = provider._headers("TextTranslateBatch", "{}")
        self.assertTrue(headers["Authorization"].startswith("TC3-HMAC-SHA256 "))
        self.assertIn("Credential=AKIDEXAMPLE/", headers["Authorization"])
        self.assertEqual(headers["X-TC-Action"], "TextTranslateBatch")
        provider.close()

    def test_aliyun_percent_encode(self):
        self.assertEqual(AliyunProvider._percent("a b+c/"), "a%20b%2Bc%2F")

    def test_missing_credentials(self):
        from core.providers import BaiduProvider, ProviderError
        provider = BaiduProvider({}, "auto", "zh-CN")
        with self.assertRaises(ProviderError):
            provider.validate()
        provider.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
