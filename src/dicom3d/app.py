"""Punctul de intrare al aplicatiei grafice."""

from __future__ import annotations

import faulthandler
import os
import sys
import traceback
from pathlib import Path


def _log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share"
    path = Path(base) / "DICOM3D"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _setup_crash_log() -> Path:
    """In .exe nu exista consola, asa ca erorile ajung intr-un fisier de log."""
    log_path = _log_dir() / "dicom3d.log"
    log = open(log_path, "w", encoding="utf-8", buffering=1)  # noqa: SIM115 - ramane deschis
    faulthandler.enable(log)  # prinde si caderile din codul nativ (Qt, VTK)
    if sys.stdout is None:  # executabil fara consola
        sys.stdout = sys.stderr = log

    def excepthook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.write(text)
        if sys.__stderr__:
            print(text, file=sys.__stderr__)

    sys.excepthook = excepthook
    log.write(f"DICOM3D pornit, Python {sys.version}\n")
    return log_path


def main(argv: list[str] | None = None) -> int:
    log_path = _setup_crash_log()
    try:
        from PySide6.QtWidgets import QApplication

        from dicom3d.ui.main_window import MainWindow

        argv = sys.argv if argv is None else argv
        app = QApplication(argv)
        app.setApplicationName("DICOM3D")
        if len(argv) > 1 and argv[1] == "--playtest":  # --playtest <folder_dicom> <folder_iesire>
            from dicom3d.playtest import run as run_playtest

            return run_playtest(app, argv[2], argv[3])
        win = MainWindow()
        win.show()
        print("Fereastra principala afisata", flush=True)
        if len(argv) > 1:  # folder DICOM dat in linia de comanda
            win.open_folder(argv[1])
        return app.exec()
    except Exception:
        traceback.print_exc()
        _show_fatal_error(log_path)
        return 1


def _show_fatal_error(log_path: Path):
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None, f"DICOM3D nu a putut porni.\nDetalii in:\n{log_path}", "DICOM3D", 0x10
        )


if __name__ == "__main__":
    sys.exit(main())
