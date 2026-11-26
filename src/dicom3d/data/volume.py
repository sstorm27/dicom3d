"""Volumul 3D de intensitati (ex. CT in unitati Hounsfield) impreuna cu geometria lui."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dicom3d.data.geometry import IDENTITY, Geometry
from dicom3d.data.metadata import AcquisitionInfo, SeriesInfo, SliceSampling


@dataclass
class Volume:
    """Volum 3D cu geometria lui fizica si metadatele seriei din care provine.

    `array` are ordinea axelor (z, y, x), ca in SimpleITK; `geometry` descrie
    unde se afla fiecare voxel in coordonatele pacientului (LPS, mm). Valorile
    sunt deja rescalate (pentru CT: unitati Hounsfield, `unit == "HU"`).
    """

    array: np.ndarray
    geometry: Geometry
    info: SeriesInfo | None = None  # seria de pe disc (fisierele)
    acquisition: AcquisitionInfo | None = None  # parametrii de achizitie
    sampling: SliceSampling | None = None  # verificarea pozitiilor feliilor
    unit: str = "HU"

    def __post_init__(self):
        if self.array.ndim != 3:
            raise ValueError(f"Volumul trebuie sa fie 3D, are forma {self.array.shape}.")
        if tuple(self.array.shape) != self.geometry.shape:
            raise ValueError(f"Array-ul are forma {self.array.shape}, "
                             f"geometria cere {self.geometry.shape} (z, y, x).")

    # ---------- acces rapid la geometrie (compatibil cu codul existent) ----------

    @property
    def spacing(self) -> tuple[float, float, float]:
        return self.geometry.spacing

    @property
    def origin(self) -> tuple[float, float, float]:
        return self.geometry.origin

    @property
    def direction(self) -> tuple[float, ...]:
        return self.geometry.direction

    @property
    def shape_xyz(self) -> tuple[int, int, int]:
        return self.geometry.size

    def value_range(self) -> tuple[float, float]:
        return float(self.array.min()), float(self.array.max())

    def value_at(self, xyz_mm) -> float:
        """Valoarea voxelului cel mai apropiat de un punct LPS (mm); NaN in afara volumului."""
        i, j, k = np.round(self.geometry.world_to_index(xyz_mm)).astype(int)
        nz, ny, nx = self.array.shape
        if 0 <= i < nx and 0 <= j < ny and 0 <= k < nz:
            return float(self.array[k, j, i])
        return float("nan")

    # ---------- conversii ----------

    @classmethod
    def from_array(cls, array: np.ndarray, spacing=(1.0, 1.0, 1.0), origin=(0.0, 0.0, 0.0),
                   direction=None, **kwargs) -> "Volume":
        """Volum dintr-un array (z, y, x) si geometria data pe componente."""
        geo = Geometry.from_shape(array.shape, spacing, origin,
                                  IDENTITY if direction is None else direction)
        return cls(array, geo, **kwargs)

    def to_sitk(self):
        import SimpleITK as sitk

        img = sitk.GetImageFromArray(self.array)
        self.geometry.apply_to_sitk(img)
        return img

    @classmethod
    def from_sitk(cls, img, **kwargs) -> "Volume":
        import SimpleITK as sitk

        return cls(sitk.GetArrayFromImage(img), Geometry.from_sitk(img), **kwargs)
