"""Incarcarea seriilor DICOM intr-un volum 3D."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import SimpleITK as sitk


@dataclass
class SeriesInfo:
    series_uid: str
    description: str
    modality: str
    num_files: int
    files: list[str] = field(repr=False)


@dataclass
class Volume:
    """Volum 3D cu geometria lui fizica.

    `array` are ordinea axelor (z, y, x), ca in SimpleITK. Valorile sunt
    deja rescalate (pentru CT: unitati Hounsfield).
    """

    array: np.ndarray
    spacing: tuple[float, float, float]  # (x, y, z) in mm
    origin: tuple[float, float, float]  # (x, y, z) in mm
    direction: tuple[float, ...]  # matrice 3x3, row-major
    info: SeriesInfo | None = None

    @property
    def shape_xyz(self) -> tuple[int, int, int]:
        z, y, x = self.array.shape
        return x, y, z

    def to_sitk(self) -> sitk.Image:
        img = sitk.GetImageFromArray(self.array)
        img.SetSpacing(self.spacing)
        img.SetOrigin(self.origin)
        img.SetDirection(self.direction)
        return img

    @classmethod
    def from_sitk(cls, img: sitk.Image, info: SeriesInfo | None = None) -> "Volume":
        return cls(
            array=sitk.GetArrayFromImage(img),
            spacing=tuple(img.GetSpacing()),
            origin=tuple(img.GetOrigin()),
            direction=tuple(img.GetDirection()),
            info=info,
        )


def find_series(folder: str | Path) -> list[SeriesInfo]:
    """Cauta recursiv toate seriile DICOM dintr-un folder."""
    folder = str(folder)
    reader = sitk.ImageSeriesReader()
    result: list[SeriesInfo] = []
    for root in _walk_dirs(folder):
        for uid in reader.GetGDCMSeriesIDs(root) or ():
            files = list(reader.GetGDCMSeriesFileNames(root, uid))
            if not files:
                continue
            desc, modality = _read_tags(files[0])
            result.append(SeriesInfo(uid, desc, modality, len(files), files))
    # seriile cu cele mai multe felii primele: de obicei cele utile
    result.sort(key=lambda s: s.num_files, reverse=True)
    return result


def load_series(series: SeriesInfo) -> Volume:
    """Citeste o serie (fisierele sunt deja sortate spatial de GDCM)."""
    if series.num_files < 2:
        raise ValueError("Seria are o singura felie; e nevoie de un volum 3D.")
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(series.files)
    img = reader.Execute()
    # int16 acopera CT in HU si ocupa jumatate din memoria unui float32
    if img.GetPixelID() not in (sitk.sitkInt16, sitk.sitkFloat32):
        img = sitk.Cast(img, sitk.sitkFloat32)
    return Volume.from_sitk(img, info=series)


def load_folder(folder: str | Path) -> Volume:
    """Incarca cea mai mare serie gasita in folder."""
    series = find_series(folder)
    if not series:
        raise FileNotFoundError(f"Nu am gasit nicio serie DICOM in {folder}")
    return load_series(series[0])


def _walk_dirs(folder: str):
    yield folder
    for p in sorted(Path(folder).rglob("*")):
        if p.is_dir():
            yield str(p)


def _read_tags(path: str) -> tuple[str, str]:
    r = sitk.ImageFileReader()
    r.SetFileName(path)
    r.LoadPrivateTagsOff()
    try:
        r.ReadImageInformation()
    except RuntimeError:
        return "", ""

    def tag(key: str) -> str:
        return r.GetMetaData(key).strip() if r.HasMetaDataKey(key) else ""

    return tag("0008|103e"), tag("0008|0060")
