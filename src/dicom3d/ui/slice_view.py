"""Vizualizare 2D a feliilor, cu fereastra CT si suprapunerea mastii."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QSlider, QVBoxLayout, QWidget

MASK_RGB = np.array([255, 80, 40], dtype=np.float32)
MASK_ALPHA = 0.45


class SliceView(QWidget):
    sliceChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._volume: np.ndarray | None = None
        self._threshold: tuple[float, float] | None = None
        self._mask: np.ndarray | None = None
        self._window = (400.0, 40.0)  # latime, centru (fereastra de tesut moale)
        self._aspect = 1.0  # spacing_y / spacing_x

        self.image = QLabel("Deschideti un folder DICOM (Fisier > Deschide)")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(256, 256)
        self.image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image.setStyleSheet("background:#111; color:#aaa;")

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._on_slider)
        self.label = QLabel("-")
        self.label.setMinimumWidth(70)

        row = QHBoxLayout()
        row.addWidget(self.slider, 1)
        row.addWidget(self.label)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.image, 1)
        lay.addLayout(row)

    def set_volume(self, array: np.ndarray, spacing: tuple[float, float, float]):
        self._volume = array
        self._mask = None
        self._aspect = spacing[1] / spacing[0]
        n = array.shape[0]
        self.slider.blockSignals(True)
        self.slider.setRange(0, n - 1)
        self.slider.setValue(n // 2)
        self.slider.blockSignals(False)
        self.slider.setEnabled(True)
        self._render()

    def set_window(self, width: float, center: float):
        self._window = (max(width, 1.0), center)
        self._render()

    def set_threshold_preview(self, lower: float | None, upper: float | None = None):
        """Previzualizare rapida: pragul se aplica doar feliei curente."""
        self._threshold = None if lower is None else (lower, upper)
        self._render()

    def set_mask(self, mask: np.ndarray | None):
        """Masca finala (dupa post-procesare); are prioritate fata de previzualizare."""
        self._mask = mask
        self._render()

    def current_index(self) -> int:
        return self.slider.value()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    def _on_slider(self, value: int):
        self._render()
        self.sliceChanged.emit(value)

    def _render(self):
        if self._volume is None:
            return
        k = self.slider.value()
        sl = self._volume[k].astype(np.float32)
        width, center = self._window
        gray = np.clip((sl - (center - width / 2)) / width, 0, 1) * 255
        rgb = np.repeat(gray[..., None], 3, axis=2)

        overlay = None
        if self._mask is not None:
            overlay = self._mask[k].astype(bool)
        elif self._threshold is not None:
            lo, hi = self._threshold
            overlay = (sl >= lo) & (sl <= hi)
        if overlay is not None and overlay.any():
            rgb[overlay] = rgb[overlay] * (1 - MASK_ALPHA) + MASK_RGB * MASK_ALPHA

        rgb = np.ascontiguousarray(rgb.astype(np.uint8))
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        # corectam pixelii ne-patrati, apoi incadram in widget
        pix = pix.scaled(w, round(h * self._aspect), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        pix = pix.scaled(self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image.setPixmap(pix)
        self.label.setText(f"{k + 1} / {self._volume.shape[0]}")
