"""Geometria fizica a unei grile de voxeli: unde se afla fiecare voxel in corpul pacientului.

Conventii (aceleasi ca DICOM, ITK si SimpleITK):

* Sistemul de coordonate al pacientului este **LPS**, in milimetri:
  +x spre stanga pacientului (Left), +y spre spate (Posterior), +z spre cap (Superior).
* Indicii voxelilor se scriu (i, j, k) = (coloana, rand, felie), adica (x, y, z).
  Array-urile numpy sunt insa in ordinea inversa (k, j, i) = (z, y, x).
* `origin` este pozitia **centrului** voxelului (0, 0, 0), nu coltul lui.
* `direction` este matricea 3x3 (row-major) a cosinusurilor directoare: coloana `c`
  este directia in LPS in care creste indicele de pe axa `c`.

Transformarea index -> pacient:

    p = origin + D * diag(spacing) * (i, j, k)^T
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

IDENTITY: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)

# litera anatomica spre care arata fiecare semiaxa LPS (+ si -)
_LPS_LETTERS = (("L", "R"), ("P", "A"), ("S", "I"))


@dataclass(frozen=True)
class Geometry:
    """Grila de esantionare a unui volum, independenta de valorile din voxeli.

    Doua obiecte (volumul CT, o masca, o harta de etichete) care au aceeasi
    `Geometry` se suprapun voxel cu voxel; daca nu, trebuie reesantionate.
    """

    size: tuple[int, int, int]  # (nx, ny, nz) numarul de voxeli pe axele i, j, k
    spacing: tuple[float, float, float]  # (sx, sy, sz) in mm, distanta dintre centre
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)  # mm, LPS, centrul voxelului 0
    direction: tuple[float, ...] = IDENTITY  # 3x3 row-major, coloanele = axele i, j, k

    def __post_init__(self):
        # normalizam tipurile, ca egalitatea si hash-ul sa nu depinda de int/float/numpy
        object.__setattr__(self, "size", tuple(int(v) for v in self.size))
        object.__setattr__(self, "spacing", tuple(float(v) for v in self.spacing))
        object.__setattr__(self, "origin", tuple(float(v) for v in self.origin))
        object.__setattr__(self, "direction", tuple(float(v) for v in self.direction))
        if len(self.size) != 3 or min(self.size) < 1:
            raise ValueError(f"Dimensiune invalida: {self.size}")
        if len(self.spacing) != 3 or min(self.spacing) <= 0:
            raise ValueError(f"Spatierea trebuie sa fie pozitiva: {self.spacing}")
        if len(self.origin) != 3:
            raise ValueError(f"Originea trebuie sa aiba 3 componente: {self.origin}")
        if len(self.direction) != 9:
            raise ValueError("Matricea de directie trebuie sa aiba 9 elemente (3x3).")
        d = self.matrix
        if not np.allclose(d.T @ d, np.eye(3), atol=1e-3):
            raise ValueError("Matricea de directie nu este ortonormata.")

    # ---------- constructie ----------

    @classmethod
    def from_shape(cls, shape_zyx: tuple[int, int, int], spacing=(1.0, 1.0, 1.0),
                   origin=(0.0, 0.0, 0.0), direction=IDENTITY) -> "Geometry":
        """Geometria pentru un array numpy (z, y, x)."""
        nz, ny, nx = shape_zyx
        return cls((nx, ny, nz), spacing, origin, direction)

    @classmethod
    def from_sitk(cls, img) -> "Geometry":
        return cls(img.GetSize(), img.GetSpacing(), img.GetOrigin(), img.GetDirection())

    def apply_to_sitk(self, img) -> None:
        """Copiaza geometria pe o imagine SimpleITK (dimensiunea trebuie sa fie aceeasi)."""
        if tuple(img.GetSize()) != self.size:
            raise ValueError(f"Imaginea are {img.GetSize()} voxeli, geometria {self.size}.")
        img.SetSpacing(self.spacing)
        img.SetOrigin(self.origin)
        img.SetDirection(self.direction)

    # ---------- marimi derivate ----------

    @property
    def shape(self) -> tuple[int, int, int]:
        """Forma array-ului numpy corespunzator: (nz, ny, nx)."""
        nx, ny, nz = self.size
        return nz, ny, nx

    @property
    def num_voxels(self) -> int:
        nx, ny, nz = self.size
        return nx * ny * nz

    @property
    def matrix(self) -> np.ndarray:
        """Matricea de directie 3x3."""
        return np.array(self.direction, dtype=float).reshape(3, 3)

    @property
    def voxel_volume_mm3(self) -> float:
        sx, sy, sz = self.spacing
        return sx * sy * sz

    @property
    def extent_mm(self) -> tuple[float, float, float]:
        """Lungimea acoperita pe fiecare axa (de la marginea primului voxel la a ultimului)."""
        return tuple(n * s for n, s in zip(self.size, self.spacing))

    @property
    def affine(self) -> np.ndarray:
        """Matricea omogena 4x4 index (i, j, k, 1) -> pacient LPS (mm)."""
        m = np.eye(4)
        m[:3, :3] = self.matrix * np.array(self.spacing)
        m[:3, 3] = self.origin
        return m

    # ---------- transformari ----------

    def index_to_world(self, ijk) -> np.ndarray:
        """Indici (i, j, k) -> coordonate LPS in mm. Accepta (3,) sau (N, 3); indicii pot fi fractionari."""
        ijk = np.asarray(ijk, dtype=float)
        return ijk @ (self.matrix * np.array(self.spacing)).T + np.array(self.origin)

    def world_to_index(self, xyz) -> np.ndarray:
        """Coordonate LPS (mm) -> indici continui (i, j, k). Rotunjiti dau voxelul cel mai apropiat."""
        xyz = np.asarray(xyz, dtype=float)
        local = (xyz - np.array(self.origin)) @ self.matrix  # D^-1 = D^T
        return local / np.array(self.spacing)

    def corners(self) -> np.ndarray:
        """Cele 8 colturi ale cutiei acoperite de centrele voxelilor, in LPS (8, 3)."""
        nx, ny, nz = self.size
        ijk = np.array([[i, j, k] for i in (0, nx - 1) for j in (0, ny - 1) for k in (0, nz - 1)])
        return self.index_to_world(ijk)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Cutia aliniata cu axele LPS care contine toate centrele de voxel: (min, max)."""
        c = self.corners()
        return c.min(axis=0), c.max(axis=0)

    # ---------- orientare ----------

    def axis_codes(self) -> str:
        """Codul de orientare din 3 litere, ex. "LPS" sau "RAI".

        Litera `c` spune spre ce parte a pacientului creste indicele de pe axa `c`
        (axa LPS dominanta a coloanei din matricea de directie).
        """
        d = self.matrix
        letters = []
        for c in range(3):
            col = d[:, c]
            a = int(np.argmax(np.abs(col)))
            letters.append(_LPS_LETTERS[a][0 if col[a] > 0 else 1])
        return "".join(letters)

    def obliquity_deg(self) -> float:
        """Cel mai mare unghi (grade) dintre o axa a grilei si cea mai apropiata axa LPS."""
        d = np.abs(self.matrix)
        cosines = np.clip(d.max(axis=0), -1.0, 1.0)
        return float(np.degrees(np.arccos(cosines)).max())

    def is_oblique(self, tolerance_deg: float = 0.5) -> bool:
        return self.obliquity_deg() > tolerance_deg

    # ---------- comparatie ----------

    def same_grid(self, other: "Geometry", tol_mm: float = 1e-3) -> bool:
        """True daca cele doua geometrii au aceiasi voxeli in aceleasi locuri."""
        return (
            self.size == other.size
            and np.allclose(self.spacing, other.spacing, atol=tol_mm)
            and np.allclose(self.origin, other.origin, atol=tol_mm)
            and np.allclose(self.direction, other.direction, atol=1e-4)
        )
