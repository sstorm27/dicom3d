"""Catalogul local de studii CT: o baza de date SQLite cu pacienti, studii, serii si fisiere.

Modelul urmeaza ierarhia DICOM (pacient -> studiu -> serie -> instanta), plus colectia
publica din care provine seria (ex. NSCLC-Radiomics din TCIA):

    collection 1─* patient 1─* study 1─* series 1─* instance

Baza de date NU contine date de identificare: nici numele pacientului, nici data
nasterii, nici ID-ul real. Pentru colectiile publice TCIA se pastreaza pseudonimul
publicat (ex. LUNG1-157), care e deja anonimizat de arhiva. Pentru seriile proprii,
ID-ul pacientului se inlocuieste cu un hash (vezi `indexer.patient_key`).

Fisierele DICOM raman pe disc; baza de date retine doar unde sunt si metadatele lor,
ca seria sa poata fi aleasa din interfata fara o noua cautare in foldere.

Fiecare operatie deschide o conexiune scurta, asa ca obiectul `Catalog` se poate folosi
si din firele de lucru ale interfetei (sqlite3 nu permite partajarea unei conexiuni).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from dicom3d.data import SeriesInfo

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS collection (
    id           TEXT PRIMARY KEY,          -- ex. nsclc_radiomics; 'local' pentru serii proprii
    name         TEXT NOT NULL,
    region       TEXT NOT NULL DEFAULT '',  -- torace, abdomen ...
    doi          TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL DEFAULT '',
    license      TEXT NOT NULL DEFAULT '',
    license_url  TEXT NOT NULL DEFAULT '',
    citation     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS patient (
    id            INTEGER PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collection(id),
    patient_key   TEXT NOT NULL,            -- pseudonim TCIA sau hash, niciodata ID-ul real
    sex           TEXT NOT NULL DEFAULT '', -- M / F / O / ''
    age_years     INTEGER,                  -- varsta la data studiului
    UNIQUE (collection_id, patient_key)
);

CREATE TABLE IF NOT EXISTS study (
    study_uid    TEXT PRIMARY KEY,
    patient_id   INTEGER NOT NULL REFERENCES patient(id) ON DELETE CASCADE,
    study_date   TEXT NOT NULL DEFAULT '',  -- AAAALLZZ (in TCIA datele sunt decalate)
    description  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS series (
    series_uid          TEXT PRIMARY KEY,
    study_uid           TEXT NOT NULL REFERENCES study(study_uid) ON DELETE CASCADE,
    modality            TEXT NOT NULL DEFAULT '',
    description         TEXT NOT NULL DEFAULT '',
    series_number       INTEGER,
    body_part           TEXT NOT NULL DEFAULT '',
    region              TEXT NOT NULL DEFAULT '',
    manufacturer        TEXT NOT NULL DEFAULT '',
    model               TEXT NOT NULL DEFAULT '',
    convolution_kernel  TEXT NOT NULL DEFAULT '',
    contrast_agent      TEXT NOT NULL DEFAULT '',
    kvp                 REAL,
    rows                INTEGER,
    columns             INTEGER,
    pixel_spacing_mm    REAL,               -- in plan (randuri; de obicei egal cu coloanele)
    slice_thickness_mm  REAL,               -- grosimea nominala
    slice_spacing_mm    REAL,               -- distanta mediana dintre pozitiile feliilor
    extent_mm           REAL,               -- lungimea acoperita pe axa feliilor
    num_instances       INTEGER NOT NULL,
    size_bytes          INTEGER NOT NULL DEFAULT 0,
    folder              TEXT NOT NULL,
    indexed_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS instance (
    sop_uid          TEXT PRIMARY KEY,
    series_uid       TEXT NOT NULL REFERENCES series(series_uid) ON DELETE CASCADE,
    path             TEXT NOT NULL,
    instance_number  INTEGER,
    position_mm      REAL,                  -- pozitia pe normala la felie (pentru sortare)
    size_bytes       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_instance_series ON instance(series_uid);
CREATE INDEX IF NOT EXISTS ix_series_study ON series(study_uid);
CREATE INDEX IF NOT EXISTS ix_study_patient ON study(patient_id);

CREATE VIEW IF NOT EXISTS v_series AS
SELECT s.series_uid, s.modality, s.description, s.series_number, s.body_part,
       COALESCE(NULLIF(s.region, ''), c.region) AS region,
       s.manufacturer, s.model, s.convolution_kernel, s.contrast_agent, s.kvp,
       s.rows, s.columns, s.pixel_spacing_mm, s.slice_thickness_mm, s.slice_spacing_mm,
       s.extent_mm, s.num_instances, s.size_bytes, s.folder, s.indexed_at,
       st.study_uid, st.study_date, st.description AS study_description,
       p.patient_key, p.sex, p.age_years,
       c.id AS collection_id, c.name AS collection_name, c.license
FROM series s
JOIN study st ON st.study_uid = s.study_uid
JOIN patient p ON p.id = st.patient_id
JOIN collection c ON c.id = p.collection_id;
"""

