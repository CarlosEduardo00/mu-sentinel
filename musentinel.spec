# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: MU Sentinel em modo onedir (pasta com .exe), sem UPX.
# Uso: pyinstaller --noconfirm musentinel.spec   (o build.ps1 já faz isso)

import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

ROOT = Path(SPECPATH)
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
nums = tuple(int(x) for x in (VERSION.split(".") + ["0"] * 4)[:4])

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1,
                      subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("041604B0", [
            StringStruct("CompanyName", "MU Sentinel"),
            StringStruct("FileDescription", "MU Sentinel - monitor de janelas do MU Online"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "MUSentinel"),
            StringStruct("OriginalFilename", "MUSentinel.exe"),
            StringStruct("ProductName", "MU Sentinel"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
    ],
)

datas = [
    (str(ROOT / "assets" / "profiles"), "assets/profiles"),
    (str(ROOT / "assets" / "musentinel.ico"), "assets"),
    (str(ROOT / "assets" / "musentinel.png"), "assets"),
]
datas += collect_data_files("rapidocr_onnxruntime")  # modelos .onnx e config do OCR
binaries = []
hiddenimports = collect_submodules("keyring.backends") + ["win32ctypes.core", "win32timezone"]
for pkg in ("windows_capture",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

excludes = [
    "tkinter", "matplotlib", "IPython", "pytest",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtSensors",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
# Corta o que o app não usa (deixa o zip bem menor)
DROP = ("opengl32sw.dll", "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard", "Qt6OpenGL", "qtquick",
        "qml", "qpdf", "QtQuick", "QtQml")


def keep(entry) -> bool:
    name = entry[0].replace("\\", "/")
    if any(d in name for d in DROP):
        return False
    if "/translations/" in name and not ("pt_BR" in name or name.endswith("_pt.qm")):
        return False
    return True


a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MUSentinel",
    icon=str(ROOT / "assets" / "musentinel.ico"),
    version=version_info,
    console=False,
    uac_admin=False,  # manifest asInvoker: abre sem pedir administrador
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MUSentinel")
