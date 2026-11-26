"""Metadatele unei serii DICOM: ce s-a gasit pe disc si cum a fost achizitionata.

Structurile de aici NU contin date de identificare ale pacientului (nume, CNP/ID,
data nasterii). Aplicatia nu are nevoie de ele, iar lipsa lor face ca rezultatele
(modele, rapoarte, capturi) sa poata fi folosite in lucrare fara anonimizare separata.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class SeriesInfo:
    """O serie DICOM gasita pe disc, inainte de a fi citita (rezultatul cautarii)."""

    series_uid: str
    description: str
    modality: str
    num_files: int
    files: list[str] = field(repr=False)  # sortate spatial de GDCM


# Taguri DICOM citite din prima felie, cheia SimpleITK/GDCM "grup|element"
TAGS: dict[str, str] = {
    "study_uid": "0020|000d",
    "series_uid": "0020|000e",
    "frame_of_reference_uid": "0020|0052",
    "modality": "0008|0060",
    "description": "0008|103e",
    "series_number": "0020|0011",
    "study_date": "0008|0020",
    "manufacturer": "0008|0070",
    "model": "0008|1090",
    "body_part": "0018|0015",
    "patient_position": "0018|5100",
    "image_type": "0008|0008",
    "slice_thickness": "0018|0050",
    "kvp": "0018|0060",
    "tube_current": "0018|1151",
    "convolution_kernel": "0018|1210",
    "contrast_agent": "0018|0010",
    "rescale_slope": "0028|1053",
    "rescale_intercept": "0028|1052",
    "rescale_type": "0028|1054",
    "bits_stored": "0028|0101",
}


@dataclass
class AcquisitionInfo:
    """Parametrii de achizitie si reconstructie ai seriei (din prima felie).

    Campurile lipsa din fisier raman goale (`""` sau `None`).
    """

    modality: str = ""
    description: str = ""
    study_uid: str = ""
    series_uid: str = ""
    # seriile cu acelasi Frame of Reference UID au acelasi sistem de coordonate:
    # se pot suprapune (fuziune) fara inregistrare (registration)
    frame_of_reference_uid: str = ""
    series_number: int | None = None
    study_date: str = ""  # AAAALLZZ
    manufacturer: str = ""
    model: str = ""
    body_part: str = ""
    patient_position: str = ""  # ex. HFS = cu capul inainte, pe spate
    image_type: str = ""
    slice_thickness_mm: float | None = None  # grosimea nominala, NU distanta dintre felii
    kvp: float | None = None
    tube_current_ma: float | None = None
    convolution_kernel: str = ""  # filtrul de reconstructie (os / tesut moale)
    contrast_agent: str = ""
    rescale_slope: float = 1.0
    rescale_intercept: float = 0.0
    rescale_type: str = ""  # "HU" la CT; gol inseamna de obicei tot HU
    bits_stored: int | None = None

    @classmethod
    def from_tags(cls, tags: dict[str, str]) -> "AcquisitionInfo":
        """Construieste din dictionarul {nume camp: valoare text} citit din DICOM."""

        def text(name: str) -> str:
            return tags.get(name, "").strip(" \x00")

        def num(name: str) -> float | None:
            v = text(name).split("\\")[0]
            try:
                return float(v)
            except ValueError:
                return None

        series_number = num("series_number")
        bits = num("bits_stored")
        return cls(
            modality=text("modality"),
            description=text("description"),
            study_uid=text("study_uid"),
            series_uid=text("series_uid"),
            frame_of_reference_uid=text("frame_of_reference_uid"),
            series_number=int(series_number) if series_number is not None else None,
            study_date=text("study_date"),
            manufacturer=text("manufacturer"),
            model=text("model"),
            body_part=text("body_part"),
            patient_position=text("patient_position"),
            image_type=text("image_type"),
            slice_thickness_mm=num("slice_thickness"),
            kvp=num("kvp"),
            tube_current_ma=num("tube_current"),
            convolution_kernel=text("convolution_kernel"),
            contrast_agent=text("contrast_agent"),
            rescale_slope=num("rescale_slope") or 1.0,
            rescale_intercept=num("rescale_intercept") or 0.0,
            rescale_type=text("rescale_type"),
            bits_stored=int(bits) if bits is not None else None,
        )

    @property
    def is_ct(self) -> bool:
        return self.modality.upper() == "CT"


@dataclass
class SliceSampling:
    """Verificarea esantionarii pe axa feliilor (pozitiile reale ale feliilor).

    Un volum 3D presupune felii paralele si egal distantate. Daca seria are felii
    lipsa, felii duplicate, pas variabil sau gantry înclinat, volumul construit
    deformeaza anatomia; aici se masoara asta inainte de reconstructie.
    """

    positions_mm: np.ndarray = field(repr=False)  # pozitia fiecarei felii pe normala ei
    spacing_mm: float  # pasul median dintre felii (cel folosit pentru volum)
    min_step_mm: float
    max_step_mm: float
    gaps: list[int] = field(default_factory=list)  # k: lipsesc felii intre k si k+1
    duplicates: list[int] = field(default_factory=list)  # k: felia k+1 e in acelasi loc
    tilt_deg: float = 0.0  # unghiul dintre normala feliei si directia stivei
    nominal_thickness_mm: float | None = None

    UNIFORM_TOLERANCE = 0.01  # abatere relativa admisa a pasului (1 %)
    TILT_TOLERANCE_DEG = 0.5

    @property
    def num_slices(self) -> int:
        return len(self.positions_mm)

    @property
    def is_uniform(self) -> bool:
        if self.num_slices < 3:
            return True
        tol = self.UNIFORM_TOLERANCE * self.spacing_mm
        return (self.max_step_mm - self.spacing_mm <= tol
                and self.spacing_mm - self.min_step_mm <= tol)

    @property
    def is_tilted(self) -> bool:
        return self.tilt_deg > self.TILT_TOLERANCE_DEG

    @property
    def overlap(self) -> bool:
        """Felii reconstruite cu suprapunere (grosime > pas): normal la CT, nu e o eroare."""
        t = self.nominal_thickness_mm
        return t is not None and t > self.spacing_mm * (1 + self.UNIFORM_TOLERANCE)

    @property
    def ok(self) -> bool:
        return self.is_uniform and not self.is_tilted and not self.gaps and not self.duplicates

    def warnings(self) -> list[str]:
        """Probleme gasite, in cuvinte (cu diacritice: apar in interfata)."""
        out = []
        if self.duplicates:
            out.append(f"{len(self.duplicates)} felii duplicate (aceeași poziție)")
        if self.gaps:
            out.append(f"{len(self.gaps)} goluri între felii (felii lipsă)")
        if not self.is_uniform and not self.gaps:
            out.append(f"pas variabil între felii: {self.min_step_mm:.2f} … "
                       f"{self.max_step_mm:.2f} mm")
        if self.is_tilted:
            out.append(f"gantry înclinat {self.tilt_deg:.1f}°: volumul e forfecat")
        return out

    @classmethod
    def from_positions(
        cls,
        positions: np.ndarray,
        row_cosine,
        col_cosine,
        nominal_thickness_mm: float | None = None,
    ) -> "SliceSampling":
        """Analizeaza pozitiile (N, 3) ale feliilor (ImagePositionPatient), in ordinea stivei.

        `row_cosine` si `col_cosine` sunt cele doua directii din ImageOrientationPatient;
        normala feliei este produsul lor vectorial.
        """
        p = np.asarray(positions, dtype=float).reshape(-1, 3)
        normal = np.cross(np.asarray(row_cosine, float), np.asarray(col_cosine, float))
        normal /= np.linalg.norm(normal)
        along = p @ normal
        if len(along) > 1 and along[-1] < along[0]:
            along = -along  # pozitiile cresc in sensul stivei
        steps = np.diff(along)
        if len(steps) == 0:
            return cls(along, 0.0, 0.0, 0.0, nominal_thickness_mm=nominal_thickness_mm)

        nonzero = steps[np.abs(steps) > 1e-3]
        spacing = float(np.median(nonzero)) if len(nonzero) else 0.0
        duplicates = [int(k) for k in np.flatnonzero(np.abs(steps) <= 1e-3)]
        gaps = ([int(k) for k in np.flatnonzero(steps > 1.5 * spacing)] if spacing > 0 else [])

        tilt = 0.0
        stack = p[-1] - p[0]
        if np.linalg.norm(stack) > 1e-6:
            cos = abs(float(stack @ normal)) / float(np.linalg.norm(stack))
            tilt = float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))

        real_steps = nonzero if len(nonzero) else steps
        return cls(
            positions_mm=along,
            spacing_mm=spacing,
            min_step_mm=float(real_steps.min()),
            max_step_mm=float(real_steps.max()),
            gaps=gaps,
            duplicates=duplicates,
            tilt_deg=tilt,
            nominal_thickness_mm=nominal_thickness_mm,
        )
