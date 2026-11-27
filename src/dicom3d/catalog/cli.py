"""Catalogul de studii CT din linia de comanda.

Exemple:
    dicom3d-db descarca                       # toate seriile din manifest (~1,3 GB)
    dicom3d-db descarca --colectie lidc_idri --max 2
    dicom3d-db indexeaza C:\\date\\CT        # adauga serii proprii
    dicom3d-db lista --regiune torace
    dicom3d-db stare
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dicom3d.catalog.db import Catalog, default_home
from dicom3d.catalog.download import (download, free_space_gb, known_series, load_manifest,
                                      register_collections, select)
from dicom3d.catalog.indexer import index_folder


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dicom3d-db", description=__doc__.splitlines()[0])
    ap.add_argument("--home", type=Path, default=None,
                    help=f"folderul cu catalogul si datele (implicit {default_home()})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("descarca", help="descarca serii reale din colectiile TCIA (prin IDC)")
    d.add_argument("--colectie", action="append", help="doar aceasta colectie (se poate repeta)")
    d.add_argument("--max", type=int, help="cel mult atatea serii din fiecare colectie")
    d.add_argument("--simulare", action="store_true", help="arata ce s-ar descarca, fara descarcare")

    i = sub.add_parser("indexeaza", help="adauga in catalog seriile dintr-un folder")
    i.add_argument("folder", type=Path)
    i.add_argument("--regiune", default="", help="ex. torace, abdomen")

    lst = sub.add_parser("lista", help="seriile din catalog")
    lst.add_argument("--regiune", default="")
    lst.add_argument("--colectie", default="")
    lst.add_argument("text", nargs="?", default="")

    sub.add_parser("stare", help="ce contine catalogul, pe colectii")
    sub.add_parser("colectii", help="colectiile disponibile, cu licenta si citarea")

    args = ap.parse_args(argv)
    home = args.home or default_home()
    catalog = Catalog(home / "catalog.sqlite")

    if args.cmd == "descarca":
        manifest = load_manifest()
        chosen = select(manifest, args.colectie, args.max)
        mb = sum(s["mb"] for s in chosen)
        print(f"{len(chosen)} serii, ~{mb / 1024:.2f} GB, in {home / 'date'}")
        if args.simulare:
            for s in chosen:
                print(f"  {s['colectie']:16} {s['pacient']:16} {s['felii']:4} felii  {s['mb']:6.1f} MB")
            return 0
        if free_space_gb(home) < mb / 1024 * 1.1:
            print("Nu este destul spatiu liber pe disc.", file=sys.stderr)
            return 1
        uids = download(home, catalog, args.colectie, args.max, progress=print)
        print(f"Gata: {len(uids)} serii in catalog ({catalog.path}).")
    elif args.cmd == "indexeaza":
        register_collections(catalog)
        uids = index_folder(catalog, args.folder, region=args.regiune, progress=print,
                            known=known_series())
        print(f"Adaugate {len(uids)} serii.")
    elif args.cmd == "lista":
        for r in catalog.series(args.text, args.regiune, args.colectie):
            age = f"{r.age_years}a" if r.age_years is not None else "-"
            th = f"{r.slice_thickness_mm:g} mm" if r.slice_thickness_mm else "-"
            print(f"{r.collection_name[:18]:18} {r.patient_key:18} {r.sex or '-':1} {age:>4} "
                  f"{r.region or '-':8} {r.num_instances:4} felii {th:>7}  {r.title[:40]}")
    elif args.cmd == "stare":
        s = catalog.stats()
        print(f"{catalog.path}\n{s['patients']} pacienti, {s['studies']} studii, {s['series']} serii, "
              f"{s['instances']} fisiere, {s['size_bytes'] / 1024**3:.2f} GB")
        for c in catalog.collections():
            if c["series"]:
                print(f"  {c['name']:32} {c['patients']:3} pacienti {c['series']:3} serii  {c['license']}")
    elif args.cmd == "colectii":
        for cid, c in load_manifest()["colectii"].items():
            print(f"{c['nume']} [{cid}] — {c['regiune']}, licenta {c['licenta']}\n  {c['citare']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
