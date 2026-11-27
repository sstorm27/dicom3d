"""Genereaza src/dicom3d/catalog/colectii_tcia.json din indexul oficial NCI Imaging Data Commons.

    pip install idc-index-data duckdb pandas
    python scripts/genereaza_manifest_tcia.py <folderul cu idc_index.parquet> > src/dicom3d/catalog/colectii_tcia.json

Alege, din fiecare colectie, cate o serie CT axiala pe pacient (80-300 de felii, fara
reconstructii sagitale/coronale, MIP sau topograme), intr-o ordine stabila (hash pe UID).
"""
import html
import json
import re
import sys

import duckdb

IDX = sys.argv[1]
c = duckdb.connect()
c.execute(f"create view s as select * from '{IDX}/idc_index.parquet'")
c.execute(f"create view col as select * from '{IDX}/collections_index.parquet'")
PLAN = [  # (collection, regiune, cate, filtru suplimentar)
    ("nsclc_radiomics", "torace", 8, "true"),
    ("lidc_idri", "torace", 4, "PatientSex is not null and PatientAge is not null"),
    ("pancreas_ct", "abdomen", 3, "true"),
    ("hcc_tace_seg", "abdomen", 3, "lower(coalesce(SeriesDescription,'')) similar to '.*(liver|phase|c-a-p|cap|standard).*'"),
]
# serii verificate la descarcare si scoase: HCC_002 are doua faze cu aceleasi pozitii intr-o serie
EXCLUDE = ("HCC_002",)
BAD = "(sag|cor|mip|scout|topo|locali|mpr|dose|report|lung window)"
out = {"sursa": "NCI Imaging Data Commons (IDC), copie publica a colectiilor TCIA; idc-index-data 25.0.5",
       "colectii": {}, "serii": []}
for cid, region, n, extra in PLAN:
    must = ["'LUNG1-157'"] if cid == "nsclc_radiomics" else []
    rows = c.execute(f"""
      with cand as (
        select *, count(*) over (partition by PatientID) nser from s
        where collection_id='{cid}' and Modality='CT' and instanceCount between 80 and 300
          and not regexp_matches(lower(coalesce(SeriesDescription,'')), '{BAD}') and {extra} and PatientID not in {tuple(EXCLUDE) + ('',)!r})
      select collection_id, PatientID, PatientSex, PatientAge, StudyInstanceUID, SeriesInstanceUID,
             StudyDate, StudyDescription, SeriesDescription, BodyPartExamined, Manufacturer,
             ManufacturerModelName, instanceCount, series_size_MB, aws_bucket, crdc_series_uuid,
             license_short_name, source_DOI
      from cand
      qualify row_number() over (partition by PatientID order by instanceCount desc) = 1
      order by (PatientID in ({','.join(must) or "''"})) desc, hash(SeriesInstanceUID)
      limit {n}""").df()
    meta = c.execute(f"select collection_name, sources from col where collection_id='{cid}'").fetchone()
    src = next((x for x in meta[1] if x["modalities"] and "CT" in x["modalities"]), meta[1][0])
    out["colectii"][cid] = {
        "nume": meta[0], "regiune": region, "doi": src["source_doi"], "url": src["source_url"],
        "licenta": src["license"]["license_short_name"], "licenta_url": src["license"]["license_url"],
        "citare": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(src["citation"]))).strip()}
    for r in rows.to_dict("records"):
        out["serii"].append({
            "colectie": cid, "pacient": r["PatientID"], "sex": r["PatientSex"] or "",
            "varsta": r["PatientAge"] or "", "studiu_uid": r["StudyInstanceUID"],
            "serie_uid": r["SeriesInstanceUID"], "data_studiu": r["StudyDate"] or "",
            "descriere_studiu": r["StudyDescription"] or "", "descriere": r["SeriesDescription"] or "",
            "regiune": region, "producator": r["Manufacturer"] or "",
            "felii": int(r["instanceCount"]), "mb": round(float(r["series_size_MB"]), 1),
            "bucket": r["aws_bucket"], "prefix": r["crdc_series_uuid"],
        })
for k in ("sex","varsta","data_studiu","descriere_studiu","descriere","producator"):
    for x in out["serii"]:
        if x[k] != x[k]: x[k] = ""   # NaN
sys.stdout.reconfigure(encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=False))
