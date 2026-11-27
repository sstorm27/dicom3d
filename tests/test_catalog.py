"""Baza de date (catalogul SQLite): indexare, anonimizare, cautare, incarcare si descarcare."""

import shutil
import sqlite3

import pydicom
import pytest

from dicom3d.catalog import Catalog
from dicom3d.catalog import download as dl
from dicom3d.catalog.indexer import index_folder, parse_age, patient_key
from dicom3d.io.dicom_loader import load_series


@pytest.fixture
def catalog(tmp_path):
    return Catalog(tmp_path / "catalog.sqlite")


def test_index_folder_builds_patient_study_series(catalog, phantom_dir):
    uids = index_folder(catalog, phantom_dir, region="test")
    assert len(uids) == 1
    st = catalog.stats()
    assert (st["patients"], st["studies"], st["series"]) == (1, 1, 1)
    assert st["instances"] == len(list(phantom_dir.glob("*.dcm")))
    row = catalog.series()[0]
    assert row.collection_id == "local"
    assert row.modality == "CT" and row.region == "test"
    assert row.slice_spacing_mm == pytest.approx(2.0)
    assert row.extent_mm == pytest.approx((row.num_instances - 1) * 2.0)
    assert (row.rows, row.columns, row.pixel_spacing_mm) == (128, 128, 1.0)


def test_local_patient_id_is_never_stored(catalog, phantom_dir):
    index_folder(catalog, phantom_dir)
    dump = "\n".join(sqlite3.connect(catalog.path).iterdump())
    assert "PHANTOM001" not in dump and "Fantoma^Sintetica" not in dump
    assert catalog.series()[0].patient_key == patient_key("PHANTOM001", "local")


def test_public_pseudonym_is_kept():
    assert patient_key("LUNG1-157", "nsclc_radiomics") == "LUNG1-157"
    assert patient_key("LUNG1-157", "local").startswith("P-")


def test_reindexing_does_not_duplicate(catalog, phantom_dir):
    index_folder(catalog, phantom_dir)
    index_folder(catalog, phantom_dir)
    assert catalog.stats()["series"] == 1
    assert catalog.stats()["instances"] == len(list(phantom_dir.glob("*.dcm")))


def test_series_info_is_sorted_and_loads(catalog, phantom_dir):
    uid = index_folder(catalog, phantom_dir)[0]
    info = catalog.series_info(uid)
    # fantoma e scrisa cu feliile in ordine inversa: catalogul le sorteaza dupa pozitie
    z = [float(pydicom.dcmread(f, stop_before_pixels=True).ImagePositionPatient[2])
         for f in info.files]
    assert z == sorted(z)
    vol = load_series(info)
    assert vol.shape_xyz[2] == info.num_files
    assert not vol.sampling.warnings()


def test_missing_files_are_reported(catalog, phantom_dir, tmp_path):
    copy = tmp_path / "copie"
    shutil.copytree(phantom_dir, copy)
    uid = index_folder(catalog, copy)[0]
    next(copy.glob("*.dcm")).unlink()
    with pytest.raises(FileNotFoundError, match="lipsesc"):
        catalog.series_info(uid)


def test_search_and_filters(catalog, phantom_dir):
    index_folder(catalog, phantom_dir, region="torace")
    assert len(catalog.series("fantoma")) == 1
    assert catalog.series("nu-exista") == []
    assert len(catalog.series(region="torace")) == 1
    assert catalog.series(region="abdomen") == []
    assert catalog.regions() == ["torace"]


def test_remove_series_cleans_up(catalog, phantom_dir):
    uid = index_folder(catalog, phantom_dir)[0]
    catalog.remove_series(uid)
    st = catalog.stats()
    assert (st["patients"], st["studies"], st["series"], st["instances"]) == (0, 0, 0, 0)


