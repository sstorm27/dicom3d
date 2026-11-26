"""Pipeline-ul complet: volum -> masca -> mesh. Folosit de interfata si de CLI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
from dicom3d import vtk_lite as vtk

from dicom3d.data import Label, LabelMap, Volume
from dicom3d.mesh.surface import MeshOptions, marching_cubes, mesh_stats
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
    """Ce produce o reconstructie: structura segmentata si suprafata ei 3D."""

    segmentation: LabelMap  # pe aceeasi grila ca volumul de intrare
    label: Label  # structura reconstruita din `segmentation`
    mesh: vtk.vtkPolyData  # in coordonatele pacientului (LPS, mm)
    stats: dict[str, float] = field(default_factory=dict)

    @property
    def mask(self) -> np.ndarray:
        """Masca binara uint8 (z, y, x) a structurii reconstruite."""
        return self.segmentation.mask(self.label.value)


def reconstruct(
    volume: Volume,
    params: ThresholdParams,
    mesh_options: MeshOptions | None = None,
    label: Label | None = None,
) -> ReconstructionResult:
    """Segmenteaza prin prag, apoi extrage suprafata cu Marching Cubes.

    `label` da numele si culoarea structurii; implicit "Segment" cu valoarea 1.
    """
    mask = threshold_mask(
        volume,
        params.lower,
        params.upper,
        keep_largest=params.keep_largest,
        fill_holes=params.fill_holes,
        smoothing_sigma_mm=params.smoothing_sigma_mm,
        exclude_outside=params.exclude_outside,
    )
    mesh = marching_cubes(mask, volume.spacing, volume.origin, volume.direction, mesh_options)
    if label is None:
        label = Label(1, "Segment")
    label = Label(label.value, label.name, label.color, "prag", asdict(params))
    segmentation = LabelMap.from_mask(mask, volume.geometry, label)
    return ReconstructionResult(segmentation, label, mesh, mesh_stats(mesh))
