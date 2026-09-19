import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
from office_assistant.tasks.worker import run_callable_job


def test_run_callable_job_success():
    ev = threading.Event()
    result = run_callable_job(lambda: 42, ev)
    assert result == 42


def test_run_callable_job_propagates():
    ev = threading.Event()
    try:
        run_callable_job(lambda: (_ for _ in ()).throw(RuntimeError("失败了")), ev)
        assert False
    except RuntimeError as exc:
        assert "失败了" in str(exc)


def test_run_callable_job_cancelled():
    ev = threading.Event()
    ev.set()
    try:
        run_callable_job(lambda: 42, ev)
        assert False
    except RuntimeError as exc:
        assert "已取消" in str(exc)


def test_job_worker_emits_finished_and_failed():
    from office_assistant.tasks.worker import JobWorker

    finished: list[object] = []
    failed: list[str] = []
    worker = JobWorker(lambda: 7, threading.Event())
    worker.finished.connect(finished.append)
    worker.failed.connect(failed.append)
    worker.run_job()
    assert finished == [7]
    assert failed == []

    worker_fail = JobWorker(lambda: (_ for _ in ()).throw(RuntimeError("失败了")), threading.Event())
    worker_fail.finished.connect(finished.append)
    worker_fail.failed.connect(failed.append)
    worker_fail.run_job()
    assert finished == [7]
    assert failed == ["失败了"]


def test_main_window_shell_without_display():
    from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QProgressBar, QPushButton, QStackedWidget

    from office_assistant.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    assert win.windowTitle() == "办公文件助手"

    nav = win.findChild(QListWidget)
    assert nav is not None
    assert [nav.item(i).text() for i in range(nav.count())] == ["合并 PDF", "删除页面", "重命名"]

    from office_assistant.ui.delete_page import DeletePage
    from office_assistant.ui.merge_page import MergePage
    from office_assistant.ui.rename_page import RenamePage

    stack = win.findChild(QStackedWidget)
    assert stack is not None
    assert stack.count() == 3
    assert isinstance(stack.widget(0), MergePage)
    assert isinstance(stack.widget(1), DeletePage)
    assert isinstance(stack.widget(2), RenamePage)

    cancel = next(btn for btn in win.findChildren(QPushButton) if btn.text() == "取消")
    assert cancel.isEnabled() is False
    assert win.findChild(QProgressBar) is not None
    assert any(isinstance(child, QLabel) and child.text() == "就绪" for child in win.findChildren(QLabel))

    nav.setCurrentRow(1)
    assert stack.currentIndex() == 1
    nav.setCurrentRow(2)
    assert stack.currentIndex() == 2
    _ = app
