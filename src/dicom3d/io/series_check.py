"""Verificari de geometrie pentru o serie DICOM, inainte de reconstructie.

SimpleITK presupune felii paralele, echidistante si perpendiculare pe directia de
avans. Daca seria incalca aceste ipoteze, modelul 3D iese deformat fara niciun
mesaj; aici detectam cazurile si le spunem utilizatorului.
"""

from __future__ import annotations

import numpy as np
import SimpleITK as sitk

from dicom3d.io.dicom_loader import SeriesInfo

# toleranta pentru spatierea intre felii (fractiune din spatierea mediana)
SPACING_TOLERANCE = 0.05
# unghiul (grade) peste care consideram gantry-ul inclinat
TILT_TOLERANCE_DEG = 0.5


def slice_positions(files: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Pozitiile (N, 3) ale feliilor si normala planului feliei (din orientare)."""
    positions, normal = [], None
    r = sitk.ImageFileReader()
    r.LoadPrivateTagsOff()
    for path in files:
        r.SetFileName(path)
        r.ReadImageInformation()
        positions.append([float(v) for v in r.GetMetaData("0020|0032").split("\\")])
        if normal is None:
            o = [float(v) for v in r.GetMetaData("0020|0037").split("\\")]
            normal = np.cross(o[:3], o[3:])
    return np.array(positions), np.asarray(normal, dtype=float)


def check_geometry(series: SeriesInfo) -> list[str]:
    """Intoarce o lista de avertismente (goala daca geometria e in regula)."""
    try:
        pos, normal = slice_positions(series.files)
    except (RuntimeError, ValueError):
        return ["Nu am putut citi pozitiile feliilor (tag-urile 0020,0032 / 0020,0037)."]
    if len(pos) < 3:
        return []
    warnings: list[str] = []
    # distanta fiecarei felii de-a lungul normalei, in ordinea fisierelor (deja sortate)
    d = pos @ normal
    gaps = np.abs(np.diff(d))
    med = float(np.median(gaps))
    if med <= 0:
        return ["Mai multe felii au aceeasi pozitie: seria pare duplicata sau multi-faza."]
    off = np.abs(gaps - med) > SPACING_TOLERANCE * med
    if off.any():
        missing = int(np.sum(np.round(gaps[off] / med) - 1).clip(min=0))
        warnings.append(
            f"Spatiere neuniforma intre felii: {int(off.sum())} intervale difera de "
            f"{med:.2f} mm (intre {gaps.min():.2f} si {gaps.max():.2f} mm)"
            + (f"; probabil lipsesc ~{missing} felii" if missing else "")
            + ". Modelul poate fi deformat pe axa z."
        )
    # gantry tilt: directia de avans nu e paralela cu normala feliei
    advance = pos[-1] - pos[0]
    if np.linalg.norm(advance) > 0:
        cos = abs(advance @ normal) / np.linalg.norm(advance)
        angle = float(np.degrees(np.arccos(np.clip(cos, -1, 1))))
        if angle > TILT_TOLERANCE_DEG:
            warnings.append(
                f"Gantry inclinat cu ~{angle:.1f} grade: feliile sunt deplasate lateral, "
                f"iar volumul apare forfecat."
            )
    return warnings
