"""Componentele interfetei: rigla Hounsfield, casete de bifat, file, campuri HU etc.

Animatiile sunt scurte (sub 300 ms), cu ease-out, si doar acolo unde arata o
schimbare de stare. Derularea feliilor si scurtaturile de tastatura raman instant.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import (
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from dicom3d.ui import icons, theme


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    return lbl


def value_label(text: str = "", size: int = 13, muted: bool = True) -> QLabel:
    """Eticheta pentru numere: cifre tabulare, ca valorile sa nu sara cand se schimba."""
    lbl = label(text, "muted" if muted else None)
    lbl.setFont(theme.num_font(size))
    return lbl


def fmt_hu(value: float) -> str:
    """Numar cu semnul minus tipografic (−), ca in viewerele medicale."""
    return f"{value:.0f}".replace("-", "−")


def fmt_num(value: float, decimals: int = 1) -> str:
    """Numar zecimal in scrierea romaneasca: virgula zecimala, minus tipografic."""
    return f"{value:.{decimals}f}".replace(".", ",").replace("-", "−")


def fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


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


def separator(vertical: bool = False) -> QFrame:
    line = QFrame()
    line.setObjectName("vsep" if vertical else "sep")
    return line


class ElidedLabel(QLabel):
    """Text pe un rand care se scurteaza cu „…” cand nu incape (nu largeste layout-ul)."""

    def __init__(self, text: str = "", role: str | None = None, parent=None):
        super().__init__(text, parent)
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

    def paintEvent(self, event):
        p = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, rect.width())
        self.style().drawItemText(p, rect, int(self.alignment()) | Qt.AlignVCenter, self.palette(),
                                  self.isEnabled(), text, self.foregroundRole())


class CheckRow(QCheckBox):
    """Caseta de bifat patrata, cu textul in dreapta; tot randul se poate apasa."""

    BOX = 14

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + self.BOX + 12, 26)

    def minimumSizeHint(self):
        return QSize(self.BOX + 40, 26)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        box = QRectF(0.5, (self.height() - self.BOX) / 2 + 0.5, self.BOX - 1, self.BOX - 1)
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.TEXT if enabled else theme.FAINT))
            p.drawRect(box.adjusted(-0.5, -0.5, 0.5, 0.5))
            check = QPainterPath(QPointF(box.left() + 3, box.center().y() + 0.5))
            check.lineTo(box.left() + 5.8, box.center().y() + 3.2)
            check.lineTo(box.right() - 2.6, box.top() + 3.4)
            p.setPen(QPen(QColor(theme.INK0), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(check)
        else:
            hover = enabled and self.underMouse()
            p.setPen(QPen(QColor(theme.MUTED if hover else theme.LINE_STRONG), 1))
            p.setBrush(QColor(theme.INK2))
            p.drawRect(box)
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.TEXT), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(box.adjusted(-2.5, -2.5, 2.5, 2.5))
        p.setPen(QColor(theme.TEXT if enabled else theme.FAINT))
        text_rect = self.rect().adjusted(self.BOX + 10, 0, 0, 0)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft,
                   self.fontMetrics().elidedText(self.text(), Qt.ElideRight, text_rect.width()))


class SegmentedControl(QWidget):
    """File de text subliniate (fereastra CT, vederile 3D); checkable=True pastreaza alegerea."""

    currentTextChanged = Signal(str)
    clicked = Signal(str)

    def __init__(self, items, current: str | None = None, checkable: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("tabs")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
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
            lay.addWidget(b, 0, Qt.AlignBottom)
            self._buttons[text] = b
        if checkable:
            self._buttons[current or next(iter(self._buttons))].setChecked(True)

    def currentText(self) -> str:
        b = self._group.checkedButton()
        return b.text() if b else ""

    def setCurrentText(self, text: str):
        self._buttons[text].setChecked(True)


class HounsfieldRuler(QWidget):
    """Scala Hounsfield verticala: pragul, histograma seriei si presetarile pe aceeasi gradatie.

    Sus sunt valorile mari (osul), jos aerul, ca pe un termometru. Intervalul ales se trage
    de cele doua manere; o presetare se alege cu click pe numele ei sau cu sagetile sus/jos.
    Paranteza de langa presetarea aleasa arata intervalul ei de referinta.
    """

    rangeEdited = Signal(int, int)
    presetActivated = Signal(str)

    LO, HI = -1024.0, 3071.0
    BINS = 160
    PAD = 10
    AXIS = 44  # x-ul axei; la stanga ei stau valorile scalei
    GRAB = 7  # px in jurul unui maner in care il poti apuca
    ROW = 16  # distanta minima intre numele presetarilor

    def __init__(self, presets: dict, parent=None):
        super().__init__(parent)
        self._presets = [(name, float(p.lower), float(p.upper)) for name, p in presets.items()]
        self._current = self._presets[0][0]
        self._hover: str | None = None
        self._bars: np.ndarray | None = None
        self._lo, self._hi = self._presets[0][1], self._presets[0][2]
        self._color = QColor(theme.TISSUE_COLORS.get(self._current, theme.TEXT))
        self._drag: int | None = None
        self._anim = QVariantAnimation(self, duration=theme.NORMAL, easingCurve=theme.EASE_OUT)
        self._anim.valueChanged.connect(self._on_anim)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(130)
        self.setAccessibleName("Scala Hounsfield: prag și presetări de țesut")

    def sizeHint(self):
        return QSize(248, 300)

    def minimumSizeHint(self):
        return QSize(180, 130)

    # ---------- API ----------

    def names(self) -> list[str]:
        return [name for name, _, _ in self._presets]

    def current(self) -> str:
        return self._current

    def set_current(self, name: str):
        self._current = name
        self.update()

    def activate(self, name: str):
        """Alegerea unei presetari, ca de la utilizator (click sau tastatura)."""
        self.set_current(name)
        self.presetActivated.emit(name)

    def set_values(self, values: np.ndarray):
        counts, _ = np.histogram(np.clip(values, self.LO, self.HI), bins=self.BINS,
                                 range=(self.LO, self.HI))
        bars = np.log1p(counts.astype(np.float64))  # logaritmic: se vad si varfurile mici (osul)
        self._bars = bars / bars.max() if bars.max() > 0 else bars
        self.update()

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def set_range(self, lo: float, hi: float, animate: bool = False):
        self._anim.stop()
        if animate and self._drag is None and self.isVisible():
            self._anim.setStartValue(QPointF(self._lo, self._hi))
            self._anim.setEndValue(QPointF(lo, hi))
            self._anim.start()
        else:
            self._lo, self._hi = float(lo), float(hi)
            self.update()

    def range(self) -> tuple[float, float]:
        return self._lo, self._hi

    def _on_anim(self, value: QPointF):
        self._lo, self._hi = value.x(), value.y()
        self.update()

    # ---------- geometrie ----------

    def _top(self) -> float:
        return self.PAD

    def _bottom(self) -> float:
        return self.height() - self.PAD

    def _y(self, hu: float) -> float:
        t = (self.HI - min(max(hu, self.LO), self.HI)) / (self.HI - self.LO)
        return self._top() + t * (self._bottom() - self._top())

    def _hu(self, y: float) -> int:
        t = min(max((y - self._top()) / (self._bottom() - self._top()), 0.0), 1.0)
        return int(round(self.HI - t * (self.HI - self.LO)))

    def _cols(self) -> dict[str, float]:
        hist0 = self.AXIS + 8
        hist_w = min(max((self.width() - hist0) * 0.3, 36.0), 80.0)
        band1 = hist0 + hist_w + 6
        bracket = band1 + 14
        return {"hist0": hist0, "hist_w": hist_w, "band1": band1, "bracket": bracket,
                "swatch": bracket + 8, "text": bracket + 20}

    def _anchor(self, lo: int, hi: int) -> float:
        """Unde sta eticheta unui tesut pe scala: la mijlocul intervalului sau, pentru
        intervalele deschise in sus (os, piele), acolo unde incepe tesutul."""
        if hi >= 3000:
            return self._y(lo)
        return (self._y(lo) + self._y(hi)) / 2

    def _label_rows(self) -> list[tuple[str, float, float, float]]:
        """(nume, y eticheta, y sus, y jos), cu etichetele departate cat sa nu se suprapuna."""
        rows = sorted(((n, self._anchor(lo, hi), self._y(hi), self._y(lo))
                       for n, lo, hi in self._presets), key=lambda r: r[1])
        ys = [r[1] for r in rows]
        for i in range(1, len(ys)):
            ys[i] = max(ys[i], ys[i - 1] + self.ROW)
        ys[-1] = min(ys[-1], self._bottom() - 4)
        for i in range(len(ys) - 2, -1, -1):
            ys[i] = min(ys[i], ys[i + 1] - self.ROW)
        return [(n, y, top, bottom) for (n, _, top, bottom), y in zip(rows, ys)]

    def _preset_at(self, pos: QPointF) -> str | None:
        if pos.x() < self._cols()["bracket"] - 4:
            return None
        for name, y, _, _ in self._label_rows():
            if abs(pos.y() - y) <= self.ROW / 2:
                return name
        return None

    # ---------- desenare ----------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._cols()
        top, bottom = self._top(), self._bottom()
        axis = self.AXIS + 0.5

        # scala: gradatii la 100 HU, valori la 500 (la 1000 cand rigla e scunda)
        every = 500 if bottom - top >= 220 else 1000
        p.setFont(theme.num_font(11))
        tick_pen = QPen(QColor(theme.TICK), 1)
        for hu in range(-1000, 3001, 100):
            y = round(self._y(hu)) + 0.5
            major = hu % 500 == 0
            p.setPen(tick_pen)
            p.drawLine(QPointF(axis, y), QPointF(axis + (8 if major else 4), y))
            if hu % every == 0:
                p.setPen(QColor(theme.FAINT))
                p.drawText(QRectF(0, y - 8, self.AXIS - 8, 16), Qt.AlignRight | Qt.AlignVCenter,
                           fmt_hu(hu))
        p.setPen(QPen(QColor(theme.LINE_STRONG), 1))
        p.drawLine(QPointF(axis, top), QPointF(axis, bottom))

        # intervalul ales si histograma
        y_hi, y_lo = self._y(self._hi), self._y(self._lo)
        band = QColor(self._color)
        band.setAlphaF(0.07)
        p.fillRect(QRectF(axis + 0.5, y_hi, c["band1"] - axis, max(y_lo - y_hi, 1)), band)
        if self._bars is not None:
            idle = QColor("#2f3736")
            sel = QColor(self._color)
            sel.setAlphaF(0.6)
            width = (self.HI - self.LO) / len(self._bars)
            p.setPen(Qt.NoPen)
            for i, v in enumerate(self._bars):
                if v <= 0:
                    continue
                a, b = self.LO + i * width, self.LO + (i + 1) * width
                ya, yb = self._y(a), self._y(b)
                p.setBrush(sel if self._lo <= (a + b) / 2 <= self._hi else idle)
                p.drawRect(QRectF(c["hist0"], yb, max(v * c["hist_w"], 1.0), ya - yb + 0.4))

        p.setPen(QPen(self._color, 1.5))
        for y in (y_hi, y_lo):
            p.drawLine(QPointF(axis - 6, y), QPointF(c["band1"], y))
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        for y in (y_hi, y_lo):
            p.drawPolygon(QPolygonF([QPointF(c["band1"], y), QPointF(c["band1"] + 6, y - 4.5),
                                     QPointF(c["band1"] + 6, y + 4.5)]))

        # presetarile: numele la mijlocul intervalului lor de referinta
        for name, y, y_top, y_bottom in self._label_rows():
            color = QColor(theme.TISSUE_COLORS.get(name, theme.TEXT))
            current, hover = name == self._current, name == self._hover
            if current or hover:
                p.setPen(QPen(color if current else QColor(theme.MUTED), 2 if current else 1))
                x = c["bracket"]
                p.drawLine(QPointF(x, y_top), QPointF(x, y_bottom))
                p.drawLine(QPointF(x - 4, y_top), QPointF(x, y_top))
                p.drawLine(QPointF(x - 4, y_bottom), QPointF(x, y_bottom))
            p.fillRect(QRectF(c["swatch"], y - 3, 6, 6), color)
            text = theme.TISSUE_LABELS.get(name, name)
            font = theme.sans_font(13, QFont.DemiBold if current else QFont.Normal)
            p.setFont(font)
            p.setPen(color if current else QColor(theme.TEXT if hover else theme.MUTED))
            avail = self.width() - c["text"] - 2
            rect = QRectF(c["text"], y - 9, avail, 18)
            p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(text, Qt.ElideRight, int(avail)))
            if current:
                lo, hi = next((a, b) for n, a, b in self._presets if n == name)
                span = f"{fmt_hu(lo)} … {fmt_hu(hi)}"
                used = p.fontMetrics().horizontalAdvance(text) + 6
                p.setFont(theme.num_font(12))
                if used + p.fontMetrics().horizontalAdvance(span) <= avail:
                    p.setPen(QColor(theme.MUTED))
                    p.drawText(rect.adjusted(used, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, span)
                if self.hasFocus():
                    p.setPen(QPen(QColor(theme.TEXT), 1))
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(QRectF(c["swatch"] - 4, y - 10, avail + c["text"] - c["swatch"] + 4, 20))

    # ---------- mouse si tastatura ----------

    def _nearest_handle(self, y: float) -> int:
        return 0 if abs(y - self._y(self._lo)) <= abs(y - self._y(self._hi)) else 1

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        name = self._preset_at(pos)
        if name is not None:
            self.activate(name)
            return
        if pos.x() <= self._cols()["band1"] + 8:
            self._anim.stop()
            self._drag = self._nearest_handle(pos.y())
            self._drag_to(pos.y())

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._drag is not None:
            self._drag_to(pos.y())
            return
        name = self._preset_at(pos)
        if name != self._hover:
            self._hover = name
            self.update()
        if name is not None:
            lo, hi = next((a, b) for n, a, b in self._presets if n == name)
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{theme.TISSUE_LABELS.get(name, name)}: {fmt_hu(lo)} … {fmt_hu(hi)} HU",
                              self)
            self.setCursor(Qt.PointingHandCursor)
            return
        near = pos.x() <= self._cols()["band1"] + 8 and min(
            abs(pos.y() - self._y(self._lo)), abs(pos.y() - self._y(self._hi))) <= self.GRAB
        self.setCursor(Qt.SizeVerCursor if near else Qt.ArrowCursor)

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            order = [n for n, _, _, _ in self._label_rows()]  # de sus in jos
            i = order.index(self._current)
            i = max(i - 1, 0) if event.key() == Qt.Key_Up else min(i + 1, len(order) - 1)
            if order[i] != self._current:
                self.activate(order[i])
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def _drag_to(self, y: float):
        hu = self._hu(y)
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
        self.value_label = value_label()
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
        lay.setSpacing(2)
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
        self.value_label.setText(f"{fmt_num(v, self._decimals)}{self._suffix}")

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
    s.setFont(theme.num_font(14, QFont.Medium))
    s.setMinimumWidth(48)  # altfel latimea pentru „10000 HU” ar largi panoul ingust
    guard_wheel(s)
    return s


def field(prefix: str, widget: QWidget) -> QFrame:
    """Camp cu eticheta in interior („de la 250 HU”)."""
    box = QFrame()
    box.setObjectName("field")
    lay = QHBoxLayout(box)
    lay.setContentsMargins(10, 0, 8, 0)
    lay.setSpacing(6)
    lay.addWidget(label(prefix, "hint"))
    lay.addWidget(widget, 1)
    return box


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
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)
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
        w = self.width() or (self.parentWidget().width() if self.parentWidget() else 248)
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
        clear = QColor(theme.TEXT)
        clear.setAlpha(0)
        g.setColorAt(0, clear)
        g.setColorAt(0.5, QColor(theme.TEXT))
        g.setColorAt(1, clear)
        p.fillRect(QRectF(x, 0, seg, self.height()), g)


class StatusDot(QWidget):
    """Patratelul de stare din bara de jos: gata, in lucru sau eroare."""

    COLORS = {"ok": theme.OK, "busy": theme.TEXT, "error": theme.DANGER, "idle": theme.FAINT}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._kind = "idle"

    def set_kind(self, kind: str):
        self._kind = kind
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(QRectF(2.5, 2.5, 7, 7), QColor(self.COLORS[self._kind]))


def icon_button(name: str, tooltip: str) -> QPushButton:
    b = QPushButton()
    b.setProperty("variant", "icon")
    b.setIcon(icons.icon(name, theme.OVERLAY_TEXT))
    b.setIconSize(QSize(16, 16))
    b.setToolTip(tooltip)
    b.setAccessibleName(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b
