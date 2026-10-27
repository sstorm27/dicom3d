"""Vizualizarea 3D a modelului cu VTK, integrata in Qt."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QVariantAnimation
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QVBoxLayout, QWidget
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from dicom3d import vtk_lite as vtk
from dicom3d.ui import theme

# directia din care priveste camera si "sus"-ul imaginii, in coordonate LPS (DICOM)
VIEWS = {
    "Anterior": ((0, -1, 0), (0, 0, 1)),  # pacientul priveste spre utilizator
    "Lateral": ((1, 0, 0), (0, 0, 1)),  # din partea stanga a pacientului
    "Superior": ((0, 0, 1), (0, -1, 0)),  # de sus, cu fata pacientului in sus
}


def _rgb(color: str) -> tuple[float, float, float]:
    c = QColor(color)
    return c.redF(), c.greenF(), c.blueF()


def _slerp(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    """Interpolare pe sfera intre doua directii (pentru rotirea lina a camerei)."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    dot = float(np.clip(a @ b, -1.0, 1.0))
    if dot > 0.9995:
        v = a + (b - a) * t
        return v / np.linalg.norm(v)
    if dot < -0.9995:  # directii opuse: ocolim printr-o axa perpendiculara
        perp = np.cross(a, (0.0, 0.0, 1.0))
        if np.linalg.norm(perp) < 1e-6:
            perp = np.cross(a, (0.0, 1.0, 0.0))
        perp /= np.linalg.norm(perp)
        return np.cos(np.pi * t) * a + np.sin(np.pi * t) * perp
    th = np.arccos(dot)
    return (np.sin((1 - t) * th) * a + np.sin(t * th) * b) / np.sin(th)


