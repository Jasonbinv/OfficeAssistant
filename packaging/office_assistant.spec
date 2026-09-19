# -*- mode: python ; coding: utf-8 -*-
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

spec_dir = Path(SPECPATH).resolve()
root = spec_dir.parent
src = root / "src"
entry = src / "office_assistant" / "app.py"
licenses_dir = spec_dir / "licenses"
user_guide = root / "使用说明.txt"

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
shiboken_datas, shiboken_binaries, shiboken_hidden = collect_all("shiboken6")
pdfium_datas, pdfium_binaries, pdfium_hidden = collect_all("pypdfium2")
pillow_datas, pillow_binaries, pillow_hidden = collect_all("PIL")

a = Analysis(
    [str(entry)],
    pathex=[str(src)],
    binaries=pyside_binaries + shiboken_binaries + pdfium_binaries + pillow_binaries,
    datas=pyside_datas
    + shiboken_datas
    + pdfium_datas
    + pillow_datas
    + [(str(licenses_dir), "licenses"), (str(user_guide), ".")],
    hiddenimports=pyside_hidden
    + shiboken_hidden
    + pdfium_hidden
    + pillow_hidden
    + [
        "pypdf",
        "PIL",
        "office_assistant",
        "office_assistant.app",
        "office_assistant.qt_preload",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OfficeAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="OfficeAssistant")

# PyInstaller 6 onedir: "." datas land under _internal; copy user guide beside the exe.
_dist_app = Path(DISTPATH) / "OfficeAssistant"
if user_guide.is_file() and _dist_app.is_dir():
    shutil.copy2(user_guide, _dist_app / user_guide.name)
