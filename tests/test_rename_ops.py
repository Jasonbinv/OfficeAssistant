from pathlib import Path
from unittest.mock import patch

from office_assistant.rename_ops import (
    _is_hidden_windows,
    list_directory_files,
    preview_list_rename,
    preview_template_rename,
)

def _touch(dir: Path, name: str) -> Path:
    path = dir / name
    path.write_bytes(b"x")
    return path


def test_is_hidden_windows_invalid_attributes_not_hidden(tmp_path: Path):
    path = _touch(tmp_path, "normal.pdf")
    with patch(
        "office_assistant.rename_ops._GetFileAttributesW",
        return_value=0xFFFFFFFF,
    ):
        assert _is_hidden_windows(path) is False


def test_list_directory_includes_file_when_attributes_unreadable(tmp_path: Path):
    _touch(tmp_path, "readable.pdf")
    with patch(
        "office_assistant.rename_ops._GetFileAttributesW",
        return_value=0xFFFFFFFF,
    ):
        files = list_directory_files(tmp_path, {"pdf"})
    assert [p.name for p in files] == ["readable.pdf"]


def test_preview_mismatched_lengths_raises():
    path = Path("x.pdf")
    try:
        preview_list_rename([path], [True, True], ["a"], copy=False)
    except ValueError as exc:
        assert "same length" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_list_directory_skips_hidden_and_desktop_ini(tmp_path: Path):
    _touch(tmp_path, "a.pdf")
    _touch(tmp_path, "desktop.ini")
    _touch(tmp_path, ".hidden.pdf")
    files = list_directory_files(tmp_path, {"pdf"})
    assert [p.name for p in files] == ["a.pdf"]


def test_preview_maps_checked_files_in_order(tmp_path: Path):
    f1 = _touch(tmp_path, "扫描1.pdf")
    f2 = _touch(tmp_path, "扫描2.pdf")
    f3 = _touch(tmp_path, "扫描3.pdf")
    result = preview_list_rename(
        [f1, f2, f3],
        [True, True, True],
        ["水施-01_封皮", "水施-01_图纸目录"],
        copy=False,
    )
    assert result.rows[0].new_name == "水施-01_封皮.pdf"
    assert result.rows[0].status == "ok"
    assert result.rows[2].status == "missing_line"
    assert result.unused_names == []


def test_preview_extra_names_listed(tmp_path: Path):
    f1 = _touch(tmp_path, "扫描1.pdf")
    result = preview_list_rename(
        [f1], [True], ["a", "b"], copy=False
    )
    assert result.unused_names == ["b"]
    assert result.rows[0].new_name == "a.pdf"


def test_preview_collision_and_unchanged(tmp_path: Path):
    keep = _touch(tmp_path, "已存在.pdf")
    src = _touch(tmp_path, "扫描1.pdf")
    same = _touch(tmp_path, "老.pdf")
    result = preview_list_rename(
        [src, same, keep],
        [True, True, False],
        ["已存在", "老"],
        copy=False,
    )
    assert result.rows[0].status == "collision"
    assert result.rows[1].status == "unchanged"


def test_copy_mode_does_not_vacate_old_name(tmp_path: Path):
    a = _touch(tmp_path, "a.pdf")
    b = _touch(tmp_path, "b.pdf")
    result = preview_list_rename([a, b], [True, True], ["b", "c"], copy=True)
    assert result.rows[0].status == "collision"
    inplace = preview_list_rename([a, b], [True, True], ["b", "a"], copy=False)
    assert inplace.rows[0].status == "ok"
    assert inplace.rows[1].status == "ok"


def test_duplicate_targets_are_invalid(tmp_path: Path):
    a = _touch(tmp_path, "a.pdf")
    b = _touch(tmp_path, "b.pdf")
    result = preview_list_rename([a, b], [True, True], ["同名", "同名"], copy=False)
    assert result.rows[0].status == "collision"
    assert result.rows[1].status == "collision"


def test_template_preview(tmp_path: Path):
    a = _touch(tmp_path, "扫描.pdf")
    result = preview_template_rename(
        [a],
        [True],
        template="{原名}_{序号}",
        prefix="",
        suffix="",
        copy=False,
        date="20260919",
    )
    assert result.rows[0].new_name == "扫描_01.pdf"
    assert result.rows[0].status == "ok"
