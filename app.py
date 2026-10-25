
from __future__ import annotations

import argparse
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core.config import (
    AppConfig, LIBRARY_PATH, LOG_PATH, install_exception_hook, resource_path,
    setup_logging,
)
from core.library import TranslationLibrary


def _show_startup_error(message: str) -> None:
    """QApplication 还没创建时也能告诉用户出了什么问题。"""
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, message, "肥鱼译文 · 启动失败", 0x10
            )
    except Exception:
        pass
    try:
        print(message, file=sys.stderr)
    except Exception:
        pass


def parse_args(argv):
    parser = argparse.ArgumentParser(description="肥鱼译文 · 原位对照翻译")
    parser.add_argument("pdf", nargs="?", help="启动后自动打开的 PDF")
    parser.add_argument("--demo", action="store_true",
                        help="打开内置示例文档并用本地演示库自动翻译")
    parser.add_argument("--check", action="store_true", help="环境自检，不打开界面")
    parser.add_argument("--smoke", metavar="OUT.pdf",
                        help="打包自检：翻译内置示例、导出 PDF、写结果日志后退出")
    parser.add_argument("--auto", action="store_true",
                        help="打开传入的 PDF 后自动开始翻译")
    return parser.parse_args(argv)


def run_smoke(output_pdf: str) -> int:
    """无界面自检，专门用于验证 PyInstaller 包中的资源与 PDF 写回。"""
    import tempfile
    import traceback

    log_path = os.path.abspath(output_pdf) + ".log"
    lines = ["肥鱼译文 · 打包自检", "=" * 52]
    ok = False
    library = None
    temp_dir = None
    try:
        from core.extract import extract_document
        from core.library import DemoMemory, TranslationLibrary
        from core.pipeline import TranslationPipeline
        from core.render import render_document

        import fitz

        src = resource_path("demo", "sample.pdf")
        demo = DemoMemory(resource_path("demo", "demo_library.json"))
        info = extract_document(src, "zh-CN")
        lines.append(f"示例页数 / 文本块 : {len(info.pages)} / {info.total_blocks}")
        lines.append(f"演示语料         : {len(demo)} 条")
        temp_dir = tempfile.mkdtemp(prefix="yipage_smoke_")
        library = TranslationLibrary(os.path.join(temp_dir, "library.sqlite"))

        def on_block(page, index, translation, status, quality, error):
            block = info.pages[page].blocks[index]
            block.translation = translation
            block.status = status

        summary = TranslationPipeline(
            info, library, demo, "demo", "auto", "zh-CN", {},
            on_block=on_block,
        ).run()
        lines.append(f"翻译结果         : {summary.translated}/{summary.total} 段，"
                     f"失败 {summary.errors}，未命中 {summary.misses}")
        result = render_document(
            info, os.path.abspath(output_pdf), target_lang="zh-CN"
        )
        lines.append(f"写回 PDF         : {result.rendered} 段，{os.path.getsize(output_pdf)} 字节")
        doc = fitz.open(output_pdf)
        try:
            text = doc[0].get_text() if doc.page_count else ""
            pages = doc.page_count
        finally:
            doc.close()
        has_cjk = "城市" in text or "翻译" in text
        lines.append(f"输出页数         : {pages}")
        lines.append(f"含中文           : {'是' if has_cjk else '否'}")
        ok = (
            summary.translated >= 1
            and result.rendered >= 1
            and os.path.getsize(output_pdf) > 0
            and pages >= 1
            and has_cjk
        )
    except Exception:
        lines.append(traceback.format_exc())
    finally:
        if library is not None:
            try:
                library.close()
            except Exception:
                pass
        if temp_dir is not None:
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
    lines.append("=" * 52)
    lines.append("结论：" + ("通过" if ok else "失败"))
    try:
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except Exception:
        pass
    return 0 if ok else 1


