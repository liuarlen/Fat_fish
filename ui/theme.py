"""视觉主题：配色、字体加载与 Qt 样式表。"""

from __future__ import annotations

import os
from typing import List

from PySide6.QtGui import QFont, QFontDatabase, QPalette, QColor
from PySide6.QtWidgets import QApplication

# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #
BG = "#F2F5FA"
SURFACE = "#FFFFFF"
SURFACE_SOFT = "#F8FAFD"
SURFACE_TINT = "#F0F5FF"
BORDER = "#E2E8F2"
BORDER_STRONG = "#CDD7E6"
TEXT = "#162033"
TEXT_SECONDARY = "#5C6B82"
TEXT_MUTED = "#8A97AA"
ACCENT = "#2563EB"
ACCENT_DARK = "#1D4ED8"
ACCENT_SOFT = "#EAF1FF"
ORANGE = "#E1754A"
ORANGE_SOFT = "#FFF2EC"
GREEN = "#109B6B"
GREEN_SOFT = "#E8F8F2"
RED = "#D14343"
RED_SOFT = "#FDECEC"
CANVAS = "#E7EDF5"
PAGE_SHADOW = QColor(25, 38, 64, 28)

FONT_CANDIDATES = [
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "DengXian",
    "Segoe UI",
]

_loaded_families: List[str] = []
_font_family = "Microsoft YaHei UI"


