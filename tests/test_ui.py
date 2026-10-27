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
    w.ruler.activate("Plamani (aer)")
    assert (w.lower_spin.value(), w.upper_spin.value()) == (-1000, -400)
    assert w.outside_check.isChecked()
    assert w.window_seg.currentText() == "Plămâni"  # fereastra CT urmeaza tesutul
    w.lower_spin.setValue(-900)
    w.ruler.activate("Plamani (aer)")  # acelasi tesut, ales din nou
    p = PRESETS["Plamani (aer)"]
    assert (w.lower_spin.value(), w.upper_spin.value()) == (p.lower, p.upper)
    w.view3d.close_vtk()


def test_ruler_drag_keeps_lower_below_upper(app):
    import numpy as np

    from dicom3d.segmentation.threshold import PRESETS
    from dicom3d.ui.widgets import HounsfieldRuler

    r = HounsfieldRuler(PRESETS)
    r.resize(248, 300)
    r.set_values(np.linspace(-1024, 3000, 10_000))
    r.set_range(-100, 200)
    edits = []
    r.rangeEdited.connect(lambda lo, hi: edits.append((lo, hi)))
    r._drag = 0
    r._drag_to(r._y(1500))  # manerul de jos tras peste cel de sus
    assert edits[-1][0] <= edits[-1][1] == 200


def test_ruler_labels_do_not_overlap_and_click_picks_preset(app):
    from PySide6.QtCore import QPointF

    from dicom3d.segmentation.threshold import PRESETS
    from dicom3d.ui.widgets import HounsfieldRuler

    r = HounsfieldRuler(PRESETS)
    for height in (170, 300, 600):
        r.resize(248, height)
        ys = sorted(y for _, y, _, _ in r._label_rows())
        assert all(b - a >= r.ROW - 0.01 for a, b in zip(ys, ys[1:]))
        assert ys[0] >= 0 and ys[-1] <= height
    picked = []
    r.presetActivated.connect(picked.append)
    name, y, _, _ = r._label_rows()[0]
    assert r._preset_at(QPointF(r._cols()["text"] + 5, y)) == name


def test_window_fits_small_screen(app):
    from dicom3d.ui.main_window import MainWindow

    w = MainWindow()
    avail = w.screen().availableGeometry()
    assert w.width() <= avail.width() and w.height() <= avail.height()
    w.view3d.close_vtk()


def test_console_without_romanian_letters_does_not_crash(tmp_path):
    """Consola Windows foloseste cp1252, fara ă si ț; playtest-ul scrie mesaje cu diacritice."""
    import subprocess
    import sys

    script = (
        "import pathlib, dicom3d.app as a; a._log_dir = lambda: pathlib.Path(r'%s'); "
        "a._setup_crash_log(); print('Serie fără descriere, țesut')" % tmp_path
    )
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, env=env)
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
