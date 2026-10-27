"""Vizualizarea 3D a modelului cu VTK, integrata in Qt."""

from __future__ import annotations

import vtk
from PySide6.QtWidgets import QVBoxLayout, QWidget
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor


class View3D(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.vtk_widget)

        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.10, 0.11, 0.13)
        self.renderer.SetBackground2(0.25, 0.27, 0.32)
        self.renderer.GradientBackgroundOn()
        rw = self.vtk_widget.GetRenderWindow()
        rw.AddRenderer(self.renderer)
        self.interactor = rw.GetInteractor()
        self.interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

        self._actor: vtk.vtkActor | None = None
        self._add_orientation_axes()

    def initialize(self):
        """Se apeleaza dupa ce fereastra e afisata (cerinta VTK pe Windows)."""
        self.vtk_widget.Initialize()
        self.vtk_widget.Start()

    def set_mesh(self, poly: vtk.vtkPolyData, color=(0.95, 0.90, 0.80)):
        if self._actor is not None:
            self.renderer.RemoveActor(self._actor)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly)
        mapper.ScalarVisibilityOff()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetSpecular(0.3)
        prop.SetSpecularPower(20)
        self.renderer.AddActor(actor)
        self._actor = actor
        self.reset_camera()

    def clear(self):
        if self._actor is not None:
            self.renderer.RemoveActor(self._actor)
            self._actor = None
        self.render()

    def set_opacity(self, value: float):
        if self._actor is not None:
            self._actor.GetProperty().SetOpacity(value)
            self.render()

    def reset_camera(self):
        cam = self.renderer.GetActiveCamera()
        # vedere anterioara: pacientul priveste spre utilizator (conventia LPS din DICOM)
        cam.SetPosition(0, -1, 0)
        cam.SetFocalPoint(0, 0, 0)
        cam.SetViewUp(0, 0, 1)
        self.renderer.ResetCamera()
        self.render()

    def render(self):
        self.vtk_widget.GetRenderWindow().Render()

    def close_vtk(self):
        self.vtk_widget.Finalize()

    def _add_orientation_axes(self):
        axes = vtk.vtkAxesActor()
        axes.SetXAxisLabelText("L")
        axes.SetYAxisLabelText("P")
        axes.SetZAxisLabelText("S")
        self._marker = vtk.vtkOrientationMarkerWidget()
        self._marker.SetOrientationMarker(axes)
        self._marker.SetInteractor(self.interactor)
        self._marker.SetViewport(0.0, 0.0, 0.18, 0.18)
        self._marker.SetEnabled(1)
        self._marker.InteractiveOff()
