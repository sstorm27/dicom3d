"""Preprocesarea volumului inainte de segmentare: curatare HU, reducere zgomot,
reesantionare izotropa.

Fiecare pas intoarce un `Volume` nou, cu geometria actualizata (spatiere, origine),
deci restul pipeline-ului nu trebuie sa stie ce s-a facut inainte.

Modelele matematice si sursele lor sunt descrise in documentatie:
- interpolare B-spline cubica (Thevenaz, Blu, Unser 2000; Lehmann et al. 1999)
- difuzie anizotropa (Perona & Malik 1990; Gerig et al. 1992)
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import SimpleITK as sitk

from dicom3d.data import Geometry, Volume

# aerul in CT; valorile mai mici sunt umplutura din afara campului de reconstructie
AIR_HU = -1024.0

DENOISE_METHODS = ("niciuna", "gaussian", "median", "anizotropic")
INTERPOLATIONS = {"liniara": sitk.sitkLinear, "bspline": sitk.sitkBSpline}


@dataclass
class PreprocessOptions:
    denoise: str = "niciuna"  # vezi DENOISE_METHODS; presetarile aleg una potrivita
    gaussian_sigma_mm: float = 1.0  # doar pentru denoise="gaussian"
    diffusion_iterations: int = 5  # doar pentru denoise="anizotropic"
    isotropic: bool = True
    interpolation: str = "bspline"  # "liniara" sau "bspline"
    target_spacing_mm: float | None = None  # None = cea mai mica spatiere a seriei
    # limita de memorie: volumul reesantionat nu depaseste atatia voxeli
    max_voxels: int = 40_000_000


def clean_hu(volume: Volume) -> Volume:
    """Aduce valorile de umplutura (ex. -2048, -3024) la aer.

    Altfel interpolarea si filtrele ar trage marginea corpului spre valori
    nefizice, iar langa marginea campului apar suprafete false.
    """
    arr = volume.array
    if arr.min() >= AIR_HU:
        return volume
    return _with_array(volume, np.maximum(arr, np.asarray(AIR_HU, dtype=arr.dtype)))


def denoise(volume: Volume, options: PreprocessOptions) -> Volume:
    method = options.denoise
    if method not in DENOISE_METHODS:
        raise ValueError(f"Metoda de filtrare necunoscuta: {method}")
    if method == "niciuna":
        return volume
    img = sitk.Cast(volume.to_sitk(), sitk.sitkFloat32)
    if method == "gaussian":
        if options.gaussian_sigma_mm <= 0:
            return volume
        img = sitk.SmoothingRecursiveGaussian(img, options.gaussian_sigma_mm)
    elif method == "median":
        img = sitk.Median(img, [1, 1, 1])
    else:
        # schema explicita e stabila pentru pas <= spatiere_min / 2^(N+1) (N = 3)
        step = min(volume.spacing) / 2 ** 4 * 0.9
        img = sitk.CurvatureAnisotropicDiffusion(
            img,
            timeStep=step,
            conductanceParameter=3.0,
            conductanceScalingUpdateInterval=1,
            numberOfIterations=options.diffusion_iterations,
        )
    return replace(volume, array=sitk.GetArrayFromImage(img))


def isotropic_spacing(volume: Volume, options: PreprocessOptions) -> float:
    """Pasul izotrop ales: cel cerut sau cel mai mic din serie, marit daca e nevoie
    ca volumul sa incapa in `max_voxels`."""
    s = options.target_spacing_mm or min(volume.spacing)
    extent = np.array(volume.shape_xyz) * np.array(volume.spacing)
    n = np.prod(np.ceil(extent / s))
    if n > options.max_voxels:
        s *= (n / options.max_voxels) ** (1 / 3)
    return float(s)


def resample_isotropic(volume: Volume, options: PreprocessOptions) -> Volume:
    """Reesantioneaza pe un grid cu voxeli cubici, acoperind aceeasi regiune fizica."""
    if options.interpolation not in INTERPOLATIONS:
        raise ValueError(f"Interpolare necunoscuta: {options.interpolation}")
    s = isotropic_spacing(volume, options)
    if np.allclose(volume.spacing, s, rtol=1e-3):
        return volume
    img = sitk.Cast(volume.to_sitk(), sitk.sitkFloat32)
    old_sp = np.array(volume.spacing)
    old_size = np.array(volume.shape_xyz)
    new_size = np.maximum(1, np.round(old_size * old_sp / s)).astype(int)
    # centrele primului si ultimului voxel raman pe aceleasi pozitii fizice:
    # extindem pe fiecare axa cu jumatate din diferenta de acoperire
    span_old = (old_size - 1) * old_sp
    span_new = (new_size - 1) * s
    shift_idx = (span_old - span_new) / 2  # mm, in sistemul imaginii
    d = np.array(volume.direction, dtype=float).reshape(3, 3)
    origin = np.array(volume.origin) + d @ shift_idx
    out = sitk.Resample(
        img,
        [int(v) for v in new_size],
        sitk.Transform(),
        INTERPOLATIONS[options.interpolation],
        tuple(origin),
        (s, s, s),
        volume.direction,
        AIR_HU,
        sitk.sitkFloat32,
    )
    # B-spline cubic depaseste usor valorile vecine la marginile abrupte (os/aer)
    lo, hi = float(volume.array.min()), float(volume.array.max())
    out = sitk.Clamp(out, sitk.sitkFloat32, lo, hi)
    return replace(volume, array=sitk.GetArrayFromImage(out), geometry=Geometry.from_sitk(out))


def crop_to_range(volume: Volume, lower: float, upper: float, margin_mm: float = 6.0) -> Volume:
    """Taie volumul la cutia care contine toti voxelii din [lower, upper], plus o margine.

    Reduce memoria si timpul pentru filtrare si reesantionare (ex. os: doar scheletul).
    """
    inside = (volume.array >= lower) & (volume.array <= upper)
    if not inside.any():
        return volume
    idx = np.nonzero(inside)
    sz, sy, sx = (np.ceil(margin_mm / np.array(volume.spacing[::-1]))).astype(int)
    z0, y0, x0 = (max(0, int(i.min()) - m) for i, m in zip(idx, (sz, sy, sx)))
    nz, ny, nx = volume.array.shape
    z1, y1, x1 = (min(n, int(i.max()) + 1 + m) for i, m, n in zip(idx, (sz, sy, sx), (nz, ny, nx)))
    if (z0, y0, x0, z1, y1, x1) == (0, 0, 0, nz, ny, nx):
        return volume
    d = np.array(volume.direction, dtype=float).reshape(3, 3)
    origin = np.array(volume.origin) + d @ (np.array([x0, y0, z0]) * np.array(volume.spacing))
    array = np.ascontiguousarray(volume.array[z0:z1, y0:y1, x0:x1])
    geometry = Geometry.from_shape(array.shape, volume.spacing,
                                   tuple(float(v) for v in origin), volume.direction)
    return replace(volume, array=array, geometry=geometry)


def preprocess(volume: Volume, options: PreprocessOptions) -> Volume:
    volume = clean_hu(volume)
    volume = denoise(volume, options)
    if options.isotropic:
        volume = resample_isotropic(volume, options)
    return volume


def mask_to_grid(mask: np.ndarray, source: Volume, reference: Volume) -> np.ndarray:
    """Muta o masca de pe gridul `source` pe gridul `reference` (cel mai apropiat vecin).

    Folosit ca masca sa poata fi afisata peste feliile originale.
    """
    if source.geometry.same_grid(reference.geometry):
        return mask
    src = sitk.GetImageFromArray(mask.astype(np.uint8))
    src.SetSpacing(source.spacing)
    src.SetOrigin(source.origin)
    src.SetDirection(source.direction)
    ref = sitk.Image(list(reference.shape_xyz), sitk.sitkUInt8)
    ref.SetSpacing(reference.spacing)
    ref.SetOrigin(reference.origin)
    ref.SetDirection(reference.direction)
    out = sitk.Resample(src, ref, sitk.Transform(), sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
    return sitk.GetArrayFromImage(out)


def _with_array(volume: Volume, array: np.ndarray) -> Volume:
    return replace(volume, array=array)