def load_fonts() -> List[str]:
    """把系统的微软雅黑显式注册给 Qt，避免在部分环境下回退成宋体。"""
    global _loaded_families, _font_family
    if _loaded_families:
        return _loaded_families
    candidates = [
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        for name in ("msyh.ttc", "msyhbd.ttc", "msyhl.ttc", "Deng.ttf")
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id >= 0:
            for family in QFontDatabase.applicationFontFamilies(font_id):
                if family not in _loaded_families:
                    _loaded_families.append(family)
    available = set(QFontDatabase.families())
    for family in _loaded_families + FONT_CANDIDATES:
        if family in available:
            _font_family = family
            break
    return _loaded_families


def app_font(pixel_size: int = 13, weight: QFont.Weight = QFont.Weight.Normal,
             family: str = "") -> QFont:
    font = QFont()
    families = []
    if family:
        families.append(family)
    families.extend(_loaded_families)
    families.extend(FONT_CANDIDATES)
    font.setFamilies(families)
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def font_family() -> str:
    return _font_family


def hex_rgba(color: str, alpha: int) -> str:
    """#RRGGBB + alpha(0-255) -> rgba()"""
    color = color.lstrip("#")
    r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


STYLE_SHEET = f"""
* {{
    outline: none;
}}
QWidget {{
    color: {TEXT};
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "DengXian", "Segoe UI";
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {BG};
}}
QFrame#TopBar {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}
QFrame#ToolBar {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}
QFrame#StatusBar {{
    background: {SURFACE};
    border-top: 1px solid {BORDER};
}}
QLabel#BrandTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#BrandSub {{
    font-size: 11px;
    color: {TEXT_MUTED};
}}
QLabel#SectionTitle {{
    font-size: 15px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#PageTitle {{
    font-size: 30px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#PageSub {{
    font-size: 13px;
    color: {TEXT_SECONDARY};
}}
QLabel#Muted {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#Secondary {{
    color: {TEXT_SECONDARY};
}}
QLabel#Pill {{
    background: {SURFACE_SOFT};
    border: 1px solid {BORDER};
    border-radius: 9px;
    color: {TEXT_SECONDARY};
    padding: 3px 9px;
    font-size: 11px;
}}
QLabel#SoftPill {{
    background: {ACCENT_SOFT};
    border: 1px solid #D7E3FF;
    border-radius: 9px;
    color: {ACCENT_DARK};
    padding: 3px 9px;
    font-size: 11px;
}}
QLabel#GreenPill {{
    background: {GREEN_SOFT};
    border: 1px solid #CBEEDF;
    border-radius: 9px;
    color: {GREEN};
    padding: 3px 9px;
    font-size: 11px;
}}
QLabel#OrangePill {{
    background: {ORANGE_SOFT};
    border: 1px solid #F7D9CC;
    border-radius: 9px;
    color: #B85A35;
    padding: 3px 9px;
    font-size: 11px;
}}
QFrame#FileChip {{
    background: {SURFACE_SOFT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#PaneCard {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QWidget#PaneHeader {{
    background: #FCFDFF;
    border-bottom: 1px solid {BORDER};
}}
QWidget#ViewWrap {{
    background: {CANVAS};
    border-bottom-left-radius: 11px;
    border-bottom-right-radius: 11px;
}}
QGraphicsView {{
    background: {CANVAS};
    border: none;
}}
QPushButton {{
    border-radius: 8px;
    padding: 0 13px;
    min-height: 33px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton#Primary {{
    background: {ACCENT};
    color: white;
    border: 1px solid {ACCENT};
    font-weight: 600;
}}
QPushButton#Primary:hover {{
    background: {ACCENT_DARK};
    border-color: {ACCENT_DARK};
}}
QPushButton#Primary:pressed {{
    background: #1742B0;
}}
QPushButton#Primary:disabled {{
    background: #AEC6F7;
    border-color: #AEC6F7;
    color: rgba(255,255,255,0.88);
}}
QPushButton#Secondary, QToolButton#Secondary {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    font-weight: 500;
}}
QPushButton#Secondary:hover, QToolButton#Secondary:hover {{
    background: {SURFACE_SOFT};
    border-color: #B7C6DB;
}}
QPushButton#Secondary:pressed, QToolButton#Secondary:pressed {{
    background: #EFF4FA;
}}
QPushButton#Secondary:disabled, QToolButton#Secondary:disabled {{
    color: {TEXT_MUTED};
    border-color: {BORDER};
    background: {SURFACE_SOFT};
}}
QPushButton#Ghost, QToolButton#Ghost {{
    background: transparent;
    color: {TEXT_SECONDARY};
    border: 1px solid transparent;
}}
QPushButton#Ghost:hover, QToolButton#Ghost:hover {{
    background: {SURFACE_TINT};
    color: {ACCENT_DARK};
}}
QPushButton#DangerGhost {{
    background: transparent;
    color: {RED};
    border: 1px solid transparent;
}}
QPushButton#DangerGhost:hover {{
    background: {RED_SOFT};
}}
QPushButton#LinkButton {{
    background: transparent;
    border: none;
    color: {ACCENT};
    padding: 0;
    min-height: 22px;
    font-size: 12px;
    text-align: left;
}}
QPushButton#LinkButton:hover {{
    color: {ACCENT_DARK};
    text-decoration: underline;
}}
QToolButton#IconButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0;
}}
QToolButton#IconButton:hover {{
    background: {SURFACE_TINT};
    border-color: #DDE8FF;
}}
QToolButton#IconButton:pressed {{
    background: #DCE8FF;
}}
QToolButton#Secondary {{
    padding: 0 10px;
}}
QComboBox {{
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 0 28px 0 11px;
    min-height: 33px;
    color: {TEXT};
}}
QComboBox:hover {{
    border-color: #B5C5DC;
}}
QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox:disabled {{
    color: {TEXT_MUTED};
    background: {SURFACE_SOFT};
    border-color: {BORDER};
}}
QComboBox::drop-down {{
    border: none;
    width: 0px;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0px;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    min-height: 30px;
    padding: 0 9px;
    border-radius: 6px;
}}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 0 10px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}
QLineEdit, QSpinBox, QDoubleSpinBox {{
    min-height: 33px;
}}
QTextEdit, QPlainTextEdit {{
    padding: 8px 10px;
}}
QLineEdit:hover, QTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: #B5C5DC;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled, QTextEdit:disabled {{
    background: {SURFACE_SOFT};
    color: {TEXT_MUTED};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 16px;
    border: none;
    background: transparent;
}}
QCheckBox {{
    spacing: 8px;
    color: {TEXT};
}}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 1px solid {BORDER_STRONG};
    background: {SURFACE};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: url(:/nonexistent.png);
}}
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 3px 2px;
}}
QScrollBar::handle:vertical {{
    background: #C6D2E2;
    min-height: 30px;
    border-radius: 4px;
    margin: 0 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: #AEBFD5;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px 3px;
}}
QScrollBar::handle:horizontal {{
    background: #C6D2E2;
    min-width: 30px;
    border-radius: 4px;
    margin: 2px 0;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
QProgressBar {{
    background: #E8EEF7;
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 3px;
}}
QSplitter::handle {{
    background: transparent;
    width: 12px;
}}
QSplitter::handle:hover {{
    background: #DCE7F8;
    border-radius: 5px;
}}
QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 6px;
}}
QMenu::item {{
    padding: 8px 26px 8px 12px;
    border-radius: 6px;
    color: {TEXT};
}}
QMenu::item:selected {{
    background: {ACCENT_SOFT};
    color: {TEXT};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 5px 8px;
}}
QTableWidget, QTableView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
    alternate-background-color: #FAFBFE;
}}
QTableWidget::item, QTableView::item {{
    padding: 8px 10px;
    border-bottom: 1px solid #EEF2F8;
}}
QHeaderView::section {{
    background: {SURFACE_SOFT};
    color: {TEXT_SECONDARY};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 9px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_SECONDARY};
    padding: 8px 14px;
    border: none;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    font-weight: 600;
}}
QDialogButtonBox QPushButton {{
    min-width: 78px;
}}
QToolTip {{
    background: {TEXT};
    color: white;
    border: none;
    padding: 6px 9px;
    border-radius: 5px;
    font-size: 11px;
}}
QMessageBox {{
    background: {SURFACE};
}}
QFrame#DialogHeader {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}
QLabel#DialogTitle {{
    font-size: 21px;
    font-weight: 700;
    color: {TEXT};
}}
QFrame#SettingsNav {{
    background: #FAFBFE;
    border-right: 1px solid {BORDER};
}}
QPushButton#NavButton {{
    text-align: left;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0 13px;
    min-height: 37px;
    color: {TEXT_SECONDARY};
    font-weight: 500;
    font-size: 12px;
}}
QPushButton#NavButton:hover {{
    background: #EFF4FB;
    color: {TEXT};
}}
QPushButton#NavButton:checked {{
    background: {ACCENT_SOFT};
    border-color: #DDE8FF;
    color: {ACCENT_DARK};
    font-weight: 600;
}}
QFrame#StatCard {{
    background: {SURFACE_SOFT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#StatNumber {{
    font-size: 21px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#DialogSection {{
    font-size: 14px;
    font-weight: 600;
    color: {TEXT};
}}
QFrame#SoftCard {{
    background: {SURFACE_SOFT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#Divider {{
    background: {BORDER};
    min-height: 1px;
    max-height: 1px;
}}
QPushButton#SegButton {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 0 14px;
    min-height: 31px;
    color: {TEXT_SECONDARY};
    font-weight: 500;
}}
QPushButton#SegButton:hover {{
    color: {TEXT};
    background: #F0F4FB;
}}
QPushButton#SegButton:checked {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    font-weight: 600;
}}
"""


def apply_theme(app: QApplication) -> None:
    load_fonts()
    app.setFont(app_font(13))
    app.setStyleSheet(STYLE_SHEET)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)
