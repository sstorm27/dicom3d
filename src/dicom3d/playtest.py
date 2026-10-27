"""Playtest automat al interfetei: apasa singur pe butoane si salveaza capturi.

Ruleaza pe placa video reala, fara interventia utilizatorului:
    DICOM3D-debug.exe --playtest C:\\date\\ct_torace C:\\date\\playtest
Rezultatul: capturi PNG si raport.txt in folderul de iesire.
"""

from __future__ import annotations

import platform
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox


class Playtest:
    def __init__(self, app: QApplication, folder: str, out_dir: str):
        from dicom3d.ui.main_window import MainWindow

        self.app = app
        self.folder = folder
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.lines: list[str] = []
        self.dialogs: list[str] = []
        self.save_path: str | None = None
        self._patch_dialogs()
        self.w = MainWindow()
        self.w.resize(1500, 850)
        self.w.show()

    # ---------- utilitare ----------

    def log(self, text: str):
        print(text, flush=True)
        self.lines.append(text)

    def _patch_dialogs(self):
        """Dialogurile modale ar bloca testul: le inregistram in loc sa le afisam."""

        def record(kind):
            def show(parent, title, text, *args, **kwargs):
                self.dialogs.append(f"{kind}: {text}")
                self.log(f"    dialog {kind}: {text}")
                return QMessageBox.Ok

            return staticmethod(show)

        QMessageBox.warning = record("avertisment")
        QMessageBox.critical = record("eroare")
        QMessageBox.information = record("info")
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (self.save_path or "", ""))
        QInputDialog.getItem = staticmethod(lambda p, t, l, items, *a, **k: (items[0], True))

    def pump(self, seconds: float = 0.3):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents(QEventLoop.AllEvents, 50)
            time.sleep(0.01)

    def wait(self, cond, timeout: float) -> bool:
        end = time.time() + timeout
        while not cond():
            if time.time() > end:
                return False
            self.app.processEvents(QEventLoop.AllEvents, 50)
            time.sleep(0.01)
        return True

    def screenshot(self, name: str):
        """Fereastra + randarea VTK (grab() nu prinde mereu continutul OpenGL)."""
        from dicom3d import vtk_lite as vtk
        from vtkmodules.util import numpy_support
        from PySide6.QtGui import QImage

        self.w.view3d.render()
        self.pump(0.2)
        pix = self.w.grab()
        rw = self.w.view3d.vtk_widget.GetRenderWindow()
        f = vtk.vtkWindowToImageFilter()
        f.SetInput(rw)
        f.ReadFrontBufferOff()
        f.Update()
        img = f.GetOutput()
        wdt, hgt, _ = img.GetDimensions()
        arr = numpy_support.vtk_to_numpy(img.GetPointData().GetScalars())
        arr = arr.reshape(hgt, wdt, -1)[::-1].copy()  # VTK are originea jos
        fmt = QImage.Format_RGBA8888 if arr.shape[2] == 4 else QImage.Format_RGB888
        qimg = QImage(arr.data, wdt, hgt, arr.strides[0], fmt).copy()
        target = self.w.view3d.vtk_widget
        top_left = target.mapTo(self.w, target.rect().topLeft())
        painter = QPainter(pix)
        painter.drawImage(target.rect().translated(top_left),
                          qimg.scaled(target.size(), Qt.IgnoreAspectRatio))
        painter.end()
        path = self.out / f"{name}.png"
        pix.save(str(path))
        self.log(f"    captura: {path.name}")

    def choose_preset(self, name: str):
        """Ca un click pe numele tesutului de pe scala Hounsfield."""
        self.w.ruler.activate(name)

    def build(self, label: str) -> float | None:
        w = self.w
        w.result = None
        n = len(self.dialogs)
        t0 = time.time()
        w.build_model()
        ok = self.wait(lambda: w.result is not None or len(self.dialogs) > n, 900)
        dt = time.time() - t0
        if w.result is not None:
            s = w.result.stats
            self.log(f"  OK {label}: {s['triangles']:,} triunghiuri, {s['volume_ml']:.0f} ml, "
                     f"{dt:.1f} s")
            return dt
        self.log(f"  {label}: fara model ({'eroare' if ok else 'TIMEOUT'}, {dt:.1f} s)")
        return None

    # ---------- scenariul ----------

    def run(self) -> int:
        from dicom3d.segmentation.threshold import PRESETS
        from dicom3d.ui.main_window import WINDOWS

        w = self.w
        self.log(f"Playtest DICOM3D - {time.strftime('%Y-%m-%d %H:%M')}")
        self.log(f"Sistem: {platform.platform()}, Python {platform.python_version()}")
        self.pump(1)
        rw = w.view3d.vtk_widget.GetRenderWindow()
        caps = [ln.strip() for ln in rw.ReportCapabilities().splitlines()
                if "OpenGL renderer" in ln or "OpenGL version" in ln]
        self.log("OpenGL: " + "; ".join(caps))

        self.log("1. Incarcare serie")
        t0 = time.time()
        w.open_folder(self.folder)
        if not self.wait(lambda: w.volume is not None or self.dialogs, 300) or w.volume is None:
            self.log("  ESEC: seria nu s-a incarcat")
            return self.finish()
        self.log(f"  OK in {time.time() - t0:.1f} s: " + w.series_summary())
        self.screenshot("01_incarcat")

        self.log("2. Ferestre 2D si felii")
        for name in WINDOWS:
            w.window_seg.setCurrentText(name)
            self.pump(0.1)
        w.window_seg.setCurrentText("Os")
        for v in (0, w.volume.array.shape[0] - 1, w.volume.array.shape[0] // 2):
            w.slice_view.slider.setValue(v)
            self.pump(0.1)
        self.log("  OK")

        self.log("3. Toate presetarile")
        for i, name in enumerate(PRESETS, start=3):
            self.choose_preset(name)
            if self.build(name) is not None:
                self.screenshot(f"{i:02d}_{name.split()[0].lower()}")

        self.log("4. Camera 3D: rotire, zoom, reset")
        self.choose_preset("Os")
        self.build("Os")
        cam = w.view3d.renderer.GetActiveCamera()
        t0 = time.time()
        for _ in range(36):
            cam.Azimuth(10)
            w.view3d.render()
        fps = 36 / (time.time() - t0)
        self.log(f"  rotire 360 grade: {fps:.1f} cadre/s")
        cam.Zoom(1.5)
        cam.Elevation(30)
        self.screenshot("10_rotit")
        w.view3d.reset_camera()
        w.opacity_slider.setValue(40)
        self.screenshot("11_opacitate_40")
        w.opacity_slider.setValue(100)

        self.log("5. Optiuni: decimare 50%, umple golurile, netezire imagine 1 mm")
        w.decim_spin.setValue(50)
        w.fill_check.setChecked(True)
        w.sigma_spin.setValue(1.0)
        self.build("Os cu optiuni")
        w.decim_spin.setValue(0)
        w.fill_check.setChecked(False)
        w.sigma_spin.setValue(0)

        self.log("6. Export")
        for ext in ("stl", "obj", "ply"):
            self.save_path = str(self.out / f"model.{ext}")
            w.export_model()
            p = Path(self.save_path)
            size = f"{p.stat().st_size / 1e6:.1f} MB" if p.exists() else "LIPSA"
            self.log(f"  {ext}: {size}")

        self.log("7. Cazuri limita")
        w.lower_spin.setValue(500)
        w.upper_spin.setValue(100)
        self.build("prag inferior > superior")
        w.lower_spin.setValue(5000)
        w.upper_spin.setValue(6000)
        self.build("interval fara voxeli")
        self.choose_preset("Os")
        self.pump(0.3)
        self.log(f"  dupa schimbarea pragului, exportul ramane activ: {w.export_btn.isEnabled()}")

        self.log("8. Fereastra maximizata")
        w.showMaximized()
        self.pump(1)
        self.screenshot("12_maximizat")
        return self.finish()

    def finish(self) -> int:
        self.log(f"Dialoguri afisate: {len(self.dialogs)}")
        (self.out / "raport.txt").write_text("\n".join(self.lines), encoding="utf-8")
        self.w.close()
        return 0


def run(app: QApplication, folder: str, out_dir: str) -> int:
    try:
        return Playtest(app, folder, out_dir).run()
    except Exception:
        traceback.print_exc()
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "raport.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return 1
