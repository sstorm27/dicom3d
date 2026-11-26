"""Segmentare clasica prin prag (baseline pentru comparatia cu AI)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import SimpleITK as sitk

from dicom3d.data import Volume


@dataclass(frozen=True)
class ThresholdPreset:
    name: str
    lower: float
    upper: float
    # elimina regiunile care ating marginile laterale ale imaginii (aerul din jurul corpului)
    exclude_outside: bool = False
    # reducerea zgomotului recomandata (vezi preprocessing.DENOISE_METHODS): structurile
    # cu contrast mic fata de vecini (tesut moale, vase, plamani cu vasele lor) au nevoie
    # de filtrare ca pragul sa nu prinda zgomotul; osul si pielea au contrast mare, iar
    # filtrarea doar ar subtia structurile fine (corticala, coastele)
    denoise: str = "niciuna"
    # cu "doar cea mai mare componenta": pastreaza si celelalte componente de cel putin
    # atatia ml. Scheletul toracic nu e o singura bucata (claviculele, omoplatii,
    # sternul si coastele superioare nu ating coloana peste prag), deci doar cea mai
    # mare componenta ar pastra numai coloana cu cateva coaste.
    min_component_ml: float = 0.0
    # os compact: inchidere morfologica + umplerea golurilor felie cu felie, ca
    # spongioasa (sub prag) din vertebre si canalul medular din coaste sa nu
    # apara ca un burete sau ca tuburi goale
    solid: bool = False


# Intervale tipice in unitati Hounsfield (CT)
PRESETS: dict[str, ThresholdPreset] = {
    p.name: p
    for p in (
        ThresholdPreset("Os", 250, 3000, min_component_ml=2.0, solid=True),
        ThresholdPreset("Tesut moale", -100, 200, denoise="anizotropic"),
        ThresholdPreset("Vase cu contrast", 150, 500, denoise="anizotropic"),
        ThresholdPreset("Plamani (aer)", -1000, -400, exclude_outside=True,
                        denoise="anizotropic"),
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
    min_component_ml: float = 0.0,
    solid: bool = False,
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
        if min_component_ml > 0:
            mask = large_components(mask, min_component_ml)
        else:
            mask = largest_component(mask)
    if solid:
        mask = solidify(mask)
    if fill_holes:
        mask = sitk.BinaryFillhole(mask)
    return sitk.GetArrayFromImage(mask).astype(np.uint8)


def largest_component(mask: sitk.Image) -> sitk.Image:
    cc = sitk.ConnectedComponent(mask)
    relabeled = sitk.RelabelComponent(cc, sortByObjectSize=True)
    return sitk.Cast(relabeled == 1, sitk.sitkUInt8)


def large_components(mask: sitk.Image, min_ml: float) -> sitk.Image:
    """Pastreaza cea mai mare componenta si toate componentele de cel putin `min_ml`."""
    voxel_ml = float(np.prod(mask.GetSpacing())) / 1000.0
    relabeled = sitk.RelabelComponent(sitk.ConnectedComponent(mask), sortByObjectSize=True)
    sizes = sitk.LabelShapeStatisticsImageFilter()
    sizes.Execute(relabeled)
    keep = [lab for lab in sizes.GetLabels()
            if lab == 1 or sizes.GetNumberOfPixels(lab) * voxel_ml >= min_ml]
    if not keep:
        return sitk.Cast(relabeled > 0, sitk.sitkUInt8)
    return sitk.Cast(relabeled <= max(keep), sitk.sitkUInt8) * sitk.Cast(relabeled > 0, sitk.sitkUInt8)


def solidify(mask: sitk.Image, closing_mm: float = 1.5) -> sitk.Image:
    """Inchidere morfologica, apoi umplerea golurilor in fiecare felie pe cele 3 axe.

    Umplerea 3D (BinaryFillhole) nu ajuta la os: canalul medular al coastelor si
    spongioasa vertebrelor sunt deschise la capete, deci nu sunt goluri inchise in 3D.
    Intr-o felie insa, corticala le inconjoara complet.
    """
    radius = [max(1, int(round(closing_mm / s))) for s in mask.GetSpacing()]
    closed = sitk.BinaryMorphologicalClosing(mask, radius)
    arr = sitk.GetArrayFromImage(closed).astype(bool)
    out = arr.copy()
    for axis in range(3):
        moved = np.moveaxis(arr, axis, 0)
        filled = np.stack([
            sitk.GetArrayFromImage(sitk.BinaryFillhole(sitk.GetImageFromArray(sl.astype(np.uint8))))
            for sl in moved
        ]).astype(bool)
        out |= np.moveaxis(filled, 0, axis)
    img = sitk.GetImageFromArray(out.astype(np.uint8))
    img.CopyInformation(mask)
    return img


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
