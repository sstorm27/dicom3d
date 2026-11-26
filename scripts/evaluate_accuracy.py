"""Evalueaza cat de precis reconstruieste pipeline-ul forme cu geometrie cunoscuta.

Fantome analitice: o sfera (r = 12 mm, ca un corp vertebral mic) si o capsula
inclinata (r = 3 mm, ca o coasta), os 700 HU in tesut 40 HU, plus o sfera cu
contrast mic (120 HU in 40 HU, ca o leziune in tesut moale) si zgomot mai mare. Sunt esantionate ca
un CT real cu voxeli anizotropi (implicit 0.98 x 0.98 x 3 mm): forma e desenata pe
un grid fin, estompata cu un PSF gaussian, mediata pe fiecare voxel (efectul de
volum partial) si apoi i se adauga zgomot gaussian.

Pentru fiecare configuratie a pipeline-ului se masoara eroarea de volum si
distanta varfurilor mesh-ului fata de suprafata exacta.

    python scripts/evaluate_accuracy.py
    python scripts/evaluate_accuracy.py --z-spacing 5 --noise 30
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import numpy as np
import SimpleITK as sitk
from vtkmodules.util import numpy_support

from dicom3d.data import Volume
from dicom3d.mesh.surface import MeshOptions
from dicom3d.pipeline import NO_PREPROCESSING, ThresholdParams, reconstruct
from dicom3d.preprocessing import PreprocessOptions

BONE_HU, TISSUE_HU = 700.0, 40.0
# pragul la jumatatea distantei intre cele doua materiale pune marginea la locul ei
HALF_MAX = (BONE_HU + TISSUE_HU) / 2
FINE = (4, 4, 6)  # suprae-santionare pe x, y, z


@dataclass
class Shape:
    name: str
    volume_mm3: float

    def distance(self, p: np.ndarray) -> np.ndarray:  # distanta cu semn, < 0 in interior
        raise NotImplementedError


class Sphere(Shape):
    def __init__(self, center, r):
        super().__init__("Sfera r=12 mm", 4 / 3 * np.pi * r**3)
        self.c, self.r = np.asarray(center, float), r

    def distance(self, p):
        return np.linalg.norm(p - self.c, axis=-1) - self.r


class Capsule(Shape):
    def __init__(self, center, axis, length, r):
        super().__init__("Tija inclinata r=3 mm", np.pi * r**2 * length + 4 / 3 * np.pi * r**3)
        axis = np.asarray(axis, float) / np.linalg.norm(axis)
        self.a = np.asarray(center, float) - axis * length / 2
        self.b = np.asarray(center, float) + axis * length / 2
        self.r = r

    def distance(self, p):
        ab = self.b - self.a
        t = np.clip(((p - self.a) @ ab) / (ab @ ab), 0, 1)
        return np.linalg.norm(p - (self.a + t[..., None] * ab), axis=-1) - self.r


def make_ct(shape: Shape, spacing, size_mm=48.0, psf_mm=0.6, noise=20.0, seed=0,
            inside_hu=BONE_HU, outside_hu=TISSUE_HU) -> Volume:
    spacing = np.asarray(spacing, float)
    n = np.round(size_mm / spacing).astype(int)  # voxeli pe x, y, z
    fine_sp = spacing / FINE
    nf = n * FINE
    # coordonatele centrelor voxelilor fini, ordine (z, y, x)
    axes = [(np.arange(nf[i]) + 0.5) * fine_sp[i] for i in range(3)]
    zz, yy, xx = np.meshgrid(axes[2], axes[1], axes[0], indexing="ij")
    pts = np.stack([xx, yy, zz], axis=-1)
    fine = np.where(shape.distance(pts) < 0, inside_hu, outside_hu).astype(np.float32)
    img = sitk.GetImageFromArray(fine)
    img.SetSpacing(tuple(fine_sp))
    fine = sitk.GetArrayFromImage(sitk.SmoothingRecursiveGaussian(img, psf_mm))
    fx, fy, fz = FINE
    coarse = fine.reshape(n[2], fz, n[1], fy, n[0], fx).mean(axis=(1, 3, 5))
    coarse += np.random.default_rng(seed).normal(0, noise, coarse.shape).astype(np.float32)
    # originea = coltul gridului + jumatate de voxel (centrul primului voxel)
    origin = tuple(spacing / 2)
    return Volume.from_array(coarse.astype(np.float32), tuple(spacing), origin)


CONFIGS = {
    "Vechi: masca binara, fara netezire": (NO_PREPROCESSING, MeshOptions(0, surface="binar")),
    "Vechi: masca binara + netezire mesh (implicit)": (NO_PREPROCESSING, MeshOptions(20, surface="binar")),
    "MC pe nivele de gri": (NO_PREPROCESSING, MeshOptions(20)),
    "Izotrop B-spline + masca binara": (
        PreprocessOptions(denoise="niciuna"), MeshOptions(20, surface="binar")),
    "Izotrop liniar + nivele de gri": (
        PreprocessOptions(denoise="niciuna", interpolation="liniara"), MeshOptions(20)),
    "Nou: izotrop B-spline + nivele de gri (implicit os/piele)": (
        PreprocessOptions(denoise="niciuna"), MeshOptions(20)),
    "Nou + difuzie anizotropa (implicit tesut moale/vase/plamani)": (
        PreprocessOptions(denoise="anizotropic"), MeshOptions(20)),
}


def evaluate(shape: Shape, volume: Volume, pre, mesh_opts, threshold: float):
    t0 = time.perf_counter()
    res = reconstruct(volume, ThresholdParams(threshold, 3000), mesh_opts, preprocess_options=pre)
    dt = time.perf_counter() - t0
    pts = numpy_support.vtk_to_numpy(res.mesh.GetPoints().GetData()).astype(float)
    d = np.abs(shape.distance(pts))
    vol_err = (res.stats["volume_ml"] * 1000 - shape.volume_mm3) / shape.volume_mm3 * 100
    return d.mean(), np.percentile(d, 95), vol_err, res.stats["triangles"], dt


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--xy-spacing", type=float, default=0.9766)
    ap.add_argument("--z-spacing", type=float, default=3.0)
    ap.add_argument("--noise", type=float, default=20.0, help="deviatia standard a zgomotului (HU)")
    args = ap.parse_args(argv)
    spacing = (args.xy_spacing, args.xy_spacing, args.z_spacing)
    sphere = Sphere((24.3, 23.7, 24.9), 12.0)
    rod = Capsule((24.2, 23.9, 24.6), (np.sin(0.6) * np.cos(0.35), np.sin(0.6) * np.sin(0.35),
                                       np.cos(0.6)), 26.0, 3.0)
    # (forma, HU interior, HU exterior, zgomot)
    phantoms = [
        (sphere, BONE_HU, TISSUE_HU, args.noise),
        (rod, BONE_HU, TISSUE_HU, args.noise),
        (sphere, 120.0, TISSUE_HU, args.noise * 1.5),
    ]
    print(f"Voxel {spacing[0]:.2f} x {spacing[1]:.2f} x {spacing[2]:.2f} mm; pragul e la "
          f"jumatatea distantei dintre cele doua materiale (half-maximum)\n")
    for shape, hu_in, hu_out, noise in phantoms:
        vol = make_ct(shape, spacing, noise=noise, inside_hu=hu_in, outside_hu=hu_out)
        threshold = (hu_in + hu_out) / 2
        print(f"### {shape.name}, {hu_in:g} HU in {hu_out:g} HU, zgomot {noise:g} HU\n")
        print("| Configuratie | Dist. medie (mm) | Dist. P95 (mm) | Eroare volum (%) "
              "| Triunghiuri | Timp (s) |")
        print("| --- | --- | --- | --- | --- | --- |")
        for name, (pre, mopts) in CONFIGS.items():
            m, p95, ve, tri, dt = evaluate(shape, vol, pre, mopts, threshold)
            print(f"| {name} | {m:.3f} | {p95:.3f} | {ve:+.1f} | {tri:,} | {dt:.2f} |")
        print()


if __name__ == "__main__":
    main()
