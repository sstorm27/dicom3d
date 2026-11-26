"""Generarea suprafetei 3D (Marching Cubes) si exportul ei."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from vtkmodules.util import numpy_support

from dicom3d import vtk_lite as vtk


@dataclass
class MeshOptions:
    smoothing_iterations: int = 20  # 0 = fara netezire
    decimation: float = 0.0  # fractiunea de triunghiuri eliminate, 0..0.95
    patient_coords: bool = True  # aplica originea si orientarea din DICOM
    # "nivele de gri": Marching Cubes pe valorile HU (pozitie sub-voxel a marginii);
    # "binar": Marching Cubes pe masca 0/1 (suprafata in trepte, comportamentul vechi)
    surface: str = "nivele de gri"


SURFACE_MODES = ("nivele de gri", "binar")


def mask_to_image_data(
    mask: np.ndarray, spacing: tuple[float, float, float]
) -> vtk.vtkImageData:
    """Converteste o masca (z, y, x) in vtkImageData, in coordonate de voxel * spacing."""
    return _to_image_data(np.ascontiguousarray(mask, dtype=np.uint8), spacing,
                          vtk.VTK_UNSIGNED_CHAR)


def _to_image_data(array: np.ndarray, spacing, vtk_type) -> vtk.vtkImageData:
    z, y, x = array.shape
    img = vtk.vtkImageData()
    img.SetDimensions(x, y, z)
    img.SetSpacing(spacing)
    img.SetOrigin(0.0, 0.0, 0.0)
    # VTK parcurge x cel mai rapid, la fel ca ordinea C a unui array (z, y, x)
    arr = numpy_support.numpy_to_vtk(array.ravel(), deep=True, array_type=vtk_type)
    img.GetPointData().SetScalars(arr)
    return img


def inside_field(
    image: np.ndarray, mask: np.ndarray, lower: float, upper: float, eps: float = 0.5
) -> np.ndarray:
    """Camp continuu care e pozitiv in interiorul structurii si zero pe marginea ei.

    g = min(f - lower, upper - f) e pozitiv exact cand valoarea HU f e in [lower, upper]
    si variaza continuu, deci izosuprafata g = 0 trece printre voxeli acolo unde
    interpolarea liniara a valorilor reale pune marginea (efectul de volum partial
    devine informatie sub-voxel). Semnul e fortat sa coincida cu masca, deci tot ce a
    hotarat segmentarea (componenta cea mai mare, goluri umplute, aer exterior
    eliminat) se pastreaza; doar pozitia exacta a marginii vine din imagine.
    """
    f = image.astype(np.float32, copy=False)
    g = np.minimum(f - np.float32(lower), np.float32(upper) - f)
    inside = mask.astype(bool)
    return np.where(inside, np.maximum(g, eps), np.minimum(g, -eps)).astype(np.float32)


def marching_cubes(
    mask: np.ndarray,
    spacing: tuple[float, float, float],
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    direction: tuple[float, ...] = (1, 0, 0, 0, 1, 0, 0, 0, 1),
    options: MeshOptions | None = None,
) -> vtk.vtkPolyData:
    """Extrage suprafata mastii binare cu Marching Cubes la izovaloarea 0.5.

    Folosim Flying Edges, implementarea paralela din VTK a algoritmului Marching
    Cubes: aceleasi triunghiuri, dar de ~15 ori mai rapid pe volume mari.
    """
    if not mask.any():
        raise ValueError("Masca este goala: nu exista nimic de reconstruit.")
    # bordura de un voxel inchide suprafata la marginile volumului
    image = mask_to_image_data(np.pad(mask, 1), spacing)
    return _surface(image, 0.5, spacing, origin, direction, options or MeshOptions())


def marching_cubes_field(
    field: np.ndarray,
    spacing: tuple[float, float, float],
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    direction: tuple[float, ...] = (1, 0, 0, 0, 1, 0, 0, 0, 1),
    options: MeshOptions | None = None,
) -> vtk.vtkPolyData:
    """Marching Cubes pe un camp continuu (vezi `inside_field`), la izovaloarea 0.

    Varfurile se pun prin interpolare liniara pe muchii, p = p1 + (0 - f1)/(f2 - f1)(p2 - p1),
    deci suprafata urmeaza valorile reale in loc sa stea mereu la jumatatea muchiei.
    """
    if not (field > 0).any():
        raise ValueError("Masca este goala: nu exista nimic de reconstruit.")
    padded = np.pad(field, 1, mode="edge")
    # bordura are semnul opus vecinului: suprafata se inchide la jumatatea muchiei,
    # exact ca in varianta binara
    shell = np.ones(padded.shape, bool)
    shell[1:-1, 1:-1, 1:-1] = False
    padded[shell] = -np.abs(padded[shell])
    image = _to_image_data(np.ascontiguousarray(padded, np.float32), spacing, vtk.VTK_FLOAT)
    return _surface(image, 0.0, spacing, origin, direction, options or MeshOptions())


def _surface(image, iso, spacing, origin, direction, options: MeshOptions) -> vtk.vtkPolyData:
    mc = vtk.vtkFlyingEdges3D()
    mc.SetInputData(image)
    mc.SetValue(0, iso)
    mc.ComputeNormalsOff()
    mc.ComputeGradientsOff()
    mc.ComputeScalarsOff()
    mc.Update()
    poly: vtk.vtkPolyData = mc.GetOutput()

    if options.smoothing_iterations > 0:
        smooth = vtk.vtkWindowedSincPolyDataFilter()
        smooth.SetInputData(poly)
        smooth.SetNumberOfIterations(options.smoothing_iterations)
        smooth.SetPassBand(0.1)
        smooth.NonManifoldSmoothingOn()
        smooth.NormalizeCoordinatesOn()
        smooth.BoundarySmoothingOff()
        smooth.Update()
        poly = smooth.GetOutput()

    # decimarea dupa netezire: altfel metrica cuadrica ar pastra fidel tocmai treptele
    if options.decimation > 0:
        dec = vtk.vtkQuadricDecimation()
        dec.SetInputData(poly)
        dec.SetTargetReduction(min(options.decimation, 0.95))
        dec.Update()
        poly = dec.GetOutput()

    poly = _to_patient(poly, spacing, origin, direction, options.patient_coords)

    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(poly)
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.SplittingOff()
    normals.Update()
    return normals.GetOutput()


def _to_patient(poly, spacing, origin, direction, enabled: bool) -> vtk.vtkPolyData:
    """Scade bordura adaugata si, optional, muta mesh-ul in coordonatele pacientului."""
    m = vtk.vtkMatrix4x4()
    d = np.array(direction, dtype=float).reshape(3, 3) if enabled else np.eye(3)
    o = np.array(origin, dtype=float) if enabled else np.zeros(3)
    pad = -np.array(spacing, dtype=float)  # o felie de bordura pe fiecare axa
    t = o + d @ pad
    for i in range(3):
        for j in range(3):
            m.SetElement(i, j, d[i, j])
        m.SetElement(i, 3, t[i])
    transform = vtk.vtkTransform()
    transform.SetMatrix(m)
    f = vtk.vtkTransformFilter()
    f.SetInputData(poly)
    f.SetTransform(transform)
    f.Update()
    return f.GetOutput()


def mesh_stats(poly: vtk.vtkPolyData) -> dict[str, float]:
    mass = vtk.vtkMassProperties()
    tri = vtk.vtkTriangleFilter()
    tri.SetInputData(poly)
    tri.Update()
    mass.SetInputData(tri.GetOutput())
    mass.Update()
    return {
        "triangles": poly.GetNumberOfPolys(),
        "vertices": poly.GetNumberOfPoints(),
        "surface_mm2": mass.GetSurfaceArea(),
        "volume_ml": mass.GetVolume() / 1000.0,
    }


def export_mesh(poly: vtk.vtkPolyData, path: str | Path) -> Path:
    """Salveaza mesh-ul; formatul se alege dupa extensie (.stl, .obj, .ply)."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in (".stl", ".obj", ".ply"):
        raise ValueError(f"Format necunoscut: {ext} (folositi .stl, .obj sau .ply)")
    path.parent.mkdir(parents=True, exist_ok=True)
    if ext == ".ply":
        writer = vtk.vtkPLYWriter()
        writer.SetFileTypeToBinary()
        writer.SetFileName(str(path))
        writer.SetInputData(poly)
        if writer.Write() != 1:
            raise IOError(f"Nu am putut scrie {path}")
        return path
    # STL si OBJ le scriem direct: writer-ele VTK sunt in vtkIOGeometry, care trage
    # dupa el module blocate de Smart App Control pe Windows (vezi vtk_lite.py)
    points, triangles = mesh_arrays(poly)
    if ext == ".stl":
        _write_stl(path, points, triangles)
    else:
        _write_obj(path, points, triangles)
    return path