class View3D(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.vtk_widget)

        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.0, 0.0, 0.0)  # negru, ca felia: nimic nu concureaza cu modelul
        # depth peeling: cu opacitate sub 100 % suprafetele din spate se vad corect prin cele din fata
        self.renderer.SetUseDepthPeeling(1)
        self.renderer.SetMaximumNumberOfPeels(8)
        self.renderer.SetOcclusionRatio(0.0)
        lights = vtk.vtkLightKit()  # lumina din mai multe directii: relief mai lizibil
        lights.SetKeyLightIntensity(1.0)
        lights.AddLightsToRenderer(self.renderer)
        rw = self.vtk_widget.GetRenderWindow()
        rw.SetAlphaBitPlanes(1)
        rw.SetMultiSamples(0)  # depth peeling nu merge cu multisampling pe unele placi video
        rw.AddRenderer(self.renderer)
        self.interactor = rw.GetInteractor()
        self.interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

        self._actor: vtk.vtkActor | None = None
        self._color = theme.TISSUE_COLORS["Os"]
        self._add_orientation_axes()

        self._cam_from = self._cam_to = None
        self._cam_anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=280,
                                           easingCurve=theme.EASE_OUT)
        self._cam_anim.valueChanged.connect(self._camera_step)

    def initialize(self):
        """Se apeleaza dupa ce fereastra e afisata (cerinta VTK pe Windows)."""
        self.vtk_widget.Initialize()
        self.vtk_widget.Start()

    def has_mesh(self) -> bool:
        return self._actor is not None

    def set_mesh(self, poly: vtk.vtkPolyData, color: str | None = None):
        if self._actor is not None:
            self.renderer.RemoveActor(self._actor)
        if color is not None:
            self._color = color
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly)
        mapper.ScalarVisibilityOff()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*_rgb(self._color))
        prop.SetAmbient(0.06)
        prop.SetDiffuse(0.88)
        prop.SetSpecular(0.22)
        prop.SetSpecularPower(28)
        self.renderer.AddActor(actor)
        self._actor = actor
        self._marker.GetOrientationMarker().SetVisibility(True)
        self.reset_camera()

    def set_color(self, color: str):
        self._color = color
        if self._actor is not None:
            self._actor.GetProperty().SetColor(*_rgb(color))
            self.render()

    def clear(self):
        if self._actor is not None:
            self.renderer.RemoveActor(self._actor)
            self._actor = None
        self._marker.GetOrientationMarker().SetVisibility(False)
        self.render()

    def set_opacity(self, value: float):
        if self._actor is not None:
            self._actor.GetProperty().SetOpacity(value)
            self.render()

    def reset_camera(self):
        """Vedere anterioara, instant (se foloseste si din tastatura)."""
        self._cam_anim.stop()
        self._place_camera("Anterior")
        self.render()

    def set_view(self, name: str, animate: bool = True):
        """Roteste camera lin spre una dintre vederile standard."""
        self._cam_anim.stop()
        cam = self.renderer.GetActiveCamera()
        start = self._camera_state()
        self._place_camera(name)
        end = self._camera_state()
        if not animate or self._actor is None:
            self.render()
            return
        self._cam_from, self._cam_to = start, end
        self._apply_camera(*start)
        cam.Modified()
        self._cam_anim.start()

    def save_screenshot(self, path: str) -> bool:
        from vtkmodules.util import numpy_support

        self.render()
        f = vtk.vtkWindowToImageFilter()
        f.SetInput(self.vtk_widget.GetRenderWindow())
        f.ReadFrontBufferOff()
        f.Update()
        img = f.GetOutput()
        w, h, _ = img.GetDimensions()
        arr = numpy_support.vtk_to_numpy(img.GetPointData().GetScalars())
        arr = np.ascontiguousarray(arr.reshape(h, w, -1)[::-1])  # VTK are originea jos
        fmt = QImage.Format_RGBA8888 if arr.shape[2] == 4 else QImage.Format_RGB888
        return QImage(arr.data, w, h, arr.strides[0], fmt).copy().save(path)

    def render(self):
        self.vtk_widget.GetRenderWindow().Render()

    def close_vtk(self):
        self._cam_anim.stop()
        self.vtk_widget.Finalize()

    # ---------- camera ----------

    def _place_camera(self, name: str):
        direction, up = VIEWS[name]
        cam = self.renderer.GetActiveCamera()
        cam.SetPosition(*direction)
        cam.SetFocalPoint(0, 0, 0)
        cam.SetViewUp(*up)
        self.renderer.ResetCamera()

    def _camera_state(self):
        cam = self.renderer.GetActiveCamera()
        return (np.array(cam.GetPosition()), np.array(cam.GetFocalPoint()),
                np.array(cam.GetViewUp()))

    def _apply_camera(self, pos, focal, up):
        cam = self.renderer.GetActiveCamera()
        cam.SetFocalPoint(*focal)
        cam.SetPosition(*pos)
        cam.SetViewUp(*up)
        cam.OrthogonalizeViewUp()
        self.renderer.ResetCameraClippingRange()

    def _camera_step(self, t):
        if self._cam_from is None:
            return
        t = float(t)
        (p0, f0, u0), (p1, f1, u1) = self._cam_from, self._cam_to
        focal = f0 + (f1 - f0) * t
        d0, d1 = p0 - f0, p1 - f1
        r0, r1 = np.linalg.norm(d0), np.linalg.norm(d1)
        pos = focal + _slerp(d0, d1, t) * (r0 + (r1 - r0) * t)
        self._apply_camera(pos, focal, _slerp(u0, u1, t))
        self.render()

    def _add_orientation_axes(self):
        """Indicatorul de orientare din coltul din dreapta sus: axe gri, litere lizibile."""
        axes = vtk.vtkAxesActor()
        axes.SetXAxisLabelText("L")
        axes.SetYAxisLabelText("P")
        axes.SetZAxisLabelText("S")
        axes.SetShaftTypeToLine()
        axes.SetTotalLength(1.0, 1.0, 1.0)
        axes.SetConeRadius(0.3)
        line, text_color = _rgb(theme.OVERLAY_TEXT), _rgb(theme.TEXT)
        for shaft, tip, caption in (
            (axes.GetXAxisShaftProperty(), axes.GetXAxisTipProperty(), axes.GetXAxisCaptionActor2D()),
            (axes.GetYAxisShaftProperty(), axes.GetYAxisTipProperty(), axes.GetYAxisCaptionActor2D()),
            (axes.GetZAxisShaftProperty(), axes.GetZAxisTipProperty(), axes.GetZAxisCaptionActor2D()),
        ):
            shaft.SetColor(*line)
            shaft.SetLineWidth(1.5)
            tip.SetColor(*line)
            caption.GetTextActor().SetTextScaleModeToNone()  # litere de marime fixa, nu minuscule
            text = caption.GetCaptionTextProperty()
            text.SetColor(*text_color)
            text.SetFontSize(15)
            text.ItalicOff()
            text.BoldOn()
            text.ShadowOff()
            text.SetFontFamilyToArial()
        self._marker = vtk.vtkOrientationMarkerWidget()
        self._marker.SetOrientationMarker(axes)
        self._marker.SetInteractor(self.interactor)
        self._place_marker()
        self._marker.SetEnabled(1)
        self._marker.InteractiveOff()
        self._marker.GetOrientationMarker().SetVisibility(False)  # apare odata cu modelul

    MARKER_PX = 116  # latura indicatorului de orientare, in pixeli, indiferent de marimea vederii

    def _place_marker(self):
        w, h = max(self.width(), 1), max(self.height(), 1)
        fw, fh = min(self.MARKER_PX / w, 0.4), min(self.MARKER_PX / h, 0.4)
        self._marker.SetViewport(1.0 - fw, 1.0 - fh, 1.0, 1.0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_marker()
