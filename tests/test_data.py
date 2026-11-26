"""Structurile de date: geometrie, verificarea feliilor, volum, harta de etichete."""

import shutil

import numpy as np
import pytest

from dicom3d.data import Geometry, Label, LabelMap, SliceSampling, Volume
from dicom3d.io.dicom_loader import load_folder
from dicom3d.pipeline import ThresholdParams, reconstruct

# axele i, j, k rotite 30 grade in jurul lui z
_C, _S = np.cos(np.radians(30)), np.sin(np.radians(30))
ROTATED = (_C, -_S, 0, _S, _C, 0, 0, 0, 1)


# ---------- Geometry ----------

def test_index_world_roundtrip():
    g = Geometry((50, 40, 30), (0.7, 0.7, 2.5), (-100.0, 20.0, 300.0), ROTATED)
    ijk = np.array([[0, 0, 0], [49, 39, 29], [10.5, 3.25, 7]])
    assert g.world_to_index(g.index_to_world(ijk)) == pytest.approx(ijk)
    # matricea afina da acelasi rezultat
    h = np.c_[ijk, np.ones(len(ijk))] @ g.affine.T
    assert h[:, :3] == pytest.approx(g.index_to_world(ijk))
    assert g.index_to_world([0, 0, 0]) == pytest.approx(g.origin)


def test_shape_order_and_voxel_volume():
    g = Geometry.from_shape((30, 40, 50), spacing=(0.5, 0.5, 2.0))
    assert g.size == (50, 40, 30) and g.shape == (30, 40, 50)
    assert g.voxel_volume_mm3 == pytest.approx(0.5)
    assert g.extent_mm == pytest.approx((25, 20, 60))


def test_axis_codes_and_obliquity():
    assert Geometry((2, 2, 2), (1, 1, 1)).axis_codes() == "LPS"
    flipped = Geometry((2, 2, 2), (1, 1, 1), direction=(-1, 0, 0, 0, -1, 0, 0, 0, 1))
    assert flipped.axis_codes() == "RAS"
    rot = Geometry((2, 2, 2), (1, 1, 1), direction=ROTATED)
    assert rot.obliquity_deg() == pytest.approx(30) and rot.is_oblique()
    assert not flipped.is_oblique()


def test_invalid_geometry_is_rejected():
    with pytest.raises(ValueError):
        Geometry((2, 2, 2), (1, 0, 1))
    with pytest.raises(ValueError):
        Geometry((2, 2, 2), (1, 1, 1), direction=(2, 0, 0, 0, 1, 0, 0, 0, 1))


def test_same_grid():
    a = Geometry((10, 10, 10), (1, 1, 2), (0, 0, 0))
    assert a.same_grid(Geometry((10, 10, 10), (1, 1, 2.0000001), (0, 0, 0)))
    assert not a.same_grid(Geometry((10, 10, 10), (1, 1, 2), (0, 0, 1)))
    assert not a.same_grid(Geometry((10, 10, 11), (1, 1, 2), (0, 0, 0)))


# ---------- SliceSampling ----------

def _stack(z, x_shift=None):
    z = np.asarray(z, float)
    x = np.zeros_like(z) if x_shift is None else np.asarray(x_shift, float)
    return np.c_[x, np.zeros_like(z), z]


def test_uniform_stack_is_ok():
    s = SliceSampling.from_positions(_stack(np.arange(10) * 1.25), (1, 0, 0), (0, 1, 0), 2.5)
    assert s.ok and s.spacing_mm == pytest.approx(1.25) and s.warnings() == []
    assert s.overlap  # grosime 2.5 mm la pas 1.25 mm: reconstructie cu suprapunere


def test_reversed_stack_has_positive_steps():
    s = SliceSampling.from_positions(_stack(np.arange(10)[::-1] * 2.0), (1, 0, 0), (0, 1, 0))
    assert s.ok and s.spacing_mm == pytest.approx(2.0)


def test_missing_and_duplicate_slices_are_found():
    z = [0, 2, 4, 8, 10, 10, 12]  # lipseste 6, 10 apare de doua ori
    s = SliceSampling.from_positions(_stack(z), (1, 0, 0), (0, 1, 0))
    assert s.gaps == [2] and s.duplicates == [4] and not s.ok
    assert len(s.warnings()) == 2


