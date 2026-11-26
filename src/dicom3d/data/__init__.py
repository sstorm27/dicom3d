"""Structurile de date ale aplicatiei (vezi docs/structura-datelor.md).

    SeriesInfo      seria gasita pe disc (fisiere, UID, descriere)
    AcquisitionInfo parametrii de achizitie (kVp, kernel, grosime felie, rescale...)
    SliceSampling   verificarea pozitiilor feliilor (goluri, duplicate, pas, inclinare)
    Geometry        grila de voxeli in coordonatele pacientului (LPS, mm)
    Volume          intensitatile (HU) + Geometry + metadate
    Label, LabelMap rezultatul segmentarii, una sau mai multe structuri
"""

from dicom3d.data.geometry import Geometry
from dicom3d.data.metadata import AcquisitionInfo, SeriesInfo, SliceSampling
from dicom3d.data.segmentation import BACKGROUND, Label, LabelMap
from dicom3d.data.volume import Volume

__all__ = [
    "AcquisitionInfo", "BACKGROUND", "Geometry", "Label", "LabelMap", "SeriesInfo",
    "SliceSampling", "Volume",
]
