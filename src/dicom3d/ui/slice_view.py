"""Vizualizare 2D a feliilor, cu fereastra CT si suprapunerea mastii.

Felia si masca se deseneaza ca doua imagini separate, ca masca sa poata aparea
lin peste felie. In colturi stau informatiile, ca intr-un viewer medical; pe
marginea stanga si sub felie sunt rigle in centimetri, iar in dreapta o scala
gradata a feliilor, pe care se poate da click sau trage.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QSlider, QVBoxLayout, QWidget

from dicom3d.ui import icons, theme
from dicom3d.ui.widgets import fmt_hu, fmt_num

MASK_ALPHA = 0.40  # interiorul mastii; conturul se deseneaza opac, ca sa se vada pe orice tesut

# marginile din jurul feliei: colturile cu text, riglele si scala feliilor
M_LEFT, M_TOP, M_RIGHT, M_BOTTOM = 30, 42, 32, 54
SCRUB_GAP = 12  # distanta dintre felie si scala feliilor


def _orientation_letter(vec) -> str:
    """Litera directiei anatomice (LPS) pentru un vector din matricea de directie."""
    i = int(np.argmax(np.abs(vec)))
    return ("L", "P", "S")[i] if vec[i] > 0 else ("R", "A", "I")[i]


def _ruler_steps(px_per_mm: float) -> tuple[int, int, int]:
    """Pasii riglei in mm: gradatie mica, medie si cea cu valoare (la cel putin 4 px / 30 px)."""
    minor = 10 if 10 * px_per_mm >= 4 else 50
    labeled = 100 if 100 * px_per_mm >= 30 else 200
    return minor, 50, labeled


class SliceCanvas(QWidget):
    openRequested = Signal()
    hoverChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(280, 280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.ClickFocus)
        self.view: SliceView | None = None
        self.drop_hover = False
        self.fade = 1.0
        self.overlay_fade = 1.0
        self._scrubbing = False
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
        area = QRectF(self.rect()).adjusted(M_LEFT, M_TOP, -M_RIGHT, -M_BOTTOM)
        scale = max(min(area.width() / w, area.height() / h_eff), 0.01)
        tw, th = w * scale, h_eff * scale
        return QRectF(area.center().x() - tw / 2, area.center().y() - th / 2, tw, th)

    def _scrub_x(self, target: QRectF) -> float:
        return round(target.right() + SCRUB_GAP) + 0.5

    def _in_scrubber(self, pos: QPointF, target: QRectF) -> bool:
        x = self._scrub_x(target)
        return x - 8 <= pos.x() <= x + 16 and target.top() - 6 <= pos.y() <= target.bottom() + 6

    def _slice_at(self, y: float, target: QRectF) -> int:
        n = self.view._volume.shape[0]
        t = min(max((y - target.top()) / max(target.height(), 1), 0.0), 1.0)
        return round(t * (n - 1))

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
        self._paint_rulers(p, target)
        self._paint_scrubber(p, target)
        self._paint_corners(p, target)

    def _paint_empty(self, p: QPainter):
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(0, 0, min(360, self.width() - 32), 168)
        box.moveCenter(QPointF(self.rect().center()))
        pen = QPen(QColor(theme.TEXT if self.drop_hover else theme.LINE_STRONG), 1)
        if not self.drop_hover:
            pen.setDashPattern([4, 4])
        p.setPen(pen)
        fill = QColor(theme.TEXT)
        fill.setAlphaF(0.05 if self.drop_hover else 0.0)
        p.setBrush(fill)
        p.drawRect(box.adjusted(0.5, 0.5, -0.5, -0.5))
        ic = icons.pixmap("upload", 28, theme.TEXT if self.drop_hover else theme.MUTED, 1.6)
        p.drawPixmap(QRectF(box.center().x() - 14, box.top() + 32, 28, 28).toRect(), ic)
        p.setFont(theme.sans_font(15, QFont.DemiBold))
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(box.left(), box.top() + 72, box.width(), 24), Qt.AlignCenter,
                   "Trage aici un folder DICOM")
        p.setFont(theme.sans_font(13))
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(box.left() + 16, box.top() + 100, box.width() - 32, 44),
                   Qt.AlignCenter | Qt.TextWordWrap,
                   "sau apasă Ctrl+O ori fă clic aici. Seriile din folder sunt găsite automat.")

    def _paint_rulers(self, p: QPainter, target: QRectF):
        """Rigle in centimetri sub felie si in stanga ei, la scara reala a imaginii."""
        v = self.view
        h, w = v._volume.shape[1:]
        width_mm, height_mm = w * v._spacing[0], h * v._spacing[1]
        ppm = target.width() / width_mm
        minor, mid, labeled = _ruler_steps(ppm)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(QPen(QColor(theme.TICK), 1))
        y0 = round(target.bottom()) + 4
        for mm in range(0, int(width_mm) + 1, minor):
            x = round(target.left() + mm * ppm)
            length = 9 if mm % labeled == 0 else 6 if mm % mid == 0 else 3
            p.drawLine(x, y0, x, y0 + length)
        x0 = round(target.left()) - 4
        for mm in range(0, int(height_mm) + 1, minor):
            y = round(target.top() + mm * ppm)
            length = 9 if mm % labeled == 0 else 6 if mm % mid == 0 else 3
            p.drawLine(x0, y, x0 - length, y)
        p.setFont(theme.num_font(11))
        p.setPen(QColor(theme.FAINT))
        marks = list(range(0, int(width_mm) + 1, labeled))
        for i, mm in enumerate(marks):
            x = target.left() + mm * ppm
            text = f"{mm // 10} cm" if i == len(marks) - 1 else f"{mm // 10}"
            align = Qt.AlignLeft if i == 0 else Qt.AlignHCenter
            rect = QRectF(x - (0 if i == 0 else 30), y0 + 11, 60 if i == 0 else 60, 14)
            p.drawText(rect, align | Qt.AlignTop, text)
        for mm in range(labeled, int(height_mm) + 1, labeled):  # 0 e deja pe rigla de jos
            y = target.top() + mm * ppm
            p.drawText(QRectF(x0 - 9 - 3 - 24, y - 7, 24, 14), Qt.AlignRight | Qt.AlignVCenter,
                       f"{mm // 10}")
        p.setRenderHint(QPainter.Antialiasing)

    def _paint_scrubber(self, p: QPainter, target: QRectF):
        v = self.view
        n = v._volume.shape[0]
        x = self._scrub_x(target)
        top, bottom = target.top(), target.bottom()
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(QPen(QColor(theme.LINE_STRONG), 1))
        p.drawLine(QPointF(x, top), QPointF(x, bottom))
        step = 10 if (bottom - top) / max(n - 1, 1) * 10 >= 6 else 50
        p.setPen(QPen(QColor(theme.TICK), 1))
        for k in range(0, n, step):
            y = round(top + k / max(n - 1, 1) * (bottom - top))
            p.drawLine(QPointF(x, y + 0.5), QPointF(x + 6, y + 0.5))
        k = v.slider.value()
        y = top + k / max(n - 1, 1) * (bottom - top)
        p.fillRect(QRectF(x - 0.5, y - 1.5, 14, 3), QColor(theme.TEXT))
        p.setRenderHint(QPainter.Antialiasing)

    def _paint_corners(self, p: QPainter, target: QRectF):
        v = self.view
        p.setFont(theme.num_font(13))
        fm = p.fontMetrics()
        lh = fm.height() + 1
        r = QRect(12, 9, self.width() - 24, self.height() - 16)
        k, n = v.slider.value() + 1, v._volume.shape[0]
        width, center = v._window
        tl = [(f"Felia {k} / {n}", theme.OVERLAY_TEXT),
              (f"grosime {fmt_num(v._spacing[2], 1)} mm", theme.FAINT)]
        tr = [(f"Fereastră {width:.0f} · Nivel {fmt_hu(center)}", theme.OVERLAY_TEXT)]
        if v.window_name:
            tr.append((f"presetare {v.window_name}", theme.FAINT))
        bl = []
        if v.hover is not None:
            x, y, hu = v.hover
            bl.append((f"HU {fmt_hu(hu)} · ({x}, {y})", theme.OVERLAY_TEXT))
        br = []
        if v.overlay_fraction is not None:
            br.append((f"selecție {fmt_num(v.overlay_fraction * 100, 1)} %", theme.OVERLAY_TEXT))

        def block(lines, align, top: bool):
            for i, (text, color) in enumerate(lines):
                y = r.top() + i * lh if top else r.bottom() - (len(lines) - i) * lh
                p.setPen(QColor(color))
                p.drawText(QRect(r.left(), y, r.width(), lh), align, text)

        block(tl, Qt.AlignLeft, True)
        block(tr, Qt.AlignRight, True)
        block(bl, Qt.AlignLeft, False)
        block(br, Qt.AlignRight, False)

        if v.orientation:
            top, bottom, left, right = v.orientation
            p.setFont(theme.sans_font(13, QFont.DemiBold))
            p.setPen(QColor(theme.OVERLAY_TEXT))
            cx, cy = target.center().x(), target.center().y()
            p.drawText(QRectF(cx - 10, target.top() + 4, 20, 16), Qt.AlignCenter, top)
            p.drawText(QRectF(cx - 10, target.bottom() - 20, 20, 16), Qt.AlignCenter, bottom)
            p.drawText(QRectF(target.left() + 4, cy - 8, 16, 16), Qt.AlignCenter, left)
            p.drawText(QRectF(target.right() - 20, cy - 8, 16, 16), Qt.AlignCenter, right)

    # ---------- mouse si tastatura ----------

    def mouseMoveEvent(self, event):
        v = self.view
        target = self.image_rect()
        if v is None or target is None:
            return
        pos = event.position()
        if self._scrubbing:
            v.slider.setValue(self._slice_at(pos.y(), target))
            return
        self.setCursor(Qt.SizeVerCursor if self._in_scrubber(pos, target) else Qt.CrossCursor)
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
        v = self.view
        if v is None or event.button() != Qt.LeftButton:
            return
        if v._volume is None:
            self.openRequested.emit()
            return
        target = self.image_rect()
        if self._in_scrubber(event.position(), target):
            self._scrubbing = True
            v.slider.setValue(self._slice_at(event.position().y(), target))

    def mouseReleaseEvent(self, event):
        self._scrubbing = False

    def wheelEvent(self, event):
        v = self.view
        if v is None or v._volume is None:
            return
        steps = event.angleDelta().y() // 120 or (1 if event.angleDelta().y() > 0 else -1)
        v.slider.setValue(v.slider.value() + steps)

    def keyPressEvent(self, event):
        v = self.view
        if v is None or v._volume is None:
            return super().keyPressEvent(event)
        n = v._volume.shape[0]
        moves = {Qt.Key_Up: -1, Qt.Key_Down: 1, Qt.Key_PageUp: -10, Qt.Key_PageDown: 10}
        if event.key() in moves:
            v.slider.setValue(v.slider.value() + moves[event.key()])
        elif event.key() == Qt.Key_Home:
            v.slider.setValue(0)
        elif event.key() == Qt.Key_End:
            v.slider.setValue(n - 1)
        else:
            super().keyPressEvent(event)


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
        self._color = QColor(theme.TEXT)
        self.orientation: tuple[str, str, str, str] | None = None  # sus, jos, stanga, dreapta
        self.hover: tuple[int, int, float] | None = None
        self.overlay_fraction: float | None = None
        self._base_cache: tuple | None = None
        self._overlay_cache: tuple | None = None

        self.canvas = SliceCanvas()
        self.canvas.view = self
        # felia curenta; scala gradata de pe felie e cea pe care o vede utilizatorul
        self.slider = QSlider(Qt.Vertical, self)
        self.slider.hide()
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._on_slider)

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
        self.canvas.setFocusPolicy(Qt.StrongFocus)
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
        self.canvas.update()
        self.sliceChanged.emit(value)
