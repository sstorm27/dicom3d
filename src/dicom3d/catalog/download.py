"""Descarcarea seriilor CT reale din colectiile publice TCIA, prin NCI Imaging Data Commons.

Imaging Data Commons (IDC, https://imaging.datacommons.cancer.gov) pastreaza o copie a
colectiilor TCIA in containere publice (Amazon S3), fara cont si fara cheie. Fiecare serie
este un "folder" `s3://<bucket>/<crdc_series_uuid>/` cu cate un fisier .dcm pe felie.

Seriile alese sunt in `colectii_tcia.json` (generat cu scripts/genereaza_manifest_tcia.py din
indexul oficial IDC): colectia, pacientul (pseudonimul public), UID-urile, numarul de felii si
locul din S3. Licentele si citarile obligatorii sunt tot acolo.

Doar biblioteca standard: merge si in aplicatia impachetata (.exe), fara pachete in plus.
"""

from __future__ import annotations

import json
import shutil
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from importlib import resources
from pathlib import Path
from typing import Callable

from dicom3d.catalog.db import Catalog, default_home
from dicom3d.catalog.indexer import index_folder

MANIFEST = "colectii_tcia.json"
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_USER_AGENT = "dicom3d-catalog/1.0"

Progress = Callable[[str], None]


def load_manifest() -> dict:
    """Manifestul colectiilor: {"colectii": {id: meta}, "serii": [...]}."""
    text = resources.files("dicom3d.catalog").joinpath(MANIFEST).read_text(encoding="utf-8")
    return json.loads(text)


def known_series(manifest: dict | None = None) -> dict[str, dict]:
    """UID serie -> intrarea din manifest (pentru recunoasterea seriilor la indexare)."""
    manifest = manifest or load_manifest()
    return {s["serie_uid"]: s for s in manifest["serii"]}


def register_collections(catalog: Catalog, manifest: dict | None = None) -> None:
    manifest = manifest or load_manifest()
    for cid, meta in manifest["colectii"].items():
        catalog.add_collection({
            "id": cid, "name": meta["nume"], "region": meta["regiune"], "doi": meta["doi"],
            "url": meta["url"], "license": meta["licenta"], "license_url": meta["licenta_url"],
            "citation": meta["citare"]})


def select(manifest: dict, collections: list[str] | None = None,
           max_per_collection: int | None = None) -> list[dict]:
    """Seriile de descarcat, in ordinea din manifest."""
    out, count = [], {}
    for s in manifest["serii"]:
        cid = s["colectie"]
        if collections and cid not in collections:
            continue
        if max_per_collection is not None and count.get(cid, 0) >= max_per_collection:
            continue
        count[cid] = count.get(cid, 0) + 1
        out.append(s)
    return out


def series_folder(home: Path, entry: dict) -> Path:
    return home / "date" / entry["colectie"] / entry["pacient"] / entry["serie_uid"]


def _get(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    last = None
    for attempt in range(4):  # retele instabile: reincearca de cateva ori, cu pauza tot mai mare
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except OSError as exc:  # URLError, timeout, conexiune intrerupta
            last = exc
            time.sleep(1.5 * 2 ** attempt)
    raise ConnectionError(f"Nu pot descarca {url}: {last}")


def list_objects(bucket: str, prefix: str) -> list[tuple[str, int]]:
    """Cheile (si marimile) din `s3://bucket/prefix/`, prin API-ul public ListObjectsV2."""
    items, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix.rstrip("/") + "/"}
        if token:
            q["continuation-token"] = token
        xml = _get(f"https://{bucket}.s3.amazonaws.com/?{urllib.parse.urlencode(q)}")
        keys, token = parse_listing(xml)
        items += keys
        if not token:
            return items


def parse_listing(xml: bytes) -> tuple[list[tuple[str, int]], str | None]:
    root = ET.fromstring(xml)
    keys = [(c.findtext(f"{_S3_NS}Key"), int(c.findtext(f"{_S3_NS}Size") or 0))
            for c in root.iter(f"{_S3_NS}Contents")]
    truncated = (root.findtext(f"{_S3_NS}IsTruncated") or "").lower() == "true"
    return keys, root.findtext(f"{_S3_NS}NextContinuationToken") if truncated else None


def download_series(entry: dict, home: Path, progress: Progress | None = None,
                    workers: int = 8) -> Path:
    """Descarca o serie (fisierele deja descarcate complet se sar). Intoarce folderul seriei."""
    dest = series_folder(home, entry)
    dest.mkdir(parents=True, exist_ok=True)
    keys = list_objects(entry["bucket"], entry["prefix"])
    if not keys:
        raise FileNotFoundError(f"Seria {entry['pacient']} nu mai exista la sursa ({entry['prefix']}).")
    todo = [(k, size) for k, size in keys
            if not ((dest / Path(k).name).exists() and (dest / Path(k).name).stat().st_size == size)]
    done = len(keys) - len(todo)

    def fetch(item):
        key, size = item
        target = dest / Path(key).name
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(_get(f"https://{entry['bucket']}.s3.amazonaws.com/{urllib.parse.quote(key)}"))
        if size and tmp.stat().st_size != size:
            tmp.unlink(missing_ok=True)
            raise ConnectionError(f"Fisier incomplet: {key}")
        tmp.replace(target)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(fetch, todo):
            done += 1
            if progress and (done % 10 == 0 or done == len(keys)):
                progress(f"{entry['pacient']}: {done}/{len(keys)} felii")
    return dest


def download(home: str | Path | None = None, catalog: Catalog | None = None,
             collections: list[str] | None = None, max_per_collection: int | None = None,
             progress: Progress | None = None) -> list[str]:
    """Descarca seriile alese din manifest si le adauga in catalog. Intoarce UID-urile."""
    home = Path(home) if home else default_home()
    catalog = catalog or Catalog(home / "catalog.sqlite")
    manifest = load_manifest()
    register_collections(catalog, manifest)
    known = known_series(manifest)
    chosen = select(manifest, collections, max_per_collection)
    total_mb = sum(s["mb"] for s in chosen)
    added = []
    for n, entry in enumerate(chosen, 1):
        if progress:
            progress(f"Seria {n}/{len(chosen)} ({entry['pacient']}, ~{entry['mb']:.0f} MB; "
                     f"total ~{total_mb / 1024:.1f} GB)")
        folder = download_series(entry, home, progress)
        added += index_folder(catalog, folder, known=known)
    return added


def free_space_gb(path: Path) -> float:
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free / 1024**3
