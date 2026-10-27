"""Doar clasele VTK folosite de aplicatie.

`import vtk` incarca toate cele ~150 de module VTK. Pe Windows cu Smart App
Control, unele module nesemnate (ex. vtkFiltersCellGrid) sunt blocate si
aplicatia nu mai porneste; in plus, pachetul .exe iese mult mai mare.
Restul codului foloseste `from dicom3d import vtk_lite as vtk`.

Nu importa vtkIOGeometry: importul lui Python incarca vtkFiltersCellGrid
(exact modulul blocat). STL si OBJ se scriu in mesh/surface.py.
"""

# randarea OpenGL, textul (etichetele axelor) si stilurile de interactiune se
# inregistreaza ca implementari ale claselor abstracte doar daca sunt importate
import vtkmodules.vtkInteractionStyle  # noqa: F401
import vtkmodules.vtkRenderingFreeType  # noqa: F401
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
from vtkmodules.vtkCommonCore import VTK_UNSIGNED_CHAR
from vtkmodules.vtkCommonDataModel import vtkImageData, vtkPolyData
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from vtkmodules.vtkCommonTransforms import vtkTransform
from vtkmodules.vtkFiltersCore import (
    vtkFeatureEdges,
    vtkFlyingEdges3D,
    vtkMarchingCubes,
    vtkMassProperties,
    vtkPolyDataNormals,
    vtkQuadricDecimation,
    vtkTriangleFilter,
    vtkWindowedSincPolyDataFilter,
)
from vtkmodules.vtkFiltersGeneral import vtkTransformFilter
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
from vtkmodules.vtkIOPLY import vtkPLYWriter
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkLightKit,
    vtkPolyDataMapper,
    vtkRenderer,
    vtkWindowToImageFilter,
)

__all__ = [name for name in dir() if name.startswith(("vtk", "VTK_"))]
