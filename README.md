# DICOM3D

Aplicatie desktop offline (Windows) pentru reconstructia 3D a structurilor anatomice
din serii DICOM: incarcare, segmentare, generare model 3D (Marching Cubes) si export STL.

Proiect de licenta. Etapa curenta: **pipeline clasic** (segmentare prin prag).
Segmentarea cu AI (nnU-Net, TotalSegmentator) urmeaza in etapele urmatoare.

## Ce face acum

- incarca o serie DICOM dintr-un folder (cauta recursiv, permite alegerea seriei)
- afiseaza feliile axiale cu ferestre CT (tesut moale, os, plamani, creier)
- segmentare prin prag in HU, cu presetari (os, tesut moale, vase, plamani, piele),
  pastrarea componentelor mari (nu doar a celei mai mari: claviculele, omoplatii si coastele
  superioare sunt bucati separate), os compact (umplerea spongioasei si a canalului medular),
  umplerea golurilor, netezire gaussiana
- previzualizare live a pragului pe felia curenta
- verificarea geometriei seriei (felii lipsa, spatiere neuniforma, gantry inclinat)
- preprocesare: valorile de umplutura aduse la aer, reducerea zgomotului (gaussian, median,
  difuzie anizotropa Perona-Malik), reesantionare la voxeli izotropi cu interpolare B-spline cubica
- model 3D cu Marching Cubes pe valorile HU (pozitia sub-voxel a marginii, nu doar masca 0/1),
  netezire (windowed sinc) si decimare cuadrica, in coordonatele pacientului (mm)
- vizualizare 3D interactiva (VTK) cu marcaj de orientare
- export STL (binar), OBJ, PLY; statistici (triunghiuri, volum in ml, suprafata)
- interfata in linie de comanda pentru procesare in lot

## Instalare (dezvoltare)

Necesita Python 3.10+.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Rulare

```powershell
python -m dicom3d                      # interfata grafica
python -m dicom3d C:\date\CT_serie     # deschide direct un folder
dicom3d-cli C:\date\CT_serie --preset Os -o os.stl
```

## Date de test

- Fantoma sintetica (fara date reale): `python scripts/make_phantom.py data/phantom`
- Date reale publice: de ex. seturile CT din [The Cancer Imaging Archive](https://www.cancerimagingarchive.net/)
  sau datele de exemplu din 3D Slicer. Folderul `data/` este ignorat de git:
  nu urcati date medicale in repo.

## Evaluarea preciziei

`python scripts/evaluate_accuracy.py` reconstruieste fantome cu geometrie cunoscuta (o sfera si
o tija inclinata, esantionate ca un CT real cu felii de 3 mm) cu fiecare varianta a pipeline-ului
si masoara distanta fata de suprafata exacta si eroarea de volum.

## Teste

```powershell
python -m pytest
```

## Construire .exe

```powershell
cd packaging
pyinstaller dicom3d.spec --noconfirm
```

Rezultatul este `packaging/dist/DICOM3D/DICOM3D.exe`. CI-ul (GitHub Actions) ruleaza testele
pe Linux si Windows si publica build-ul Windows ca artefact descarcabil.

## Structura

```
src/dicom3d/
  io/dicom_loader.py        incarcare serii DICOM (SimpleITK/GDCM)
  io/series_check.py        verificarea geometriei feliilor
  preprocessing.py          curatare HU, reducere zgomot, reesantionare izotropa
  segmentation/threshold.py segmentare prin prag + post-procesare
  mesh/surface.py           Marching Cubes, netezire, decimare, export
  pipeline.py               volum -> masca -> mesh
  ui/                       interfata PySide6 + VTK
  cli.py                    linie de comanda
scripts/make_phantom.py     generator de serie CT sintetica
scripts/evaluate_accuracy.py  precizia reconstructiei pe fantome analitice
packaging/                  PyInstaller
tests/                      teste automate
```
