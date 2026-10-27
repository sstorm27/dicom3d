"""Tema vizuala: culori, fonturi, durate de animatie si foaia de stil Qt.

Aspect intunecat, ca la statiile de radiologie: imaginea CT ramane in centrul
atentiei, iar interfata foloseste griuri cu nuanta de ardezie si un singur
accent cian. Spatierea urmeaza scara 4/8/12/16/24 px.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEasingCurve
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QWidget

ASSETS = Path(__file__).resolve().parent / "assets"

INK0 = "#0a1015"  # fundalul ferestrei
INK1 = "#0f171e"  # panouri
INK2 = "#16212a"  # campuri si butoane secundare
INK3 = "#1d2a35"  # hover, sina sliderelor
LINE = "#223140"
LINE_HOVER = "#2e4153"
TEXT = "#e3eaef"
MUTED = "#8396a5"
FAINT = "#5a6d7c"
ACCENT = "#56c2d0"
ACCENT_HOVER = "#71d0dc"
ACCENT_PRESSED = "#48aebb"
ACCENT_INK = "#062126"
OK = "#5fcf95"
WARN = "#e8b04f"
DANGER = "#e5636f"
OVERLAY_TEXT = "#b9c7d1"  # textul din colturile feliei

SANS = "IBM Plex Sans"
MONO = "IBM Plex Mono"

# culoarea fiecarui tesut, aceeasi pe felie (masca) si pe modelul 3D
TISSUE_COLORS = {
    "Os": "#ecd08f",
    "Tesut moale": "#e8a04f",
    "Vase cu contrast": "#d9475a",
    "Plamani (aer)": "#f07b6a",
    "Piele": "#e9b8a0",
}
TISSUE_LABELS = {
    "Os": "Os",
    "Tesut moale": "Țesut moale",
    "Vase cu contrast": "Vase",
    "Plamani (aer)": "Plămâni",
    "Piele": "Piele",
}

# animatii scurte, cu ease-out puternic; nimic animat la actiuni din tastatura
EASE_OUT = QEasingCurve.OutQuint
FAST = 160  # comutatoare, iesiri
NORMAL = 220  # intrari, schimbari de stare


def mix(a: str | QColor, b: str | QColor, t: float) -> QColor:
    """Culoarea a amestecata cu b; t=0 da a, t=1 da b."""
    a, b = QColor(a), QColor(b)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def mono_font(pixel_size: int = 12, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont(MONO)
    f.setStyleHint(QFont.Monospace)
    f.setPixelSize(pixel_size)
    f.setWeight(weight)
    return f


STYLESHEET = """
* { outline: none; }
QWidget { color: @TEXT; font-family: "@SANS", "Segoe UI", sans-serif; font-size: 13px; }
QMainWindow, #central { background: @INK0; }
QToolTip { background: @INK2; color: @TEXT; border: 1px solid @LINE; border-radius: 6px;
           padding: 6px 8px; font-size: 12px; }

#topbar { background: @INK1; border-bottom: 1px solid @LINE; }
#sidebar { background: @INK1; border-right: 1px solid @LINE; }
#sidebarFooter { background: @INK1; border-top: 1px solid @LINE; }
QScrollArea, #sidebarContent { background: transparent; border: none; }

QLabel { background: transparent; }
QLabel[role="brand"] { font-size: 14px; font-weight: 600; letter-spacing: 0.5px; }
QLabel[role="version"], QLabel[role="kbd"] { font-family: "@MONO"; font-size: 11px; color: @FAINT; }
QLabel[role="section"] { font-size: 11px; font-weight: 600; letter-spacing: 1.2px; color: @MUTED; }
QLabel[role="step"] { font-family: "@MONO"; font-size: 11px; font-weight: 600; color: @ACCENT; }
QLabel[role="muted"] { color: @MUTED; }
QLabel[role="faint"] { color: @FAINT; font-size: 12px; }
QLabel[role="value"] { font-family: "@MONO"; font-size: 12px; }
QLabel[role="series"] { font-weight: 500; }
QLabel[role="pill"] { font-family: "@MONO"; font-size: 11px; color: @MUTED; background: @INK2;
                      border: 1px solid @LINE; border-radius: 9px; padding: 1px 8px; }
QLabel[role="vpTitle"] { font-weight: 600; }

QPushButton { background: @INK2; border: 1px solid @LINE; border-radius: 8px; padding: 0 14px;
              min-height: 30px; font-weight: 500; }
QPushButton:hover { background: @INK3; border-color: @LINE_HOVER; }
QPushButton:pressed { background: @INK1; }
QPushButton:disabled { color: @FAINT; background: @INK1; border-color: @INK3; }
QPushButton[variant="primary"] { background: @ACCENT; color: @ACCENT_INK; border: none;
                                 font-weight: 600; font-size: 14px; min-height: 40px; }
QPushButton[variant="primary"]:hover { background: @ACCENT_HOVER; }
QPushButton[variant="primary"]:pressed { background: @ACCENT_PRESSED; }
QPushButton[variant="primary"]:disabled { background: @INK3; color: @FAINT; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; color: @MUTED; }
QPushButton[variant="ghost"]:hover { background: @INK2; color: @TEXT; }
QPushButton[variant="icon"] { background: transparent; border: none; border-radius: 7px; padding: 0;
                              min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; }
QPushButton[variant="icon"]:hover { background: @INK2; }
QPushButton[variant="icon"]:pressed { background: @INK3; }
QPushButton[variant="chip"] { min-height: 30px; padding: 0 11px 0 9px; font-weight: 400; }
QPushButton[variant="chip"]:checked { font-weight: 500; }

