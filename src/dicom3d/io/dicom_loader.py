"""Incarcarea seriilor DICOM in structurile din `dicom3d.data`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import SimpleITK as sitk

from dicom3d.data import AcquisitionInfo, SeriesInfo, SliceSampling, Volume
from dicom3d.data.metadata import TAGS

__all__ = ["SeriesInfo", "Volume", "find_series", "load_folder", "load_series"]

_IPP = "0020|0032"  # Image Position (Patient)
_IOP = "0020|0037"  # Image Orientation (Patient)


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
    """Citeste o serie (fisierele sunt deja sortate spatial de GDCM).

    Pe langa voxeli, citeste metadatele de achizitie din prima felie si pozitia
    fiecarei felii, ca sa verifice daca stiva formeaza un volum corect esantionat.
    """
    if series.num_files < 2:
        raise ValueError("Seria are o singura felie; e nevoie de un volum 3D.")
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(series.files)
    reader.MetaDataDictionaryArrayUpdateOn()
    reader.LoadPrivateTagsOff()
    img = reader.Execute()
    # int16 acopera CT in HU si ocupa jumatate din memoria unui float32
    if img.GetPixelID() not in (sitk.sitkInt16, sitk.sitkFloat32):
        img = sitk.Cast(img, sitk.sitkFloat32)

    def tag(i: int, key: str) -> str:
        return reader.GetMetaData(i, key) if reader.HasMetaDataKey(i, key) else ""

    acquisition = AcquisitionInfo.from_tags({name: tag(0, key) for name, key in TAGS.items()})
    return Volume.from_sitk(img, info=series, acquisition=acquisition,
                            sampling=_slice_sampling(reader, tag, acquisition, len(series.files)))


def load_folder(folder: str | Path) -> Volume:
    """Incarca cea mai mare serie gasita in folder."""
    series = find_series(folder)
    if not series:
        raise FileNotFoundError(f"Nu am gasit nicio serie DICOM in {folder}")
    return load_series(series[0])


def _slice_sampling(reader, tag, acquisition: AcquisitionInfo, n: int) -> SliceSampling | None:
    try:
        positions = np.array([_floats(tag(i, _IPP)) for i in range(n)])
        iop = _floats(tag(0, _IOP))
    except ValueError:
        return None  # lipsesc pozitiile (ex. imagini secundare): nu putem verifica
    if positions.shape != (n, 3) or len(iop) != 6:
        return None
    return SliceSampling.from_positions(positions, iop[:3], iop[3:],
                                        nominal_thickness_mm=acquisition.slice_thickness_mm)


def _floats(value: str) -> list[float]:
    return [float(v) for v in value.strip().split("\\") if v.strip()]


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