LOCAL_COLLECTION = {"id": "local", "name": "Serii proprii", "region": "",
                    "license": "", "citation": ""}


def default_home() -> Path:
    """Folderul cu datele aplicatiei: catalogul si seriile descarcate.

    `DICOM3D_HOME` il poate muta (ex. pe alt disc); implicit Documente/DICOM3D.
    """
    env = os.environ.get("DICOM3D_HOME")
    if env:
        return Path(env)
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "DICOM3D"


def default_db_path() -> Path:
    return default_home() / "catalog.sqlite"


@dataclass
class SeriesRow:
    """Un rand din catalog, asa cum il arata interfata."""

    series_uid: str
    collection_id: str
    collection_name: str
    license: str
    patient_key: str
    sex: str
    age_years: int | None
    study_uid: str
    study_date: str
    study_description: str
    modality: str
    description: str
    region: str
    body_part: str
    manufacturer: str
    model: str
    convolution_kernel: str
    contrast_agent: str
    rows: int | None
    columns: int | None
    pixel_spacing_mm: float | None
    slice_thickness_mm: float | None
    slice_spacing_mm: float | None
    extent_mm: float | None
    num_instances: int
    size_bytes: int
    folder: str

    @property
    def title(self) -> str:
        return self.description or self.study_description or "(fără descriere)"


_ROW_FIELDS = list(SeriesRow.__dataclass_fields__)


