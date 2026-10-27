"""Pipeline-ul complet: volum -> masca -> mesh. Folosit de interfata si de CLI."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import vtk

from dicom3d.io.dicom_loader import Volume
from dicom3d.mesh.surface import MeshOptions, marching_cubes, mesh_stats
from dicom3d.segmentation.threshold import threshold_mask


@dataclass
class ThresholdParams:
    lower: float = 250
    upper: float = 3000
    keep_largest: bool = True
    fill_holes: bool = False
    smoothing_sigma_mm: float = 0.0


@dataclass
class ReconstructionResult:
    mask: np.ndarray
    mesh: vtk.vtkPolyData
    stats: dict[str, float] = field(default_factory=dict)


def reconstruct(
    volume: Volume,
    params: ThresholdParams,
    mesh_options: MeshOptions | None = None,
) -> ReconstructionResult:
    mask = threshold_mask(
        volume,
        params.lower,
        params.upper,
        keep_largest=params.keep_largest,
        fill_holes=params.fill_holes,
        smoothing_sigma_mm=params.smoothing_sigma_mm,
    )
    mesh = marching_cubes(mask, volume.spacing, volume.origin, volume.direction, mesh_options)
    return ReconstructionResult(mask, mesh, mesh_stats(mesh))
