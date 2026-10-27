"""Iconite vectoriale (SVG desenat in cod), colorate dupa tema."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from dicom3d.ui import theme

# contur 1.8 px pe o grila de 24 px; "currentColor" se inlocuieste la desenare
_PATHS = {
    "logo": '<path d="M3.5 3.5h17v17h-17z"/><path d="M3.5 8h3.5M3.5 12h6M3.5 16h3.5"/>'
            '<circle cx="15" cy="12" r="3"/>',
    "folder": '<path d="M3 6.5h6l2 2h10v10.5H3z"/>',
    "export": '<path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14"/>',
    "cube": '<path d="M12 3 4 7.5v9L12 21l8-4.5v-9z"/><path d="M4 7.5 12 12l8-4.5M12 12v9"/>',
    "reset": '<path d="M4 12a8 8 0 1 0 2.4-5.7M4 4v4h4"/>',
    "camera": '<rect x="3" y="6.5" width="18" height="13.5" rx="2"/><circle cx="12" cy="13" r="3.5"/>'
              '<path d="M8.5 6.5 10 4h4l1.5 2.5"/>',
    "check": '<path d="M5 12.5 10 17l9-10"/>',
    "warning": '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5m0 2.5v.5"/>',
    "upload": '<path d="M3 6.5h6l2 2h10v10.5H3z"/><path d="M12 17v-5.5m0 0-2.5 2.5M12 11.5l2.5 2.5"/>',
}


def _svg(name: str, color: str, stroke: float) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
        f"{_PATHS[name]}</svg>"
    ).encode()


def pixmap(name: str, size: int = 16, color: str = theme.TEXT, stroke: float = 1.8,
           ratio: float = 2.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(_svg(name, color, stroke)))
    pix = QPixmap(round(size * ratio), round(size * ratio))
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, pix.width(), pix.height()))
    p.end()
    pix.setDevicePixelRatio(ratio)
    return pix


def icon(name: str, color: str = theme.TEXT, disabled: str = theme.FAINT, size: int = 16) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, size, color), QIcon.Normal)
    ic.addPixmap(pixmap(name, size, disabled), QIcon.Disabled)
    return ic


def swatch(color: str, size: int = 8, ratio: float = 2.0) -> QPixmap:
    """Patratelul de culoare al unui tesut."""
    pix = QPixmap(round(size * ratio), round(size * ratio))
    pix.fill(QColor(color))
    pix.setDevicePixelRatio(ratio)
    return pix


def app_icon() -> QIcon:
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.INK1))
        p.drawRect(QRectF(0, 0, size, size))
        inner = size * 0.1
        QSvgRenderer(QByteArray(_svg("logo", theme.TEXT, 2.0))).render(
            p, QRectF(inner, inner, size - 2 * inner, size - 2 * inner))
        p.end()
        ic.addPixmap(pix)
    return ic
