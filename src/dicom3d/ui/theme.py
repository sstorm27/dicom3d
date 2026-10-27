"""Tema vizuala: culori, fonturi, durate de animatie si foaia de stil Qt.

Directia „instrument de precizie": grafit aproape monocrom, colturi drepte,
linii subtiri in loc de carduri. Singura culoare de pe ecran e tesutul ales
(masca, rigla Hounsfield, modelul 3D); actiunile si selectia sunt albe.
Spatierea urmeaza scara 4/8/12/16/20 px.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEasingCurve
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QWidget

ASSETS = Path(__file__).resolve().parent / "assets"

INK0 = "#0b0d0d"  # fundalul ferestrei, barele de sus si de jos
INK1 = "#111414"  # panoul lateral
INK2 = "#191d1d"  # campuri
INK3 = "#232828"  # hover, sina sliderelor
LINE = "#232828"  # marginile zonelor
LINE_SOFT = "#1c2020"  # separatoarele din panou
LINE_STRONG = "#3a4242"  # butoane cu contur, axa riglei
TICK = "#56605e"  # gradatiile riglelor
TEXT = "#e6eae9"
MUTED = "#97a19f"
FAINT = "#7a8583"
ACCENT = "#eef1f0"  # actiunea principala si selectia: alb, ca sa nu concureze cu tesutul
ACCENT_HOVER = "#ffffff"
ACCENT_PRESSED = "#c9cfcd"
ACCENT_INK = "#0b0d0d"
OK = "#6cc28a"
WARN = "#e8b04f"
DANGER = "#e5636f"
OVERLAY_TEXT = "#b8c2c0"  # textul din colturile feliei

SANS = "Barlow"
NUM = "Barlow Semi Condensed"  # cifre si valori, cu cifre de latime egala

# culoarea fiecarui tesut, aceeasi pe felie (masca), pe rigla HU si pe modelul 3D
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
    "Vase cu contrast": "Vase cu contrast",
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


def num_font(pixel_size: int = 13, weight: QFont.Weight = QFont.Normal) -> QFont:
    """Fontul pentru valori: semi-condensat, cu cifre tabulare (coloanele nu tremura)."""
    f = QFont(NUM)
    f.setPixelSize(pixel_size)
    f.setWeight(weight)
    f.setFeature(QFont.Tag("tnum"), 1)
    return f


def sans_font(pixel_size: int = 13, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont(SANS)
    f.setPixelSize(pixel_size)
    f.setWeight(weight)
    return f


# Fontul de baza vine din app.setFont; foaia de stil nu seteaza font-family pe QWidget,
# ca etichetele cu valori sa-si pastreze fontul cu cifre tabulare.
STYLESHEET = """
* { outline: none; }
QMainWindow, #central { background: @INK0; }
QToolTip { background: @INK2; color: @TEXT; border: 1px solid @LINE_STRONG; border-radius: 2px;
           padding: 5px 8px; }

#topbar { background: @INK0; border-bottom: 1px solid @LINE; }
#sidebar { background: @INK1; border-right: 1px solid @LINE; }
#sidebarFooter { background: @INK1; }
QScrollArea, #sidebarContent { background: transparent; border: none; }
#sep { background: @LINE_SOFT; border: none; min-height: 1px; max-height: 1px; }
#vsep { background: @LINE_STRONG; border: none; min-width: 1px; max-width: 1px; }

QLabel { background: transparent; color: @TEXT; }
QLabel[role="brand"] { font-size: 14px; font-weight: 600; letter-spacing: 0.3px; }
QLabel[role="h"] { font-weight: 600; }
QLabel[role="muted"] { color: @MUTED; }
QLabel[role="faint"] { color: @FAINT; }
QLabel[role="hint"] { color: @MUTED; font-size: 12px; }

QPushButton { background: transparent; color: @TEXT; border: 1px solid @LINE_STRONG; border-radius: 2px;
              padding: 0 12px; min-height: 30px; font-weight: 500; }
QPushButton:hover { background: @INK3; }
QPushButton:pressed { background: @INK2; }
QPushButton:focus { border-color: @TEXT; }
QPushButton:disabled { color: @FAINT; border-color: @INK3; background: transparent; }
QPushButton[variant="primary"] { background: @ACCENT; color: @ACCENT_INK; border: none;
                                 font-weight: 600; font-size: 14px; min-height: 40px; }