def test_variable_spacing_and_tilt():
    s = SliceSampling.from_positions(_stack([0, 1, 2, 3.5, 5, 6]), (1, 0, 0), (0, 1, 0))
    assert not s.is_uniform and not s.gaps
    tilted = SliceSampling.from_positions(_stack(np.arange(10.0), np.arange(10) * 0.2),
                                          (1, 0, 0), (0, 1, 0))
    assert tilted.tilt_deg == pytest.approx(np.degrees(np.arctan(0.2)))
    assert tilted.is_tilted and not tilted.ok


# ---------- Volume ----------

def test_volume_checks_shape_against_geometry():
    with pytest.raises(ValueError):
        Volume(np.zeros((3, 4, 5)), Geometry((3, 4, 5), (1, 1, 1)))  # size e (x, y, z)
    v = Volume.from_array(np.arange(60).reshape(3, 4, 5), spacing=(1, 1, 1))
    assert v.shape_xyz == (5, 4, 3)
    assert v.value_at(v.geometry.index_to_world([4, 1, 2])) == v.array[2, 1, 4]
    assert np.isnan(v.value_at([100, 0, 0]))


def test_sitk_roundtrip_keeps_geometry():
    g = Geometry((5, 4, 3), (0.5, 0.6, 2.0), (1, 2, 3), ROTATED)
    v = Volume(np.random.default_rng(0).normal(size=g.shape).astype(np.float32), g)
    back = Volume.from_sitk(v.to_sitk())
    assert back.geometry.same_grid(g) and np.array_equal(back.array, v.array)


# ---------- LabelMap ----------

def test_labelmap_add_merge_and_volumes():
    g = Geometry.from_shape((10, 10, 10), spacing=(1, 1, 2))
    a = np.zeros(g.shape, np.uint8)
    a[:5] = 1
    b = np.zeros(g.shape, np.uint8)
    b[3:] = 1
    lm = LabelMap.from_mask(a, g, Label(1, "Os"))
    other = LabelMap.from_mask(b, g, Label(2, "Plamani"))
    lm.merge(other)  # suprapunerea (feliile 3, 4) ramane la prima structura
    assert lm.voxel_count(1) == 500 and lm.voxel_count(2) == 500
    assert lm.volume_ml(1) == pytest.approx(1.0)
    assert lm.by_name("Plamani").value == 2
    with pytest.raises(ValueError):
        lm.add(a, Label(1, "Din nou"))
    with pytest.raises(ValueError):
        lm.merge(LabelMap.empty(Geometry.from_shape((10, 10, 10), spacing=(1, 1, 1))))


def test_labelmap_grows_to_uint16():
    g = Geometry.from_shape((2, 2, 2))
    lm = LabelMap.empty(g)
    lm.add(np.ones(g.shape, np.uint8), Label(300, "Mare"))
    assert lm.array.dtype == np.uint16 and lm.voxel_count(300) == 8


# ---------- incarcare DICOM ----------

def test_loaded_volume_has_metadata_and_sampling(phantom_dir):
    vol = load_folder(phantom_dir)
    assert vol.geometry.axis_codes() == "LPS"
    acq = vol.acquisition
    assert acq.is_ct and acq.rescale_intercept == -1024 and acq.slice_thickness_mm == 2.0
    assert acq.frame_of_reference_uid
    assert vol.sampling.ok and vol.sampling.num_slices == 60
    assert vol.sampling.spacing_mm == pytest.approx(vol.spacing[2])


def test_missing_slice_is_reported(phantom_dir, tmp_path):
    files = sorted(phantom_dir.glob("*.dcm"))
    for f in files[:20] + files[21:]:
        shutil.copy(f, tmp_path)
    vol = load_folder(tmp_path)
    assert vol.sampling.gaps and not vol.sampling.ok
    assert any("lips" in w for w in vol.sampling.warnings())


def test_reconstruction_keeps_label_and_params(phantom_dir):
    vol = load_folder(phantom_dir)
    result = reconstruct(vol, ThresholdParams(250, 3000), label=Label(1, "Os", (1, 0.8, 0.5)))
    assert result.segmentation.geometry.same_grid(vol.geometry)
    assert result.label.name == "Os" and result.label.source == "prag"
    assert result.label.params["lower"] == 250
    assert result.mask.dtype == np.uint8 and result.mask.any()
