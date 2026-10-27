"""Punctul de intrare al aplicatiei grafice."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from dicom3d.ui.main_window import MainWindow

    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("DICOM3D")
    win = MainWindow()
    win.show()
    if len(argv) > 1:  # folder DICOM dat in linia de comanda
        win.open_folder(argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
