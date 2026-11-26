"""Teste pentru reconstructia din segmentarea AI (fara sa ruleze reteaua).

Reteaua TotalSegmentator e o dependinta optionala si grea; aici ii simulam iesirea
cu o harta de etichete construita de mana si verificam ce face aplicatia cu ea.
"""

import numpy as np
import pytest

from dicom3d.data import Label, LabelMap, Volume
from dicom3d.mesh.surface import (
    MeshOptions,
    marching_cubes,
    marching_cubes_field,
    mesh_arrays,
    mesh_stats,
    smooth_mask_field,
)
from dicom3d.pipeline import reconstruct_ai
from dicom3d.segmentation import ai

SPACING = (1.0, 1.0, 3.0)  # felii groase, ca seria NSCLC
RADIUS = 15.0


def _sphere(shape=(24, 64, 64), spacing=SPACING, radius=RADIUS):
    z, y, x = np.indices(shape).astype(float)
    c = [(n - 1) / 2 for n in shape]
    d2 = (((x - c[2]) * spacing[0]) ** 2 + ((y - c[1]) * spacing[1]) ** 2
          + ((z - c[0]) * spacing[2]) ** 2)
    return d2 <= radius ** 2


def _labelmap(mask, name="sternum", fast=True):
    vol = Volume.from_array(np.where(mask, 700, -50).astype(np.int16), SPACING)
    lab = Label(5, name, (1, 1, 1), "ai:TotalSegmentator-fast", {"rapid": fast})
    return vol, LabelMap.from_mask(mask, vol.geometry, lab)


def test_groups_cover_the_chest_structures():
    assert ai.AI_GROUPS["Os"].matches("sternum")
    assert ai.AI_GROUPS["Os"].matches("rib_left_7")
    assert ai.AI_GROUPS["Os"].matches("costal_cartilages")
    assert ai.AI_GROUPS["Plamani"].matches("lung_middle_lobe_right")
    assert ai.AI_GROUPS["Vase"].matches("aorta")
    assert ai.AI_GROUPS["Vase"].matches("superior_vena_cava")
    assert not ai.AI_GROUPS["Vase"].matches("heart")
    assert not ai.AI_GROUPS["Os"].matches("spinal_cord")
    assert set(ai.PRESET_TO_GROUP.values()) <= set(ai.AI_GROUPS)


def test_group_mask_joins_all_structures_of_a_group():
    geo = Volume.from_array(np.zeros((2, 2, 2), np.int16)).geometry
    arr = np.array([[[1, 2], [3, 0]], [[0, 0], [0, 0]]], np.uint8)
    lm = LabelMap(arr, geo, {1: Label(1, "sternum"), 2: Label(2, "rib_left_1"),
                             3: Label(3, "heart")})
    assert ai.group_mask(lm, "Os").sum() == 2
    assert ai.group_mask(lm, "Inima").sum() == 1


def test_smoothed_mask_has_no_slice_steps():
    """Pe felii de 3 mm, masca binara da trepte; campul netezit nu."""
    mask = _sphere()
    true_ml = 4 / 3 * np.pi * RADIUS ** 3 / 1000
    opts = MeshOptions(smoothing_iterations=0)
    stepped = marching_cubes(mask.astype(np.uint8), SPACING, options=opts)
    fld, sp, origin, direction = smooth_mask_field(mask, SPACING, (0, 0, 0),
                                                   (1, 0, 0, 0, 1, 0, 0, 0, 1))
    smooth = marching_cubes_field(fld, sp, origin, direction, opts)

    # treptele: la masca binara, varfurile stau pe cateva inaltimi (felii si jumatati)
    z_stepped = np.unique(np.round(mesh_arrays(stepped)[0][:, 2], 2)).size
    z_smooth = np.unique(np.round(mesh_arrays(smooth)[0][:, 2], 2)).size
    assert z_smooth > 5 * z_stepped
    # si volumul ramane aproape de cel adevarat
    assert mesh_stats(smooth)["volume_ml"] == pytest.approx(true_ml, rel=0.08)


def test_smooth_field_keeps_patient_position():
    mask = _sphere()
    origin = (-100.0, 50.0, 20.0)
    fld, sp, o, d = smooth_mask_field(mask, SPACING, origin, (1, 0, 0, 0, 1, 0, 0, 0, 1))
    mesh = marching_cubes_field(fld, sp, o, d, MeshOptions(smoothing_iterations=0))
    pts = mesh_arrays(mesh)[0]
    center = np.array(origin) + (np.array(mask.shape[::-1]) - 1) / 2 * SPACING
    assert pts.mean(0) == pytest.approx(center, abs=0.6)


@pytest.mark.parametrize("refine", [None, (250.0, 3000.0)])
def test_reconstruct_ai_from_given_labelmap(refine):
    mask = _sphere()
    vol, lm = _labelmap(mask)
    result, same = reconstruct_ai(vol, "Os", MeshOptions(smoothing_iterations=10),
                                  labelmap=lm, refine_hu=refine)
    assert same is lm  # segmentarea se refoloseste, nu se recalculeaza
    assert result.label.name == "Os"
    assert result.label.source.startswith("ai:")
    assert result.label.params["structuri"] == ["sternum"]
    assert result.mask.sum() == mask.sum()
    true_ml = 4 / 3 * np.pi * RADIUS ** 3 / 1000
    assert result.stats["volume_ml"] == pytest.approx(true_ml, rel=0.12)


def test_hu_refinement_fills_what_the_threshold_misses():
    """Sternul la felii groase: reteaua il gaseste, dar e sub prag pe jumatate."""
    mask = _sphere()
    vol, lm = _labelmap(mask)
    arr = vol.array.copy()
    arr[:, :, :32] = np.where(mask[:, :, :32], 150, -50)  # jumatate sub 250 HU
    vol = Volume(arr, vol.geometry)
    result, _ = reconstruct_ai(vol, "Os", MeshOptions(smoothing_iterations=0),
                               labelmap=lm, refine_hu=(250.0, 3000.0))
    true_ml = 4 / 3 * np.pi * RADIUS ** 3 / 1000
    # fara completarea retelei ar ramane doar ~jumatate din volum
    assert result.stats["volume_ml"] > 0.8 * true_ml


def test_missing_group_is_reported():
    vol, lm = _labelmap(_sphere(), name="liver")
    with pytest.raises(ValueError, match="Plamani"):
        reconstruct_ai(vol, "Plamani", labelmap=lm)
