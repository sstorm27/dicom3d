"""Indexarea fisierelor DICOM in catalog: citeste doar antetele (fara pixeli), grupeaza
fisierele pe serii si scrie in baza de date pacientul, studiul, seria si fisierele.

Din antet se pastreaza doar ce trebuie pentru alegerea si verificarea seriei. Numele
pacientului, data nasterii si ID-ul real nu se citesc in baza de date.
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pydicom
from pydicom.errors import InvalidDicomError

from dicom3d.catalog.db import LOCAL_COLLECTION, Catalog

# antetele citite (restul fisierului, inclusiv pixelii, nu se incarca)
_TAGS = [
    "SOPInstanceUID", "SeriesInstanceUID", "StudyInstanceUID", "PatientID", "PatientSex",
    "PatientAge", "StudyDate", "StudyDescription", "SeriesDescription", "SeriesNumber",
    "Modality", "BodyPartExamined", "Manufacturer", "ManufacturerModelName",
    "ConvolutionKernel", "ContrastBolusAgent", "KVP", "Rows", "Columns", "PixelSpacing",
    "SliceThickness", "ImagePositionPatient", "ImageOrientationPatient", "InstanceNumber",
]

Progress = Callable[[str], None]


def patient_key(patient_id: str, collection_id: str) -> str:
    """Cheia pacientului in catalog.

    Colectiile publice TCIA publica deja un pseudonim (LUNG1-157, LIDC-IDRI-0098), pastrat
    ca sa se poata cita cazul. Pentru seriile proprii ID-ul ar putea fi unul real, asa ca
    se pastreaza doar un hash: aceleasi serii ale aceluiasi pacient raman grupate, dar ID-ul
    nu se poate citi din baza de date.
    """
    if collection_id != LOCAL_COLLECTION["id"] and patient_id:
        return patient_id
    digest = hashlib.sha256(("dicom3d|" + (patient_id or "")).encode()).hexdigest()
    return "P-" + digest[:10].upper()


def parse_age(value: str) -> int | None:
    """Varsta DICOM (AS): 057Y, 006M, 010W, 003D -> ani."""
    value = (value or "").strip().upper()
    if len(value) < 2 or not value[:-1].isdigit():
        return None
    n, unit = int(value[:-1]), value[-1]
    return {"Y": n, "M": n // 12, "W": n // 52, "D": n // 365}.get(unit)


def _str(ds, name: str) -> str:
    v = ds.get(name, "")
    if v is None:
        return ""
    if isinstance(v, (list, tuple)) or type(v).__name__ == "MultiValue":
        return "\\".join(str(x).strip() for x in v)
    return str(v).strip()


def _float(ds, name: str) -> float | None:
    try:
        v = ds.get(name)
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(ds, name: str) -> int | None:
    f = _float(ds, name)
    return int(f) if f is not None else None


def read_header(path: str | Path):
    """Antetul unui fisier DICOM, sau None daca fisierul nu e DICOM sau nu e o imagine."""
    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, specific_tags=_TAGS)
    except (InvalidDicomError, OSError, ValueError, KeyError, EOFError):
        return None
    if not ds.get("SeriesInstanceUID") or not ds.get("SOPInstanceUID"):
        return None
    return ds


def iter_files(folder: str | Path) -> Iterable[Path]:
    for root, _dirs, files in os.walk(folder):
        for name in sorted(files):
            if not name.startswith(".") and not name.endswith((".part", ".sqlite", ".json")):
                yield Path(root) / name


def index_folder(catalog: Catalog, folder: str | Path, collection_id: str | None = None,
                 region: str = "", progress: Progress | None = None,
                 known: dict[str, dict] | None = None) -> list[str]:
    """Indexeaza recursiv toate seriile dintr-un folder. Intoarce UID-urile seriilor adaugate.

    `known` leaga UID-ul seriei de intrarea din manifestul colectiilor publice: seriile
    descarcate de la TCIA se recunosc si primesc colectia, regiunea, sexul si varsta.
    """
    groups: dict[str, list[tuple[Path, object]]] = defaultdict(list)
    for n, path in enumerate(iter_files(folder), 1):
        ds = read_header(path)
        if ds is not None:
            groups[str(ds.SeriesInstanceUID)].append((path, ds))
        if progress and n % 200 == 0:
            progress(f"Citesc antetele DICOM: {n} fisiere…")
    added = []
    for uid, items in groups.items():
        entry = (known or {}).get(uid)
        cid = entry["colectie"] if entry else (collection_id or LOCAL_COLLECTION["id"])
        reg = entry["regiune"] if entry else region
        _add_series(catalog, items, cid, reg, entry)
        added.append(uid)
    return added


def index_files(catalog: Catalog, files: list[str], known: dict[str, dict] | None = None) -> list[str]:
    """Indexeaza doar fisierele date (ex. seria tocmai deschisa din interfata)."""
    groups: dict[str, list] = defaultdict(list)
    for f in files:
        ds = read_header(f)
        if ds is not None:
            groups[str(ds.SeriesInstanceUID)].append((Path(f), ds))
    for uid, items in groups.items():
        entry = (known or {}).get(uid)
        _add_series(catalog, items, entry["colectie"] if entry else LOCAL_COLLECTION["id"],
                    entry["regiune"] if entry else "", entry)
    return list(groups)


def _add_series(catalog: Catalog, items: list[tuple[Path, object]], collection_id: str,
                region: str, entry: dict | None) -> None:
    first = items[0][1]
    iop = [float(v) for v in first.get("ImageOrientationPatient", []) or []]
    normal = np.cross(iop[:3], iop[3:6]) if len(iop) == 6 else None

    instances, positions = [], []
    for path, ds in items:
        pos = None
        ipp = ds.get("ImagePositionPatient")
        if normal is not None and ipp is not None and len(ipp) == 3:
            pos = float(np.dot([float(v) for v in ipp], normal))
            positions.append(pos)
        instances.append({
            "sop_uid": str(ds.SOPInstanceUID), "path": str(path.resolve()),
            "instance_number": _int(ds, "InstanceNumber"), "position_mm": pos,
            "size_bytes": path.stat().st_size,
        })

    spacing = extent = None
    if len(positions) >= 2:
        p = np.sort(np.array(positions))
        steps = np.diff(p)
        steps = steps[steps > 1e-3]  # pozitiile duplicate nu sunt pasul real
        spacing = round(float(np.median(steps)), 3) if steps.size else None
        extent = round(float(p[-1] - p[0]), 1)

    ps = first.get("PixelSpacing")
    paths = [Path(i["path"]) for i in instances]
    folder = os.path.commonpath([str(p.parent) for p in paths])
    pid = _str(first, "PatientID")
    sex = (entry or {}).get("sex") or _str(first, "PatientSex")
    age = parse_age((entry or {}).get("varsta") or _str(first, "PatientAge"))
    catalog.add_series({
        "collection_id": collection_id,
        "patient_key": (entry or {}).get("pacient") or patient_key(pid, collection_id),
        "sex": sex if sex in ("M", "F", "O") else "",
        "age_years": age,
        "study_uid": _str(first, "StudyInstanceUID") or "fara-studiu:" + str(first.SeriesInstanceUID),
        "study_date": _str(first, "StudyDate"),
        "study_description": _str(first, "StudyDescription"),
        "series_uid": str(first.SeriesInstanceUID),
        "modality": _str(first, "Modality"),
        "description": _str(first, "SeriesDescription"),
        "series_number": _int(first, "SeriesNumber"),
        "body_part": _str(first, "BodyPartExamined"),
        "region": region,
        "manufacturer": _str(first, "Manufacturer"),
        "model": _str(first, "ManufacturerModelName"),
        "convolution_kernel": _str(first, "ConvolutionKernel"),
        "contrast_agent": _str(first, "ContrastBolusAgent"),
        "kvp": _float(first, "KVP"),
        "rows": _int(first, "Rows"),
        "columns": _int(first, "Columns"),
        "pixel_spacing_mm": float(ps[0]) if ps else None,
        "slice_thickness_mm": _float(first, "SliceThickness"),
        "slice_spacing_mm": spacing,
        "extent_mm": extent,
        "num_instances": len(instances),
        "size_bytes": sum(i["size_bytes"] for i in instances),
        "folder": folder,
    }, instances)
