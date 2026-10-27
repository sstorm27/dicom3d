"""Vizualizare 2D a feliilor, cu fereastra CT si suprapunerea mastii.

Felia si masca se deseneaza ca doua imagini separate, ca masca sa poata aparea
lin peste felie. In colturi stau informatiile, ca intr-un viewer medical.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QSlider, QVBoxLayout, QWidget

from dicom3d.ui import icons, theme
from dicom3d.ui.widgets import fmt_hu

MASK_ALPHA = 0.40  # interiorul mastii; conturul se deseneaza opac, ca sa se vada pe orice tesut


def _orientation_letter(vec) -> str:
    """Litera directiei anatomice (LPS) pentru un vector din matricea de directie."""
    i = int(np.argmax(np.abs(vec)))
    return ("L", "P", "S")[i] if vec[i] > 0 else ("R", "A", "I")[i]


class SliceCanvas(QWidget):
    openRequested = Signal()
    hoverChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(256, 256)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.view: SliceView | None = None
        self.drop_hover = False
        self.fade = 1.0
        self.overlay_fade = 1.0
        self._fade_anim = QVariantAnimation(self, startValue=0.0, endValue=1.0,
                                            duration=theme.NORMAL, easingCurve=theme.EASE_OUT)
        self._fade_anim.valueChanged.connect(lambda v: self._set("fade", v))
        self._overlay_anim = QVariantAnimation(self, startValue=0.0, endValue=1.0,
                                               duration=theme.NORMAL, easingCurve=theme.EASE_OUT)
        self._overlay_anim.valueChanged.connect(lambda v: self._set("overlay_fade", v))

    def _set(self, attr, v):
        setattr(self, attr, float(v))
        self.update()

    def fade_in(self):
        self._fade_anim.start()

    def fade_in_overlay(self):
        self._overlay_anim.start()

    def set_drop_hover(self, on: bool):
        self.drop_hover = on
        self.update()

    # ---------- geometrie ----------

    def image_rect(self) -> QRectF | None:
        v = self.view
        if v is None or v._volume is None:
            return None
        h, w = v._volume.shape[1:]
        h_eff = h * v._aspect
        scale = min(self.width() / w, self.height() / h_eff)
        tw, th = w * scale, h_eff * scale
        return QRectF((self.width() - tw) / 2, (self.height() - th) / 2, tw, th)

    # ---------- desenare ----------

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))
        v = self.view
        if v is None or v._volume is None:
            self._paint_empty(p)
            return
        target = self.image_rect()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(self.fade)
        p.drawImage(target, v.base_image())
        overlay = v.overlay_image()
        if overlay is not None:
            p.setOpacity(self.fade * self.overlay_fade)
            p.drawImage(target, overlay)
        p.setOpacity(1.0)
        self._paint_corners(p, target)

    def _paint_empty(self, p: QPainter):
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(0, 0, min(380, self.width() - 32), 176)
        box.moveCenter(QPointF(self.rect().center()))
        accent = QColor(theme.ACCENT)
        fill = QColor(theme.ACCENT)
        fill.setAlphaF(0.09 if self.drop_hover else 0.035)
        border = QColor(theme.ACCENT) if self.drop_hover else theme.mix(theme.LINE, theme.ACCENT, 0.45)
        pen = QPen(border, 1.5)
        if not self.drop_hover:
            pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.setBrush(fill)
        p.drawRoundedRect(box, 12, 12)
        ic = icons.pixmap("upload", 30, accent.name(), 1.6)
        p.drawPixmap(QRectF(box.center().x() - 15, box.top() + 34, 30, 30).toRect(), ic)
        title = p.font()
        title.setPixelSize(15)
        title.setWeight(QFont.DemiBold)
        p.setFont(title)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(box.left(), box.top() + 76, box.width(), 24), Qt.AlignCenter,
                   "Trage aici un folder DICOM")
        sub = p.font()
        sub.setPixelSize(12)
        sub.setWeight(QFont.Normal)
        p.setFont(sub)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(box.left() + 16, box.top() + 104, box.width() - 32, 40),
                   Qt.AlignCenter | Qt.TextWordWrap,
                   "sau apasă Ctrl+O ori fă clic aici. Seriile din folder sunt găsite automat.")

    def _paint_corners(self, p: QPainter, target: QRectF):
        v = self.view
        p.setFont(theme.mono_font(11))
        fm = p.fontMetrics()
        lh = fm.height() + 2
        r = QRect(12, 10, self.width() - 24, self.height() - 20)
        k, n = v.slider.value() + 1, v._volume.shape[0]
        width, center = v._window
        tl = [f"Felia {k} / {n}", f"{v._spacing[2]:.2f} mm"]
        tr = [f"W {width:.0f}  L {fmt_hu(center)}", v.window_name]
        bl = []
        if v.hover is not None:
            x, y, hu = v.hover
            bl.append(f"{fmt_hu(hu)} HU  ({x}, {y})")
        br = [f"selecție {v.overlay_fraction * 100:.1f} %"] if v.overlay_fraction is not None else []

        def block(lines, align, top: bool):
            for i, text in enumerate(lines):
                y = r.top() + i * lh if top else r.bottom() - (len(lines) - i) * lh
                rect = QRect(r.left(), y, r.width(), lh)
                p.setPen(QColor(0, 0, 0, 200))
                p.drawText(rect.translated(1, 1), align, text)
                p.setPen(QColor(theme.OVERLAY_TEXT))
                p.drawText(rect, align, text)

        block(tl, Qt.AlignLeft, True)
        block(tr, Qt.AlignRight, True)
        block(bl, Qt.AlignLeft, False)
        block(br, Qt.AlignRight, False)

        if v.orientation:
            top, bottom, left, right = v.orientation
            p.setFont(theme.mono_font(12, QFont.DemiBold))
            accent = QColor(theme.ACCENT)
            accent.setAlphaF(0.85)
            p.setPen(accent)
            cx, cy = target.center().x(), target.center().y()
            p.drawText(QRectF(cx - 10, max(target.top(), 0) + 6, 20, 16), Qt.AlignCenter, top)
            p.drawText(QRectF(cx - 10, min(target.bottom(), self.height()) - 22, 20, 16),
                       Qt.AlignCenter, bottom)
            p.drawText(QRectF(max(target.left(), 0) + 6, cy - 8, 16, 16), Qt.AlignCenter, left)
            p.drawText(QRectF(min(target.right(), self.width()) - 22, cy - 8, 16, 16),
                       Qt.AlignCenter, right)

    # ---------- mouse ----------

    def mouseMoveEvent(self, event):
        v = self.view
        target = self.image_rect()
        if v is None or target is None:
            return
        pos = event.position()
        h, w = v._volume.shape[1:]
        x = int((pos.x() - target.left()) / target.width() * w)
        y = int((pos.y() - target.top()) / target.height() * h)
        if 0 <= x < w and 0 <= y < h:
            v.hover = (x, y, float(v._volume[v.slider.value(), y, x]))
        else:
            v.hover = None
        self.update()

    def leaveEvent(self, event):
        if self.view is not None:
            self.view.hover = None
        self.update()

    def mousePressEvent(self, event):
        if self.view is not None and self.view._volume is None and event.button() == Qt.LeftButton:
            self.openRequested.emit()

    def wheelEvent(self, event):
        v = self.view
        if v is None or v._volume is None:
            return
        steps = event.angleDelta().y() // 120 or (1 if event.angleDelta().y() > 0 else -1)
        v.slider.setValue(v.slider.value() + steps)


class SliceView(QWidget):
    sliceChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._volume: np.ndarray | None = None
        self._threshold: tuple[float, float] | None = None
        self._mask: np.ndarray | None = None
        self._window = (400.0, 40.0)  # latime, centru (fereastra de tesut moale)
        self.window_name = ""
        self._aspect = 1.0  # spacing_y / spacing_x
        self._spacing = (1.0, 1.0, 1.0)
        self._color = QColor(theme.ACCENT)
        self.orientation: tuple[str, str, str, str] | None = None  # sus, jos, stanga, dreapta
        self.hover: tuple[int, int, float] | None = None
        self.overlay_fraction: float | None = None
        self._base_cache: tuple | None = None
        self._overlay_cache: tuple | None = None

        self.canvas = SliceCanvas()
        self.canvas.view = self
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.valueChanged.connect(self._on_slider)
        self.label = QLabel("–")
        self.label.setProperty("role", "value")
        self.label.setMinimumWidth(64)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.footer = QWidget()
        self.footer.setObjectName("vpFooter")
        row = QHBoxLayout(self.footer)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(12)
        row.addWidget(self.slider, 1)
        row.addWidget(self.label)
        self.footer.setFixedHeight(38)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.canvas, 1)

    # ---------- API folosit de fereastra principala ----------

    def set_volume(self, array: np.ndarray, spacing: tuple[float, float, float],
                   direction: tuple[float, ...] | None = None):
        self._volume = array
        self._mask = None
        self._spacing = spacing
        self._aspect = spacing[1] / spacing[0]
        self._base_cache = self._overlay_cache = None
        self.orientation = None
        if direction is not None and len(direction) == 9:
                    # coloanele matricei: directia axelor x (coloane) si y (randuri) ale imaginii
            d = np.array(direction, dtype=float).reshape(3, 3)
            col, row = d[:, 0], d[:, 1]
            self.orientation = (_orientation_letter(-row), _orientation_letter(row),
                                _orientation_letter(-col), _orientation_letter(col))
        n = array.shape[0]
        self.slider.blockSignals(True)
        self.slider.setRange(0, n - 1)
        self.slider.setValue(n // 2)
        self.slider.blockSignals(False)
        self.slider.setEnabled(True)
        self.canvas.setCursor(Qt.CrossCursor)
        self._update_label()
        self.canvas.fade_in()

    def set_window(self, width: float, center: float, name: str = ""):
        self._window = (max(width, 1.0), center)
        self.window_name = name
        self.canvas.update()

    def set_overlay_color(self, color: str):
        self._color = QColor(color)
        self._overlay_cache = None
        self.canvas.update()

    def set_threshold_preview(self, lower: float | None, upper: float | None = None):
        """Previzualizare rapida: pragul se aplica doar feliei curente."""
        self._threshold = None if lower is None else (lower, upper)
        self._overlay_cache = None
        self.canvas.update()

    def set_mask(self, mask: np.ndarray | None):
        """Masca finala (dupa post-procesare); are prioritate fata de previzualizare."""
        self._mask = mask
        self._overlay_cache = None
        if mask is not None:
            self.canvas.fade_in_overlay()
        self.canvas.update()

    def current_index(self) -> int:
        return self.slider.value()

    # ---------- imagini ----------

    def base_image(self) -> QImage:
        k = self.slider.value()
        key = (k, self._window)
        if self._base_cache is None or self._base_cache[0] != key:
            sl = self._volume[k].astype(np.float32)
            width, center = self._window
            gray = np.clip((sl - (center - width / 2)) / width, 0, 1) * 255
            gray = np.ascontiguousarray(gray.astype(np.uint8))
            h, w = gray.shape
            img = QImage(gray.data, w, h, w, QImage.Format_Grayscale8).copy()
            self._base_cache = (key, img)
        return self._base_cache[1]

    def overlay_image(self) -> QImage | None:
        k = self.slider.value()
        key = (k, id(self._mask), self._threshold, self._color.rgba())
        if self._overlay_cache is None or self._overlay_cache[0] != key:
            overlay = None
            if self._mask is not None:
                overlay = self._mask[k].astype(bool)
            elif self._threshold is not None:
                lo, hi = self._threshold
                sl = self._volume[k]
                overlay = (sl >= lo) & (sl <= hi)
            img = None
            self.overlay_fraction = None
            if overlay is not None:
                self.overlay_fraction = float(overlay.mean())
                if overlay.any():
                    h, w = overlay.shape
                    inner = overlay.copy()  # interiorul = pixelii cu toti vecinii in masca
                    inner[1:, :] &= overlay[:-1, :]
                    inner[:-1, :] &= overlay[1:, :]
                    inner[:, 1:] &= overlay[:, :-1]
                    inner[:, :-1] &= overlay[:, 1:]
                    rgba = np.zeros((h, w, 4), np.uint8)
                    c = self._color
                    rgba[overlay] = (c.red(), c.green(), c.blue(), round(255 * MASK_ALPHA))
                    if self._mask is not None:  # la previzualizare, zgomotul ar umple felia de contururi
                        rgba[overlay & ~inner] = (c.red(), c.green(), c.blue(), 255)
                    img = QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
            self._overlay_cache = (key, img)
        return self._overlay_cache[1]

    # ---------- evenimente ----------

    def _on_slider(self, value: int):
        if self.hover is not None:
            x, y, _ = self.hover
            self.hover = (x, y, float(self._volume[value, y, x]))
        self._update_label()
        self.canvas.update()
        self.sliceChanged.emit(value)

    def _update_label(self):
        if self._volume is not None:
            self.label.setText(f"{self.slider.value() + 1} / {self._volume.shape[0]}")
