"""离屏截图，用于检查界面。开发脚本，不属于运行时依赖。

用法：
    python tools/capture_ui.py --demo --output docs/screenshot.png
    python tools/capture_ui.py --empty --output docs/empty.png
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
# 截图使用隔离的数据目录，不碰用户真实的设置与翻译库
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="yipage_capture_")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from core.config import AppConfig
from core.library import TranslationLibrary
from ui import theme
from ui.main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--output", default="docs/screenshot.png")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=920)
    parser.add_argument("--page", type=int, default=1, help="截图前跳到第 N 页")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    theme.apply_theme(app)
    config = AppConfig()
    if args.demo:
        config.set("engine", "demo")
        config.save()
    library = TranslationLibrary()
    window = MainWindow(config, library)
    window.resize(args.width, args.height)
    window.show()

    if args.demo:
        sample = os.path.join(HERE, "resources", "demo", "sample.pdf")
        QTimer.singleShot(120, lambda: window.load_document(sample, autostart=True))

    def capture() -> None:
        try:
            window.toast.hide()
        except Exception:
            pass
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        pixmap = window.grab()
        pixmap.save(args.output)
        print(f"saved {args.output} {pixmap.width()}x{pixmap.height()}")
        window._skip_close_prompt = True
        app.quit()

    def go_and_capture() -> None:
        if args.page > 1:
            window.go_page(args.page - 1)
            QTimer.singleShot(800, capture)
        else:
            capture()

    QTimer.singleShot(2600, go_and_capture)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
