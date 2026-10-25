"""离屏抓取设置 / 翻译库 / 校对对话框截图。开发脚本。"""

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
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="yipage_shots_")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from core.config import AppConfig
from core.library import TranslationLibrary
from ui import theme
from ui.library_dialog import LibraryDialog
from ui.segment_dialog import SegmentDialog
from ui.settings_dialog import SettingsDialog


def main() -> int:
    app = QApplication([])
    app.setStyle("Fusion")
    theme.apply_theme(app)
    config = AppConfig()
    library = TranslationLibrary()
    library.upsert_glossary("calm technology", "安静的技术", "en", "zh-CN", "核心术语")
    library.upsert_glossary("Urban Systems Lab", "城市系统实验室", "en", "zh-CN", "机构名")
    library.upsert_glossary("attention tax", "注意力税", "en", "zh-CN", "文章概念")
    library.remember(
        "Designing Calm Technology for the Cities of Tomorrow",
        "为未来城市设计安静的技术", "en", "zh-CN", "demo", "demo",
    )
    library.remember(
        "A city feels calm when its systems remember that people are not tasks.",
        "当系统记得人不是任务，城市才会显得安静。", "en", "zh-CN", "demo", "demo",
    )
    settings = SettingsDialog(config, library)
    settings.resize(920, 690)
    settings.show()
    library_dialog = LibraryDialog(library, config)
    library_dialog.resize(980, 680)
    library_dialog.show()
    segment = SegmentDialog(
        0, 3, "Designing Calm Technology for the Cities of Tomorrow",
        "为未来城市设计安静的技术",
    )
    segment.show()

    def capture() -> None:
        os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
        settings.grab().save(os.path.join(HERE, "docs", "settings.png"))
        library_dialog.grab().save(os.path.join(HERE, "docs", "library.png"))
        segment.grab().save(os.path.join(HERE, "docs", "correction.png"))
        print("saved docs/settings.png, docs/library.png, docs/correction.png")
        app.quit()

    QTimer.singleShot(900, capture)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
