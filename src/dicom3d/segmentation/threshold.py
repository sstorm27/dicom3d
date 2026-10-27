"""Segmentare clasica prin prag (baseline pentru comparatia cu AI)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import SimpleITK as sitk

from dicom3d.io.dicom_loader import Volume


@dataclass(frozen=True)
class ThresholdPreset:
    name: str
    lower: float
    upper: float
    # elimina regiunile care ating marginile laterale ale imaginii (aerul din jurul corpului)
    exclude_outside: bool = False


# Intervale tipice in unitati Hounsfield (CT)
PRESETS: dict[str, ThresholdPreset] = {
    p.name: p
    for p in (
        ThresholdPreset("Os", 250, 3000),
        ThresholdPreset("Tesut moale", -100, 200),
        ThresholdPreset("Vase cu contrast", 150, 500),
        ThresholdPreset("Plamani (aer)", -1000, -400, exclude_outside=True),
        ThresholdPreset("Piele", -400, 3000),
    )
}


def threshold_mask(
    volume: Volume,
    lower: float,
    upper: float,
    keep_largest: bool = True,
    fill_holes: bool = False,
    smoothing_sigma_mm: float = 0.0,
    exclude_outside: bool = False,
) -> np.ndarray:
    """Intoarce o masca binara uint8 (z, y, x) cu voxelii din [lower, upper]."""
    if lower > upper:
        raise ValueError("Pragul inferior trebuie sa fie <= pragul superior.")
    img = volume.to_sitk()
    if smoothing_sigma_mm > 0:
        img = sitk.SmoothingRecursiveGaussian(img, smoothing_sigma_mm)
    mask = sitk.BinaryThreshold(img, float(lower), float(upper), 1, 0)
    if exclude_outside:
        mask = remove_border_components(mask)
    if keep_largest:
        mask = largest_component(mask)
    if fill_holes:
        mask = sitk.BinaryFillhole(mask)
    return sitk.GetArrayFromImage(mask).astype(np.uint8)


def largest_component(mask: sitk.Image) -> sitk.Image:
    cc = sitk.ConnectedComponent(mask)
    relabeled = sitk.RelabelComponent(cc, sortByObjectSize=True)
    return sitk.Cast(relabeled == 1, sitk.sitkUInt8)


def remove_border_components(mask: sitk.Image, band_fraction: float = 0.03) -> sitk.Image:
    """Sterge componentele care ajung langa marginile x/y ale volumului.

    Marginile z nu conteaza: un organ (ex. plamanii) poate iesi din campul scanat
    pe axa z, dar aerul din jurul pacientului ajunge mereu langa marginile laterale.
    Folosim o banda de cativa pixeli, nu doar ultimul rand, pentru ca multe
    scanere pun pe margine valori de umplere (ex. -1024 HU) din afara pragului.
    """
    labels = sitk.GetArrayFromImage(sitk.ConnectedComponent(mask))
    _, ny, nx = labels.shape
    by, bx = max(2, round(ny * band_fraction)), max(2, round(nx * band_fraction))
    border = np.concatenate([
        labels[:, :by, :].ravel(), labels[:, -by:, :].ravel(),
        labels[:, :, :bx].ravel(), labels[:, :, -bx:].ravel(),
    ])
    outside = np.unique(border[border > 0])
    kept = ((labels > 0) & ~np.isin(labels, outside)).astype(np.uint8)
    out = sitk.GetImageFromArray(kept)
    out.CopyInformation(mask)
    return out


def mask_volume_ml(mask: np.ndarray, spacing: tuple[float, float, float]) -> float:
    voxel_mm3 = spacing[0] * spacing[1] * spacing[2]
    return float(mask.sum()) * voxel_mm3 / 1000.0
