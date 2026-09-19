import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from pathlib import Path
from unittest.mock import patch

from office_assistant.qt_preload import preload_pyside6

preload_pyside6()

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
)
from pypdf import PdfReader

from office_assistant.ui.delete_page import DeletePage
from office_assistant.ui.main_window import MainWindow
from tests.conftest import make_blank_pdf


def _app():
    return QApplication.instance() or QApplication([])


def _page(win: MainWindow) -> DeletePage:
    page = win.stack.widget(1)
    assert isinstance(page, DeletePage)
    return page


def _button(parent, text: str) -> QPushButton:
    return next(btn for btn in parent.findChildren(QPushButton) if btn.text() == text)


def _checkbox(parent, text: str) -> QCheckBox:
    return next(box for box in parent.findChildren(QCheckBox) if box.text() == text)


def _wait_until(predicate, timeout_s: float = 5.0) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for condition")


def _checked_pages(thumbs: QListWidget) -> set[int]:
    pages = set()
    for index in range(thumbs.count()):
        item = thumbs.item(index)
        if item.checkState() == Qt.CheckState.Checked:
            pages.add(index + 1)
    return pages


def test_delete_page_defaults_and_main_window_stack():
    app = _app()
    win = MainWindow()
    page = _page(win)
    assert _button(page, "打开") is not None
    assert _button(page, "全选") is not None
    assert _button(page, "反选") is not None
    assert _checkbox(page, "覆盖原文件").isChecked() is False
    assert _button(page, "另存为").isEnabled() is False
    thumbs = page.findChild(QListWidget)
    assert thumbs.viewMode() == QListWidget.ViewMode.IconMode
    _ = app


