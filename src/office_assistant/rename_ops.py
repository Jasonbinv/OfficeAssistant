from __future__ import annotations

import ctypes
import shutil
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from office_assistant.constants import TEMP_PREFIX
from office_assistant.naming import (
    apply_template,
    build_new_filename,
    index_width,
    is_reserved_device_name,
    natural_sort_key,
    today_yyyymmdd,
)

SKIP_FILES = {"desktop.ini", "thumbs.db"}

_FILE_ATTRIBUTE_HIDDEN = 0x2
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

try:
    _GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW  # type: ignore[attr-defined]
    _GetFileAttributesW.restype = ctypes.c_uint32
except AttributeError:
    _GetFileAttributesW = None

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


@dataclass
class ExecuteResult:
    succeeded: list[tuple[Path, Path]]
    skipped: list[str]
    failed: list[str]
    temps_left: list[Path]
    copy: bool


def _is_hidden_windows(path: Path) -> bool:
    if _GetFileAttributesW is None:
        return False
    try:
        attrs = _GetFileAttributesW(str(path))
    except Exception:
        return False
    if attrs in (-1, _INVALID_FILE_ATTRIBUTES):
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


_WIN_MAX_PATH = 259


def _dest_path_too_long(dest: Path) -> bool:
    text = str(dest)
    if text.startswith("\\\\?\\"):
        return False
    return len(text) > _WIN_MAX_PATH


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
    dest = path.with_name(new_name)
    if _dest_path_too_long(dest):
        return RenameRow(
            path=path,
            checked=True,
            old_name=path.name,
            new_name=new_name,
            status=STATUS_INVALID,
            message="路径过长，无法改名",
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
    if len(files) != len(checked):
        raise ValueError("files and checked must have the same length")
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
    if len(files) != len(checked):
        raise ValueError("files and checked must have the same length")
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


def _row_key(row: RenameRow) -> tuple[Path, str, str]:
    return (row.path, row.new_name, row.status)


def snapshot_ok(preview: PreviewResult) -> bool:
    if any(not path.is_file() for path in preview.files):
        return False
    try:
        if preview.template is None:
            fresh = preview_list_rename(
                preview.files,
                preview.checked,
                preview.source_names,
                copy=preview.copy,
            )
        else:
            fresh = preview_template_rename(
                preview.files,
                preview.checked,
                template=preview.template,
                prefix=preview.prefix,
                suffix=preview.suffix,
                copy=preview.copy,
                date=preview.date,
            )
    except OSError:
        return False
    return [_row_key(row) for row in fresh.rows] == [_row_key(row) for row in preview.rows]


def _empty_result(copy: bool) -> ExecuteResult:
    return ExecuteResult(succeeded=[], skipped=[], failed=[], temps_left=[], copy=copy)


def _cancelled(cancel_event: threading.Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _temp_path_for(path: Path) -> Path:
    while True:
        candidate = path.with_name(TEMP_PREFIX + uuid4().hex + path.suffix)
        if not candidate.exists():
            return candidate


def _skip_non_ok(rows: list[RenameRow]) -> list[str]:
    skipped: list[str] = []
    for row in rows:
        if row.status == STATUS_OK:
            continue
        if row.message:
            skipped.append(f"{row.old_name}（{row.message}）")
        else:
            skipped.append(row.old_name)
    return skipped


def _fail_msg(name: str, reason: str) -> str:
    return f"{name}（{reason}）"


def _is_case_only(src: Path, dest: Path) -> bool:
    return src.parent == dest.parent and src.name.casefold() == dest.name.casefold()


def _restore_temp(temp: Path, original: Path, temps_left: list[Path]) -> None:
    try:
        if original.exists() and not _is_case_only(temp, original):
            temps_left.append(temp)
            return
        temp.replace(original)
    except OSError:
        temps_left.append(temp)


def _is_staged_temp(dest: Path, staged_temps: set[Path]) -> bool:
    if dest in staged_temps:
        return True
    if not dest.exists():
        return False
    for temp in staged_temps:
        try:
            if temp.exists() and dest.samefile(temp):
                return True
        except OSError:
            continue
    return False


def _rollback_group_finalize(
    staged: list[tuple[RenameRow, Path, Path]],
    finalized: list[tuple[Path, Path]],
    index: int,
    temp: Path,
    old: Path,
    result: ExecuteResult,
) -> None:
    parked: list[tuple[Path, Path]] = []
    for done_old, done_dest in finalized:
        parking = _temp_path_for(done_dest)
        try:
            done_dest.replace(parking)
        except OSError:
            result.temps_left.append(done_dest)
            continue
        parked.append((done_old, parking))
    for done_old, parking in parked:
        _restore_temp(parking, done_old, result.temps_left)
    _restore_temp(temp, old, result.temps_left)
    for _, later_old, later_temp in staged[index + 1 :]:
        _restore_temp(later_temp, later_old, result.temps_left)


def _rename_independent(row: RenameRow, result: ExecuteResult) -> None:
    src = row.path
    dest = src.with_name(row.new_name)
    if not src.is_file():
        result.failed.append(_fail_msg(src.name, "文件不存在"))
        return
    try:
        if _is_case_only(src, dest):
            temp = _temp_path_for(src)
            try:
                src.replace(temp)
            except OSError as exc:
                result.failed.append(_fail_msg(src.name, str(exc)))
                return
            try:
                temp.replace(dest)
            except OSError as exc:
                _restore_temp(temp, src, result.temps_left)
                result.failed.append(_fail_msg(src.name, str(exc)))
                return
            result.succeeded.append((src, dest))
            return
        if dest.exists():
            result.failed.append(_fail_msg(dest.name, "目标文件名已被占用"))
            return
        src.replace(dest)
        result.succeeded.append((src, dest))
    except OSError as exc:
        result.failed.append(_fail_msg(src.name, str(exc)))


def _partition_ok_rows(
    rows: list[RenameRow],
) -> tuple[list[RenameRow], list[list[RenameRow]]]:
    n = len(rows)
    parent_ids = list(range(n))

    def find(i: int) -> int:
        while parent_ids[i] != i:
            parent_ids[i] = parent_ids[parent_ids[i]]
            i = parent_ids[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent_ids[rj] = ri

    for i, left in enumerate(rows):
        for j, right in enumerate(rows):
            if i >= j:
                continue
            if left.path.parent != right.path.parent:
                continue
            left_target = left.new_name.casefold()
            right_target = right.new_name.casefold()
            if left_target == right.old_name.casefold() or right_target == left.old_name.casefold():
                union(i, j)

    grouped: dict[int, list[RenameRow]] = defaultdict(list)
    for i, row in enumerate(rows):
        grouped[find(i)].append(row)

    independent: list[RenameRow] = []
    groups: list[list[RenameRow]] = []
    seen: set[int] = set()
    for i, row in enumerate(rows):
        root = find(i)
        if root in seen:
            continue
        seen.add(root)
        members = grouped[root]
        if len(members) == 1:
            independent.append(members[0])
        else:
            groups.append(members)
    return independent, groups


def _rename_group(rows: list[RenameRow], result: ExecuteResult) -> None:
    staged: list[tuple[RenameRow, Path, Path]] = []
    for row in rows:
        src = row.path
        if not src.is_file():
            for _, old, temp in reversed(staged):
                _restore_temp(temp, old, result.temps_left)
            result.failed.append(_fail_msg(src.name, "文件不存在"))
            return
        temp = _temp_path_for(src)
        try:
            src.replace(temp)
        except OSError as exc:
            for _, old, moved_temp in reversed(staged):
                _restore_temp(moved_temp, old, result.temps_left)
            result.failed.append(_fail_msg(src.name, str(exc)))
            return
        staged.append((row, src, temp))

    staged_temps = {temp for _, _, temp in staged}
    finalized: list[tuple[Path, Path]] = []
    for index, (row, old, temp) in enumerate(staged):
        dest = old.with_name(row.new_name)
        if dest.exists() and not _is_staged_temp(dest, staged_temps):
            _rollback_group_finalize(staged, finalized, index, temp, old, result)
            result.failed.append(_fail_msg(dest.name, "目标文件名已被占用"))
            return
        try:
            temp.replace(dest)
        except OSError as exc:
            _rollback_group_finalize(staged, finalized, index, temp, old, result)
            result.failed.append(_fail_msg(row.old_name, str(exc)))
            return
        finalized.append((old, dest))

    result.succeeded.extend(finalized)


def _copy_row(row: RenameRow, result: ExecuteResult, cancel_event: threading.Event | None) -> bool:
    src = row.path
    dest = src.with_name(row.new_name)
    if not src.is_file():
        result.failed.append(_fail_msg(src.name, "文件不存在"))
        return True
    if dest.exists():
        result.failed.append(_fail_msg(dest.name, "目标文件名已被占用"))
        return True
    if _cancelled(cancel_event):
        return False
    try:
        shutil.copy2(src, dest)
    except OSError as exc:
        dest.unlink(missing_ok=True)
        result.failed.append(_fail_msg(src.name, str(exc)))
        return True
    result.succeeded.append((src, dest))
    return not _cancelled(cancel_event)


def execute_renames(
    rows: list[RenameRow],
    *,
    copy: bool,
    cancel_event: threading.Event | None = None,
) -> ExecuteResult:
    result = _empty_result(copy)
    result.skipped = _skip_non_ok(rows)
    if _cancelled(cancel_event):
        return result
    ok_rows = [row for row in rows if row.status == STATUS_OK]
    if copy:
        for row in ok_rows:
            if _cancelled(cancel_event):
                break
            if not _copy_row(row, result, cancel_event):
                break
        return result

    independent, groups = _partition_ok_rows(ok_rows)
    for row in independent:
        if _cancelled(cancel_event):
            return result
        _rename_independent(row, result)
    for group in groups:
        if _cancelled(cancel_event):
            return result
        _rename_group(group, result)
    return result


def undo_renames(
    batch: ExecuteResult,
    cancel_event: threading.Event | None = None,
) -> ExecuteResult:
    result = _empty_result(batch.copy)
    if _cancelled(cancel_event):
        return result
    if batch.copy:
        for old_path, new_path in batch.succeeded:
            if _cancelled(cancel_event):
                break
            try:
                if not new_path.exists():
                    result.failed.append(_fail_msg(new_path.name, "文件不存在"))
                    continue
                new_path.unlink()
                result.succeeded.append((new_path, old_path))
            except OSError as exc:
                result.failed.append(_fail_msg(new_path.name, str(exc)))
        return result

    synthetic: list[RenameRow] = []
    for old_path, new_path in batch.succeeded:
        if not new_path.is_file():
            result.failed.append(_fail_msg(new_path.name, "文件不存在"))
            continue
        dest = new_path.with_name(old_path.name)
        if dest.exists() and not _is_case_only(new_path, dest):
            occupied_by_batch = any(other_new == dest for _, other_new in batch.succeeded)
            if not occupied_by_batch:
                result.failed.append(_fail_msg(old_path.name, "目标文件名已被占用"))
                continue
        synthetic.append(
            RenameRow(
                path=new_path,
                checked=True,
                old_name=new_path.name,
                new_name=old_path.name,
                status=STATUS_OK,
                message="",
            )
        )
    inner = execute_renames(synthetic, copy=False, cancel_event=cancel_event)
    result.succeeded = inner.succeeded
    result.failed.extend(inner.failed)
    result.temps_left.extend(inner.temps_left)
    result.skipped.extend(inner.skipped)
    return result

