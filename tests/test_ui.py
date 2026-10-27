"""Interfata: tema, campurile HU si alegerea tesutului (fara afisare pe ecran)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    from dicom3d.ui import theme

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply(app)
    return app


def test_stylesheet_has_no_unreplaced_tokens(app):
    from dicom3d.ui import theme

    assert "@" not in theme.stylesheet()


def test_hu_spin_uses_typographic_minus(app):
    from dicom3d.ui.widgets import hu_spin

    s = hu_spin()
    s.setValue(-1000)
    assert s.text() == "−1000 HU"
    s.lineEdit().setText("−400 HU")
    s.interpretText()
    assert s.value() == -400


def test_reselecting_tissue_restores_thresholds(app):
    from dicom3d.segmentation.threshold import PRESETS
    from dicom3d.ui.main_window import MainWindow

    w = MainWindow()
    w.tissue_chips._buttons["Plamani (aer)"].click()
    assert (w.lower_spin.value(), w.upper_spin.value()) == (-1000, -400)
    assert w.outside_check.isChecked()
    w.lower_spin.setValue(-900)
    w.tissue_chips._buttons["Plamani (aer)"].click()  # acelasi tesut, ales din nou
    p = PRESETS["Plamani (aer)"]
    assert (w.lower_spin.value(), w.upper_spin.value()) == (p.lower, p.upper)
    w.view3d.close_vtk()


def test_histogram_drag_keeps_lower_below_upper(app):
    import numpy as np

    from dicom3d.ui.widgets import HistogramRange

    h = HistogramRange()
    h.resize(300, 84)
    h.set_values(np.linspace(-1024, 3000, 10_000))
    h.set_range(-100, 200)
    edits = []
    h.rangeEdited.connect(lambda lo, hi: edits.append((lo, hi)))
    h._drag = 0
    h._drag_to(h._x(1500))  # manerul de jos tras peste cel de sus
    assert edits[-1][0] <= edits[-1][1] == 200