def mesh_arrays(poly: vtk.vtkPolyData) -> tuple[np.ndarray, np.ndarray]:
    """Varfurile (N, 3) si triunghiurile (M, 3, indici) ale mesh-ului."""
    tri = vtk.vtkTriangleFilter()
    tri.SetInputData(poly)
    tri.PassVertsOff()
    tri.PassLinesOff()
    tri.Update()
    out = tri.GetOutput()
    points = numpy_support.vtk_to_numpy(out.GetPoints().GetData()).astype(np.float64)
    conn = numpy_support.vtk_to_numpy(out.GetPolys().GetConnectivityArray())
    return points, conn.reshape(-1, 3).astype(np.int64)


def _write_stl(path: Path, points: np.ndarray, triangles: np.ndarray):
    v = points[triangles]  # (M, 3, 3)
    normals = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 0)
    record = np.dtype([("normal", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    data = np.zeros(len(triangles), dtype=record)
    data["normal"], data["v"] = normals, v
    with open(path, "wb") as f:
        f.write(b"DICOM3D binary STL".ljust(80, b" "))
        f.write(np.uint32(len(triangles)).tobytes())
        f.write(data.tobytes())


def _write_obj(path: Path, points: np.ndarray, triangles: np.ndarray):
    with open(path, "w", encoding="ascii") as f:
        f.write("# DICOM3D\n")
        np.savetxt(f, points, fmt="v %.6f %.6f %.6f")
        np.savetxt(f, triangles + 1, fmt="f %d %d %d")  # OBJ numara de la 1
