# PyInstaller: construieste aplicatia Windows (folder dist/DICOM3D cu DICOM3D.exe).
#   pyinstaller packaging/dicom3d.spec --noconfirm
# Nu includem toate modulele VTK: dicom3d.vtk_lite le importa explicit pe cele
# folosite, iar PyInstaller le gaseste singur (vezi comentariul din vtk_lite.py).
hidden = ["SimpleITK", "pydicom"]

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    hiddenimports=hidden,
    datas=[("../src/dicom3d/ui/assets", "dicom3d/ui/assets")],  # fonturile interfetei
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
# aceeasi aplicatie, dar cu consola: afiseaza erorile de pornire
exe_debug = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DICOM3D-debug",
    console=True,
)
coll = COLLECT(exe, exe_debug, a.binaries, a.datas, name="DICOM3D")
