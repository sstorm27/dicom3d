"""Reconstructie 3D din linia de comanda (util pentru teste si evaluare in lot).

Exemplu:
    dicom3d-cli date/CT_torace --preset Os -o os.stl
"""

from __future__ import annotations

import argparse
import sys
import time

from dicom3d.io.dicom_loader import load_folder
from dicom3d.mesh.surface import MeshOptions, export_mesh
from dicom3d.pipeline import ThresholdParams, reconstruct
from dicom3d.segmentation.threshold import PRESETS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dicom3d-cli", description=__doc__.splitlines()[0])
    ap.add_argument("folder", help="folder cu seria DICOM")
    ap.add_argument("-o", "--output", required=True, help="fisier .stl / .obj / .ply")
    ap.add_argument("--preset", choices=list(PRESETS), help="interval HU predefinit")
    ap.add_argument("--lower", type=float, help="prag inferior (HU)")
    ap.add_argument("--upper", type=float, help="prag superior (HU)")
    ap.add_argument("--all-components", action="store_true",
                    help="nu pastra doar cea mai mare componenta conexa")
    ap.add_argument("--fill-holes", action="store_true")
    ap.add_argument("--sigma", type=float, default=0.0, help="netezire gaussiana (mm)")
    ap.add_argument("--smooth", type=int, default=20, help="iteratii netezire mesh")
    ap.add_argument("--decimate", type=float, default=0.0, help="fractiune 0..0.95")
    args = ap.parse_args(argv)

    preset = PRESETS[args.preset or "Os"]
    params = ThresholdParams(
        lower=args.lower if args.lower is not None else preset.lower,
        upper=args.upper if args.upper is not None else preset.upper,
        keep_largest=not args.all_components,
        fill_holes=args.fill_holes,
        smoothing_sigma_mm=args.sigma,
    )

    t0 = time.perf_counter()
    volume = load_folder(args.folder)
    print(f"Volum: {volume.shape_xyz} voxeli, spatiere {volume.spacing} mm")
    result = reconstruct(volume, params, MeshOptions(args.smooth, args.decimate))
    export_mesh(result.mesh, args.output)
    s = result.stats
    print(f"Prag [{params.lower:g}, {params.upper:g}] HU -> {s['triangles']} triunghiuri, "
          f"{s['volume_ml']:.1f} ml")
    print(f"Salvat {args.output} in {time.perf_counter() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
