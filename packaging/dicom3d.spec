# PyInstaller: construieste aplicatia Windows (folder dist/DICOM3D cu DICOM3D.exe).
#   pyinstaller packaging/dicom3d.spec --noconfirm
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("vtkmodules") + ["SimpleITK", "pydicom"]

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DICOM3D",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="DICOM3D")
