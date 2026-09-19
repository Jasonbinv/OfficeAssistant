from __future__ import annotations

import ctypes
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from office_assistant.naming import (
    apply_template,
    build_new_filename,
    index_width,
    is_reserved_device_name,
    natural_sort_key,
    today_yyyymmdd,
)

SKIP_FILES = {"desktop.ini", "thumbs.db"}
TEMP_PREFIX = ".~$oa$"

_FILE_ATTRIBUTE_HIDDEN = 0x2
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

STATUS_OK = "ok"
STATUS_MISSING_LINE = "missing_line"
STATUS_INVALID = "invalid"
STATUS_COLLISION = "collision"
STATUS_UNCHANGED = "unchanged"
STATUS_UNCHECKED = "unchecked"


@dataclass
class RenameRow:
    path: Path
    checked: bool
    old_name: str
    new_name: str
    status: str
    message: str


@dataclass
class PreviewResult:
    rows: list[RenameRow]
    unused_names: list[str]
    source_names: list[str]
    copy: bool
    files: list[Path]
    checked: list[bool]
    template: str | None = None
    prefix: str = ""
    suffix: str = ""
    date: str = ""


def _is_hidden_windows(path: Path) -> bool:
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    except Exception:
        return False
    if attrs == _INVALID_FILE_ATTRIBUTES:
        return False
    return bool(attrs & _FILE_ATTRIBUTE_HIDDEN)


def _skip_file(path: Path) -> bool:
    name = path.name
    if name.casefold() in {item.casefold() for item in SKIP_FILES}:
        return True
    if name.startswith("."):
        return True
    return _is_hidden_windows(path)


def _extension_key(value: str) -> str:
    return value.lstrip(".").casefold()


def list_directory_files(directory: Path, extensions: set[str]) -> list[Path]:
    wanted = {_extension_key(ext) for ext in extensions}
    found: list[Path] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        if _skip_file(path):
            continue
        if _extension_key(path.suffix) not in wanted:
            continue
        found.append(path)
    found.sort(key=lambda p: natural_sort_key(p.name))
    return found


def _empty_stem(new_name: str, suffix: str) -> bool:
    if not new_name:
        return True
    if suffix and new_name.casefold() == suffix.casefold():
        return True
    stem = Path(new_name).stem
    return not stem


def _classify_new_name(path: Path, new_name: str) -> RenameRow:
    if _empty_stem(new_name, path.suffix) or is_reserved_device_name(Path(new_name).stem):
        if _empty_stem(new_name, path.suffix):
            message = "新主名为空，无法改名"
        else:
            message = "该名称是 Windows 保留设备名"
        return RenameRow(
            path=path,
            checked=True,
            old_name=path.name,
            new_name=new_name,
            status=STATUS_INVALID,
            message=message,
        )
    if new_name == path.name:
        return RenameRow(
            path=path,
            checked=True,
            old_name=path.name,
            new_name=new_name,
            status=STATUS_UNCHANGED,
            message="无需改名",
        )
    return RenameRow(
        path=path,
        checked=True,
        old_name=path.name,
        new_name=new_name,
        status=STATUS_OK,
        message="",
    )


def _unchecked_row(path: Path) -> RenameRow:
    return RenameRow(
        path=path,
        checked=False,
        old_name=path.name,
        new_name="",
        status=STATUS_UNCHECKED,
        message="",
    )


def _missing_line_row(path: Path) -> RenameRow:
    return RenameRow(
        path=path,
        checked=True,
        old_name=path.name,
        new_name="",
        status=STATUS_MISSING_LINE,
        message="（名单缺一行）",
    )


def _directory_names(directory: Path) -> set[str]:
    try:
        return {child.name.casefold() for child in directory.iterdir()}
    except OSError:
        return set()


def _apply_collisions(rows: list[RenameRow], *, copy: bool) -> None:
    green = [row for row in rows if row.status == STATUS_OK]
    target_counts: dict[str, int] = defaultdict(int)
    for row in green:
        target_counts[row.new_name.casefold()] += 1
    for row in green:
        if target_counts[row.new_name.casefold()] > 1:
            row.status = STATUS_COLLISION
            row.message = "目标文件名已被占用"

    occupied_by_dir: dict[Path, set[str]] = {}

    def occupied(directory: Path) -> set[str]:
        cached = occupied_by_dir.get(directory)
        if cached is None:
            cached = _directory_names(directory)
            occupied_by_dir[directory] = cached
        return cached

    changed = True
    while changed:
        changed = False
        movers = [row for row in rows if row.status == STATUS_OK]
        vacated: set[tuple[Path, str]] = set()
        if not copy:
            for row in movers:
                if row.old_name.casefold() != row.new_name.casefold():
                    vacated.add((row.path.parent, row.old_name.casefold()))
        for row in movers:
            key = row.new_name.casefold()
            names = occupied(row.path.parent)
            if copy:
                taken = key in names
            else:
                self_case_change = key == row.old_name.casefold()
                taken = (
                    key in names
                    and not self_case_change
                    and (row.path.parent, key) not in vacated
                )
            if taken:
                row.status = STATUS_COLLISION
                row.message = "目标文件名已被占用"
                changed = True


def _preview_result(
    *,
    rows: list[RenameRow],
    unused_names: list[str],
    source_names: list[str],
    copy: bool,
    files: list[Path],
    checked: list[bool],
    template: str | None = None,
    prefix: str = "",
    suffix: str = "",
    date: str = "",
) -> PreviewResult:
    _apply_collisions(rows, copy=copy)
    return PreviewResult(
        rows=rows,
        unused_names=unused_names,
        source_names=source_names,
        copy=copy,
        files=list(files),
        checked=list(checked),
        template=template,
        prefix=prefix,
        suffix=suffix,
        date=date,
    )


def preview_list_rename(
    files: list[Path],
    checked: list[bool],
    names: list[str],
    *,
    copy: bool,
) -> PreviewResult:
    rows: list[RenameRow] = []
    name_index = 0
    for path, is_checked in zip(files, checked):
        if not is_checked:
            rows.append(_unchecked_row(path))
            continue
        if name_index >= len(names):
            rows.append(_missing_line_row(path))
            continue
        new_name = build_new_filename(names[name_index], path.suffix)
        name_index += 1
        rows.append(_classify_new_name(path, new_name))
    unused_names = list(names[name_index:])
    return _preview_result(
        rows=rows,
        unused_names=unused_names,
        source_names=list(names),
        copy=copy,
        files=files,
        checked=checked,
    )


def preview_template_rename(
    files: list[Path],
    checked: list[bool],
    *,
    template: str,
    prefix: str,
    suffix: str,
    copy: bool,
    date: str | None = None,
) -> PreviewResult:
    resolved_date = date if date is not None else today_yyyymmdd()
    checked_count = sum(1 for flag in checked if flag)
    width = index_width(checked_count)
    rows: list[RenameRow] = []
    index = 0
    for path, is_checked in zip(files, checked):
        if not is_checked:
            rows.append(_unchecked_row(path))
            continue
        index += 1
        stem = apply_template(
            template,
            original_stem=path.stem,
            date=resolved_date,
            index=index,
            width=width,
            prefix=prefix,
            suffix=suffix,
        )
        new_name = build_new_filename(stem, path.suffix)
        rows.append(_classify_new_name(path, new_name))
    return _preview_result(
        rows=rows,
        unused_names=[],
        source_names=[],
        copy=copy,
        files=files,
        checked=checked,
        template=template,
        prefix=prefix,
        suffix=suffix,
        date=resolved_date,
    )
