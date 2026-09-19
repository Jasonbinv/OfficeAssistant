import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path
from unittest.mock import patch

from office_assistant.qt_preload import preload_pyside6

preload_pyside6()

from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QTableWidget
from pypdf import PdfReader, PdfWriter

from office_assistant.naming import unique_path
from office_assistant.ui.main_window import MainWindow
from office_assistant.ui.merge_page import MergePage
from tests.conftest import make_blank_pdf


def _app():
    return QApplication.instance() or QApplication([])


def _page(win: MainWindow) -> MergePage:
    page = win.stack.widget(0)
    assert isinstance(page, MergePage)
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


def _status(table: QTableWidget, row: int) -> str:
    return table.item(row, 1).text()


def _names(table: QTableWidget) -> list[str]:
    return [table.item(row, 0).text() for row in range(table.rowCount())]


def make_user_encrypted_pdf(path: Path, pages: int, password: str) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password=password)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_merge_page_defaults_and_main_window_stack():
    app = _app()
    win = MainWindow()
    page = _page(win)
    assert _button(page, "添加文件") is not None
    assert _button(page, "移除") is not None
    assert _button(page, "上移") is not None
    assert _button(page, "下移") is not None
    assert _button(page, "清空") is not None
    assert _checkbox(page, "合并其余完好文件").isChecked() is False
    assert _button(page, "开始合并").isEnabled() is False
    table = page.findChild(QTableWidget)
    assert table.columnCount() == 2
    _ = app


