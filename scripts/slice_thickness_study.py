"""Cat conteaza grosimea feliei si cat recupereaza segmentarea AI.

Pornim de la un CT cu felii subtiri (ex. 0,625 mm, din Medical Segmentation
Decathlon Task06_Lung, CC BY-SA 4.0) si simulam aceeasi achizitie cu felii de 3 mm
(media pe o felie groasa = profilul de sensibilitate al scanerului, apoi o felie la
3 mm). Reconstructia din feliile subtiri e referinta; pe feliile groase comparam:

  1. prag clasic (pipeline-ul aplicatiei: B-spline izotrop + Marching Cubes pe HU)
  2. segmentare AI (TotalSegmentator) + marginea din HU

Fiecare metoda e comparata cu ea insasi pe feliile subtiri: masuram cat pierde
din cauza feliilor groase, nu cat de buna e segmentarea in sine.

Masuram distanta dintre suprafete in ambele sensuri:
  - test -> referinta: cat de departe sunt suprafetele gasite (acuratete);
  - referinta -> test: cat din anatomia reala lipseste (completitudine, ex. sternul).

Exemplu:
    python scripts/slice_thickness_study.py lung_022.nii.gz rezultate/ --thick 3
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from dicom3d.data import Volume
from dicom3d.io.dicom_loader import load_volume
from dicom3d.mesh.surface import MeshOptions, export_mesh, mesh_arrays
from dicom3d.pipeline import ThresholdParams, reconstruct, reconstruct_ai
from dicom3d.preprocessing import PreprocessOptions
from dicom3d.segmentation.threshold import PRESETS


def simulate_thick(volume: Volume, thickness_mm: float) -> Volume:
    """Felii de `thickness_mm` din felii subtiri: medie gaussiana pe z, apoi esantionare."""
    img = sitk.Cast(volume.to_sitk(), sitk.sitkFloat32)
    sz = volume.spacing[2]
    sigma = thickness_mm / 2.355  # FWHM = grosimea feliei
    if sigma > sz / 2:
        img = sitk.SmoothingRecursiveGaussian(img, (1e-3, 1e-3, sigma))
    size = list(img.GetSize())
    new_n = int(np.floor((size[2] - 1) * sz / thickness_mm)) + 1
    out = sitk.Resample(img, [size[0], size[1], new_n], sitk.Transform(), sitk.sitkLinear,
                        img.GetOrigin(), (volume.spacing[0], volume.spacing[1], thickness_mm),
                        img.GetDirection(), -1024.0, sitk.sitkFloat32)
    return Volume.from_sitk(sitk.Cast(sitk.Round(out), sitk.sitkInt16))


def surface_distance(test, ref) -> dict[str, float]:
    """Distanta de la varfurile lui `test` la cel mai apropiat varf al lui `ref` (mm)."""
    from scipy.spatial import cKDTree  # doar pentru studiu, nu e dependinta a aplicatiei

    a, b = mesh_arrays(test)[0], mesh_arrays(ref)[0]
    d_tr, _ = cKDTree(b).query(a, workers=-1)
    d_rt, _ = cKDTree(a).query(b, workers=-1)
    return {
        "test_la_ref_medie_mm": float(d_tr.mean()),
        "test_la_ref_p95_mm": float(np.percentile(d_tr, 95)),
        "ref_la_test_medie_mm": float(d_rt.mean()),
        "ref_la_test_p95_mm": float(np.percentile(d_rt, 95)),
        "ref_acoperita_1mm_pct": float((d_rt <= 1.0).mean() * 100),
        "ref_acoperita_2mm_pct": float((d_rt <= 2.0).mean() * 100),
    }


def render(poly, path: Path, color=(0.93, 0.82, 0.56), size=(900, 1000), bounds=None):
    """Captura offscreen, vedere anterioara (din fata pacientului)."""
    from vtkmodules.vtkIOImage import vtkPNGWriter
    from vtkmodules.vtkRenderingCore import vtkRenderWindow

    from dicom3d import vtk_lite as vtk

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(poly)
    mapper.ScalarVisibilityOff()
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*color)
    actor.GetProperty().SetSpecular(0.25)
    actor.GetProperty().SetSpecularPower(20)
    ren = vtk.vtkRenderer()
    ren.AddActor(actor)
    ren.SetBackground(0.08, 0.09, 0.1)
    vtk.vtkLightKit().AddLightsToRenderer(ren)
    win = vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.AddRenderer(ren)
    win.SetSize(*size)
    b = bounds or poly.GetBounds()
    c = [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2]
    cam = ren.GetActiveCamera()
    cam.SetFocalPoint(*c)
    cam.SetPosition(c[0], c[1] - 1000, c[2])  # LPS: -y = anterior
    cam.SetViewUp(0, 0, 1)
    ren.ResetCamera(b)
    cam.Zoom(1.2)
    win.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.Update()
    w = vtkPNGWriter()
    w.SetFileName(str(path))
    w.SetInputData(grab.GetOutput())
    w.Write()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", help="CT cu felii subtiri: folder DICOM sau .nii.gz")
    ap.add_argument("out", help="folder pentru rezultate")
    ap.add_argument("--thick", type=float, default=3.0, help="grosimea simulata (mm)")
    ap.add_argument("--preset", default="Os", choices=["Os", "Plamani (aer)"])
    ap.add_argument("--ai-full", action="store_true", help="modelul AI complet (1,5 mm)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    p = PRESETS[args.preset]
    params = ThresholdParams(p.lower, p.upper, True, False, 0.0, p.exclude_outside,
                             p.min_component_ml, p.solid)
    opts = MeshOptions(smoothing_iterations=20)
    group = {"Os": "Os", "Plamani (aer)": "Plamani"}[args.preset]

    thin = load_volume(args.input)
    thick = simulate_thick(thin, args.thick)
    print(f"Subtire: {thin.spacing} mm, {thin.array.shape}; groasa: {thick.spacing} mm")

    results, report = {}, {"intrare": str(args.input), "felie_subtire_mm": thin.spacing[2],
                           "felie_groasa_mm": args.thick, "tesut": args.preset}
    t = time.time()
    # referinta: feliile subtiri sunt deja aproape cubice; fara reesantionare (memorie)
    results["referinta_subtire"] = reconstruct(
        thin, params, opts, preprocess_options=PreprocessOptions(denoise=p.denoise,
                                                                 isotropic=False))
    print(f"referinta: {time.time() - t:.0f} s")
    t = time.time()
    results["groasa_prag"] = reconstruct(
        thick, params, opts, preprocess_options=PreprocessOptions(denoise=p.denoise))
    print(f"prag pe felii groase: {time.time() - t:.0f} s")
    t = time.time()
    results["groasa_ai"], _ = reconstruct_ai(thick, group, opts, fast=not args.ai_full,
                                             refine_hu=(p.lower, p.upper))
    print(f"AI pe felii groase: {time.time() - t:.0f} s")

    t = time.time()
    results["referinta_subtire_ai"], _ = reconstruct_ai(thin, group, opts, fast=not args.ai_full,
                                                        refine_hu=(p.lower, p.upper))
    print(f"AI pe felii subtiri: {time.time() - t:.0f} s")

    # fiecare metoda se compara cu ea insasi pe feliile subtiri: pragul prinde si
    # vasele cu contrast, cablurile si masa (nu sunt os), deci n-ar fi o referinta
    # corecta pentru AI, iar AI pe felii subtiri nu e una corecta pentru prag
    refs = {"groasa_prag": "referinta_subtire", "groasa_ai": "referinta_subtire_ai"}
    bounds = results["referinta_subtire"].mesh.GetBounds()
    for name, res in results.items():
        entry = {"triunghiuri": res.stats["triangles"], "volum_ml": res.stats["volume_ml"]}
        if name in refs:
            entry["referinta"] = refs[name]
            entry.update(surface_distance(res.mesh, results[refs[name]].mesh))
        report[name] = entry
        render(res.mesh, out / f"{name}.png", bounds=bounds)
        export_mesh(res.mesh, out / f"{name}.stl")
        print(name, json.dumps(entry, indent=1))
    (out / "raport.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
