"""Fereastra principala a aplicatiei."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dicom3d import __version__
from dicom3d.io.dicom_loader import SeriesInfo, Volume, find_series, load_series
from dicom3d.mesh.surface import MeshOptions, export_mesh
from dicom3d.pipeline import ReconstructionResult, ThresholdParams, reconstruct
from dicom3d.segmentation.threshold import PRESETS
from dicom3d.ui.slice_view import SliceView
from dicom3d.ui.view3d import View3D
from dicom3d.ui.worker import Worker

# fereastra de afisare 2D: (latime, centru) in HU
WINDOWS = {
    "Tesut moale": (400, 40),
    "Os": (1800, 400),
    "Plamani": (1500, -600),
    "Creier": (80, 40),
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"DICOM3D {__version__}")
        self.resize(1400, 850)
        self.pool = QThreadPool.globalInstance()
        self.volume: Volume | None = None
        self.result: ReconstructionResult | None = None

        self.slice_view = SliceView()
        self.view3d = View3D()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_controls())
        splitter.addWidget(self.slice_view)
        splitter.addWidget(self.view3d)
        splitter.setSizes([300, 550, 550])
        self.setCentralWidget(splitter)
        self._build_menu()

        # previzualizarea pragului se actualizeaza cu o mica intarziere
        self._preview_timer = QTimer(self, singleShot=True, interval=80)
        self._preview_timer.timeout.connect(self._update_preview)

        self._set_busy(False)
        self.statusBar().showMessage("Gata. Deschideti un folder cu o serie DICOM.")

    # ---------- construirea interfetei ----------

    def _build_menu(self):
        m = self.menuBar().addMenu("&Fisier")
        open_act = QAction("&Deschide folder DICOM...", self, shortcut=QKeySequence.Open)
        open_act.triggered.connect(self.open_folder)
        self.export_act = QAction("&Exporta model 3D...", self, shortcut=QKeySequence("Ctrl+E"))
        self.export_act.triggered.connect(self.export_model)
        quit_act = QAction("&Iesire", self, shortcut=QKeySequence.Quit)
        quit_act.triggered.connect(self.close)
        m.addActions([open_act, self.export_act])
        m.addSeparator()
        m.addAction(quit_act)

        v = self.menuBar().addMenu("&Vizualizare")
        reset = QAction("Reseteaza camera 3D", self, shortcut=QKeySequence("R"))
        reset.triggered.connect(self.view3d.reset_camera)
        v.addAction(reset)

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)

        self.info_label = QLabel("Niciun volum incarcat")
        self.info_label.setWordWrap(True)
        g_info = QGroupBox("Serie")
        QVBoxLayout(g_info).addWidget(self.info_label)
        lay.addWidget(g_info)

        g_win = QGroupBox("Afisare 2D")
        f = QFormLayout(g_win)
        self.window_combo = QComboBox()
        self.window_combo.addItems(WINDOWS.keys())
        self.window_combo.currentTextChanged.connect(
            lambda name: self.slice_view.set_window(*WINDOWS[name])
        )
        f.addRow("Fereastra:", self.window_combo)
        lay.addWidget(g_win)

        g_seg = QGroupBox("Segmentare prin prag")
        f = QFormLayout(g_seg)
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(PRESETS.keys())
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        f.addRow("Tesut:", self.preset_combo)
        self.lower_spin = self._hu_spin()
        self.upper_spin = self._hu_spin()
        f.addRow("Prag inferior (HU):", self.lower_spin)
        f.addRow("Prag superior (HU):", self.upper_spin)
        self.largest_check = QCheckBox("Pastreaza cea mai mare componenta")
        self.largest_check.setChecked(True)
        self.fill_check = QCheckBox("Umple golurile")
        self.outside_check = QCheckBox("Exclude aerul din jurul corpului")
        f.addRow(self.largest_check)
        f.addRow(self.fill_check)
        f.addRow(self.outside_check)
        self.sigma_spin = QDoubleSpinBox(minimum=0, maximum=5, singleStep=0.5, decimals=1)
        self.sigma_spin.setSuffix(" mm")
        self.sigma_spin.setToolTip("Netezire gaussiana a imaginii inainte de prag (reduce zgomotul)")
        f.addRow("Netezire imagine:", self.sigma_spin)
        lay.addWidget(g_seg)

        g_mesh = QGroupBox("Model 3D")
        f = QFormLayout(g_mesh)
        self.smooth_spin = QSpinBox(minimum=0, maximum=100, value=20)
        f.addRow("Iteratii netezire:", self.smooth_spin)
        self.decim_spin = QSpinBox(minimum=0, maximum=95, value=0, suffix=" %")
        self.decim_spin.setToolTip("Procentul de triunghiuri eliminate (fisier STL mai mic)")
        f.addRow("Decimare:", self.decim_spin)
        self.opacity_slider = QSlider(Qt.Horizontal, minimum=10, maximum=100, value=100)
        self.opacity_slider.valueChanged.connect(lambda v: self.view3d.set_opacity(v / 100))
        f.addRow("Opacitate:", self.opacity_slider)
        lay.addWidget(g_mesh)

        self.build_btn = QPushButton("Genereaza model 3D")
        self.build_btn.clicked.connect(self.build_model)
        self.export_btn = QPushButton("Exporta STL...")
        self.export_btn.clicked.connect(self.export_model)
        lay.addWidget(self.build_btn)
        lay.addWidget(self.export_btn)

        self.stats_label = QLabel("")
        self.stats_label.setWordWrap(True)
        lay.addWidget(self.stats_label)
        lay.addStretch(1)

        self.lower_spin.valueChanged.connect(self._preview_timer_start)
        self.upper_spin.valueChanged.connect(self._preview_timer_start)
        self._apply_preset(self.preset_combo.currentText())
        return panel

    @staticmethod
    def _hu_spin() -> QSpinBox:
        s = QSpinBox(minimum=-3000, maximum=10000, singleStep=10)
        s.setKeyboardTracking(False)
        return s

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_vtk_ready", False):
            self.view3d.initialize()
            self._vtk_ready = True

    def closeEvent(self, event):
        self.view3d.close_vtk()
        super().closeEvent(event)

    # ---------- actiuni ----------

    def open_folder(self, folder: str | None = None):
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "Alegeti folderul cu seria DICOM")
            if not folder:
                return
        self._set_busy(True, f"Caut serii DICOM in {folder}...")
        self._run(find_series, folder, on_done=self._on_series_found)

    def _on_series_found(self, series: list[SeriesInfo]):
        self._set_busy(False)
        if not series:
            QMessageBox.warning(self, "DICOM3D", "Nu am gasit nicio serie DICOM in folder.")
            return
        chosen = series[0]
        if len(series) > 1:
            labels = [
                f"{s.description or '(fara descriere)'} - {s.modality} - {s.num_files} felii"
                for s in series
            ]
            label, ok = QInputDialog.getItem(self, "Alegeti seria", "Serii gasite:", labels, 0, False)
            if not ok:
                return
            chosen = series[labels.index(label)]
        self._set_busy(True, f"Incarc {chosen.num_files} felii...")
        self._run(load_series, chosen, on_done=self._on_volume_loaded)

    def _on_volume_loaded(self, volume: Volume):
        self.volume = volume
        self.result = None
        self._set_busy(False)
        self.view3d.clear()
        self.stats_label.setText("")
        self.slice_view.set_volume(volume.array, volume.spacing)
        self.slice_view.set_window(*WINDOWS[self.window_combo.currentText()])
        x, y, z = volume.shape_xyz
        sx, sy, sz = volume.spacing
        info = volume.info
        self.info_label.setText(
            f"{(info.description if info else '') or 'Serie fara descriere'}\n"
            f"Modalitate: {info.modality if info else '?'}\n"
            f"Dimensiune: {x} x {y} x {z} voxeli\n"
            f"Spatiere: {sx:.2f} x {sy:.2f} x {sz:.2f} mm\n"
            f"Interval valori: {volume.array.min():.0f} .. {volume.array.max():.0f}"
        )
        self._update_preview()
        self.statusBar().showMessage("Volum incarcat. Ajustati pragul si generati modelul 3D.")

    def build_model(self):
        if self.volume is None:
            return
        params = ThresholdParams(
            lower=self.lower_spin.value(),
            upper=self.upper_spin.value(),
            keep_largest=self.largest_check.isChecked(),
            fill_holes=self.fill_check.isChecked(),
            smoothing_sigma_mm=self.sigma_spin.value(),
            exclude_outside=self.outside_check.isChecked(),
        )
        opts = MeshOptions(
            smoothing_iterations=self.smooth_spin.value(),
            decimation=self.decim_spin.value() / 100,
        )
        self._set_busy(True, "Segmentez si generez suprafata (Marching Cubes)...")
        self._run(reconstruct, self.volume, params, opts, on_done=self._on_model_built)

    def _on_model_built(self, result: ReconstructionResult):
        self.result = result
        self._set_busy(False)
        self.slice_view.set_mask(result.mask)
        self.view3d.set_mesh(result.mesh)
        self.view3d.set_opacity(self.opacity_slider.value() / 100)
        s = result.stats
        self.stats_label.setText(
            f"Triunghiuri: {s['triangles']:,}\n"
            f"Volum model: {s['volume_ml']:.1f} ml\n"
            f"Suprafata: {s['surface_mm2'] / 100:.1f} cm²"
        )
        self.statusBar().showMessage("Model 3D generat.")

    def export_model(self):
        if self.result is None:
            QMessageBox.information(self, "DICOM3D", "Generati intai modelul 3D.")
            return
        name = self.preset_combo.currentText().split()[0].lower()
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporta model 3D", f"{name}.stl",
            "STL (*.stl);;Wavefront OBJ (*.obj);;PLY (*.ply)",
        )
        if not path:
            return
        try:
            export_mesh(self.result.mesh, path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Eroare la export", str(exc))
            return
        self.statusBar().showMessage(f"Model salvat: {path}")

    # ---------- utilitare ----------

    def _apply_preset(self, name: str):
        p = PRESETS[name]
        self.outside_check.setChecked(p.exclude_outside)
        for spin, value in ((self.lower_spin, p.lower), (self.upper_spin, p.upper)):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        self._update_preview()

    def _preview_timer_start(self):
        self._preview_timer.start()

    def _update_preview(self):
        if self.volume is None:
            return
        # pragul s-a schimbat: masca veche nu mai corespunde
        self.slice_view.set_mask(None)
        self.slice_view.set_threshold_preview(self.lower_spin.value(), self.upper_spin.value())

    def _run(self, fn, *args, on_done):
        w = Worker(fn, *args)
        w.signals.finished.connect(on_done)
        w.signals.failed.connect(self._on_error)
        self.pool.start(w)

    def _on_error(self, message: str):
        self._set_busy(False)
        QMessageBox.critical(self, "Eroare", message)
        self.statusBar().showMessage("Eroare: " + message)

    def _set_busy(self, busy: bool, message: str | None = None):
        has_volume = self.volume is not None
        self.build_btn.setEnabled(not busy and has_volume)
        self.export_btn.setEnabled(not busy and self.result is not None)
        self.export_act.setEnabled(not busy and self.result is not None)
        if busy:
            self.setCursor(Qt.WaitCursor)
        else:
            self.unsetCursor()
        if message:
            self.statusBar().showMessage(message)
