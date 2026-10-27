import numpy as np
import pytest
import vtk

from dicom3d.io.dicom_loader import find_series, load_folder
from dicom3d.mesh.surface import MeshOptions, export_mesh, marching_cubes, mesh_stats
from dicom3d.pipeline import ThresholdParams, reconstruct
from dicom3d.segmentation.threshold import mask_volume_ml, threshold_mask


def test_find_and_load_series(phantom_dir):
    series = find_series(phantom_dir)
    assert len(series) == 1 and series[0].num_files == 60
    vol = load_folder(phantom_dir)
    assert vol.array.shape == (60, 128, 128)
    assert vol.spacing == pytest.approx((1.0, 1.0, 2.0))
    # feliile au fost scrise invers; dupa sortare z creste cu indexul
    assert vol.origin[2] == pytest.approx(0.0)
    # valorile sunt in HU (rescale aplicat)
    assert -1100 < vol.array.min() < -900
    assert 600 < vol.array.max() < 800


def test_largest_component_removes_isolated_object(phantom_dir):
    vol = load_folder(phantom_dir)
    all_bone = threshold_mask(vol, 250, 3000, keep_largest=False)
    spine = threshold_mask(vol, 250, 3000, keep_largest=True)
    isolated_ml = 4 / 3 * np.pi * 6**3 / 1000
    diff = mask_volume_ml(all_bone, vol.spacing) - mask_volume_ml(spine, vol.spacing)
    assert diff == pytest.approx(isolated_ml, rel=0.25)


def test_marching_cubes_cube_volume():
    mask = np.zeros((20, 20, 20), np.uint8)
    mask[5:15, 5:15, 5:15] = 1
    poly = marching_cubes(mask, (1.0, 1.0, 1.0), options=MeshOptions(smoothing_iterations=0))
    stats = mesh_stats(poly)
    # izovaloarea 0.5 taie colturile, deci volumul e putin sub 1000 mm3
    assert 0.85 < stats["volume_ml"] < 1.0


def test_mesh_is_in_patient_coordinates():
    mask = np.zeros((10, 10, 10), np.uint8)
    mask[2:8, 2:8, 2:8] = 1
    origin = (100.0, -50.0, 20.0)
    poly = marching_cubes(mask, (2.0, 1.0, 0.5), origin=origin,
                          options=MeshOptions(smoothing_iterations=0))
    xmin, xmax, ymin, ymax, zmin, zmax = poly.GetBounds()
    # voxelii 2..7 -> margini la 1.5 si 7.5 voxeli (izovaloarea 0.5)
    assert xmin == pytest.approx(100 + 1.5 * 2.0) and xmax == pytest.approx(100 + 7.5 * 2.0)
    assert ymin == pytest.approx(-50 + 1.5) and zmax == pytest.approx(20 + 7.5 * 0.5)


def test_empty_mask_raises():
    with pytest.raises(ValueError):
        marching_cubes(np.zeros((5, 5, 5), np.uint8), (1, 1, 1))


@pytest.mark.parametrize("ext", [".stl", ".obj", ".ply"])
def test_reconstruct_and_export(phantom_dir, tmp_path, ext):
    vol = load_folder(phantom_dir)
    result = reconstruct(vol, ThresholdParams(250, 3000), MeshOptions(decimation=0.5))
    assert result.stats["triangles"] > 1000
    assert 15 < result.stats["volume_ml"] < 23  # tija + 6 sfere ~ 19 ml
    out = export_mesh(result.mesh, tmp_path / f"model{ext}")
    assert out.stat().st_size > 10_000


def test_stl_roundtrip_is_closed(phantom_dir, tmp_path):
    vol = load_folder(phantom_dir)
    result = reconstruct(vol, ThresholdParams(250, 3000))
    path = export_mesh(result.mesh, tmp_path / "os.stl")
    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(path))
    reader.Update()
    edges = vtk.vtkFeatureEdges()
    edges.SetInputConnection(reader.GetOutputPort())
    edges.BoundaryEdgesOn()
    edges.FeatureEdgesOff()
    edges.NonManifoldEdgesOff()
    edges.ManifoldEdgesOff()
    edges.Update()
    # un model imprimabil 3D nu are muchii de margine (suprafata inchisa)
    assert edges.GetOutput().GetNumberOfCells() == 0