def test_open_syncs_page_box_and_thumbs(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    src = make_blank_pdf(tmp_path / "图纸.pdf", 4)
    page.open_pdf(src)
    thumbs = page.findChild(QListWidget)
    assert thumbs.count() == 4
    page.pages_edit.setText("1,3")
    page.pages_edit.editingFinished.emit()
    assert page.selected_pages == {1, 3}
    assert _checked_pages(thumbs) == {1, 3}
    assert _button(page, "另存为").isEnabled() is True

    thumbs.item(1).setCheckState(Qt.CheckState.Checked)
    assert page.selected_pages == {1, 2, 3}
    assert page.pages_edit.text() == "1-3"
    _ = app


def test_invalid_ranges_shown_not_checked(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    page.open_pdf(make_blank_pdf(tmp_path / "src.pdf", 3))
    page.pages_edit.setText("1,99,x")
    page.pages_edit.editingFinished.emit()
    assert "无效" in page.error_label.text()
    assert page.selected_pages == {1}
    assert _checked_pages(page.findChild(QListWidget)) == {1}
    _ = app


def test_select_all_and_invert(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    page.open_pdf(make_blank_pdf(tmp_path / "src.pdf", 4))
    page.pages_edit.setText("1,3")
    page.pages_edit.editingFinished.emit()
    _button(page, "反选").click()
    assert page.selected_pages == {2, 4}
    assert page.pages_edit.text() == "2,4"
    _button(page, "全选").click()
    assert page.selected_pages == {1, 2, 3, 4}
    assert _button(page, "另存为").isEnabled() is False
    _ = app


def test_execute_disabled_when_none_or_all(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    assert _button(page, "另存为").isEnabled() is False
    page.open_pdf(make_blank_pdf(tmp_path / "src.pdf", 2))
    assert _button(page, "另存为").isEnabled() is False
    page.pages_edit.setText("1")
    page.pages_edit.editingFinished.emit()
    assert _button(page, "另存为").isEnabled() is True
    page.pages_edit.setText("1,2")
    page.pages_edit.editingFinished.emit()
    assert _button(page, "另存为").isEnabled() is False
    _ = app


def test_multi_drop_uses_first_and_warns(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    first = make_blank_pdf(tmp_path / "first.pdf", 2)
    second = make_blank_pdf(tmp_path / "second.pdf", 5)
    with patch("office_assistant.ui.delete_page.QMessageBox.warning") as warn:
        page.handle_dropped_paths([first, second])
    warn.assert_called_once()
    assert page.findChild(QListWidget).count() == 2
    _ = app


def test_save_as_via_start_job(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    src = make_blank_pdf(tmp_path / "源文件.pdf", 4)
    page.open_pdf(src)
    page.pages_edit.setText("1,3")
    page.pages_edit.editingFinished.emit()
    dest = tmp_path / "源文件_删页.pdf"
    captured: dict[str, str] = {}

    def fake_save(parent, title, start, filt="", **kwargs):
        captured["start"] = start
        return str(dest), "PDF (*.pdf)"

    with patch("office_assistant.ui.delete_page.QFileDialog.getSaveFileName", side_effect=fake_save):
        _button(page, "另存为").click()
        _wait_until(lambda: dest.exists() and win._thread is None)

    assert Path(captured["start"]) == dest
    assert len(PdfReader(dest).pages) == 2
    assert src.exists()
    assert len(PdfReader(src).pages) == 4
    _ = app


def test_overwrite_confirm_and_locked(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    src = make_blank_pdf(tmp_path / "src.pdf", 3)
    page.open_pdf(src)
    page.pages_edit.setText("2")
    page.pages_edit.editingFinished.emit()
    _checkbox(page, "覆盖原文件").setChecked(True)

    with (
        patch("office_assistant.ui.delete_page.is_locked", return_value=True),
        patch("office_assistant.ui.delete_page.QMessageBox.warning") as warn,
        patch(
            "office_assistant.ui.delete_page.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
    ):
        _button(page, "另存为").click()
        app.processEvents()
    warn.assert_called()
    assert "关闭" in warn.call_args.args[2]
    assert len(PdfReader(src).pages) == 3

    with (
        patch("office_assistant.ui.delete_page.is_locked", return_value=False),
        patch(
            "office_assistant.ui.delete_page.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
    ):
        _button(page, "另存为").click()
        _wait_until(lambda: win._thread is None and len(PdfReader(src).pages) == 2)
    assert len(PdfReader(src).pages) == 2
    _ = app


def test_inplace_delete_cancel_no_success_summary(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    src = make_blank_pdf(tmp_path / "src.pdf", 3)
    original = src.read_bytes()
    page.open_pdf(src)
    page.pages_edit.setText("2")
    page.pages_edit.editingFinished.emit()
    _checkbox(page, "覆盖原文件").setChecked(True)
    ev = threading.Event()
    ev.set()
    with (
        patch.object(page, "_cancel_event", return_value=ev),
        patch("office_assistant.ui.delete_page.is_locked", return_value=False),
        patch(
            "office_assistant.ui.delete_page.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
    ):
        _button(page, "另存为").click()
        _wait_until(lambda: win._thread is None)
    assert src.read_bytes() == original
    summary = win.summary_label.text()
    assert "已保存" not in summary
    assert "已合并" not in summary
    _ = app


def test_delete_unique_dest_not_source(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    src = make_blank_pdf(tmp_path / "src.pdf", 4)
    page.open_pdf(src)
    page.pages_edit.setText("1")
    page.pages_edit.editingFinished.emit()
    dest = tmp_path / "out.pdf"
    dest.write_bytes(b"old")
    with (
        patch("office_assistant.ui.delete_page.QFileDialog.getSaveFileName", return_value=(str(dest), "")),
        patch("office_assistant.ui.delete_page.ask_existing_dest", return_value=src),
        patch("office_assistant.ui.delete_page.QMessageBox.warning") as warn,
        patch("office_assistant.ui.delete_page.QMessageBox.question") as question,
    ):
        _button(page, "另存为").click()
        _wait_until(lambda: win._thread is None)
    assert len(PdfReader(src).pages) == 4
    if question.called:
        return
    if warn.called:
        assert "已保存" not in win.summary_label.text()
        return
    summary = win.summary_label.text()
    assert summary.startswith("已保存到")
    saved_name = summary.split("到 ", 1)[-1]
    assert saved_name != src.name
    _ = app


def test_overwrite_cancels_thumbs_before_is_locked(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    src = make_blank_pdf(tmp_path / "src.pdf", 3)
    page.open_pdf(src)
    page.pages_edit.setText("2")
    page.pages_edit.editingFinished.emit()
    _checkbox(page, "覆盖原文件").setChecked(True)
    order: list[str] = []
    original_cancel = page._cancel_thumbs

    def cancel_and_record() -> None:
        order.append("cancel")
        original_cancel()

    def locked(_path: Path) -> bool:
        order.append("locked")
        return True

    with (
        patch.object(page, "_cancel_thumbs", side_effect=cancel_and_record),
        patch("office_assistant.ui.delete_page.is_locked", side_effect=locked),
        patch(
            "office_assistant.ui.delete_page.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch("office_assistant.ui.delete_page.QMessageBox.warning"),
    ):
        _button(page, "另存为").click()
        app.processEvents()
    assert "cancel" in order
    assert "locked" in order
    assert order.index("cancel") < order.index("locked")
    _ = app


def test_queue_visible_thumbs_skipped_while_overwrite_or_job(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    src = make_blank_pdf(tmp_path / "src.pdf", 3)
    page.open_pdf(src)
    page._rendered.clear()
    with (
        patch.object(page, "isVisible", return_value=True),
        patch.object(page, "_visible_indexes", return_value=[0, 1]),
        patch.object(page, "_start_thumb_worker") as start,
    ):
        with patch.object(page, "_job_busy", return_value=True):
            page._queue_visible_thumbs()
        start.assert_not_called()
        page._thumbs_paused = True
        with patch.object(page, "_job_busy", return_value=False):
            page._queue_visible_thumbs()
        start.assert_not_called()
    _ = app


def test_delete_save_dialog_dont_confirm_overwrite(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    src = make_blank_pdf(tmp_path / "src.pdf", 3)
    page.open_pdf(src)
    page.pages_edit.setText("1")
    page.pages_edit.editingFinished.emit()
    with patch(
        "office_assistant.ui.delete_page.QFileDialog.getSaveFileName",
        return_value=("", ""),
    ) as mock_save:
        _button(page, "另存为").click()
        app.processEvents()
    mock_save.assert_called_once()
    options = mock_save.call_args.kwargs.get("options")
    assert options is not None
    assert options & QFileDialog.Option.DontConfirmOverwrite
    _ = app


def test_thumbnail_ready_runs_on_gui_thread(tmp_path: Path):
    app = _app()
    gui_thread = QThread.currentThread()
    win = MainWindow()
    page = _page(win)
    seen: list[QThread] = []
    original_set_icon = QListWidgetItem.setIcon

    def set_icon(self, icon):
        seen.append(QThread.currentThread())
        return original_set_icon(self, icon)

    src = make_blank_pdf(tmp_path / "src.pdf", 2)
    page.open_pdf(src)
    with (
        patch.object(QListWidgetItem, "setIcon", set_icon),
        patch.object(page, "isVisible", return_value=True),
        patch.object(page, "_visible_indexes", return_value=[0, 1]),
    ):
        page._queue_visible_thumbs()
        _wait_until(lambda: len(seen) >= 1, timeout_s=8)
    assert seen[0] is gui_thread
    page._cancel_thumbs()
    win.close()
    app.processEvents()
    _ = app


def test_close_window_while_thumbs_rendering(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    src = make_blank_pdf(tmp_path / "src.pdf", 3)
    page.open_pdf(src)
    with (
        patch.object(page, "isVisible", return_value=True),
        patch.object(page, "_visible_indexes", return_value=[0, 1, 2]),
    ):
        page._queue_visible_thumbs()
        app.processEvents()
        win.close()
        app.processEvents()
    assert win._thread is None
    _ = app
