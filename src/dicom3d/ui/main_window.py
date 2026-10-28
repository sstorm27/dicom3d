"""Fereastra principala a aplicatiei.

Aranjament: bara de sus (seria si actiunile), panoul din stanga (rigla
Hounsfield cu pragul, curatarea mastii, modelul) si doua vederi pe negru:
felia 2D si modelul 3D.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dicom3d import __version__
from dicom3d.io.dicom_loader import SeriesInfo, Volume, find_series, load_series
from dicom3d.mesh.surface import MeshOptions, export_mesh
from dicom3d.pipeline import ReconstructionResult, ThresholdParams, reconstruct
from dicom3d.segmentation.threshold import PRESETS
from dicom3d.ui import icons, theme
from dicom3d.ui.slice_view import SliceView
from dicom3d.ui.view3d import VIEWS, View3D
from dicom3d.ui.widgets import (
    Banner,
    BusyBar,
    CheckRow,
    ElidedLabel,
    HounsfieldRuler,
    SegmentedControl,
    StatusDot,
    ValueSlider,
    field,
    fmt_hu,
    fmt_int,
    fmt_num,
    guard_wheel,
    hu_spin,
    icon_button,
    label,
    separator,
    value_label,
)
from dicom3d.ui.worker import Worker

LARGE_MESH_TRIANGLES = 2_000_000
SIDEBAR_WIDTH = 288
SIDEBAR_NARROW = 264  # sub 1180 px latime a ferestrei
STACK_BELOW = 900  # sub aceasta latime a zonei de vizualizare, vederile se aseaza una sub alta
PREFERRED_SIZE = QSize(1440, 880)

# fereastra de afisare 2D: (latime, centru) in HU
WINDOWS = {
    "Țesut moale": (400, 40),
    "Os": (1800, 400),
    "Plămâni": (1500, -600),
    "Creier": (80, 40),
}
# la alegerea unui tesut, felia trece pe fereastra in care el se vede cel mai bine
PRESET_WINDOW = {
    "Os": "Os",
    "Tesut moale": "Țesut moale",
    "Vase cu contrast": "Țesut moale",
    "Plamani (aer)": "Plămâni",
    "Piele": "Țesut moale",
}

STALE_TEXT = "Modelul nu mai corespunde setărilor. Generează-l din nou."
LARGE_TEXT = ("Model foarte mare: rotirea și exportul pot fi lente. "
              "Mărește Simplificarea sau folosește un prag mai strict.")


def _section(title: str, hint: str = "") -> QHBoxLayout:
    head = QHBoxLayout()
    head.setContentsMargins(0, 0, 0, 0)
    head.addWidget(label(title, "h"))
    head.addStretch(1)
    if hint:
        head.addWidget(label(hint, "hint"))
    return head


def _column(margins=(20, 12, 20, 12), spacing: int = 6) -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return w, lay


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DICOM3D")
        self.setWindowIcon(icons.app_icon())
        self._fit_to_screen()
        self.setAcceptDrops(True)
        self.pool = QThreadPool.globalInstance()
        self.volume: Volume | None = None
        self.result: ReconstructionResult | None = None
        self._stale = False
        self._busy = False
        self._built_tissue = ""
        self._summary = ""

        self.slice_view = SliceView()
        self.view3d = View3D()
        self.busy_bar = BusyBar()

        central = QWidget()
        central.setObjectName("central")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())
        root.addWidget(self.busy_bar)
        body = QHBoxLayout()
        body.setContentsMargins(theme.GUTTER, 0, theme.GUTTER, theme.GUTTER)
        body.setSpacing(theme.GUTTER)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_stage(), 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)
        self._build_statusbar()
        self._build_actions()

        # previzualizarea pragului se actualizeaza cu o mica intarziere
        self._preview_timer = QTimer(self, singleShot=True, interval=60)
        self._preview_timer.timeout.connect(self._update_preview)

        self._apply_preset(self.ruler.current(), animate=False)
        self._set_busy(False)
        self._set_status("Gata. Deschide un folder cu o serie DICOM.", "idle")

    def _fit_to_screen(self):
        """Fereastra incape in ecran; pe ecrane mici (ex. 1280×800 cu scalare) porneste maximizata."""
        screen = self.screen()
        avail = screen.availableGeometry() if screen else None
        if avail is None or avail.width() <= 0:
            self.resize(PREFERRED_SIZE)
            self.setMinimumSize(960, 620)
            return
        w = min(PREFERRED_SIZE.width(), avail.width() - 32)
        h = min(PREFERRED_SIZE.height(), avail.height() - 64)  # loc pentru bara de titlu
        self.setMinimumSize(min(960, w), min(600, h))
        self.resize(w, h)
        if w < PREFERRED_SIZE.width() or h < PREFERRED_SIZE.height():
            self.setWindowState(Qt.WindowMaximized)

    # ---------- construirea interfetei ----------

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(48)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, theme.GUTTER, 0)
        lay.setSpacing(12)

        logo = label()
        logo.setPixmap(icons.pixmap("logo", 18, theme.TEXT, 1.6))
        lay.addWidget(logo)
        lay.addWidget(label("DICOM3D", "brand"))
        version = value_label(__version__, 12)
        version.setProperty("role", "faint")
        lay.addWidget(version)
        self.series_sep = separator(vertical=True)
        self.series_sep.setFixedHeight(18)
        self.modality_label = label("", "h")
        self.series_title = label("")
        self.series_meta = ElidedLabel("", "muted")
        self.series_meta.setFont(theme.num_font(13))
        for w in (self.series_sep, self.modality_label, self.series_title):
            w.hide()
            lay.addWidget(w, 0, Qt.AlignVCenter)
        lay.addWidget(self.series_meta, 1)

        self.open_btn = QPushButton(" Deschide serie")
        self.open_btn.setProperty("variant", "ghost")
        self.open_btn.setIcon(icons.icon("folder"))
        self.open_btn.setToolTip("Deschide un folder cu o serie DICOM (Ctrl+O)")
        self.open_btn.clicked.connect(lambda: self.open_folder())
        self.export_btn = QPushButton(" Exportă model")
        self.export_btn.setIcon(icons.icon("export"))
        self.export_btn.setToolTip("Salvează modelul afișat ca STL, OBJ sau PLY (Ctrl+E)")
        self.export_btn.clicked.connect(self.export_model)
        for b in (self.open_btn, self.export_btn):
            b.setIconSize(QSize(16, 16))
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        return bar

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        self.sidebar = side
        side.setFixedWidth(SIDEBAR_WIDTH)
        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        content.setObjectName("sidebarContent")
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # pragul: rigla Hounsfield cu histograma si presetarile, apoi valorile exacte
        sec, g = _column((20, 12, 20, 12), 4)
        g.addLayout(_section("Prag", "unități Hounsfield"))
        self.ruler = HounsfieldRuler(PRESETS)
        self.ruler.setToolTip("Trage manerele ca să alegi pragul; alege un țesut din dreapta scalei")
        # activated (nu doar schimbarea): re-alegerea aceluiasi tesut reface pragurile
        self.ruler.presetActivated.connect(self._apply_preset)
        self.ruler.rangeEdited.connect(self._on_ruler_edit)
        g.addWidget(self.ruler, 1)
        rng = QHBoxLayout()
        rng.setSpacing(8)
        rng.setContentsMargins(0, 6, 0, 0)
        self.lower_spin = hu_spin()
        self.upper_spin = hu_spin()
        self.lower_spin.setToolTip("Prag inferior")
        self.upper_spin.setToolTip("Prag superior")
        rng.addWidget(field("de la", self.lower_spin), 1)
        rng.addWidget(field("până la", self.upper_spin), 1)
        g.addLayout(rng)
        col.addWidget(sec, 1)
        col.addWidget(separator())

        # curatarea mastii
        sec, g = _column((20, 10, 20, 12), 0)
        g.addLayout(_section("Curățare"))
        g.addSpacing(4)
        self.largest_check = CheckRow("Doar cea mai mare componentă")
        self.largest_check.setChecked(True)
        self.outside_check = CheckRow("Fără aerul din jurul corpului")
        self.fill_check = CheckRow("Umple golurile")
        for c in (self.largest_check, self.outside_check, self.fill_check):
            g.addWidget(c)
        g.addSpacing(6)
        self.sigma_spin = ValueSlider("Netezire imagine", 0, 5, step=0.5, suffix=" mm", decimals=1)
        self.sigma_spin.setToolTip("Netezire gaussiană a imaginii înainte de prag (reduce zgomotul)")
        g.addWidget(self.sigma_spin)
        col.addWidget(sec)
        col.addWidget(separator())

        # modelul
        sec, g = _column((20, 10, 20, 12), 8)
        g.addLayout(_section("Model"))
        self.smooth_spin = ValueSlider("Netezire suprafață", 0, 100, value=20)
        self.smooth_spin.setToolTip("Iterații de netezire a suprafeței generate")
        self.decim_spin = ValueSlider("Simplificare", 0, 95, value=0, suffix=" %")
        self.decim_spin.setToolTip("Procentul de triunghiuri eliminate (fișier STL mai mic)")
        g.addWidget(self.smooth_spin)
        g.addWidget(self.decim_spin)
        col.addWidget(sec)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        foot = QFrame()
        foot.setObjectName("sidebarFooter")
        f = QVBoxLayout(foot)
        f.setContentsMargins(20, 8, 20, 14)
        f.setSpacing(10)
        self.banner = Banner()
        f.addWidget(self.banner)
        self.build_btn = QPushButton(" Generează model 3D")
        self.build_btn.setProperty("variant", "primary")
        self.build_btn.setIcon(icons.icon("cube", theme.ACCENT_INK, theme.FAINT))
        self.build_btn.setIconSize(QSize(16, 16))
        self.build_btn.setToolTip("Segmentează și construiește suprafața 3D (Ctrl+G)")
        self.build_btn.setCursor(Qt.PointingHandCursor)
        self.build_btn.clicked.connect(self.build_model)
        f.addWidget(self.build_btn)
        outer.addWidget(foot)

        self.lower_spin.valueChanged.connect(self._on_threshold_changed)
        self.upper_spin.valueChanged.connect(self._on_threshold_changed)
        for w in (self.lower_spin, self.upper_spin, self.sigma_spin, self.smooth_spin,
                  self.decim_spin):
            w.valueChanged.connect(self._mark_stale)
        for check in (self.largest_check, self.fill_check, self.outside_check):
            check.toggled.connect(self._mark_stale)
        return side

    def _viewport(self, title: str, header_widgets, content: QWidget,
                  footer: QWidget | None = None) -> QFrame:
        frame = QFrame()
        frame.setObjectName("viewport")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QFrame()
        head.setObjectName("vpHeader")
        head.setFixedHeight(34)
        h = QHBoxLayout(head)
        h.setContentsMargins(12, 0, 8, 0)
        h.setSpacing(12)
        h.addWidget(label(title, "h"))
        h.addStretch(1)
        for w in header_widgets:
            h.addWidget(w, 0, Qt.AlignBottom if isinstance(w, SegmentedControl) else Qt.AlignVCenter)
        lay.addWidget(head)
        lay.addWidget(content, 1)
        if footer is not None:
            footer.setObjectName("vpFooter")
            footer.setFixedHeight(40)
            lay.addWidget(footer)
        return frame

    def _build_stage(self) -> QWidget:
        self.window_seg = SegmentedControl(WINDOWS.keys(), current="Os")
        self.window_seg.setToolTip("Fereastra CT a feliei (se schimbă și odată cu țesutul)")
        self.window_seg.currentTextChanged.connect(self._on_window_changed)
        self.slice_view.set_window(*WINDOWS["Os"], "Os")
        self.slice_view.canvas.openRequested.connect(lambda: self.open_folder())
        vp2d = self._viewport("Axial", [self.window_seg], self.slice_view)

        self.view_seg = SegmentedControl(VIEWS.keys(), checkable=False)
        self.view_seg.setToolTip("Rotește camera spre o vedere standard")
        self.view_seg.clicked.connect(self.view3d.set_view)
        line = separator(vertical=True)
        line.setFixedHeight(16)
        reset_btn = icon_button("reset", "Resetează camera (R)")
        reset_btn.clicked.connect(self.view3d.reset_camera)
        self.shot_btn = icon_button("camera", "Salvează o captură PNG a modelului")
        self.shot_btn.clicked.connect(self.save_screenshot)

        foot = QWidget()
        f = QHBoxLayout(foot)
        f.setContentsMargins(14, 0, 12, 0)
        f.setSpacing(10)
        self.model_dot = label()
        self.model_name = label("", "h")
        self.stats_label = ElidedLabel("Încă niciun model.", "faint")
        self.stats_label.setFont(theme.num_font(13))
        f.addWidget(self.model_dot)
        f.addWidget(self.model_name)
        f.addWidget(self.stats_label, 1)
        f.addWidget(label("Opacitate", "muted"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setFixedWidth(80)
        self.opacity_slider.setCursor(Qt.PointingHandCursor)
        guard_wheel(self.opacity_slider)
        self.opacity_value = value_label("100 %", 13, muted=False)
        self.opacity_value.setFixedWidth(40)
        self.opacity_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        f.addWidget(self.opacity_slider)
        f.addWidget(self.opacity_value)
        vp3d = self._viewport("Model 3D", [self.view_seg, line, reset_btn, self.shot_btn],
                              self.view3d, foot)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(theme.GUTTER)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(vp2d)
        self.splitter.addWidget(vp3d)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        return self.splitter

    def _build_statusbar(self):
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        sb.setFixedHeight(28)
        wrap = QWidget()
        w = QHBoxLayout(wrap)
        w.setContentsMargins(10, 0, 0, 0)
        w.setSpacing(6)
        self.status_dot = StatusDot()
        self.status_label = ElidedLabel("")
        w.addWidget(self.status_dot)
        w.addWidget(self.status_label, 1)
        sb.addWidget(wrap, 1)
        self.params_label = value_label("", 12)
        sb.addPermanentWidget(self.params_label)

    def _build_actions(self):
        def act(text, shortcut, slot):
            a = QAction(text, self, shortcut=QKeySequence(shortcut))
            a.setShortcutContext(Qt.WindowShortcut)
            a.triggered.connect(slot)
            self.addAction(a)
            return a

        act("Deschide", QKeySequence.Open, lambda: self.open_folder())
        self.export_act = act("Exportă", "Ctrl+E", self.export_model)
        self.build_act = act("Generează", "Ctrl+G", self.build_model)
        act("Resetează camera", "R", self.view3d.reset_camera)
        act("Ieșire", QKeySequence.Quit, self.close)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_vtk_ready", False):
            theme.dark_title_bar(self)
            QTimer.singleShot(0, lambda: self.splitter.setSizes([10_000, 10_000]))
            self.view3d.initialize()
            self._vtk_ready = True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # fereastra ingusta: panoul lateral se strange, iar vederile trec una sub alta
        self.sidebar.setFixedWidth(SIDEBAR_WIDTH if self.width() >= 1180 else SIDEBAR_NARROW)
        stage_w = self.width() - self.sidebar.width()
        orient = Qt.Vertical if stage_w < STACK_BELOW else Qt.Horizontal
        if self.splitter.orientation() != orient:
            self.splitter.setOrientation(orient)
            self.splitter.setSizes([10_000, 10_000])

    def closeEvent(self, event):
        self.view3d.close_vtk()
        super().closeEvent(event)

    # ---------- trage si lasa un folder ----------

    @staticmethod
    def _dropped_folder(event) -> str | None:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        for url in urls:
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                return str(p if p.is_dir() else p.parent)
        return None

    def dragEnterEvent(self, event):
        if self._dropped_folder(event) and not self._busy:
            event.acceptProposedAction()
            self.slice_view.canvas.set_drop_hover(True)

    def dragLeaveEvent(self, event):
        self.slice_view.canvas.set_drop_hover(False)

    def dropEvent(self, event):
        self.slice_view.canvas.set_drop_hover(False)
        folder = self._dropped_folder(event)
        if folder:
            event.acceptProposedAction()
            self.open_folder(folder)

    # ---------- actiuni ----------

    def open_folder(self, folder: str | None = None):
        if self._busy:
            return
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "Alege folderul cu seria DICOM")
            if not folder:
                return
        self._folder = folder
        self._set_busy(True, f"Caut serii DICOM în {folder}…")
        self._run(find_series, folder, on_done=self._on_series_found)

    def _on_series_found(self, series: list[SeriesInfo]):
        self._set_busy(False)
        if not series:
            self._set_status("Nu am găsit nicio serie DICOM în folder.", "error")
            QMessageBox.warning(self, "DICOM3D", "Nu am găsit nicio serie DICOM în folder.")
            return
        chosen = series[0]
        if len(series) > 1:
            labels = [
                f"{s.description or '(fără descriere)'} · {s.modality} · {s.num_files} felii"
                for s in series
            ]
            text, ok = QInputDialog.getItem(self, "Alege seria", "Serii găsite:", labels, 0, False)
            if not ok:
                self._set_status("Nicio serie aleasă.", "idle")
                return
            chosen = series[labels.index(text)]
        self._set_busy(True, f"Încarc {chosen.num_files} felii…")
        self._run(load_series, chosen, on_done=self._on_volume_loaded)

    def _on_volume_loaded(self, volume: Volume):
        self.volume = volume
        self.result = None
        self._stale = False
        self._set_busy(False)
        self.view3d.clear()
        self._update_banner()
        self._show_model_info()
        self.slice_view.set_volume(volume.array, volume.spacing, volume.direction)
        self.ruler.set_values(volume.array[:, ::4, ::4])

        x, y, z = volume.shape_xyz
        sx, sy, sz = volume.spacing
        info = volume.info
        desc = (info.description if info else "") or "Serie fără descriere"
        modality = info.modality if info and info.modality else "?"
        meta = (f"{x} × {y} × {z}  ·  {fmt_num(sx, 2)} × {fmt_num(sy, 2)} × {fmt_num(sz, 2)} mm  ·  "
                f"{fmt_hu(volume.array.min())} … {fmt_hu(volume.array.max())} HU")
        self.modality_label.setText(modality)
        self.series_title.setText(desc)
        self.series_meta.setText(meta)
        self.series_meta.setToolTip(f"{meta}  ·  {Path(getattr(self, '_folder', '') or '.').name}")
        for w in (self.series_sep, self.modality_label, self.series_title):
            w.show()
        self._summary = f"{desc} | {modality} | {meta}"
        self.setWindowTitle(f"{desc} – DICOM3D")
        self.ruler.set_range(self.lower_spin.value(), self.upper_spin.value())
        self._update_preview()
        self._set_busy(False)
        self._set_status("Serie încărcată. Alege țesutul pe scala Hounsfield, ajustează pragul și "
                         "generează modelul 3D.", "ok")

    def series_summary(self) -> str:
        """Rezumatul seriei pe un rand (folosit de playtest)."""
        return self._summary

    def build_model(self):
        if self.volume is None or self._busy:
            return
        lo, hi = self.lower_spin.value(), self.upper_spin.value()
        if lo > hi:
            QMessageBox.warning(self, "DICOM3D",
                                "Pragul inferior trebuie să fie mai mic decât pragul superior.")
            return
        if not ((self.volume.array >= lo) & (self.volume.array <= hi)).any():
            QMessageBox.warning(self, "DICOM3D",
                                f"Niciun voxel nu are valori între {fmt_hu(lo)} și {fmt_hu(hi)} HU.\n"
                                f"Valorile din serie sunt între {fmt_hu(self.volume.array.min())} "
                                f"și {fmt_hu(self.volume.array.max())} HU.")
            return
        params = ThresholdParams(
            lower=lo,
            upper=hi,
            keep_largest=self.largest_check.isChecked(),
            fill_holes=self.fill_check.isChecked(),
            smoothing_sigma_mm=self.sigma_spin.value(),
            exclude_outside=self.outside_check.isChecked(),
        )
        opts = MeshOptions(
            smoothing_iterations=int(self.smooth_spin.value()),
            decimation=self.decim_spin.value() / 100,
        )
        self._building_tissue = self.ruler.current()
        self._building_params = (lo, hi, opts.smoothing_iterations, self.decim_spin.value())
        self._set_busy(True, "Segmentez și generez suprafața (Marching Cubes)…")
        self._build_started = _now()
        self._run(reconstruct, self.volume, params, opts, on_done=self._on_model_built)

    def _on_model_built(self, result: ReconstructionResult):
        self.result = result
        self._stale = False
        self._built_tissue = self._building_tissue
        self._set_busy(False)
        color = theme.TISSUE_COLORS.get(self._built_tissue, theme.TEXT)
        self.slice_view.set_overlay_color(color)
        self.slice_view.set_mask(result.mask)
        self.view3d.set_mesh(result.mesh, color)
        self.view3d.set_opacity(self.opacity_slider.value() / 100)
        self._show_model_info()
        self._update_banner()
        lo, hi, it, dec = self._building_params
        self.params_label.setText(
            f"{fmt_hu(lo)} … {fmt_hu(hi)} HU  ·  netezire {it}  ·  simplificare {dec} %   ")
        self._set_status(f"Model 3D generat în {fmt_num(_now() - self._build_started, 1)} s.", "ok")

    def export_model(self):
        if self.result is None:
            QMessageBox.information(self, "DICOM3D", "Generează întâi modelul 3D.")
            return
        name = (self._built_tissue or "model").split()[0].lower()
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportă model 3D", f"{name}.stl",
            "STL (*.stl);;Wavefront OBJ (*.obj);;PLY (*.ply)",
        )
        if not path:
            return
        try:
            export_mesh(self.result.mesh, path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Eroare la export", str(exc))
            self._set_status(f"Exportul a eșuat: {exc}", "error")
            return
        self._set_status(f"Model salvat: {path}", "ok")

    def save_screenshot(self):
        if not self.view3d.has_mesh():
            QMessageBox.information(self, "DICOM3D", "Generează întâi modelul 3D.")
            return
        name = (self._built_tissue or "model").split()[0].lower()
        path, _ = QFileDialog.getSaveFileName(self, "Salvează captura", f"{name}.png", "PNG (*.png)")
        if not path:
            return
        if self.view3d.save_screenshot(path):
            self._set_status(f"Captură salvată: {path}", "ok")
        else:
            self._set_status("Captura nu s-a putut salva.", "error")

    # ---------- utilitare ----------

    def _apply_preset(self, name: str, animate: bool = True):
        p = PRESETS[name]
        self.ruler.set_current(name)
        color = theme.TISSUE_COLORS.get(name, theme.TEXT)
        self.ruler.set_color(color)
        if self.result is None or self._stale:
            self.slice_view.set_overlay_color(color)
        self.outside_check.setChecked(p.exclude_outside)
        for spin, value in ((self.lower_spin, p.lower), (self.upper_spin, p.upper)):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        self.ruler.set_range(p.lower, p.upper, animate=animate)
        self.window_seg.setCurrentText(PRESET_WINDOW.get(name, "Țesut moale"))
        self._mark_stale()
        self._update_preview()

    def _on_ruler_edit(self, lo: int, hi: int):
        for spin, value in ((self.lower_spin, lo), (self.upper_spin, hi)):
            if spin.value() != value:
                spin.setValue(value)

    def _on_threshold_changed(self):
        self.ruler.set_range(self.lower_spin.value(), self.upper_spin.value())
        self._preview_timer.start()

    def _on_window_changed(self, name: str):
        self.slice_view.set_window(*WINDOWS[name], name)

    def _on_opacity(self, value: int):
        self.opacity_value.setText(f"{value} %")
        self.view3d.set_opacity(value / 100)

    def _mark_stale(self):
        """Modelul afisat nu mai corespunde setarilor din panou."""
        if self.result is None:
            return
        self._stale = True
        self.slice_view.set_overlay_color(theme.TISSUE_COLORS.get(self.ruler.current(), theme.TEXT))
        self._update_banner()

    def _update_banner(self):
        if self._stale:
            self.banner.show_message(STALE_TEXT)
        elif self.result is not None and self.result.stats["triangles"] > LARGE_MESH_TRIANGLES:
            self.banner.show_message(LARGE_TEXT)
        else:
            self.banner.dismiss()

    def _show_model_info(self):
        if self.result is None:
            self.model_dot.clear()
            self.model_name.setText("")
            self.stats_label.setText("Încă niciun model.")
            self.stats_label.setToolTip("")
            return
        s = self.result.stats
        color = theme.TISSUE_COLORS.get(self._built_tissue, theme.TEXT)
        self.model_dot.setPixmap(icons.swatch(color, 8))
        self.model_name.setText(theme.TISSUE_LABELS.get(self._built_tissue, self._built_tissue))
        n = s["triangles"]
        tri = f"{fmt_num(n / 1e6, 1)} mil." if n >= 1_000_000 else fmt_int(n)
        # volumul primul: daca nu e loc, se scurteaza numarul de triunghiuri
        self.stats_label.setText(f"{fmt_num(s['volume_ml'], 1)} ml  ·  {tri} triunghiuri")
        self.stats_label.setToolTip(
            f"{fmt_int(n)} triunghiuri, volum {fmt_num(s['volume_ml'], 1)} ml, "
            f"suprafață {fmt_num(s['surface_mm2'] / 100, 1)} cm²")

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
        self._set_status("Eroare: " + message, "error")
        QMessageBox.critical(self, "Eroare", message)

    def _set_status(self, text: str, kind: str = "idle"):
        self.status_dot.set_kind(kind)
        self.status_label.setText(text)

    def _set_busy(self, busy: bool, message: str | None = None):
        self._busy = busy
        has_volume = self.volume is not None
        can_export = not busy and self.result is not None
        self.build_btn.setEnabled(not busy and has_volume)
        self.build_btn.setText(" Se generează…" if busy and message and "Segmentez" in message
                               else " Generează model 3D")
        self.build_act.setEnabled(not busy and has_volume)
        self.export_btn.setEnabled(can_export)
        self.export_act.setEnabled(can_export)
        self.shot_btn.setEnabled(not busy and self.result is not None)
        self.open_btn.setEnabled(not busy)
        if busy:
            self.busy_bar.start()
            self.setCursor(Qt.BusyCursor)
        else:
            self.busy_bar.stop()
            self.unsetCursor()
        if message:
            self._set_status(message, "busy" if busy else "idle")


def _now() -> float:
    import time

    return time.perf_counter()
