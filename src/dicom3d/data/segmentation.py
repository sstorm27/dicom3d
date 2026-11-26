"""Rezultatul segmentarii: harta de etichete (un numar intreg per voxel) si tabelul de etichete.

O singura harta poate tine mai multe structuri (os, plamani, ficat...), fiecare cu
eticheta ei; 0 inseamna fundal. Asa se pot combina (fuziona) rezultatele mai multor
metode: prag clasic acum, retele neurale (nnU-Net, TotalSegmentator) mai tarziu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from dicom3d.data.geometry import Geometry

BACKGROUND = 0


@dataclass(frozen=True)
class Label:
    """O structura anatomica din harta de etichete."""

    value: int  # valoarea din voxeli, >= 1
    name: str  # ex. "Os", "Plaman stang"
    color: tuple[float, float, float] = (0.9, 0.9, 0.9)  # RGB 0..1
    source: str = "prag"  # metoda care a produs-o: "prag", "manual", "ai:<model>"
    params: dict = field(default_factory=dict, compare=False, hash=False)  # ex. {"lower": 250}

    def __post_init__(self):
        if self.value < 1:
            raise ValueError("Valoarea 0 este rezervata fundalului.")


@dataclass
class LabelMap:
    """Harta de etichete pe aceeasi grila ca volumul segmentat.

    `array` este (z, y, x), uint8 (pana la 255 de structuri) sau uint16; valoarea
    fiecarui voxel este `Label.value` a structurii careia ii apartine, 0 = fundal.
    """

    array: np.ndarray
    geometry: Geometry
    labels: dict[int, Label] = field(default_factory=dict)

    def __post_init__(self):
        if tuple(self.array.shape) != self.geometry.shape:
            raise ValueError(f"Harta are forma {self.array.shape}, "
                             f"geometria cere {self.geometry.shape} (z, y, x).")
        if self.array.dtype not in (np.uint8, np.uint16):
            raise ValueError(f"Harta de etichete trebuie sa fie uint8/uint16, nu {self.array.dtype}.")

    # ---------- constructie ----------

    @classmethod
    def empty(cls, geometry: Geometry, dtype=np.uint8) -> "LabelMap":
        return cls(np.zeros(geometry.shape, dtype=dtype), geometry)

    @classmethod
    def from_mask(cls, mask: np.ndarray, geometry: Geometry, label: Label) -> "LabelMap":
        """Harta cu o singura structura, dintr-o masca binara (z, y, x)."""
        lm = cls.empty(geometry, np.uint8 if label.value <= 255 else np.uint16)
        lm.add(mask, label)
        return lm

    def add(self, mask: np.ndarray, label: Label, overwrite: bool = False) -> None:
        """Adauga o structura. Fara `overwrite`, voxelii deja etichetati raman neschimbati."""
        if mask.shape != self.array.shape:
            raise ValueError("Masca nu are aceeasi forma ca harta de etichete.")
        if label.value > np.iinfo(self.array.dtype).max:
            self.array = self.array.astype(np.uint16)
        if label.value in self.labels:
            raise ValueError(f"Eticheta {label.value} exista deja ({self.labels[label.value].name}).")
        sel = mask.astype(bool)
        if not overwrite:
            sel &= self.array == BACKGROUND
        self.array[sel] = label.value
        self.labels[label.value] = label

    def merge(self, other: "LabelMap", overwrite: bool = False) -> None:
        """Fuzioneaza alta harta pe aceeasi grila (etichetele ei trebuie sa fie noi)."""
        if not self.geometry.same_grid(other.geometry):
            raise ValueError("Hartile nu sunt pe aceeasi grila; reesantionati intai.")
        for value, label in other.labels.items():
            self.add(other.array == value, label, overwrite=overwrite)

    # ---------- interogare ----------

    def mask(self, value: int) -> np.ndarray:
        """Masca binara uint8 (z, y, x) a unei structuri."""
        return (self.array == value).astype(np.uint8)

    def by_name(self, name: str) -> Label:
        for label in self.labels.values():
            if label.name == name:
                return label
        raise KeyError(name)

    def voxel_count(self, value: int) -> int:
        return int(np.count_nonzero(self.array == value))

    def volume_ml(self, value: int) -> float:
        """Volumul structurii numarand voxelii (1 ml = 1000 mm³)."""
        return self.voxel_count(value) * self.geometry.voxel_volume_mm3 / 1000.0

    def to_sitk(self):
        import SimpleITK as sitk

        img = sitk.GetImageFromArray(self.array)
        self.geometry.apply_to_sitk(img)
        return img
