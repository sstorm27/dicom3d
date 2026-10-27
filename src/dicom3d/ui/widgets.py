"""Componentele interfetei: comutatoare, histograma HU, butoane segmentate etc.

Animatiile sunt scurte (sub 300 ms), cu ease-out, si doar acolo unde arata o
schimbare de stare. Derularea feliilor si scurtaturile de tastatura raman instant.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import (
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from dicom3d.ui import icons, theme


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    return lbl


def fmt_hu(value: float) -> str:
    """Numar cu semnul minus tipografic (−), ca in viewerele medicale."""
    return f"{value:.0f}".replace("-", "−")


class _WheelGuard(QObject):
    """Rotita mouse-ului deruleaza panoul; nu schimba valori decat in campul activ."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        return False


_wheel_guard = _WheelGuard()


def guard_wheel(widget: QWidget):
    widget.setFocusPolicy(Qt.StrongFocus)
    widget.installEventFilter(_wheel_guard)


class FlowLayout(QLayout):
    """Asaza elementele pe randuri si trece pe randul urmator cand nu mai incap."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect, apply: bool) -> int:
        x, y, row_h = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and row_h > 0:
                x, y, row_h = rect.x(), y + row_h + self._spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_h = max(row_h, hint.height())
        return y + row_h - rect.y()


class ToggleSwitch(QCheckBox):
    """Comutator pornit/oprit: textul in stanga, comutatorul in dreapta."""

    W, H, KNOB = 32, 18, 12

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._pos = 0.0
        self._anim = QVariantAnimation(self, duration=theme.FAST, easingCurve=theme.EASE_OUT)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate_to)

    def _on_anim(self, value):
        self._pos = float(value)
        self.update()

    def _animate_to(self, on: bool):
        self._anim.stop()
        if not self.isVisible():
            self._on_anim(1.0 if on else 0.0)
            return
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.text()) + 16 + self.W, max(26, fm.height() + 8))

    def minimumSizeHint(self):
        return QSize(self.W + 40, self.sizeHint().height())

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        enabled = self.isEnabled()
        p.setPen(QColor(theme.TEXT if enabled else theme.FAINT))
        text_rect = r.adjusted(0, 0, -(self.W + 12), 0)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft,
                   self.fontMetrics().elidedText(self.text(), Qt.ElideRight, text_rect.width()))

        track = QRectF(r.right() - self.W, r.center().y() - self.H / 2 + 1, self.W, self.H)
        on = theme.mix(theme.INK3, theme.ACCENT, 0.38)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.mix(theme.INK3, on, self._pos) if enabled else QColor(theme.INK2))
        p.drawRoundedRect(track, self.H / 2, self.H / 2)
        if self.hasFocus() and self.focusPolicy() != Qt.NoFocus:
            p.setPen(QPen(QColor(theme.ACCENT), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(track.adjusted(-2, -2, 2, 2), self.H / 2 + 2, self.H / 2 + 2)
            p.setPen(Qt.NoPen)
        pad = (self.H - self.KNOB) / 2
        x = track.left() + pad + self._pos * (self.W - 2 * pad - self.KNOB)
        p.setBrush(theme.mix(theme.MUTED, theme.ACCENT, self._pos) if enabled else QColor(theme.FAINT))
        p.drawEllipse(QRectF(x, track.top() + pad, self.KNOB, self.KNOB))


class SegmentedControl(QFrame):
    """Butoane alaturate; checkable=True pastreaza o optiune aleasa."""

    currentTextChanged = Signal(str)
    clicked = Signal(str)

    def __init__(self, items, current: str | None = None, checkable: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for text in items:
            b = QPushButton(text)
            b.setCheckable(checkable)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.TabFocus)
            if checkable:
                self._group.addButton(b)
                b.toggled.connect(lambda on, t=text: on and self.currentTextChanged.emit(t))
            b.clicked.connect(lambda _=False, t=text: self.clicked.emit(t))
            lay.addWidget(b)
            self._buttons[text] = b
        if checkable:
            self._buttons[current or next(iter(self._buttons))].setChecked(True)

    def currentText(self) -> str:
        b = self._group.checkedButton()
        return b.text() if b else ""

    def setCurrentText(self, text: str):
        self._buttons[text].setChecked(True)


class TissueChips(QWidget):
    """Alegerea tesutului. `activated` se emite la orice click, si pe tesutul deja ales,
    ca re-alegerea sa refaca pragurile."""

    activated = Signal(str)

    def __init__(self, names, parent=None):
        super().__init__(parent)
        lay = FlowLayout(self, spacing=6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for name in names:
            color = theme.TISSUE_COLORS.get(name, theme.ACCENT)
            b = QPushButton(" " + theme.TISSUE_LABELS.get(name, name))
            b.setProperty("variant", "chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(icons.dot(color))
            b.setIconSize(QSize(10, 10))
            fill = theme.mix(theme.INK2, color, 0.13).name()
            b.setStyleSheet(f"QPushButton:checked {{ border-color: {color}; background: {fill}; }}")
            b.clicked.connect(lambda _=False, n=name: self.activated.emit(n))
            self._group.addButton(b)
            lay.addWidget(b)
            self._buttons[name] = b

    def names(self) -> list[str]:
        return list(self._buttons)

    def current(self) -> str:
        for name, b in self._buttons.items():
            if b.isChecked():
                return name
        return next(iter(self._buttons))

    def set_current(self, name: str):
        self._buttons[name].setChecked(True)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.layout().heightForWidth(width)


class HistogramRange(QWidget):
    """Histograma valorilor HU din serie, cu intervalul de prag tras cu mouse-ul."""

    rangeEdited = Signal(int, int)

    BINS = 150
    HANDLE_GRAB = 8  # px in jurul unui maner in care il poti apuca

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(84)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._bars: np.ndarray | None = None
        self._dom = (-1024.0, 3071.0)
        self._lo, self._hi = 0.0, 0.0
        self._color = QColor(theme.ACCENT)
        self._drag: int | None = None
        self._anim = QVariantAnimation(self, duration=theme.NORMAL, easingCurve=theme.EASE_OUT)
        self._anim.valueChanged.connect(self._on_anim)

    def sizeHint(self):
        return QSize(260, 84)

    # ---------- date ----------

    def set_values(self, values: np.ndarray):
        lo = max(float(values.min()), -1024.0)
        hi = min(float(values.max()), 3071.0)
        if hi <= lo:
            hi = lo + 1
        counts, _ = np.histogram(values, bins=self.BINS, range=(lo, hi))
        bars = np.sqrt(counts.astype(np.float64))  # radacina: se vad si varfurile mici (osul)
        self._bars = bars / bars.max() if bars.max() > 0 else bars
        self._dom = (lo, hi)
        self.update()

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def set_range(self, lo: float, hi: float, animate: bool = False):
        self._anim.stop()
        if animate and self._drag is None and self.isVisible() and self._bars is not None:
            self._anim.setStartValue(QPointF(self._lo, self._hi))
            self._anim.setEndValue(QPointF(lo, hi))
            self._anim.start()
        else:
            self._lo, self._hi = float(lo), float(hi)
            self.update()

    def _on_anim(self, value: QPointF):
        self._lo, self._hi = value.x(), value.y()
        self.update()

    # ---------- geometrie ----------

    def _plot(self) -> QRectF:
        return QRectF(self.rect()).adjusted(8, 10, -8, -20)

    def _x(self, hu: float) -> float:
        r = self._plot()
        lo, hi = self._dom
        t = min(max((hu - lo) / (hi - lo), 0.0), 1.0)
        return r.left() + t * r.width()

    def _hu(self, x: float) -> int:
        r = self._plot()
        lo, hi = self._dom
        t = min(max((x - r.left()) / r.width(), 0.0), 1.0)
        return int(round(lo + t * (hi - lo)))

    # ---------- desenare ----------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.LINE), 1))
        p.setBrush(QColor(theme.INK0))
        p.drawRoundedRect(frame, 8, 8)

        if self._bars is None:
            p.setPen(QColor(theme.FAINT))
            p.drawText(self.rect(), Qt.AlignCenter, "Histograma HU apare după încărcare")
            return

        plot = self._plot()
        x0, x1 = self._x(self._lo), self._x(self._hi)
        band = QColor(self._color)
        band.setAlphaF(0.10)
        p.fillRect(QRectF(x0, plot.top() - 4, max(x1 - x0, 1), plot.height() + 4), band)

        lo, hi = self._dom
        step = plot.width() / len(self._bars)
        idle = QColor("#32465a")
        p.setPen(Qt.NoPen)
        for i, v in enumerate(self._bars):
            h = max(1.0, v * plot.height())
            hu_mid = lo + (i + 0.5) / len(self._bars) * (hi - lo)
            p.setBrush(self._color if self._lo <= hu_mid <= self._hi else idle)
            p.drawRect(QRectF(plot.left() + i * step, plot.bottom() - h, max(step - 1, 1), h))

        for x in (x0, x1):
            p.setBrush(QColor(theme.ACCENT))
            p.drawRect(QRectF(x - 1, plot.top() - 4, 2, plot.height() + 4))
            p.drawEllipse(QPointF(x, plot.top() - 2), 4.5, 4.5)

        p.setFont(theme.mono_font(10))
        p.setPen(QColor(theme.FAINT))
        y = int(plot.bottom()) + 4
        p.drawText(QRect(int(plot.left()), y, 80, 14), Qt.AlignLeft, fmt_hu(lo))
        p.drawText(QRect(int(plot.right()) - 80, y, 80, 14), Qt.AlignRight, f"{fmt_hu(hi)} HU")
        if lo < 0 < hi and plot.width() > 200:
            zx = int(self._x(0))
            p.drawText(QRect(zx - 20, y, 40, 14), Qt.AlignHCenter, "0")

    # ---------- mouse ----------

    def _nearest(self, x: float) -> int:
        return 0 if abs(x - self._x(self._lo)) <= abs(x - self._x(self._hi)) else 1

    def mousePressEvent(self, event):
        if self._bars is None or event.button() != Qt.LeftButton:
            return
        self._anim.stop()
        self._drag = self._nearest(event.position().x())
        self._drag_to(event.position().x())

    def mouseMoveEvent(self, event):
        x = event.position().x()
        if self._drag is not None:
            self._drag_to(x)
            return
        near = self._bars is not None and min(abs(x - self._x(self._lo)),
                                              abs(x - self._x(self._hi))) <= self.HANDLE_GRAB
        self.setCursor(Qt.SizeHorCursor if near else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self._drag = None

    def _drag_to(self, x: float):
        hu = self._hu(x)
        if self._drag == 0:
            self._lo = min(hu, self._hi)
        else:
            self._hi = max(hu, self._lo)
        self.update()
        self.rangeEdited.emit(int(self._lo), int(self._hi))


class ValueSlider(QWidget):
    """Slider cu eticheta si valoarea afisata; accepta si pasi zecimali."""

    valueChanged = Signal(float)

    def __init__(self, text: str, minimum: float, maximum: float, step: float = 1,
                 value: float = 0, suffix: str = "", decimals: int = 0, parent=None):
        super().__init__(parent)
        self._step, self._suffix, self._decimals = step, suffix, decimals
        self.title = label(text)
        self.value_label = label("", "value")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(round(minimum / step), round(maximum / step))
        self.slider.setCursor(Qt.PointingHandCursor)
        guard_wheel(self.slider)
        self.slider.valueChanged.connect(self._on_change)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.value_label)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addLayout(head)
        lay.addWidget(self.slider)
        self.setValue(value)
        self._show(self.value())

    def value(self) -> float:
        v = self.slider.value() * self._step
        return int(round(v)) if self._decimals == 0 else round(v, self._decimals)

    def setValue(self, value: float):
        self.slider.setValue(round(value / self._step))

    def setToolTip(self, text: str):
        super().setToolTip(text)
        self.title.setToolTip(text)
        self.slider.setToolTip(text)

    def _show(self, v: float):
        self.value_label.setText(f"{v:.{self._decimals}f}{self._suffix}")

    def _on_change(self, _):
        v = self.value()
        self._show(v)
        self.valueChanged.emit(v)


class HUSpinBox(QSpinBox):
    """Camp pentru un prag in unitati Hounsfield, afisat cu minusul tipografic."""

    def textFromValue(self, value):
        return fmt_hu(value)

    def valueFromText(self, text):
        return super().valueFromText(text.replace("−", "-"))

    def validate(self, text, pos):
        result = super().validate(text.replace("−", "-"), pos)
        state = result[0] if isinstance(result, tuple) else result
        return state, text, pos


def hu_spin() -> QSpinBox:
    # sagetile sunt ascunse din foaia de stil (cu NoButtons, Qt strica latimea textului)
    s = HUSpinBox()
    s.setRange(-3000, 10000)
    s.setSingleStep(10)
    s.setSuffix(" HU")
    s.setKeyboardTracking(False)
    s.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    s.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    guard_wheel(s)
    return s


class Banner(QFrame):
    """Avertisment discret care apare si dispare lin (inaltime + opacitate)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        self.icon = QLabel()
        self.icon.setPixmap(icons.pixmap("warning", 16, theme.WARN, 2.0))
        self.icon.setAlignment(Qt.AlignTop)
        self.text = label("", wrap=True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        lay.addWidget(self.text, 1)
        self._effect = QGraphicsOpacityEffect(self, opacity=1.0)
        self.setGraphicsEffect(self._effect)
        self._group: QParallelAnimationGroup | None = None
        self.setMaximumHeight(0)
        self.hide()

    def show_message(self, text: str):
        changed = text != self.text.text()
        self.text.setText(text)
        if self.isVisible() and self._group is None:
            if changed:
                self.setMaximumHeight(self._target_height())
            return
        self.show()
        self._animate(self._target_height(), 1.0, theme.NORMAL)

    def dismiss(self):
        if not self.isVisible():
            return
        self._animate(0, 0.0, theme.FAST, hide_after=True)

    def _target_height(self) -> int:
        w = self.width() or (self.parentWidget().width() if self.parentWidget() else 280)
        return max(self.layout().totalHeightForWidth(w), self.sizeHint().height())

    def _animate(self, height: int, opacity: float, duration: int, hide_after: bool = False):
        if self._group is not None:
            self._group.stop()
        group = QParallelAnimationGroup(self)
        for target, prop, end in ((self, b"maximumHeight", height), (self._effect, b"opacity", opacity)):
            a = QPropertyAnimation(target, prop, group)
            a.setDuration(duration)
            a.setEasingCurve(theme.EASE_OUT)
            a.setEndValue(end)
            group.addAnimation(a)

        def done():
            self._group = None
            if hide_after:
                self.hide()
                self.text.setText("")

        group.finished.connect(done)
        self._group = group
        group.start()


class BusyBar(QWidget):
    """Linie subtire de progres nedeterminat; ocupa mereu acelasi loc, ca layout-ul sa nu sara."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(2)
        self._t = 0.0
        self._anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1100)
        self._anim.setLoopCount(-1)  # miscare continua: liniara
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, v):
        self._t = float(v)
        self.update()

    def start(self):
        self._anim.start()

    def stop(self):
        self._anim.stop()
        self.update()

    def running(self) -> bool:
        return self._anim.state() == QVariantAnimation.Running

    def paintEvent(self, event):
        if not self.running():
            return
        p = QPainter(self)
        w = self.width()
        seg = w * 0.3
        x = -seg + self._t * (w + seg)
        g = QLinearGradient(x, 0, x + seg, 0)
        clear = QColor(theme.ACCENT)
        clear.setAlpha(0)
        g.setColorAt(0, clear)
        g.setColorAt(0.5, QColor(theme.ACCENT))
        g.setColorAt(1, clear)
        p.fillRect(QRectF(x, 0, seg, self.height()), g)


class StatusDot(QWidget):
    """Bulina de stare din bara de jos: gata, in lucru sau eroare."""

    COLORS = {"ok": theme.OK, "busy": theme.ACCENT, "error": theme.DANGER, "idle": theme.FAINT}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._kind = "idle"

    def set_kind(self, kind: str):
        self._kind = kind
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self.COLORS[self._kind])
        halo = QColor(c)
        halo.setAlphaF(0.22)
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(7, 7), 6, 6)
        p.setBrush(c)
        p.drawEllipse(QPointF(7, 7), 3.5, 3.5)


def icon_button(name: str, tooltip: str) -> QPushButton:
    b = QPushButton()
    b.setProperty("variant", "icon")
    b.setIcon(icons.icon(name, theme.MUTED))
    b.setIconSize(QSize(16, 16))
    b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b

