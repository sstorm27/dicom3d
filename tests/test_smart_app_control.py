"""Modulele VTK blocate de Smart App Control pe Windows nu trebuie incarcate.

Lista vine dintr-un test pe un PC cu Smart App Control activ (VTK 9.7.1):
fiecare fisier .pyd/.dll din build a fost incarcat separat.
"""

import subprocess
import sys

BLOCKED = [
    "vtkmodules.vtkFiltersCellGrid",
    "vtkmodules.vtkFiltersGeometry",
    "vtkmodules.vtkAcceleratorsVTKmFilters",
    "vtkmodules.vtkIOVeraOut",
]

SCRIPT = """
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import dicom3d.ui.main_window  # importa toata interfata
from dicom3d.mesh.surface import export_mesh, marching_cubes, mesh_stats
mask = np.zeros((8, 8, 8), np.uint8); mask[2:6, 2:6, 2:6] = 1
poly = marching_cubes(mask, (1.0, 1.0, 1.0))
mesh_stats(poly)
for ext in (".stl", ".obj", ".ply"):
    export_mesh(poly, os.path.join(sys.argv[1], "m" + ext))
print("\\n".join(m for m in sys.modules if m.startswith("vtkmodules.")))
"""


def test_blocked_vtk_modules_are_not_imported(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(tmp_path)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.split()
    assert "vtkmodules.vtkRenderingOpenGL2" in out  # verificam ca lista e reala
    assert not set(BLOCKED) & set(out)