def check_environment() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=" * 62)
    print("肥鱼译文 · 环境自检")
    print("=" * 62)
    ok = True
    print(f"Python      : {sys.version.split()[0]}  ({sys.executable})")
    try:
        import PySide6
        print(f"PySide6     : {PySide6.__version__}")
    except Exception as exc:
        ok = False
        print(f"PySide6     : 缺失（{exc}）")
    try:
        import fitz
        print(f"PyMuPDF     : {fitz.__doc__.splitlines()[0] if fitz.__doc__ else 'ok'}")
    except Exception as exc:
        ok = False
        print(f"PyMuPDF     : 缺失（{exc}）")
    try:
        import requests
        print(f"requests    : {requests.__version__}")
    except Exception as exc:
        ok = False
        print(f"requests    : 缺失（{exc}）")
    print("界面字体    : Microsoft YaHei UI（启动时自动加载）")
    print(f"配置目录    : {os.path.dirname(LIBRARY_PATH)}")
    print(f"日志        : {LOG_PATH}")
    try:
        cfg = AppConfig()
        print(f"翻译库文件  : {cfg.library_file()}")
    except Exception as exc:
        cfg = None
        print(f"翻译库文件  : 读取配置失败（{exc}）")
    sample = resource_path("demo", "sample.pdf")
    print(f"示例 PDF    : {'已找到' if os.path.isfile(sample) else '缺失'}")
    try:
        from core.library import DemoMemory
        demo = DemoMemory(resource_path("demo", "demo_library.json"))
        print(f"演示语料    : {len(demo)} 条")
    except Exception as exc:
        print(f"演示语料    : 读取失败（{exc}）")
    try:
        lib = TranslationLibrary(cfg.library_file() if cfg is not None else LIBRARY_PATH)
        stats = lib.stats()
        lib.close()
        print(f"本地翻译库  : {stats['glossary']} 术语 / {stats['memory']} 记忆")
    except Exception as exc:
        print(f"本地翻译库  : 初始化失败（{exc}）")
    print("-" * 62)
    print("结论：" + ("环境正常，可以启动 app.py" if ok else "存在缺失项，请安装 requirements.txt"))
    return 0 if ok else 1


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.smoke:
        return run_smoke(args.smoke)
    if args.check:
        return check_environment()

    log_path = setup_logging()
    install_exception_hook()

    try:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
        from ui import theme
        from ui.main_window import MainWindow
    except Exception as exc:
        _show_startup_error(
            "缺少运行依赖或依赖损坏：\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            "请先运行 install.bat 安装依赖。"
        )
        return 1

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Fat_fish")
    app.setApplicationDisplayName("肥鱼译文")
    app.setOrganizationName("YiPage")
    app.setWindowIcon(QIcon(resource_path("app.ico")))
    app.setStyle("Fusion")
    theme.apply_theme(app)

    config = AppConfig()
    try:
        library = TranslationLibrary(config.library_file())
    except Exception as exc:
        if not config.get("library_dir"):
            _show_startup_error(f"翻译库无法打开：\n\n{type(exc).__name__}: {exc}")
            return 1
        bad_dir = config.library_dir()
        library = TranslationLibrary(LIBRARY_PATH)
        config.set("library_dir", "")
        config.save()
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            None,
            "翻译库位置不可用",
            f"自定义翻译库位置无法打开：\n{bad_dir}\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            "已切回默认位置。可在「设置 → 本地翻译库」重新选择。",
        )

    def _shutdown():
        try:
            library.close()
        except Exception:
            pass

    app.aboutToQuit.connect(_shutdown)
    window = MainWindow(config, library)
    window.show()

    target_pdf = args.pdf
    if args.demo and not target_pdf:
        target_pdf = resource_path("demo", "sample.pdf")
        config.set("engine", "demo")
        config.save()
        window._apply_config()
    elif args.demo:
        config.set("engine", "demo")
        config.save()
        window._apply_config()

    if target_pdf:
        autostart = bool(args.demo or args.auto)
        QTimer.singleShot(140, lambda: window.load_document(target_pdf, autostart=autostart))

    if log_path:
        import logging
        logging.getLogger(__name__).info("App started; log=%s", log_path)

    try:
        return app.exec()
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
