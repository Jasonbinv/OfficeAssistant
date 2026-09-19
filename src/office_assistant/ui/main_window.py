from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from office_assistant.tasks.worker import JobWorker
from office_assistant.ui.delete_page import DeletePage
from office_assistant.ui.merge_page import MergePage
from office_assistant.ui.rename_page import RenamePage
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

NAV_ITEMS = ("合并 PDF", "删除页面", "重命名")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("办公文件助手")
        self.cancel_event = threading.Event()
        self._thread: QThread | None = None
        self._worker: JobWorker | None = None
        self._on_done: Callable[[Any], None] | None = None
        self._job_queue: list[tuple[Callable[[], Any], Callable[[Any], None] | None]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        self.nav = QListWidget()
        self.nav.setFixedWidth(120)
        for title in NAV_ITEMS:
            self.nav.addItem(title)

        self.stack = QStackedWidget()
        self.stack.addWidget(MergePage())
        self.stack.addWidget(DeletePage())
        self.stack.addWidget(RenamePage())

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)

        self.summary_label = QLabel("就绪")

        bottom = QHBoxLayout()
        bottom.addWidget(self.progress_bar, 1)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.summary_label)

        body = QHBoxLayout()
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)

        root = QVBoxLayout()
        root.addLayout(body, 1)
        root.addLayout(bottom)

        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

    def closeEvent(self, event) -> None:
        for index in range(self.stack.count()):
            page = self.stack.widget(index)
            cancel = getattr(page, "_cancel_thumbs", None)
            if callable(cancel):
                cancel()
        if self._thread is not None:
            self.cancel_event.set()
            self._thread.quit()
            self._thread.wait(30_000)
        super().closeEvent(event)

    def job_busy(self) -> bool:
        return self._thread is not None or bool(self._job_queue)

    def _sync_page_actions(self) -> None:
        for index in range(self.stack.count()):
            page = self.stack.widget(index)
            sync = getattr(page, "sync_action_buttons", None)
            if callable(sync):
                sync()

    def start_job(self, fn: Callable[[], Any], on_done: Callable[[Any], None] | None = None) -> None:
        if self._thread is not None:
            self._job_queue.append((fn, on_done))
            return
        self._on_done = on_done
        self.cancel_event = threading.Event()
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.summary_label.setText("正在执行…")

        thread = QThread(self)
        worker = JobWorker(fn, self.cancel_event)
        worker.moveToThread(thread)
        thread.started.connect(worker.run_job)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_job_finished)
        worker.failed.connect(self._on_job_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._clear_job)
        self._thread = thread
        self._worker = worker
        thread.start()
        self._sync_page_actions()

    def _on_cancel(self) -> None:
        self.cancel_event.set()

    def _on_progress(self, value: int, message: str) -> None:
        self.progress_bar.setValue(value)
        self.summary_label.setText(message)

    def _on_job_finished(self, result: Any) -> None:
        self._finish_job_ui()
        if self._on_done is not None:
            self._on_done(result)

    def _on_job_failed(self, message: str) -> None:
        self._finish_job_ui()
        self.summary_label.setText(message)

    def _finish_job_ui(self) -> None:
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(100)

    def _clear_job(self) -> None:
        sender = self.sender()
        if sender is not None and sender is not self._thread:
            return
        self._thread = None
        self._worker = None
        if self._job_queue:
            fn, on_done = self._job_queue.pop(0)
            QTimer.singleShot(0, lambda: self.start_job(fn, on_done))
            return
        self._sync_page_actions()