QPushButton[variant="primary"]:hover { background: @ACCENT_HOVER; }
QPushButton[variant="primary"]:pressed { background: @ACCENT_PRESSED; }
QPushButton[variant="primary"]:focus { border: 2px solid @MUTED; }
QPushButton[variant="primary"]:disabled { background: @INK3; color: @FAINT; }
QPushButton[variant="ghost"] { border-color: transparent; }
QPushButton[variant="ghost"]:focus { border-color: @LINE_STRONG; }
QPushButton[variant="icon"] { border: none; padding: 0; min-width: 28px; max-width: 28px;
                              min-height: 28px; max-height: 28px; }
QPushButton[variant="icon"]:focus { border: 1px solid @LINE_STRONG; }

#tabs { background: transparent; }
#tabs QPushButton { background: transparent; border: none; border-radius: 0; padding: 0 2px;
                    min-height: 33px; max-height: 33px; color: @MUTED; font-size: 13px;
                    border-bottom: 2px solid transparent; }
#tabs QPushButton:hover { color: @TEXT; }
#tabs QPushButton:checked { color: @TEXT; border-bottom: 2px solid @TEXT; }
#tabs QPushButton:focus { color: @TEXT; border-bottom: 2px solid @LINE_STRONG; }
#tabs QPushButton:checked:focus { border-bottom: 2px solid @TEXT; }
#tabs QPushButton:disabled { color: @FAINT; }

#field { background: @INK2; border: 1px solid @LINE_STRONG; border-radius: 2px; }
#field QSpinBox { background: transparent; border: none; padding: 0; min-height: 30px;
                  selection-background-color: @TEXT; selection-color: @INK0; }
#field QSpinBox:disabled { color: @FAINT; }
#field QLineEdit { background: transparent; border: none; padding: 0; min-height: 0; }
QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; }

QSlider { min-height: 18px; }
QSlider::groove:horizontal { height: 2px; background: @LINE_STRONG; }
QSlider::sub-page:horizontal { background: @TEXT; }
QSlider::handle:horizontal { background: @TEXT; width: 4px; height: 14px; margin: -6px 0; border-radius: 1px; }
QSlider::handle:horizontal:hover { background: #ffffff; width: 6px; }
QSlider::handle:horizontal:focus { background: #ffffff; width: 6px; }
QSlider::sub-page:horizontal:disabled { background: @LINE_STRONG; }
QSlider::handle:horizontal:disabled { background: @FAINT; }

QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle { background: @INK3; border-radius: 1px; min-height: 32px; min-width: 32px; }
QScrollBar::handle:hover { background: @LINE_STRONG; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QSplitter::handle { background: @LINE; }

#viewport { background: #000000; }
#vpHeader { background: @INK0; border-bottom: 1px solid @LINE_SOFT; }
#vpFooter { background: #000000; }

#banner { background: @WARN_BG; border: 1px solid @WARN_BORDER; border-radius: 2px; }
#banner QLabel { font-size: 12px; color: @TEXT; }

QStatusBar { background: @INK0; border-top: 1px solid @LINE; color: @MUTED; }
QStatusBar::item { border: none; }

QDialog, QMessageBox, QInputDialog { background: @INK1; }
QComboBox { background: @INK2; border: 1px solid @LINE_STRONG; border-radius: 2px; padding: 0 10px;
            min-height: 30px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView, QListView { background: @INK2; border: 1px solid @LINE_STRONG; outline: none;
                                         selection-background-color: @INK3; selection-color: @TEXT; }
QLineEdit { background: @INK2; border: 1px solid @LINE_STRONG; border-radius: 2px; padding: 0 10px;
            min-height: 30px; selection-background-color: @TEXT; selection-color: @INK0; }
QLineEdit:focus { border-color: @TEXT; }
QMenu { background: @INK2; border: 1px solid @LINE_STRONG; padding: 4px; }
QMenu::item { padding: 6px 14px; }
QMenu::item:selected { background: @INK3; }
"""


def stylesheet() -> str:
    tokens = {
        "@WARN_BG": rgba(WARN, 0.08),
        "@WARN_BORDER": rgba(WARN, 0.40),
        "@ACCENT_HOVER": ACCENT_HOVER,
        "@ACCENT_PRESSED": ACCENT_PRESSED,
        "@ACCENT_INK": ACCENT_INK,
        "@ACCENT": ACCENT,
        "@LINE_STRONG": LINE_STRONG,
        "@LINE_SOFT": LINE_SOFT,
        "@LINE": LINE,
        "@INK0": INK0,
        "@INK1": INK1,
        "@INK2": INK2,
        "@INK3": INK3,
        "@TEXT": TEXT,
        "@MUTED": MUTED,
        "@FAINT": FAINT,
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
    font = sans_font(13)
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
        (QPalette.Highlight, TEXT),
        (QPalette.HighlightedText, INK0),
        (QPalette.Link, TEXT),
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
