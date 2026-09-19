import shutil
import threading
from pathlib import Path
from unittest.mock import patch

from office_assistant.rename_ops import (
    _is_hidden_windows,
    execute_renames,
    list_directory_files,
    preview_list_rename,
    preview_template_rename,
    snapshot_ok,
    undo_renames,
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


def test_execute_inplace_swap(tmp_path: Path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    preview = preview_list_rename([a, b], [True, True], ["b", "a"], copy=False)
    assert snapshot_ok(preview)
    execute_renames(preview.rows, copy=False)
    assert (tmp_path / "a.pdf").read_bytes() == b"B"
    assert (tmp_path / "b.pdf").read_bytes() == b"A"


def test_execute_copy_keeps_original(tmp_path: Path):
    a = _touch(tmp_path, "a.pdf")
    a.write_bytes(b"A")
    preview = preview_list_rename([a], [True], ["新名"], copy=True)
    result = execute_renames(preview.rows, copy=True)
    assert (tmp_path / "a.pdf").read_bytes() == b"A"
    assert (tmp_path / "新名.pdf").read_bytes() == b"A"
    undone = undo_renames(result)
    assert not (tmp_path / "新名.pdf").exists()
    assert (tmp_path / "a.pdf").exists()


def test_snapshot_ok_false_when_file_disappears(tmp_path: Path):
    a = _touch(tmp_path, "a.pdf")
    preview = preview_list_rename([a], [True], ["b"], copy=False)
    a.unlink()
    assert snapshot_ok(preview) is False


def test_case_only_rename(tmp_path: Path):
    a = _touch(tmp_path, "Abc.pdf")
    preview = preview_list_rename([a], [True], ["abc"], copy=False)
    assert preview.rows[0].status == "ok"
    execute_renames(preview.rows, copy=False)
    remaining = list(tmp_path.iterdir())
    assert remaining[0].name == "abc.pdf"


def test_cancel_stops_remaining(tmp_path: Path):
    files = [_touch(tmp_path, f"{i}.pdf") for i in range(5)]
    names = [f"n{i}" for i in range(5)]
    preview = preview_list_rename(files, [True] * 5, names, copy=False)
    ev = threading.Event()
    ev.set()
    result = execute_renames(preview.rows, copy=False, cancel_event=ev)
    assert len(result.succeeded) == 0


def test_group_rename_refuses_occupied_dest_created_after_preview(tmp_path: Path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"AAA-ORIGINAL")
    b.write_bytes(b"BBB-ORIGINAL")
    preview = preview_list_rename([a, b], [True, True], ["b", "c"], copy=False)
    assert preview.rows[0].status == "ok"
    assert preview.rows[1].status == "ok"
    occupant = tmp_path / "c.pdf"
    occupant.write_bytes(b"OCCUPANT-UNIQUE")
    result = execute_renames(preview.rows, copy=False)
    assert occupant.read_bytes() == b"OCCUPANT-UNIQUE"
    assert result.failed
    originals = {b"AAA-ORIGINAL", b"BBB-ORIGINAL"}
    if result.temps_left:
        leftover = {path.read_bytes() for path in result.temps_left if path.exists()}
        assert leftover <= originals
    restored = []
    for name in ("a.pdf", "b.pdf"):
        path = tmp_path / name
        if path.exists():
            restored.append(path.read_bytes())
    assert set(restored) | (
        {path.read_bytes() for path in result.temps_left if path.exists()}
    ) == originals


def test_three_file_chain_rollback_preserves_all_originals(tmp_path: Path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    c = tmp_path / "c.pdf"
    a.write_bytes(b"AAA")
    b.write_bytes(b"BBB")
    c.write_bytes(b"CCC")
    preview = preview_list_rename(
        [a, b, c],
        [True, True, True],
        ["b", "c", "d"],
        copy=False,
    )
    assert [row.status for row in preview.rows] == ["ok", "ok", "ok"]
    occupant = tmp_path / "d.pdf"
    occupant.write_bytes(b"OCCUPANT-UNIQUE")
    result = execute_renames(preview.rows, copy=False)
    assert occupant.read_bytes() == b"OCCUPANT-UNIQUE"
    assert result.failed
    originals = {b"AAA", b"BBB", b"CCC"}
    survivors: set[bytes] = set()
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        path = tmp_path / name
        if path.exists() and path.resolve() != occupant.resolve():
            survivors.add(path.read_bytes())
    for path in result.temps_left:
        if path.exists():
            survivors.add(path.read_bytes())
    assert survivors == originals


def test_snapshot_ok_empty_template_is_rule_mode(tmp_path: Path):
    src = tmp_path / "scan.pdf"
    src.write_bytes(b"KEEP")
    preview = preview_template_rename(
        [src],
        [True],
        template="",
        prefix="pre_",
        suffix="",
        copy=False,
        date="20260919",
    )
    assert preview.template == ""
    assert snapshot_ok(preview) is True
    assert src.read_bytes() == b"KEEP"
    assert src.exists()


def test_copy_cancel_keeps_completed_copy(tmp_path: Path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    preview = preview_list_rename([a, b], [True, True], ["a-copy", "b-copy"], copy=True)
    ev = threading.Event()
    real_copy2 = shutil.copy2

    def copy_then_cancel(src, dest, *args, **kwargs):
        real_copy2(src, dest, *args, **kwargs)
        ev.set()

    with patch("office_assistant.rename_ops.shutil.copy2", side_effect=copy_then_cancel):
        result = execute_renames(preview.rows, copy=True, cancel_event=ev)
    copied = tmp_path / "a-copy.pdf"
    assert copied.exists()
    assert copied.read_bytes() == b"A"
    assert not (tmp_path / "b-copy.pdf").exists()
    assert len(result.succeeded) == 1