#segmented { background: @INK0; border: 1px solid @LINE; border-radius: 8px; }
#segmented QPushButton { background: transparent; border: none; border-radius: 6px; padding: 0 10px;
                         min-height: 24px; max-height: 24px; color: @MUTED; font-size: 12px; }
#segmented QPushButton:hover { color: @TEXT; background: @INK2; }
#segmented QPushButton:checked { background: @INK3; color: @TEXT; }
#segmented QPushButton:disabled { color: @FAINT; background: transparent; }

QSpinBox, QDoubleSpinBox { background: @INK2; border: 1px solid @LINE; border-radius: 8px;
                           padding: 0 10px; min-height: 30px; font-family: "@MONO"; font-size: 13px;
                           selection-background-color: @ACCENT; selection-color: @ACCENT_INK; }
QSpinBox:hover, QDoubleSpinBox:hover { border-color: @LINE_HOVER; }
QSpinBox:focus, QDoubleSpinBox:focus { border-color: @ACCENT; }
QSpinBox:disabled, QDoubleSpinBox:disabled { color: @FAINT; background: @INK1; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button
    { width: 0; border: none; }

QSlider { min-height: 18px; }
QSlider::groove:horizontal { height: 4px; background: @INK3; border-radius: 2px; }
QSlider::sub-page:horizontal { background: @ACCENT; border-radius: 2px; }
QSlider::handle:horizontal { background: @TEXT; width: 14px; height: 14px; margin: -5px 0;
                             border-radius: 7px; }
QSlider::handle:horizontal:hover { background: #ffffff; }
QSlider::sub-page:horizontal:disabled { background: @INK3; }
QSlider::handle:horizontal:disabled { background: @FAINT; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: @INK3; border-radius: 3px; min-height: 32px; min-width: 32px; }
QScrollBar::handle:hover { background: @LINE_HOVER; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QSplitter::handle { background: transparent; }

#viewport { background: #000000; border: 1px solid @LINE; border-radius: 10px; }
#vpHeader { background: @INK1; border-bottom: 1px solid @LINE;
            border-top-left-radius: 9px; border-top-right-radius: 9px; }
#vpFooter { background: @INK1; border-top: 1px solid @LINE;
            border-bottom-left-radius: 9px; border-bottom-right-radius: 9px; }

#banner { background: @WARN_BG; border: 1px solid @WARN_BORDER; border-radius: 8px; }
#banner QLabel { font-size: 12px; }

QStatusBar { background: @INK1; border-top: 1px solid @LINE; color: @MUTED; font-size: 12px; }
QStatusBar::item { border: none; }

QDialog, QMessageBox, QInputDialog { background: @INK1; }
QComboBox { background: @INK2; border: 1px solid @LINE; border-radius: 8px; padding: 0 10px;
            min-height: 30px; }
QComboBox:hover { border-color: @LINE_HOVER; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView, QListView { background: @INK2; border: 1px solid @LINE; outline: none;
                                         selection-background-color: @INK3; selection-color: @TEXT; }
QLineEdit { background: @INK2; border: 1px solid @LINE; border-radius: 8px; padding: 0 10px;
            min-height: 30px; selection-background-color: @ACCENT; selection-color: @ACCENT_INK; }
QLineEdit:focus { border-color: @ACCENT; }
QMenu { background: @INK2; border: 1px solid @LINE; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 14px; border-radius: 6px; }
QMenu::item:selected { background: @INK3; }
"""


def stylesheet() -> str:
    tokens = {
        "@WARN_BG": rgba(WARN, 0.10),
        "@WARN_BORDER": rgba(WARN, 0.35),
        "@ACCENT_HOVER": ACCENT_HOVER,
        "@ACCENT_PRESSED": ACCENT_PRESSED,
        "@ACCENT_INK": ACCENT_INK,
        "@ACCENT": ACCENT,
        "@LINE_HOVER": LINE_HOVER,
        "@LINE": LINE,
        "@INK0": INK0,
        "@INK1": INK1,
        "@INK2": INK2,
        "@INK3": INK3,
        "@TEXT": TEXT,
        "@MUTED": MUTED,
        "@FAINT": FAINT,
        "@SANS": SANS,
        "@MONO": MONO,
    }
    qss = STYLESHEET
    for key, value in tokens.items():  # cheile mai lungi primele (ACCENT_INK inainte de ACCENT)
        qss = qss.replace(key, value)
    return qss


def _load_fonts():
    for path in sorted((ASSETS / "fonts").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def apply(app: QApplication):
    """Aplica tema pe toata aplicatia. Se apeleaza o data, inainte de ferestre."""
    _load_fonts()
    app.setStyle("Fusion")
    font = QFont(SANS)
    font.setPixelSize(13)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)

    pal = QPalette()
    for role, color in (
        (QPalette.Window, INK0),
        (QPalette.WindowText, TEXT),
        (QPalette.Base, INK2),
        (QPalette.AlternateBase, INK1),
        (QPalette.Text, TEXT),
        (QPalette.Button, INK2),
        (QPalette.ButtonText, TEXT),
        (QPalette.ToolTipBase, INK2),
        (QPalette.ToolTipText, TEXT),
        (QPalette.PlaceholderText, FAINT),
        (QPalette.Highlight, ACCENT),
        (QPalette.HighlightedText, ACCENT_INK),
        (QPalette.Link, ACCENT),
    ):
        pal.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(FAINT))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet())


def dark_title_bar(widget: QWidget):
    """Bara de titlu Windows intunecata, ca sa nu iasa in evidenta deasupra temei."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 10 20H1+, apoi mai vechi)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                int(widget.winId()), attr, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break
    except Exception:  # noqa: BLE001 - doar cosmetic
        pass
