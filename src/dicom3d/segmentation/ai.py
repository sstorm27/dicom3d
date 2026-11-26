"""Segmentare pe organe cu TotalSegmentator (retea nnU-Net preantrenata, open source).

TotalSegmentator (Wasserthal et al., Radiology: AI 2023, https://doi.org/10.1148/ryai.230024)
recunoaste 117 structuri in CT: fiecare vertebra si coasta, sternul, lobii pulmonari,
inima, aorta, organele abdominale etc. Spre deosebire de prag, nu depinde de un singur
interval HU, deci gaseste si oasele subtiri/spongioase (sternul) care la felii groase
cad sub prag, si separa structurile cu valori HU asemanatoare (inima de ficat).

Dependinta e optionala (`pip install dicom3d[ai]`): aduce PyTorch (~1 GB). Merge pe
procesor, fara placa video NVIDIA; in modul rapid (rezolutie 3 mm) o serie toracica
ia in jur de un minut. La prima rulare se descarca ponderile retelei (~135 MB rapid,
~1,2 GB complet) in ~/.totalsegmentator; dupa aceea merge offline.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from dicom3d.data import Label, LabelMap, Volume

MODEL = "TotalSegmentator"


@dataclass(frozen=True)
class AIGroup:
    """Un grup de structuri TotalSegmentator reconstruite impreuna (ex. tot scheletul)."""

    name: str
    patterns: tuple[str, ...]  # nume de clase TotalSegmentator, cu * ca joker
    color: tuple[float, float, float]

    def matches(self, class_name: str) -> bool:
        return any(fnmatch.fnmatchcase(class_name, p) for p in self.patterns)


AI_GROUPS: dict[str, AIGroup] = {
    g.name: g
    for g in (
        AIGroup("Os", ("vertebrae_*", "rib_*", "sternum", "costal_cartilages", "scapula_*",
                       "clavicula_*", "humerus_*", "femur_*", "hip_*", "sacrum", "skull"),
                (0.93, 0.82, 0.56)),
        AIGroup("Plamani", ("lung_*",), (0.94, 0.48, 0.42)),
        AIGroup("Inima", ("heart", "atrial_appendage_left"), (0.80, 0.25, 0.30)),
        AIGroup("Vase", ("aorta", "pulmonary_vein", "pulmonary_artery", "*_artery_*",
                         "*_vein*", "*vena_cava", "brachiocephalic_trunk"),
                (0.85, 0.28, 0.35)),
        AIGroup("Organe", ("liver", "spleen", "kidney_*", "stomach", "pancreas", "gallbladder",
                           "adrenal_gland_*", "esophagus", "trachea", "thyroid_gland",
                           "duodenum", "small_bowel", "colon", "urinary_bladder"),
                (0.91, 0.63, 0.31)),
    )
}

# tesutul ales pe rigla HU -> grupul AI corespunzator (Piele nu are corespondent)
PRESET_TO_GROUP = {
    "Os": "Os",
    "Plamani (aer)": "Plamani",
    "Vase cu contrast": "Vase",
    "Tesut moale": "Organe",
}


def available() -> bool:
    """True daca TotalSegmentator (si PyTorch) sunt instalate."""
    return importlib.util.find_spec("totalsegmentator") is not None


def class_names() -> dict[int, str]:
    """Valoare -> nume pentru cele 117 clase ale sarcinii "total"."""
    from totalsegmentator.map_to_binary import class_map

    return dict(class_map["total"])


def segment(volume: Volume, fast: bool = True, device: str = "cpu") -> LabelMap:
    """Ruleaza TotalSegmentator si intoarce harta cu toate structurile gasite.

    Harta e pe grila volumului de intrare (o eticheta per clasa, cu numele din
    TotalSegmentator), deci se poate afisa peste felii si combina cu pragul.
    """
    if not available():
        raise RuntimeError("TotalSegmentator nu este instalat. Rulati: pip install dicom3d[ai]")
    from totalsegmentator.config import set_config_key, setup_totalseg
    from totalsegmentator.python_api import totalsegmentator

    # aplicatia e offline: nu trimitem statistici de utilizare
    setup_totalseg()
    set_config_key("send_usage_stats", False)

    with tempfile.TemporaryDirectory(prefix="dicom3d_ai_") as tmp:
        src, dst = Path(tmp) / "ct.nii.gz", Path(tmp) / "seg.nii.gz"
        # SimpleITK scrie orientarea corect in NIfTI (LPS -> RAS), deci rezultatul
        # citit inapoi cade exact pe aceeasi grila
        sitk.WriteImage(sitk.Cast(volume.to_sitk(), sitk.sitkInt16), str(src))
        totalsegmentator(src, dst, ml=True, fast=fast, device=device, quiet=True)
        return load_segmentation(dst, volume, fast)


def load_segmentation(path: str | Path, volume: Volume, fast: bool = False) -> LabelMap:
    """Citeste o segmentare TotalSegmentator salvata (fisier --ml .nii.gz).

    Util cand reteaua ruleaza separat, de ex. modelul complet pe Google Colab:
    `TotalSegmentator -i ct.nii.gz -o seg.nii.gz --ml`, apoi fisierul se incarca aici.
    """
    seg = sitk.ReadImage(str(path))
    seg = sitk.Resample(seg, volume.to_sitk(), sitk.Transform(), sitk.sitkNearestNeighbor,
                        0, sitk.sitkUInt8)
    array = sitk.GetArrayFromImage(seg).astype(np.uint8)

    names = class_names()
    labels = {}
    source = f"ai:{MODEL}" + ("-fast" if fast else "")
    for value in np.unique(array):
        if value == 0:
            continue
        name = names.get(int(value), f"clasa_{value}")
        group = next((g for g in AI_GROUPS.values() if g.matches(name)), None)
        labels[int(value)] = Label(int(value), name, group.color if group else (0.7, 0.7, 0.7),
                                   source, {"rapid": fast})
    return LabelMap(array, volume.geometry, labels)


def group_mask(labelmap: LabelMap, group: str | AIGroup) -> np.ndarray:
    """Masca uint8 (z, y, x) cu toate structurile unui grup (ex. tot scheletul)."""
    g = AI_GROUPS[group] if isinstance(group, str) else group
    values = [v for v, lab in labelmap.labels.items() if g.matches(lab.name)]
    return np.isin(labelmap.array, values).astype(np.uint8)
