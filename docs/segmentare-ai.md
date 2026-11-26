# Segmentare AI (TotalSegmentator)

## Instalare (opțional)

    pip install -e .[ai]

Aduce PyTorch (~1 GB). Merge pe procesor, fără placă NVIDIA (testat fără CUDA).
La prima rulare se descarcă ponderile rețelei (~135 MB modelul rapid, ~1,2 GB cel
complet) în `~/.totalsegmentator`; apoi aplicația merge offline. Statisticile de
utilizare ale TotalSegmentator sunt dezactivate de aplicație.
Executabilul `.exe` nu include AI (PyTorch e prea mare); se rulează din sursă.

## Cum se folosește

- Interfață: bifează „Segmentare AI (TotalSegmentator)” la Calitate, alege țesutul
  (Os, Plămâni, Vase, Țesut moale → organe) și generează modelul. Segmentarea se
  calculează o dată pe serie și se refolosește la schimbarea țesutului.
- Linie de comandă: `dicom3d-cli <serie> --preset Os --ai -o os.stl`
  (`--ai-full` = modelul la 1,5 mm, `--ai-raw` = doar masca rețelei).

## Cum funcționează

1. TotalSegmentator (nnU-Net, 117 structuri) etichetează fiecare os/organ.
2. Masca grupului ales e reeșantionată la voxeli cubici și netezită gaussian
   (fără treptele de 3 mm ale feliilor).
3. Lângă structurile găsite de rețea, marginea se pune după valorile HU (ca la prag);
   rețeaua completează doar ce pragul pierde (sternul, cartilajele costale, spongioasa)
   și elimină ce nu e os (vase cu contrast, cabluri, masa).

| Seria NSCLC (3 mm), os | Timp (CPU, 4 nuclee) | RAM |
|---|---|---|
| Prag 250 HU | ~15 s | ~2 GB |
| AI rapid (3 mm) + HU | ~1 min | ~3 GB |
| AI complet (1,5 mm) + HU | ~14 min | ~6 GB |

## Grosimea feliei: studiu

`scripts/slice_thickness_study.py` ia un CT cu felii de 0,625 mm (MSD Task06_Lung,
CC BY-SA 4.0), simulează aceeași scanare la 3 mm și compară fiecare metodă cu ea
însăși pe feliile subțiri (lung_022, os):

| Metodă pe felii de 3 mm | Suprafața de referință la ≤1 mm | ≤2 mm | Distanța medie |
|---|---|---|---|
| Prag 250 HU | 63 % | 74 % | 3,7 mm |
| AI + HU | 85 % | 97 % | 0,6 mm |

Pentru lucrare: rețeaua nu „inventează” felii noi; decide doar ce voxeli sunt os.
Detaliul suprafeței vine tot din valorile măsurate, deci limita fundamentală rămâne
grosimea feliei. Cea mai bună imagine se obține cu o serie de 0,6–1,25 mm.
