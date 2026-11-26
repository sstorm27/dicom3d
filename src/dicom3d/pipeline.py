"""Pipeline-ul complet: volum -> preprocesare -> masca -> mesh. Folosit de interfata si de CLI."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import SimpleITK as sitk
from dicom3d import vtk_lite as vtk

from dicom3d.io.dicom_loader import Volume
from dicom3d.mesh.surface import (
    MeshOptions,
    inside_field,
    marching_cubes,
    marching_cubes_field,
    mesh_stats,
)
from dicom3d.preprocessing import (
    PreprocessOptions,
    clean_hu,
    crop_to_range,
    mask_to_grid,
    preprocess,
)
from dicom3d.segmentation.threshold import threshold_mask


@dataclass
class ThresholdParams:
    lower: float = 250
    upper: float = 3000
    keep_largest: bool = True
    fill_holes: bool = False
    smoothing_sigma_mm: float = 0.0
    exclude_outside: bool = False


@dataclass
class ReconstructionResult:
    mask: np.ndarray  # pe gridul volumului original, pentru afisarea peste felii
    mesh: vtk.vtkPolyData
    stats: dict[str, float] = field(default_factory=dict)


# fara preprocesare: comportamentul de dinainte (util pentru comparatii in lucrare)
NO_PREPROCESSING = PreprocessOptions(denoise="niciuna", isotropic=False)


def reconstruct(
    volume: Volume,
    params: ThresholdParams,
    mesh_options: MeshOptions | None = None,
    preprocess_options: PreprocessOptions | None = None,
) -> ReconstructionResult:
    mesh_options = mesh_options or MeshOptions()
    pre = preprocess_options or PreprocessOptions()

    work = clean_hu(volume)
    # taiem la regiunea de interes inainte de filtrare si reesantionare; nu si cand
    # eliminam aerul exterior, care se recunoaste tocmai dupa marginile imaginii
    if not params.exclude_outside:
        work = crop_to_range(work, params.lower, params.upper)
    work = preprocess(work, pre)

    mask = threshold_mask(
        work,
        params.lower,
        params.upper,
        keep_largest=params.keep_largest,
        fill_holes=params.fill_holes,
        smoothing_sigma_mm=params.smoothing_sigma_mm,
        exclude_outside=params.exclude_outside,
    )
    if mesh_options.surface == "binar":
        mesh = marching_cubes(mask, work.spacing, work.origin, work.direction, mesh_options)
    else:
        image = work.array
        if params.smoothing_sigma_mm > 0:
            # aceeasi imagine pe care s-a facut pragul
            img = sitk.SmoothingRecursiveGaussian(
                sitk.Cast(work.to_sitk(), sitk.sitkFloat32), params.smoothing_sigma_mm)
            image = sitk.GetArrayFromImage(img)
        fld = inside_field(image, mask, params.lower, params.upper)
        mesh = marching_cubes_field(fld, work.spacing, work.origin, work.direction, mesh_options)
    display_mask = mask_to_grid(mask, work, volume)
    return ReconstructionResult(display_mask, mesh, mesh_stats(mesh))
