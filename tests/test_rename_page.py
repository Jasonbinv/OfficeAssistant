import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path
from unittest.mock import patch

from office_assistant.qt_preload import preload_pyside6

preload_pyside6()

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
)

from office_assistant.rename_ops import ExecuteResult
from office_assistant.ui.main_window import MainWindow
from office_assistant.ui.rename_page import RenamePage


def _app():
    return QApplication.instance() or QApplication([])


def _touch(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_bytes(b"x")
    return path


def _page(win: MainWindow) -> RenamePage:
    page = win.stack.widget(2)
    assert isinstance(page, RenamePage)
    return page


def _button(parent, text: str) -> QPushButton:
    return next(btn for btn in parent.findChildren(QPushButton) if btn.text() == text)


def _checkbox(parent, text: str) -> QCheckBox:
    return next(box for box in parent.findChildren(QCheckBox) if box.text() == text)


def _radio(parent, text: str) -> QRadioButton:
    return next(box for box in parent.findChildren(QRadioButton) if box.text() == text)


def _wait_until(predicate, timeout_s: float = 5.0) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for condition")


def _load_dir(page: RenamePage, directory: Path) -> None:
    page.dir_edit.setText(str(directory))
    page.refresh_files()


def test_rename_page_defaults_and_main_window_stack():
    app = _app()
    win = MainWindow()
    page = _page(win)

    assert _checkbox(page, "pdf").isChecked() is True
    for ext in ("dwg", "dxf", "jpg", "jpeg", "png", "tif", "tiff", "doc", "docx", "xls", "xlsx"):
        assert _checkbox(page, ext).isChecked() is False

    assert page.template_edit.text() == "{原名}_{序号}"
    assert _checkbox(page, "复制保留原件").isChecked() is False
    assert _button(page, "确认重命名").isEnabled() is False
    assert _button(page, "撤销上次重命名").isEnabled() is False
    assert _radio(page, "名单改名").isChecked() is True
    assert isinstance(page.findChild(QPlainTextEdit), QPlainTextEdit)
    assert page.findChild(QTableWidget).columnCount() == 3
    _ = app


def test_list_preview_enables_confirm_and_colors(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    _touch(tmp_path, "扫描1.pdf")
    _touch(tmp_path, "扫描2.pdf")
    _load_dir(page, tmp_path)

    table = page.findChild(QTableWidget)
    assert table.rowCount() == 2
    assert table.item(0, 1).text() == "扫描1.pdf"

    page.name_edit.setPlainText("水施-01_封皮\n水施-01_图纸目录\n")
    assert table.item(0, 2).text() == "水施-01_封皮.pdf"
    assert table.item(1, 2).text() == "水施-01_图纸目录.pdf"
    assert table.item(0, 2).foreground().color().name() == "#0b6e4f"
    assert _button(page, "确认重命名").isEnabled() is True
    _ = app


def test_missing_line_and_unused_names(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    _touch(tmp_path, "扫描1.pdf")
    _touch(tmp_path, "扫描2.pdf")
    _load_dir(page, tmp_path)

    page.name_edit.setPlainText("水施-01_封皮")
    table = page.findChild(QTableWidget)
    assert "名单缺一行" in table.item(1, 2).text()
    assert table.item(1, 2).foreground().color().name() == "#c0392b"
    assert _button(page, "确认重命名").isEnabled() is True

    page.name_edit.setPlainText("水施-01_封皮\n水施-01_图纸目录\n多余一行")
    assert "多余一行" in page.unused_label.text()
    assert page.unused_label.styleSheet() != ""
    assert _button(page, "确认重命名").isEnabled() is True

    page.name_edit.setPlainText("")
    assert _button(page, "确认重命名").isEnabled() is False
    _ = app


def test_template_preview_default(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    _touch(tmp_path, "扫描1.pdf")
    _touch(tmp_path, "扫描2.pdf")
    _load_dir(page, tmp_path)
    _radio(page, "规则改名").click()

    table = page.findChild(QTableWidget)
    assert table.item(0, 2).text() == "扫描1_01.pdf"
    assert table.item(1, 2).text() == "扫描2_02.pdf"
    assert _button(page, "确认重命名").isEnabled() is True
    _ = app


def test_dropped_files_same_directory_selects_only_those(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    a = _touch(tmp_path, "扫描1.pdf")
    _touch(tmp_path, "扫描2.pdf")
    dwg = _touch(tmp_path, "图.dwg")

    page.handle_dropped_paths([a, dwg])
    assert Path(page.dir_edit.text()) == tmp_path
    assert _checkbox(page, "pdf").isChecked() is True
    assert _checkbox(page, "dwg").isChecked() is True

    table = page.findChild(QTableWidget)
    names = {table.item(row, 1).text() for row in range(table.rowCount())}
    assert names == {"扫描1.pdf", "扫描2.pdf", "图.dwg"}
    checked = {
        table.item(row, 1).text(): table.item(row, 0).checkState() == Qt.Checked
        for row in range(table.rowCount())
    }
    assert checked == {"扫描1.pdf": True, "扫描2.pdf": False, "图.dwg": True}
    _ = app


def test_dropped_files_different_directories_warn(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    other = tmp_path / "other"
    other.mkdir()
    a = _touch(tmp_path, "a.pdf")
    b = _touch(other, "b.pdf")
    with patch("office_assistant.ui.rename_page.QMessageBox.warning") as warn:
        page.handle_dropped_paths([a, b])
    warn.assert_called_once()
    assert "同一文件夹" in warn.call_args.args[2]
    assert page.dir_edit.text() == ""
    _ = app


def test_confirm_snapshot_stale_warns_and_does_not_rename(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    first = _touch(tmp_path, "扫描1.pdf")
    _touch(tmp_path, "扫描2.pdf")
    _load_dir(page, tmp_path)
    page.name_edit.setPlainText("水施-01_封皮\n水施-01_图纸目录")
    first.unlink()

    with patch("office_assistant.ui.rename_page.QMessageBox.warning") as warn:
        _button(page, "确认重命名").click()
        _wait_until(lambda: warn.called)

    warn.assert_called()
    assert "文件已变化，请确认后重试" in warn.call_args.args[2]
    assert (tmp_path / "扫描2.pdf").exists()
    assert not (tmp_path / "水施-01_图纸目录.pdf").exists()
    _ = app


def test_execute_and_undo_via_start_job(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    _touch(tmp_path, "扫描1.pdf")
    _touch(tmp_path, "扫描2.pdf")
    _load_dir(page, tmp_path)
    page.name_edit.setPlainText("水施-01_封皮\n水施-01_图纸目录")

    _button(page, "确认重命名").click()
    _wait_until(lambda: "成功 2 个" in win.summary_label.text() and win._thread is None)
    assert (tmp_path / "水施-01_封皮.pdf").exists()
    assert (tmp_path / "水施-01_图纸目录.pdf").exists()
    assert not (tmp_path / "扫描1.pdf").exists()
    assert _button(page, "撤销上次重命名").isEnabled() is True

    _button(page, "撤销上次重命名").click()
    _wait_until(
        lambda: (tmp_path / "扫描1.pdf").exists()
        and win._thread is None
        and "成功" in win.summary_label.text()
    )
    assert (tmp_path / "扫描2.pdf").exists()
    assert not (tmp_path / "水施-01_封皮.pdf").exists()
    _ = app


def test_undo_immediately_when_enabled_after_confirm(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    _touch(tmp_path, "扫描1.pdf")
    _touch(tmp_path, "扫描2.pdf")
    _load_dir(page, tmp_path)
    page.name_edit.setPlainText("水施-01_封皮\n水施-01_图纸目录")

    _button(page, "确认重命名").click()
    _wait_until(lambda: _button(page, "撤销上次重命名").isEnabled())
    _button(page, "撤销上次重命名").click()
    _wait_until(lambda: (tmp_path / "扫描1.pdf").exists() and (tmp_path / "扫描2.pdf").exists())
    assert not (tmp_path / "水施-01_封皮.pdf").exists()
    assert not (tmp_path / "水施-01_图纸目录.pdf").exists()
    _ = app


def test_format_summary_includes_failed_skipped_and_temps_left(tmp_path: Path):
    _app()
    page = RenamePage()
    leftover = tmp_path / ".~$oa$deadbeef.pdf"
    leftover.write_bytes(b"t")
    result = ExecuteResult(
        succeeded=[(tmp_path / "a.pdf", tmp_path / "b.pdf")],
        skipped=["扫描3.pdf（名单缺一行）"],
        failed=["foo.pdf（文件被占用）"],
        temps_left=[leftover],
        copy=False,
    )
    text = page._format_summary(result)
    assert "成功 1 个" in text
    assert "跳过 1 个" in text
    assert "名单缺一行" in text
    assert "失败 1 个" in text
    assert "foo.pdf" in text
    assert leftover.name in text


def test_undo_keeps_residual_batch_when_some_fail(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    _touch(tmp_path, "扫描1.pdf")
    _touch(tmp_path, "扫描2.pdf")
    _load_dir(page, tmp_path)
    page.name_edit.setPlainText("新1\n新2")

    _button(page, "确认重命名").click()
    _wait_until(lambda: (tmp_path / "新1.pdf").exists() and win._thread is None)

    (tmp_path / "扫描1.pdf").write_bytes(b"OCCUPIER")
    _button(page, "撤销上次重命名").click()
    _wait_until(lambda: win._thread is None and "失败" in win.summary_label.text())

    assert (tmp_path / "新1.pdf").exists()
    assert (tmp_path / "扫描2.pdf").exists()
    assert page._last_batch is not None
    assert _button(page, "撤销上次重命名").isEnabled() is True

    (tmp_path / "扫描1.pdf").unlink()
    _button(page, "撤销上次重命名").click()
    _wait_until(lambda: (tmp_path / "扫描1.pdf").exists() and win._thread is None)
    assert not (tmp_path / "新1.pdf").exists()
    assert page._last_batch is None
    _ = app


def test_confirm_ignored_when_job_busy(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    _touch(tmp_path, "扫描1.pdf")
    _load_dir(page, tmp_path)
    page.name_edit.setPlainText("新名")
    with patch.object(page, "_job_busy", return_value=True):
        page._on_confirm()
        app.processEvents()
    _wait_until(lambda: win._thread is None)
    assert (tmp_path / "扫描1.pdf").exists()
    assert not (tmp_path / "新名.pdf").exists()
    _ = app


def test_double_undo_after_confirm_no_failure_summary(tmp_path: Path):
    app = _app()
    win = MainWindow()
    page = _page(win)
    _touch(tmp_path, "扫描1.pdf")
    _touch(tmp_path, "扫描2.pdf")
    _load_dir(page, tmp_path)
    page.name_edit.setPlainText("水施-01_封皮\n水施-01_图纸目录")

    undo = _button(page, "撤销上次重命名")
    _button(page, "确认重命名").click()
    _wait_until(lambda: "成功 2 个" in win.summary_label.text() and win._thread is None)
    undo.click()
    undo.click()
    _wait_until(
        lambda: (tmp_path / "扫描1.pdf").exists()
        and (tmp_path / "扫描2.pdf").exists()
        and win._thread is None
    )
    summary = win.summary_label.text()
    assert "失败 0 个" in summary
    assert (tmp_path / "扫描1.pdf").exists()
    assert (tmp_path / "扫描2.pdf").exists()
    _ = app
