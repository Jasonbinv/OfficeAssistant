from pathlib import Path

import ctypes
import os
import sys
from ctypes import wintypes


def preload_pyside6() -> None:
    """Load Qt/PySide native libraries with the classic Windows search path.

    Python 3.8+ extension imports use a restricted DLL search that fails to
    resolve PySide6's Qt6*.dll / shiboken6 chain on some Windows setups
    (including Anaconda). LoadLibraryW succeeds; import Qt* after this.
    """
    if sys.platform != "win32":
        return
    import PySide6
    import shiboken6

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
    kernel32.LoadLibraryW.restype = wintypes.HMODULE
    add_dir = getattr(os, "add_dll_directory", None)
    roots = (Path(shiboken6.__file__).resolve().parent, Path(PySide6.__file__).resolve().parent)
    if getattr(sys, "frozen", False):
        plugin_dir = Path(PySide6.__file__).resolve().parent / "plugins"
        if plugin_dir.is_dir():
            os.environ.setdefault("QT_PLUGIN_PATH", str(plugin_dir))
        system_icu = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "icuuc.dll"
        if system_icu.is_file():
            kernel32.LoadLibraryW(str(system_icu))
    names = (
        "shiboken6.abi3.dll",
        "Qt6Core.dll",
        "Qt6Gui.dll",
        "Qt6Widgets.dll",
        "pyside6.abi3.dll",
        "QtCore.pyd",
        "QtGui.pyd",
        "QtWidgets.pyd",
    )
    for root in roots:
        if callable(add_dir):
            add_dir(str(root))
        for name in names:
            path = root / name
            if path.exists():
                kernel32.LoadLibraryW(str(path))
