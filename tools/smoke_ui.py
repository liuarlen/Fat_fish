"""离屏 UI 端到端冒烟测试：载入 → 演示翻译 → 缩放/滚动同步 → 导出。"""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
)
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="yipage_ui_")

import fitz
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from core.config import AppConfig
from core.library import TranslationLibrary
from ui import theme
from ui.main_window import ExportWorker, MainWindow


def wait_until(predicate, timeout_ms: int = 12000) -> bool:
    loop = QEventLoop()
    deadline = [False]

    def tick():
        if predicate():
            loop.quit()
        elif timeout_ms <= 0:
            deadline[0] = True
            loop.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(80)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    return predicate()


def main() -> int:
    app = QApplication([])
    app.setStyle("Fusion")
    theme.apply_theme(app)
    config = AppConfig()
    config.set("engine", "demo")
    config.save()
    library = TranslationLibrary()
    window = MainWindow(config, library)
    window.resize(1440, 920)
    window.show()

    sample = os.path.join(HERE, "resources", "demo", "sample.pdf")
    window.load_document(sample, autostart=True)

    ok = wait_until(
        lambda: window._load_worker is None
        and window._translation_worker is None
        and window.doc is not None
        and window._done_blocks > 0,
        timeout_ms=12000,
    )
    app.processEvents()
    print("loaded:", window.doc is not None, "done blocks:", window._done_blocks)
    print("page images:", [
        item.image is not None for item in window.left_view._page_items
    ], [
        item.image is not None for item in window.right_view._page_items
    ])
    assert ok, "translation did not finish in time"
    assert window._done_blocks == 30, window._done_blocks
    assert len(window.left_view._page_items) == 2
    assert all(item.image is not None for item in window.left_view._page_items)

    window.zoom_by(1.15)
    app.processEvents()
    assert abs(window.left_view.zoom - window.right_view.zoom) < 1e-6
    window._apply_fit_width()
    app.processEvents()
    assert abs(window.left_view.zoom - window.right_view.zoom) < 1e-6

    window.left_view.verticalScrollBar().setValue(300)
    app.processEvents()
    assert window.left_view.verticalScrollBar().value() == 300
    assert window.right_view.verticalScrollBar().value() == 300

    output = os.path.join(tempfile.gettempdir(), "yipage_ui_smoke.pdf")
    worker = ExportWorker(
        window.doc, output, "pdf",
        float(config.get("font_scale", 1.0)),
        bool(config.get("auto_shrink", True)),
        str(config.get("mode", "redact")),
        config.get("target_lang", "zh-CN"),
    )
    loop = QEventLoop()
    result = {"done": False, "error": ""}
    worker.done.connect(lambda path, warnings: (result.update(done=True), loop.quit()))
    worker.failed.connect(lambda error: (result.update(error=error), loop.quit()))
    worker.start()
    QTimer.singleShot(20000, loop.quit)
    loop.exec()
    worker.wait(2000)
    print("exported:", result, output)
    assert result["done"], result["error"]
    assert os.path.isfile(output)
    doc = fitz.open(output)
    text = doc[0].get_text()
    print("exported pages:", doc.page_count, "contains Chinese:", "城市" in text)
    doc.close()
    assert "城市" in text

    window.clear_translations()
    app.processEvents()
    assert window._done_blocks == 0
    print("clear translations: ok")
    window.close()
    app.processEvents()
    print("UI SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
