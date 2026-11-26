"""Teste pentru preprocesare si extragerea suprafetei pe nivele de gri."""

import sys
from pathlib import Path

import numpy as np
import pytest

from dicom3d.data import Volume
from dicom3d.mesh.surface import MeshOptions
from dicom3d.pipeline import NO_PREPROCESSING, ThresholdParams, reconstruct
from dicom3d.preprocessing import (
    PreprocessOptions,
    clean_hu,
    crop_to_range,
    denoise,
    isotropic_spacing,
    resample_isotropic,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evaluate_accuracy import HALF_MAX, Capsule, Sphere, evaluate, make_ct  # noqa: E402



def test_clean_hu_clamps_padding():
    arr = np.array([[[-3024, -1000, 500]]], np.int16)
    out = clean_hu(Volume.from_array(arr, (1, 1, 1), (0, 0, 0)))
    assert out.array.tolist() == [[[-1024, -1000, 500]]]
    assert out.array.dtype == np.int16


def test_resample_isotropic_keeps_physical_extent():
    vol = Volume.from_array(np.zeros((10, 20, 20), np.float32), (0.5, 0.5, 2.0), (10.0, -5.0, 3.0))
    iso = resample_isotropic(vol, PreprocessOptions())
    assert iso.spacing == pytest.approx((0.5, 0.5, 0.5))
    assert iso.array.shape == (40, 20, 20)
    # centrul primului si al ultimului voxel raman la aceeasi distanta fizica de centru
    first_z, last_z = iso.origin[2], iso.origin[2] + 39 * 0.5
    assert (first_z + last_z) / 2 == pytest.approx(3.0 + 9 * 2.0 / 2)


def test_resample_respects_memory_limit():
    vol = Volume.from_array(np.zeros((100, 100, 100), np.float32), (1.0, 1.0, 3.0), (0, 0, 0))
    s = isotropic_spacing(vol, PreprocessOptions(max_voxels=1_000_000))
    assert np.prod(np.array([100, 100, 300]) / s) <= 1_000_000 * 1.01


def test_crop_shifts_origin_to_kept_region():
    arr = np.full((20, 30, 40), -1000, np.float32)
    arr[5:8, 10:12, 20:25] = 700
    vol = Volume.from_array(arr, (1.0, 1.0, 2.0), (100.0, 0.0, 0.0))
    out = crop_to_range(vol, 250, 3000, margin_mm=2.0)
    assert out.array.shape == (3 + 2, 2 + 4, 5 + 4)  # margine 1 felie pe z, 2 voxeli pe x/y
    assert out.origin == pytest.approx((100.0 + 18, 8.0, 8.0))
    assert (out.array == 700).sum() == (arr == 700).sum()


def test_anisotropic_diffusion_reduces_noise_keeps_edge():
    rng = np.random.default_rng(1)
    arr = np.where(np.arange(32)[None, None, :] < 16, 0.0, 200.0) * np.ones((8, 32, 1))
    noisy = (arr + rng.normal(0, 20, arr.shape)).astype(np.float32)
    vol = Volume.from_array(noisy, (1.0, 1.0, 1.0), (0, 0, 0))
    out = denoise(vol, PreprocessOptions(denoise="anizotropic")).array
    assert out[:, :, 2:12].std() < 0.6 * noisy[:, :, 2:12].std()
    # marginea ramane abrupta: saltul intre coloanele 15 si 16 se pastreaza aproape intreg
    assert (out[:, :, 16].mean() - out[:, :, 15].mean()) > 150


@pytest.mark.parametrize("shape", [
    Sphere((24.3, 23.7, 24.9), 12.0),
    Capsule((24.2, 23.9, 24.6), (0.53, 0.20, 0.83), 26.0, 3.0),
])
def test_new_pipeline_is_closer_to_true_surface(shape):
    vol = make_ct(shape, (0.9766, 0.9766, 3.0), noise=20)
    old = evaluate(shape, vol, NO_PREPROCESSING, MeshOptions(20, surface="binar"), HALF_MAX)
    new = evaluate(shape, vol, PreprocessOptions(), MeshOptions(20), HALF_MAX)
    # distanta medie si P95 fata de suprafata exacta scad cu cel putin 20%
    assert new[0] < 0.8 * old[0] and new[1] < 0.8 * old[1]


def test_mask_returned_on_original_grid(phantom_dir):
    from dicom3d.io.dicom_loader import load_folder

    vol = load_folder(phantom_dir)  # spatiere 1 x 1 x 2 mm
    res = reconstruct(vol, ThresholdParams(250, 3000))
    assert res.mask.shape == vol.array.shape
    old = reconstruct(vol, ThresholdParams(250, 3000), preprocess_options=NO_PREPROCESSING)
    # aceeasi structura: mastile se suprapun aproape complet
    inter = (res.mask & old.mask).sum()
    assert inter / old.mask.sum() > 0.9
    assert res.stats["volume_ml"] == pytest.approx(old.stats["volume_ml"], rel=0.1)


def test_denoising_helps_low_contrast_structures():
    shape = Sphere((24.3, 23.7, 24.9), 12.0)
    vol = make_ct(shape, (0.9766, 0.9766, 3.0), noise=30, inside_hu=120, outside_hu=40)
    plain = evaluate(shape, vol, PreprocessOptions(), MeshOptions(20), 80)
    filtered = evaluate(shape, vol, PreprocessOptions(denoise="anizotropic"), MeshOptions(20), 80)
    # fara filtrare pragul prinde zgomotul de langa sfera; cu difuzie anizotropa nu
    assert filtered[1] < 0.3 * plain[1]


def test_large_components_keeps_separate_big_bones():
    from dicom3d.segmentation.threshold import threshold_mask

    arr = np.full((30, 60, 60), 40.0, np.float32)
    arr[5:25, 5:25, 5:25] = 700  # 8 ml, cea mai mare ("coloana")
    arr[5:20, 35:50, 35:50] = 700  # 3.4 ml ("omoplat")
    arr[27:29, 50:52, 50:52] = 700  # 8 voxeli, zgomot
    vol = Volume.from_array(arr, (1.0, 1.0, 1.0), (0, 0, 0))
    only_largest = threshold_mask(vol, 250, 3000, keep_largest=True)
    big = threshold_mask(vol, 250, 3000, keep_largest=True, min_component_ml=2.0)
    assert only_largest.sum() == 20**3
    assert big.sum() == 20**3 + 15**3  # zgomotul ramane eliminat


def test_solidify_fills_hollow_bone():
    from dicom3d.segmentation.threshold import threshold_mask

    z, y, x = np.mgrid[0:40, 0:40, 0:40]
    r = np.sqrt((y - 20.0) ** 2 + (x - 20.0) ** 2)
    arr = np.where((r < 8) & (r >= 6), 700.0, 40.0).astype(np.float32)  # tub: corticala
    arr[:, :, :] = np.where((r < 6), 150.0, arr)  # canal medular sub prag
    vol = Volume.from_array(arr, (1.0, 1.0, 1.0), (0, 0, 0))
    hollow = threshold_mask(vol, 250, 3000)
    solid = threshold_mask(vol, 250, 3000, solid=True)
    assert not hollow[20, 20, 20] and solid[20, 20, 20]
