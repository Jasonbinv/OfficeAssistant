from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

_GENERIC_READ = 0x80000000
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

try:
    _CreateFileW = ctypes.windll.kernel32.CreateFileW  # type: ignore[attr-defined]
    _CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    _CreateFileW.restype = ctypes.c_void_p
    _CloseHandle = ctypes.windll.kernel32.CloseHandle  # type: ignore[attr-defined]
    _CloseHandle.argtypes = [ctypes.c_void_p]
    _CloseHandle.restype = ctypes.c_int
except AttributeError:
    _CreateFileW = None
    _CloseHandle = None


def is_locked(path: Path) -> bool:
    if sys.platform != "win32" or _CreateFileW is None or _CloseHandle is None:
        return False
    handle = _CreateFileW(
        str(path),
        _GENERIC_READ,
        0,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle in (None, 0, _INVALID_HANDLE_VALUE):
        return True
    _CloseHandle(handle)
    return False


def replace_file(temp: Path, dest: Path) -> None:
    os.replace(temp, dest)
    if temp.exists():
        temp.unlink(missing_ok=True)


def remove_incomplete(path: Path) -> None:
    path.unlink(missing_ok=True)
