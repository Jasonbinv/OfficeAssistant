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
    excludes=["numpy"],
    noarchive=False,
)

# PySide6 6.10+ Qt6Core.dll imports unversioned ICU symbols (ucnv_open).
# Anaconda's icuuc.dll only exports ucnv_open_73; if it is copied into
# _internal it shadows Windows System32\icuuc.dll and the exe fails at
# startup with "无法定位程序输入点 ucnv_open".
a.binaries = [
    item
    for item in a.binaries
    if not (Path(item[0]).name.lower().startswith("icu") and Path(item[0]).name.lower().endswith(".dll"))
]

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

# PyInstaller 6 onedir: "." datas land under _internal; copy beside exe after COLLECT.
if user_guide.is_file():
    shutil.copy2(user_guide, Path(coll.name) / user_guide.name)