def test_known_series_get_collection_from_manifest(catalog, phantom_dir):
    uid = str(pydicom.dcmread(next(phantom_dir.glob("*.dcm")), stop_before_pixels=True)
              .SeriesInstanceUID)
    known = {uid: {"colectie": "nsclc_radiomics", "regiune": "torace", "pacient": "LUNG1-999",
                   "sex": "F", "varsta": "057Y"}}
    dl.register_collections(catalog)
    index_folder(catalog, phantom_dir, known=known)
    row = catalog.series()[0]
    assert (row.collection_name, row.patient_key, row.sex, row.age_years) == (
        "NSCLC-Radiomics", "LUNG1-999", "F", 57)
    assert row.license == "CC BY-NC 3.0"


@pytest.mark.parametrize("value, years", [("057Y", 57), ("018M", 1), ("", None), ("abc", None)])
def test_parse_age(value, years):
    assert parse_age(value) == years


def test_manifest_is_complete():
    m = dl.load_manifest()
    assert len(m["serii"]) >= 15
    assert len({s["pacient"] for s in m["serii"]}) == len(m["serii"])  # pacienti diferiti
    assert len({s["serie_uid"] for s in m["serii"]}) == len(m["serii"])
    assert "LUNG1-157" in {s["pacient"] for s in m["serii"]}  # seria folosita pana acum
    for cid, c in m["colectii"].items():
        assert c["licenta"].startswith("CC BY") and c["doi"] and "doi.org" in c["citare"]
        assert any(s["colectie"] == cid for s in m["serii"])
    for s in m["serii"]:
        assert s["bucket"].startswith("idc-open-data") and s["prefix"] and s["felii"] >= 80


def test_select_limits_per_collection():
    m = dl.load_manifest()
    chosen = dl.select(m, max_per_collection=1)
    assert len(chosen) == len(m["colectii"])
    assert all(s["colectie"] == "lidc_idri" for s in dl.select(m, ["lidc_idri"]))


def test_parse_s3_listing():
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>true</IsTruncated>
<NextContinuationToken>abc</NextContinuationToken>
<Contents><Key>u/1.dcm</Key><Size>10</Size></Contents>
<Contents><Key>u/2.dcm</Key><Size>20</Size></Contents></ListBucketResult>"""
    assert dl.parse_listing(xml) == ([("u/1.dcm", 10), ("u/2.dcm", 20)], "abc")


def test_download_from_fake_bucket(tmp_path, phantom_dir, monkeypatch):
    """Descarcarea completa, cu reteaua inlocuita de fisierele fantomei."""
    files = sorted(phantom_dir.glob("*.dcm"))
    uid = str(pydicom.dcmread(files[0], stop_before_pixels=True).SeriesInstanceUID)
    entry = {"colectie": "lidc_idri", "pacient": "LIDC-IDRI-9999", "sex": "M", "varsta": "036Y",
             "serie_uid": uid, "regiune": "torace", "mb": 1.0, "bucket": "idc-open-data",
             "prefix": "uuid-test", "felii": len(files)}
    manifest = dl.load_manifest()
    manifest["serii"] = [entry]
    monkeypatch.setattr(dl, "load_manifest", lambda: manifest)
    monkeypatch.setattr(dl, "list_objects",
                        lambda bucket, prefix: [(f"{prefix}/{f.name}", f.stat().st_size) for f in files])
    calls = []

    def fake_get(url, timeout=60):
        calls.append(url)
        return (phantom_dir / url.rsplit("/", 1)[1]).read_bytes()

    monkeypatch.setattr(dl, "_get", fake_get)
    cat = Catalog(tmp_path / "catalog.sqlite")
    assert dl.download(tmp_path, cat) == [uid]
    row = cat.get(uid)
    assert (row.collection_id, row.patient_key, row.age_years) == ("lidc_idri", "LIDC-IDRI-9999", 36)
    assert len(calls) == len(files)
    dl.download(tmp_path, cat)  # a doua oara: fisierele exista deja, nu se mai descarca
    assert len(calls) == len(files)
    assert load_series(cat.series_info(uid)).shape_xyz[2] == len(files)
