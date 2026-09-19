from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from office_assistant.qt_preload import preload_pyside6

preload_pyside6()

from PySide6.QtCore import QObject, Signal, Slot


def run_callable_job(fn: Callable[[], Any], cancel_event: threading.Event) -> Any:
    if cancel_event.is_set():
        raise RuntimeError("已取消")
    return fn()


class JobWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any], cancel_event: threading.Event):
        super().__init__()
        self._fn = fn
        self.cancel_event = cancel_event

    @Slot()
    def run_job(self) -> None:
        try:
            result = run_callable_job(self._fn, self.cancel_event)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