class Catalog:
    """Acces la baza de date SQLite a catalogului."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(SCHEMA)
            con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.add_collection(LOCAL_COLLECTION)

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            with con:  # tranzactie: commit la final, rollback la exceptie
                yield con
        finally:
            con.close()

    # ---------- scriere ----------

    def add_collection(self, meta: dict) -> None:
        with self._connect() as con:
            con.execute(
                """INSERT INTO collection (id, name, region, doi, url, license, license_url, citation)
                   VALUES (:id, :name, :region, :doi, :url, :license, :license_url, :citation)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, region=excluded.region,
                     doi=excluded.doi, url=excluded.url, license=excluded.license,
                     license_url=excluded.license_url, citation=excluded.citation""",
                {"region": "", "doi": "", "url": "", "license": "", "license_url": "",
                 "citation": "", **meta})

    def add_series(self, record: dict, instances: list[dict]) -> None:
        """Adauga (sau inlocuieste) o serie cu pacientul, studiul si fisierele ei.

        `record` are cheile: collection_id, patient_key, sex, age_years, study_uid,
        study_date, study_description si coloanele tabelului `series`.
        """
        with self._connect() as con:
            con.execute(
                """INSERT INTO patient (collection_id, patient_key, sex, age_years)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(collection_id, patient_key) DO UPDATE SET
                     sex = COALESCE(NULLIF(excluded.sex, ''), patient.sex),
                     age_years = COALESCE(excluded.age_years, patient.age_years)""",
                (record["collection_id"], record["patient_key"], record.get("sex", ""),
                 record.get("age_years")))
            pid = con.execute("SELECT id FROM patient WHERE collection_id=? AND patient_key=?",
                              (record["collection_id"], record["patient_key"])).fetchone()[0]
            con.execute(
                """INSERT INTO study (study_uid, patient_id, study_date, description)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(study_uid) DO UPDATE SET patient_id=excluded.patient_id,
                     study_date=excluded.study_date, description=excluded.description""",
                (record["study_uid"], pid, record.get("study_date", ""),
                 record.get("study_description", "")))
            cols = [c for c in _SERIES_COLUMNS if c in record]
            con.execute("DELETE FROM series WHERE series_uid=?", (record["series_uid"],))
            con.execute(
                f"INSERT INTO series ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [record[c] for c in cols])
            con.executemany(
                """INSERT OR REPLACE INTO instance
                   (sop_uid, series_uid, path, instance_number, position_mm, size_bytes)
                   VALUES (:sop_uid, :series_uid, :path, :instance_number, :position_mm, :size_bytes)""",
                [{**i, "series_uid": record["series_uid"]} for i in instances])

    def remove_series(self, series_uid: str) -> None:
        """Scoate seria din catalog (fisierele de pe disc raman)."""
        with self._connect() as con:
            con.execute("DELETE FROM series WHERE series_uid=?", (series_uid,))
            con.execute("DELETE FROM study WHERE study_uid NOT IN (SELECT study_uid FROM series)")
            con.execute("DELETE FROM patient WHERE id NOT IN (SELECT patient_id FROM study)")

    # ---------- citire ----------

    def series(self, text: str = "", region: str = "", collection: str = "") -> list[SeriesRow]:
        """Seriile din catalog, filtrate dupa text (pacient, descriere, colectie, producator),
        regiune si colectie."""
        where, args = [], []
        if text:
            like = f"%{text.strip()}%"
            where.append("(patient_key LIKE ? OR description LIKE ? OR study_description LIKE ?"
                         " OR collection_name LIKE ? OR manufacturer LIKE ? OR series_uid = ?)")
            args += [like, like, like, like, like, text.strip()]
        if region:
            where.append("region = ?")
            args.append(region)
        if collection:
            where.append("collection_id = ?")
            args.append(collection)
        sql = (f"SELECT {', '.join(_ROW_FIELDS)} FROM v_series"
               + (" WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY collection_id = 'local', collection_name, patient_key, study_date,"
                 " series_number")
        with self._connect() as con:
            return [SeriesRow(**dict(r)) for r in con.execute(sql, args)]

    def get(self, series_uid: str) -> SeriesRow | None:
        rows = [r for r in self.series(text=series_uid) if r.series_uid == series_uid]
        return rows[0] if rows else None

    def series_info(self, series_uid: str) -> SeriesInfo:
        """Seria ca `SeriesInfo`, cu fisierele sortate spatial, gata pentru `load_series`."""
        row = self.get(series_uid)
        if row is None:
            raise KeyError(f"Seria {series_uid} nu este in catalog.")
        with self._connect() as con:
            files = [r[0] for r in con.execute(
                """SELECT path FROM instance WHERE series_uid=?
                   ORDER BY position_mm IS NULL, position_mm, instance_number, path""",
                (series_uid,))]
        missing = [f for f in files if not os.path.exists(f)]
        if missing:
            raise FileNotFoundError(
                f"{len(missing)} din {len(files)} fisiere ale seriei lipsesc de pe disc "
                f"(ex. {missing[0]}). Seria a fost mutata sau stearsa; adauga din nou folderul.")
        return SeriesInfo(series_uid, row.description, row.modality, len(files), files)

    def collections(self) -> list[dict]:
        """Colectiile cu numarul de pacienti si serii din catalog."""
        with self._connect() as con:
            return [dict(r) for r in con.execute(
                """SELECT c.*, COUNT(DISTINCT p.id) AS patients, COUNT(s.series_uid) AS series
                   FROM collection c
                   LEFT JOIN patient p ON p.collection_id = c.id
                   LEFT JOIN study st ON st.patient_id = p.id
                   LEFT JOIN series s ON s.study_uid = st.study_uid
                   GROUP BY c.id ORDER BY c.id = 'local', c.name""")]

    def stats(self) -> dict:
        with self._connect() as con:
            r = con.execute(
                """SELECT (SELECT COUNT(*) FROM collection c WHERE EXISTS
                             (SELECT 1 FROM patient p WHERE p.collection_id = c.id)) AS collections,
                          (SELECT COUNT(*) FROM patient) AS patients,
                          (SELECT COUNT(*) FROM study) AS studies,
                          (SELECT COUNT(*) FROM series) AS series,
                          (SELECT COUNT(*) FROM instance) AS instances,
                          (SELECT COALESCE(SUM(size_bytes), 0) FROM series) AS size_bytes""").fetchone()
            return dict(r)

    def regions(self) -> list[str]:
        with self._connect() as con:
            return [r[0] for r in con.execute(
                "SELECT DISTINCT region FROM v_series WHERE region != '' ORDER BY region")]


_SERIES_COLUMNS = (
    "series_uid", "study_uid", "modality", "description", "series_number", "body_part", "region",
    "manufacturer", "model", "convolution_kernel", "contrast_agent", "kvp", "rows", "columns",
    "pixel_spacing_mm", "slice_thickness_mm", "slice_spacing_mm", "extent_mm", "num_instances",
    "size_bytes", "folder",
)
