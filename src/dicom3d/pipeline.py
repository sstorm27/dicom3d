"""Pipeline-ul complet: volum -> preprocesare -> masca -> mesh. Folosit de interfata si de CLI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import SimpleITK as sitk
from dicom3d import vtk_lite as vtk

from dicom3d.data import Label, LabelMap, Volume
from dicom3d.mesh.surface import (
    MeshOptions,
    inside_field,
    marching_cubes,
    marching_cubes_field,
    mesh_stats,
    smooth_mask_field,
)
from dicom3d.preprocessing import (
    PreprocessOptions,
    clean_hu,
    crop_to_range,
    mask_to_grid,
    preprocess,
)
from dicom3d.segmentation.threshold import threshold_mask


@dataclass
class ThresholdParams:
    lower: float = 250
    upper: float = 3000
    keep_largest: bool = True
    fill_holes: bool = False
    smoothing_sigma_mm: float = 0.0
    exclude_outside: bool = False
    min_component_ml: float = 0.0
    solid: bool = False


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


# fara preprocesare: comportamentul de dinainte (util pentru comparatii in lucrare)
NO_PREPROCESSING = PreprocessOptions(denoise="niciuna", isotropic=False)


def reconstruct(
    volume: Volume,
    params: ThresholdParams,
    mesh_options: MeshOptions | None = None,
    label: Label | None = None,
    preprocess_options: PreprocessOptions | None = None,
) -> ReconstructionResult:
    """Preproceseaza, segmenteaza prin prag, apoi extrage suprafata cu Marching Cubes.

    `label` da numele si culoarea structurii; implicit "Segment" cu valoarea 1.
    Segmentarea se face pe volumul preprocesat (eventual reesantionat), dar harta de
    etichete intoarsa e pe grila volumului de intrare, ca sa poata fi afisata peste felii.
    """
    mesh_options = mesh_options or MeshOptions()
    pre = preprocess_options or PreprocessOptions()

    work = clean_hu(volume)
    # taiem la regiunea de interes inainte de filtrare si reesantionare; nu si cand
    # eliminam aerul exterior, care se recunoaste tocmai dupa marginile imaginii
    if not params.exclude_outside:
        work = crop_to_range(work, params.lower, params.upper)
    work = preprocess(work, pre)

    mask = threshold_mask(
        work,
        params.lower,
        params.upper,
        keep_largest=params.keep_largest,
        fill_holes=params.fill_holes,
        smoothing_sigma_mm=params.smoothing_sigma_mm,
        exclude_outside=params.exclude_outside,
        min_component_ml=params.min_component_ml,
        solid=params.solid,
    )
    if mesh_options.surface == "binar":
        mesh = marching_cubes(mask, work.spacing, work.origin, work.direction, mesh_options)
    else:
        image = work.array
        if params.smoothing_sigma_mm > 0:
            # aceeasi imagine pe care s-a facut pragul
            img = sitk.SmoothingRecursiveGaussian(
                sitk.Cast(work.to_sitk(), sitk.sitkFloat32), params.smoothing_sigma_mm)
            image = sitk.GetArrayFromImage(img)
        fld = inside_field(image, mask, params.lower, params.upper)
        mesh = marching_cubes_field(fld, work.spacing, work.origin, work.direction, mesh_options)

    if label is None:
        label = Label(1, "Segment")
    label = Label(label.value, label.name, label.color, "prag",
                  {**asdict(params), "preprocesare": asdict(pre), "suprafata": mesh_options.surface})
    segmentation = LabelMap.from_mask(mask_to_grid(mask, work, volume), volume.geometry, label)
    return ReconstructionResult(segmentation, label, mesh, mesh_stats(mesh))


def reconstruct_ai(
    volume: Volume,
    group: str,
    mesh_options: MeshOptions | None = None,
    labelmap: LabelMap | None = None,
    fast: bool = True,
    refine_hu: tuple[float, float] | None = None,
    sigma_mm: float | None = None,
) -> tuple[ReconstructionResult, LabelMap]:
    """Reconstructie din segmentarea AI (TotalSegmentator) a unui grup de structuri.

    `labelmap` e segmentarea completa deja calculata (o rulare dureaza ~1 min pe CPU,
    deci interfata o pastreaza si schimba doar grupul); daca lipseste, se calculeaza.

    Cu `refine_hu` (interval HU), marginea se pune dupa valorile reale ale imaginii
    oriunde reteaua si pragul sunt de acord, iar masca retelei completeaza doar ce
    pragul pierde (sternul si cartilajele costale sub 250 HU, spongioasa). Asa
    suprafata are detaliul imaginii, nu blocurile de 1,5-3 mm ale retelei.
    Intoarce rezultatul si segmentarea completa, pentru refolosire.
    """
    from dicom3d.segmentation import ai

    mesh_options = mesh_options or MeshOptions()
    if labelmap is None:
        labelmap = ai.segment(volume, fast=fast)
    g = ai.AI_GROUPS[group]
    mask = ai.group_mask(labelmap, g)
    if not mask.any():
        raise ValueError(f"Reteaua nu a gasit nicio structura din grupul {group} in aceasta serie.")
    first = next(iter(labelmap.labels.values()))
    model_mm = 3.0 if first.params.get("rapid", fast) else 1.5
    sigma = sigma_mm if sigma_mm is not None else model_mm / 2
    fld, spacing, origin, direction = smooth_mask_field(
        mask, volume.spacing, volume.origin, volume.direction, sigma_mm=sigma)
    if refine_hu is not None:
        fld = _refine_with_hu(fld, spacing, origin, direction, volume, mask, refine_hu, model_mm)
    mesh = marching_cubes_field(fld, spacing, origin, direction, mesh_options)
    structures = sorted(lab.name for lab in labelmap.labels.values() if g.matches(lab.name))
    label = Label(1, group, g.color, first.source,
                  {"structuri": structures, "rafinare_hu": refine_hu})
    segmentation = LabelMap.from_mask(mask, volume.geometry, label)
    return ReconstructionResult(segmentation, label, mesh, mesh_stats(mesh)), labelmap


def _refine_with_hu(fld, spacing, origin, direction, volume: Volume, mask, hu_range, model_mm):
    """Combina campul netezit al retelei cu campul HU, pe aceeasi grila izotropa.

    - langa structura gasita de retea (pana la ~o celula a retelei distanta), marginea
      vine din HU: g = min(f - lower, upper - f), scalat la +-0.5;
    - in interiorul sigur al retelei (masca ei micsorata), campul e pozitiv oricum,
      deci golurile de sub prag (spongioasa, sternul subtire) se umplu;
    - departe de retea, totul e exterior: pragul nu mai prinde mobilier, catetere etc.
    """
    lower, upper = hu_range
    ref = sitk.Image([int(n) for n in fld.shape[::-1]], sitk.sitkFloat32)
    ref.SetSpacing(spacing)
    ref.SetOrigin(origin)
    ref.SetDirection(direction)
    hu = sitk.Resample(sitk.Cast(clean_hu(volume).to_sitk(), sitk.sitkFloat32), ref,
                       sitk.Transform(), sitk.sitkBSpline, -1024.0, sitk.sitkFloat32)
    hu = sitk.GetArrayFromImage(hu)
    g_hu = np.clip(np.minimum(hu - lower, upper - hu) / 200.0, -0.5, 0.5)

    # vecinatatea retelei: masca dilatata cu ~o celula a retelei
    near, *_ = smooth_mask_field(mask, volume.spacing, volume.origin, volume.direction,
                                 sigma_mm=model_mm)
    near = near[:fld.shape[0], :fld.shape[1], :fld.shape[2]]
    if near.shape != fld.shape:
        near = np.pad(near, [(0, a - b) for a, b in zip(fld.shape, near.shape)],
                      constant_values=-0.5)
    hu_part = np.where(near > -0.45, g_hu, -0.5)
    # interiorul sigur al retelei: izonivelul 0.75 in loc de 0.5 (masca micsorata)
    inner = fld - np.float32(0.25)
    return np.maximum(hu_part, inner).astype(np.float32)
