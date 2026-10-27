"""Genereaza o serie CT sintetica (fantoma) pentru teste, fara date reale.

Fantoma: un cilindru de tesut moale (40 HU) in aer, cu o "coloana" de os
(sfere de 700 HU legate de o tija) si o sfera de os separata, mai mica.

    python scripts/make_phantom.py data/phantom
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid


def make_volume(nx=128, ny=128, nz=60, spacing=(1.0, 1.0, 2.0)) -> np.ndarray:
    sx, sy, sz = spacing
    z, y, x = np.mgrid[0:nz, 0:ny, 0:nx].astype(np.float32)
    X, Y, Z = (x - nx / 2) * sx, (y - ny / 2) * sy, z * sz  # mm
    vol = np.full((nz, ny, nx), -1000, np.float32)
    vol[(X**2 + Y**2) < 55**2] = 40
    # tija + "vertebre"
    vol[(X**2 + (Y - 15) ** 2) < 4**2] = 700
    for zc in np.arange(10, nz * sz - 5, 20):
        vol[(X**2 + (Y - 15) ** 2 + (Z - zc) ** 2) < 9**2] = 700
    # obiect osos separat (trebuie eliminat de "cea mai mare componenta")
    vol[((X + 30) ** 2 + (Y + 20) ** 2 + (Z - nz * sz / 2) ** 2) < 6**2] = 700
    rng = np.random.default_rng(0)
    vol += rng.normal(0, 15, vol.shape).astype(np.float32)
    return vol


def write_series(vol: np.ndarray, out: Path, spacing=(1.0, 1.0, 2.0)) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    study, series, frame = generate_uid(), generate_uid(), generate_uid()
    now = datetime.datetime.now()
    ny, nx = vol.shape[1:]
    paths = []
    # feliile sunt scrise in ordine inversata ca sa testam sortarea spatiala
    for k in reversed(range(vol.shape[0])):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        path = out / f"slice_{vol.shape[0] - 1 - k:04d}.dcm"
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = study, series, frame
        ds.Modality = "CT"
        ds.PatientName, ds.PatientID = "Fantoma^Sintetica", "PHANTOM001"
        ds.SeriesDescription = "Fantoma sintetica DICOM3D"
        ds.StudyDate = ds.SeriesDate = now.strftime("%Y%m%d")
        ds.SeriesNumber, ds.InstanceNumber = 1, k + 1
        ds.ImagePositionPatient = [-(nx / 2) * spacing[0], -(ny / 2) * spacing[1], k * spacing[2]]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.PixelSpacing = [spacing[1], spacing[0]]
        ds.SliceThickness = spacing[2]
        ds.Rows, ds.Columns = ny, nx
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 1
        ds.RescaleIntercept, ds.RescaleSlope = -1024, 1
        ds.PixelData = (np.round(vol[k]) + 1024).astype(np.int16).tobytes()
        ds.save_as(path, enforce_file_format=True)
        paths.append(path)
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    paths = write_series(make_volume(), args.out)
    print(f"Scris {len(paths)} felii in {args.out}")


if __name__ == "__main__":
    main()
