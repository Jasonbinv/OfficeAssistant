from pathlib import Path
from office_assistant.fs_ops import is_locked, remove_incomplete, replace_file


def test_remove_incomplete_missing_ok(tmp_path: Path):
    remove_incomplete(tmp_path / "nope.pdf")


def test_replace_file(tmp_path: Path):
    dest = tmp_path / "a.pdf"
    dest.write_bytes(b"old")
    temp = tmp_path / "t.pdf"
    temp.write_bytes(b"new")
    replace_file(temp, dest)
    assert dest.read_bytes() == b"new"
    assert not temp.exists()


def test_unlocked_file_is_not_locked(tmp_path: Path):
    p = tmp_path / "a.pdf"
    p.write_bytes(b"x")
    assert is_locked(p) is False