def test_two_good_pdfs_enable_start(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    a = make_blank_pdf(tmp_path / "a.pdf", 2)
    b = make_blank_pdf(tmp_path / "b.pdf", 3)
    page.add_paths([a])
    assert _button(page, "开始合并").isEnabled() is False
    page.add_paths([b])
    table = page.findChild(QTableWidget)
    assert table.rowCount() == 2
    assert _status(table, 0) == "完好"
    assert _status(table, 1) == "完好"
    assert _button(page, "开始合并").isEnabled() is True
    _ = app


def test_duplicate_paths_rejected(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    a = make_blank_pdf(tmp_path / "a.pdf", 1)
    page.add_paths([a, a])
    assert page.findChild(QTableWidget).rowCount() == 1
    _ = app


def test_bad_file_blocks_start_until_skip_remaining(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    a = make_blank_pdf(tmp_path / "a.pdf", 1)
    b = make_blank_pdf(tmp_path / "b.pdf", 1)
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not-a-pdf")
    page.add_paths([a, b, bad])
    table = page.findChild(QTableWidget)
    assert any(_status(table, row) == "损坏" for row in range(table.rowCount()))
    assert _button(page, "开始合并").isEnabled() is False
    _checkbox(page, "合并其余完好文件").setChecked(True)
    assert _button(page, "开始合并").isEnabled() is True
    _checkbox(page, "合并其余完好文件").setChecked(False)
    assert _button(page, "开始合并").isEnabled() is False
    _ = app


def test_non_pdf_and_folder_drop_non_recursive(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    folder = tmp_path / "docs"
    nested = folder / "sub"
    nested.mkdir(parents=True)
    make_blank_pdf(folder / "top.pdf", 1)
    make_blank_pdf(nested / "nested.pdf", 1)
    txt = tmp_path / "note.txt"
    txt.write_text("x", encoding="utf-8")
    page.handle_dropped_paths([folder, txt])
    table = page.findChild(QTableWidget)
    names = set(_names(table))
    assert "top.pdf" in names
    assert "nested.pdf" not in names
    assert "note.txt" in names
    assert any(_status(table, row) == "非 PDF" for row in range(table.rowCount()))
    assert _button(page, "开始合并").isEnabled() is False
    _ = app


def test_password_row_prompt_unlocks(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    encrypted = make_user_encrypted_pdf(tmp_path / "secret.pdf", 1, "pw")
    good = make_blank_pdf(tmp_path / "ok.pdf", 1)
    page.add_paths([encrypted, good])
    table = page.findChild(QTableWidget)
    assert _status(table, 0) == "需要密码"
    assert _button(page, "开始合并").isEnabled() is False
    with patch("office_assistant.ui.merge_page.QInputDialog.getText", return_value=("pw", True)):
        page.prompt_password_for_row(0)
    assert _status(table, 0) == "完好"
    assert _button(page, "开始合并").isEnabled() is True
    _ = app


def test_remove_up_down_clear(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    a = make_blank_pdf(tmp_path / "a.pdf", 1)
    b = make_blank_pdf(tmp_path / "b.pdf", 1)
    c = make_blank_pdf(tmp_path / "c.pdf", 1)
    page.add_paths([a, b, c])
    table = page.findChild(QTableWidget)
    table.selectRow(1)
    _button(page, "上移").click()
    assert _names(table) == ["b.pdf", "a.pdf", "c.pdf"]
    table.selectRow(0)
    _button(page, "下移").click()
    assert _names(table) == ["a.pdf", "b.pdf", "c.pdf"]
    table.selectRow(2)
    _button(page, "移除").click()
    assert _names(table) == ["a.pdf", "b.pdf"]
    _button(page, "清空").click()
    assert table.rowCount() == 0
    assert _button(page, "开始合并").isEnabled() is False
    _ = app


def test_merge_via_start_job_and_default_save_name(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    a = make_blank_pdf(tmp_path / "合同.pdf", 2)
    b = make_blank_pdf(tmp_path / "附图.pdf", 3)
    page.add_paths([a, b])
    dest = tmp_path / "合同_合并.pdf"
    captured: dict[str, str] = {}

    def fake_save(parent, title, start, filt=""):
        captured["start"] = start
        return str(dest), "PDF (*.pdf)"

    with patch("office_assistant.ui.merge_page.QFileDialog.getSaveFileName", side_effect=fake_save):
        _button(page, "开始合并").click()
        _wait_until(lambda: dest.exists() and win._thread is None)

    assert Path(captured["start"]) == dest
    assert len(PdfReader(dest).pages) == 5
    assert a.exists() and b.exists()
    _ = app


def test_dest_equals_source_warns(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    a = make_blank_pdf(tmp_path / "a.pdf", 1)
    b = make_blank_pdf(tmp_path / "b.pdf", 1)
    page.add_paths([a, b])
    with (
        patch("office_assistant.ui.merge_page.QFileDialog.getSaveFileName", return_value=(str(a), "")),
        patch("office_assistant.ui.merge_page.QMessageBox.warning") as warn,
    ):
        _button(page, "开始合并").click()
        app.processEvents()
    warn.assert_called()
    assert "源" in warn.call_args.args[2]
    _ = app


def test_dest_exists_unique_overwrite_cancel(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    a = make_blank_pdf(tmp_path / "a.pdf", 1)
    b = make_blank_pdf(tmp_path / "b.pdf", 1)
    page.add_paths([a, b])
    dest = tmp_path / "out.pdf"
    dest.write_bytes(b"old")

    with (
        patch("office_assistant.ui.merge_page.QFileDialog.getSaveFileName", return_value=(str(dest), "")),
        patch("office_assistant.ui.merge_page.ask_existing_dest", return_value=None),
    ):
        _button(page, "开始合并").click()
        app.processEvents()
    assert dest.read_bytes() == b"old"

    unique = unique_path(dest)
    with (
        patch("office_assistant.ui.merge_page.QFileDialog.getSaveFileName", return_value=(str(dest), "")),
        patch("office_assistant.ui.merge_page.ask_existing_dest", return_value=unique),
    ):
        _button(page, "开始合并").click()
        _wait_until(lambda: unique.exists() and win._thread is None)
    assert dest.read_bytes() == b"old"
    assert len(PdfReader(unique).pages) == 2

    page.add_paths([a, b]) if page.findChild(QTableWidget).rowCount() == 0 else None
    with (
        patch("office_assistant.ui.merge_page.QFileDialog.getSaveFileName", return_value=(str(dest), "")),
        patch("office_assistant.ui.merge_page.ask_existing_dest", return_value=dest),
    ):
        _button(page, "开始合并").click()
        _wait_until(lambda: dest.stat().st_size != 3 and win._thread is None)
    assert len(PdfReader(dest).pages) == 2
    _ = app
