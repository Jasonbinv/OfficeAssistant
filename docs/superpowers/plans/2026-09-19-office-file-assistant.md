# 办公文件助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Windows 上交付可发给同事的中文桌面应用「办公文件助手」：PDF 整份合并、按页码/缩略图删页、按名单或模板重命名（含预检与撤销）。

**Architecture:** 无 Qt 依赖的 `naming.py` / `rename_ops.py` / `pdf_ops.py` / `fs_ops.py` 先用 pytest 钉死规则；`tasks/worker.py` 在 QThread 里调用这些函数；`ui/` 只负责左侧导航、对照表和进度。文件始终本机处理。

**Tech Stack:** Python 3.12+、PySide6、pypdf、pypdfium2、pytest、PyInstaller onedir

## Global Constraints

- 运行平台：Windows 10/11；界面与用户可见字符串全部简体中文
- Python ≥ 3.12；禁止使用 PyMuPDF（AGPL）
- PDF 读写用 pypdf，缩略图用 pypdfium2（最长边约 160px，共享读，不独占锁）
- 合并不覆盖任何源文件；输出路径不得等于任一源路径
- 删页默认另存 `{源主名}_删页.pdf`，覆盖原文件须二次确认；禁止删到 0 页；页码从 1 起算
- 重命名默认原地改名；可选复制保留原件；对照表展示净化后的最终文件名
- 执行前再预检：绿色集合若变化则整批不写盘
- 临时名使用同一目录下前缀 `.~$oa$`；取消合并/删页/复制时删除不完整新文件
- 入口 exe：`OfficeAssistant.exe`；窗口标题：办公文件助手
- 规格全文：`docs/superpowers/specs/2026-09-19-office-file-assistant-design.md`

## File Structure

```
.gitignore
pyproject.toml
pytest.ini
使用说明.txt
src/office_assistant/__init__.py
src/office_assistant/app.py
src/office_assistant/naming.py
src/office_assistant/rename_ops.py
src/office_assistant/pdf_ops.py
src/office_assistant/fs_ops.py
src/office_assistant/tasks/__init__.py
src/office_assistant/tasks/worker.py
src/office_assistant/ui/__init__.py
src/office_assistant/ui/main_window.py
src/office_assistant/ui/merge_page.py
src/office_assistant/ui/delete_page.py
src/office_assistant/ui/rename_page.py
tests/conftest.py
tests/test_naming.py
tests/test_rename_ops.py
tests/test_pdf_ops.py
tests/test_fs_ops.py
packaging/office_assistant.spec
```

`naming.py`：纯字符串/路径规则。`rename_ops.py`：目录列表、预览、执行、撤销。`pdf_ops.py`：探测/合并/删页/缩略图。`fs_ops.py`：占用、原子替换、清理。UI 不直接 `os.rename`。

---

### Task 1: 工程骨架与文件名净化

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `pytest.ini`
- Create: `src/office_assistant/__init__.py`
- Create: `src/office_assistant/naming.py`
- Create: `tests/test_naming.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `parse_name_list(text: str) -> list[str]`
  - `sanitize_stem(text: str) -> str`
  - `is_reserved_device_name(stem: str) -> bool`
  - `apply_extension(line: str, original_suffix: str) -> str`
  - `build_new_filename(line: str, original_suffix: str) -> str`
  - `original_suffix` 含点，例如 `.pdf` / `.PDF`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_naming.py`：

```python
from office_assistant.naming import (
    apply_extension,
    build_new_filename,
    is_reserved_device_name,
    parse_name_list,
    sanitize_stem,
)


def test_parse_name_list_skips_blank_and_bom_and_excel_tab():
    text = "\ufeff水施-01_封皮\n\n  \n水施-01_图纸目录\t备注列\r\n水施-02_说明 "
    assert parse_name_list(text) == [
        "水施-01_封皮",
        "水施-01_图纸目录",
        "水施-02_说明",
    ]


def test_sanitize_strips_illegal_and_trailing_dot_space():
    assert sanitize_stem('a<>:"/\\|?*b. ') == "ab"


def test_reserved_device_names():
    assert is_reserved_device_name("CON")
    assert is_reserved_device_name("com1")
    assert not is_reserved_device_name("合同")


def test_extension_not_doubled_when_same():
    assert apply_extension("封皮.pdf", ".PDF") == "封皮.PDF"
    assert apply_extension("封皮", ".pdf") == "封皮.pdf"


def test_other_extension_is_kept_then_original_appended():
    assert apply_extension("foo.dwg", ".pdf") == "foo.dwg.pdf"


def test_build_new_filename_empty_after_sanitize():
    assert build_new_filename("***", ".pdf") == ".pdf"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_naming.py -v`

Expected: FAIL，提示 `ModuleNotFoundError: office_assistant` 或无法导入 `parse_name_list`

- [ ] **Step 3: 写最小实现与骨架**

`.gitignore`：

```
.venv/
__pycache__/
.pytest_cache/
.superpowers/
dist/
build/
*.egg-info/
```

`pytest.ini`：

```
[pytest]
pythonpath = src
```

`pyproject.toml`：

```toml
[project]
name = "office-assistant"
version = "0.1.0"
description = "办公文件助手"
requires-python = ">=3.12"
dependencies = [
    "PySide6>=6.7",
    "pypdf>=5.0",
    "pypdfium2>=4.30",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

`src/office_assistant/__init__.py` 为空。

`src/office_assistant/naming.py`：

```python
from __future__ import annotations

import re

ILLEGAL_RE = re.compile(r'[\x00-\x1f\\/:*?"<>|]')
RESERVED_STEMS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def parse_name_list(text: str) -> list[str]:
    if text.startswith("\ufeff"):
        text = text[1:]
    names: list[str] = []
    for raw in text.splitlines():
        line = raw.split("\t", 1)[0].strip()
        if line:
            names.append(line)
    return names


def sanitize_stem(text: str) -> str:
    cleaned = ILLEGAL_RE.sub("", text).strip()
    return cleaned.rstrip(" .")


def is_reserved_device_name(stem: str) -> bool:
    base = stem.split(".")[0]
    return base.upper() in RESERVED_STEMS


def apply_extension(line: str, original_suffix: str) -> str:
    suffix = original_suffix if original_suffix.startswith(".") else f".{original_suffix}"
    if line.lower().endswith(suffix.lower()):
        return line[: -len(suffix)] + suffix
    return line + suffix


def build_new_filename(line: str, original_suffix: str) -> str:
    suffix = original_suffix if original_suffix.startswith(".") else f".{original_suffix}"
    if line.lower().endswith(suffix.lower()):
        stem = sanitize_stem(line[: -len(suffix)])
    else:
        stem = sanitize_stem(line)
    if not stem:
        return suffix
    return apply_extension(stem, suffix)
```

保留设备名不在本函数抛错，只产出文件名；Task 3 预检把空主名和保留名标为 `invalid`。`***` 净化后为空，结果是 `.pdf`。

- [ ] **Step 4: 安装并跑通测试**

Run:

```
python -m pip install -e ".[dev]"
python -m pytest tests/test_naming.py -v
```

Expected: PASS（5 或 6 条，视是否保留 reserved 测试；`is_reserved_device_name` 不依赖 `build_new_filename`）

- [ ] **Step 5: Commit**

```bash
git add .gitignore pyproject.toml pytest.ini src/office_assistant/__init__.py src/office_assistant/naming.py tests/test_naming.py
git commit -m "feat: add filename sanitizer and name-list parser"
```

---

### Task 2: 自然排序、模板、页码、unique_path

**Files:**
- Modify: `src/office_assistant/naming.py`
- Modify: `tests/test_naming.py`

**Interfaces:**
- Consumes: Task 1 的 `sanitize_stem`、`apply_extension`
- Produces:
  - `natural_sort_key(name: str) -> tuple`
  - `index_width(count: int) -> int`
  - `today_yyyymmdd() -> str`
  - `apply_template(template: str, *, original_stem: str, date: str, index: int, width: int, prefix: str, suffix: str) -> str`
  - `unique_path(path: Path) -> Path`（若 `path` 不存在则原样返回）
  - `parse_page_ranges(text: str, page_count: int) -> PageRangeParse`
  - `format_page_ranges(pages: set[int]) -> str`
  - `@dataclass PageRangeParse: pages: set[int]; errors: list[str]`（页码从 1 起）

- [ ] **Step 1: 写失败测试（追加到 `tests/test_naming.py`）**

```python
from pathlib import Path
from office_assistant.naming import (
    apply_template,
    format_page_ranges,
    index_width,
    natural_sort_key,
    parse_page_ranges,
    unique_path,
)


def test_natural_sort_orders_like_explorer():
    names = ["扫描10.pdf", "扫描2.pdf", "扫描1.pdf"]
    assert sorted(names, key=natural_sort_key) == [
        "扫描1.pdf",
        "扫描2.pdf",
        "扫描10.pdf",
    ]


def test_index_width_grows_with_count():
    assert index_width(8) == 2
    assert index_width(100) == 3


def test_apply_template_default_pattern():
    name = apply_template(
        "{原名}_{序号}",
        original_stem="扫描",
        date="20260919",
        index=3,
        width=2,
        prefix="",
        suffix="",
    )
    assert name == "扫描_03"


def test_unique_path_adds_numeric_suffix(tmp_path: Path):
    first = tmp_path / "合同_合并.pdf"
    first.write_bytes(b"x")
    second = unique_path(first)
    assert second == tmp_path / "合同_合并_2.pdf"
    second.write_bytes(b"y")
    third = unique_path(first)
    assert third == tmp_path / "合同_合并_3.pdf"


def test_parse_and_format_page_ranges():
    parsed = parse_page_ranges("1,3,5-8,3,99", page_count=10)
    assert parsed.pages == {1, 3, 5, 6, 7, 8}
    assert parsed.errors  # 99 越界
    assert format_page_ranges({1, 3, 5, 6, 7, 8}) == "1,3,5-8"


def test_parse_page_ranges_rejects_empty_delete_all():
    parsed = parse_page_ranges("1-3", page_count=3)
    assert parsed.pages == {1, 2, 3}
```

- [ ] **Step 2: 跑新增测试确认失败**

Run: `python -m pytest tests/test_naming.py::test_natural_sort_orders_like_explorer -v`

Expected: FAIL，`natural_sort_key` 未定义

- [ ] **Step 3: 实现**

追加到 `naming.py`：

```python
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


def natural_sort_key(name: str) -> tuple:
    parts = re.split(r"(\d+)", name)
    key = []
    for part in parts:
        if part.isdigit():
            key.append((1, int(part)))
        else:
            key.append((0, part.casefold()))
    return tuple(key)


def index_width(count: int) -> int:
    return max(2, len(str(max(count, 1))))


def today_yyyymmdd() -> str:
    return date.today().strftime("%Y%m%d")


def apply_template(
    template: str,
    *,
    original_stem: str,
    date: str,
    index: int,
    width: int,
    prefix: str,
    suffix: str,
) -> str:
    body = (
        template.replace("{原名}", original_stem)
        .replace("{日期}", date)
        .replace("{序号}", str(index).zfill(width))
    )
    return f"{prefix}{body}{suffix}"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 2
    while True:
        candidate = path.with_name(f"{stem}_{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1


@dataclass
class PageRangeParse:
    pages: set[int] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


def parse_page_ranges(text: str, page_count: int) -> PageRangeParse:
    result = PageRangeParse()
    if not text.strip():
        return result
    for chunk in text.split(","):
        token = chunk.strip()
        if not token:
            continue
        try:
            if "-" in token:
                start_s, end_s = token.split("-", 1)
                start, end = int(start_s), int(end_s)
                if start > end:
                    start, end = end, start
            else:
                start = end = int(token)
        except ValueError:
            result.errors.append(token)
            continue
        for page in range(start, end + 1):
            if 1 <= page <= page_count:
                result.pages.add(page)
            else:
                result.errors.append(str(page))
    return result


def format_page_ranges(pages: set[int]) -> str:
    if not pages:
        return ""
    ordered = sorted(pages)
    ranges: list[str] = []
    start = prev = ordered[0]
    for page in ordered[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = page
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(ranges)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_naming.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/office_assistant/naming.py tests/test_naming.py
git commit -m "feat: add natural sort, templates, page ranges, unique paths"
```

---

### Task 3: 重命名预览与预检

**Files:**
- Create: `src/office_assistant/rename_ops.py`
- Create: `tests/test_rename_ops.py`

**Interfaces:**
- Consumes: `parse_name_list`, `build_new_filename`, `is_reserved_device_name`, `sanitize_stem`, `natural_sort_key`, `apply_template`, `index_width`, `today_yyyymmdd`
- Produces:
  - `SKIP_FILES = {"desktop.ini", "thumbs.db"}`
  - `TEMP_PREFIX = ".~$oa$"`
  - `@dataclass RenameRow`: `path: Path; checked: bool; old_name: str; new_name: str; status: str; message: str`
  - `@dataclass PreviewResult`: `rows: list[RenameRow]; unused_names: list[str]; source_names: list[str]; copy: bool; files: list[Path]; checked: list[bool]; template: str | None = None; prefix: str = ""; suffix: str = ""; date: str = ""`
  - `list_directory_files(directory: Path, extensions: set[str]) -> list[Path]`（不递归、跳过隐藏与 SKIP_FILES，按 `natural_sort_key` 排序）
  - `preview_list_rename(files: list[Path], checked: list[bool], names: list[str], *, copy: bool) -> PreviewResult`
  - `preview_template_rename(files: list[Path], checked: list[bool], *, template: str, prefix: str, suffix: str, copy: bool, date: str | None = None) -> PreviewResult`
  - `status` 取值：`ok` | `missing_line` | `invalid` | `collision` | `unchanged` | `unchecked`
  - 只有 `status=="ok"` 视为绿色可执行行

- [ ] **Step 1: 写失败测试**

`tests/test_rename_ops.py`：

```python
from pathlib import Path

from office_assistant.rename_ops import (
    list_directory_files,
    preview_list_rename,
    preview_template_rename,
)


def _touch(dir: Path, name: str) -> Path:
    path = dir / name
    path.write_bytes(b"x")
    return path


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_rename_ops.py -v`

Expected: FAIL，无法导入 `rename_ops`

- [ ] **Step 3: 实现 `rename_ops.py` 预览部分**

实现 `list_directory_files`：只接受文件；扩展名比较用去掉点后的小写；跳过 `desktop.ini`、`thumbs.db`（大小写不敏感）；跳过 `name.startswith(".")` 以及 Windows 隐藏属性（`ctypes` 读 `GetFileAttributesW`，若失败则忽略）。

实现预览算法：

1. 未勾选 → `status="unchecked"`，`new_name=""`
2. 勾选文件按列表顺序与 `names` 第 N 条配对
3. `new_name = build_new_filename(name, path.suffix)`；主名为空或 `is_reserved_device_name(Path(new_name).stem)` → `invalid`
4. 新旧名相同（大小写也相同）→ `unchanged`
5. 统计绿色候选的目标 `directory / new_name`（大小写不敏感比较占用）
6. 原地：其它绿色行将改走的旧名可腾出；未被腾出的已存在文件 → `collision`；绿色行之间目标相同 → 全部 `collision`
7. 复制：任何已存在目标或绿色行目标重复 → `collision`，不腾挪
8. 多余名单进 `unused_names`

`preview_template_rename`：对勾选文件按顺序 `index=1..n`，`width=index_width(n)`，`stem=apply_template(...)` 再 `build_new_filename`；未勾选不占序号。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_rename_ops.py tests/test_naming.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/office_assistant/rename_ops.py tests/test_rename_ops.py
git commit -m "feat: add rename preview and collision preflight"
```

---

### Task 4: 重命名执行、两阶段、撤销

**Files:**
- Modify: `src/office_assistant/rename_ops.py`
- Modify: `tests/test_rename_ops.py`

**Interfaces:**
- Consumes: `PreviewResult`、`RenameRow`、`TEMP_PREFIX`
- Produces:
  - `@dataclass ExecuteResult`: `succeeded: list[tuple[Path, Path]]`（执行前路径, 执行后路径）；`skipped: list[str]`；`failed: list[str]`；`temps_left: list[Path]`；`copy: bool`
  - `snapshot_ok(preview: PreviewResult) -> bool`：用 `preview.files`、`preview.checked`、`preview.source_names`、`preview.copy` 再跑 `preview_list_rename`，比较每行 `(path, new_name, status)` 是否与 `preview.rows` 一致。规则模式用同样字段再跑 `preview_template_rename` 时，给 `PreviewResult` 增加可选 `template: str | None`、`prefix: str`、`suffix: str`、`date: str`，名单模式这些为空
  - `execute_renames(rows: list[RenameRow], *, copy: bool, cancel_event: threading.Event | None = None) -> ExecuteResult`
  - `undo_renames(batch: ExecuteResult, cancel_event: threading.Event | None = None) -> ExecuteResult`
  - 只执行 `status=="ok"` 的行
  - 临时文件：`path.with_name(TEMP_PREFIX + uuid4().hex + path.suffix)`

- [ ] **Step 1: 写失败测试**

追加：

```python
import threading
from office_assistant.rename_ops import execute_renames, snapshot_ok, undo_renames


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_rename_ops.py::test_execute_inplace_swap -v`

Expected: FAIL，`execute_renames` 未定义

- [ ] **Step 3: 实现执行与撤销**

`snapshot_ok`：若 `preview.template` 为空，调用 `preview_list_rename(preview.files, preview.checked, preview.source_names, copy=preview.copy)`；否则调用 `preview_template_rename(...)`。比较新旧 `PreviewResult.rows` 的 `(path, new_name, status)` 元组列表。不一致则返回 False。

`execute_renames`（原地）：

1. 过滤 `ok` 行；若 `cancel_event` 已 set，立即返回空成功
2. 分组：目标名（大小写不敏感）等于组内其它行旧名的划入依赖组，其余独立
3. 独立行：若仅大小写变化或 `dest.exists()` 因大小写——先改到 `TEMP_PREFIX` 临时名再改到目标；否则 `Path.replace`。失败记 `failed`，继续
4. 依赖组：全部先改为互不冲突临时名；任一步失败则把已改临时名改回旧名；成功后再从临时名改到最终名
5. `succeeded` 记录 `(old_path, new_path)`

复制模式：`shutil.copy2(src, dest)`，失败不删源；取消时若副本写了一半则 `dest.unlink(missing_ok=True)`。

`undo_renames`：若 `batch.copy`，删除 `new_path`；否则把 `new_path` 改回 `old_path`（同样两阶段）。目标被占用则该条 `failed`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_rename_ops.py tests/test_naming.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/office_assistant/rename_ops.py tests/test_rename_ops.py
git commit -m "feat: execute rename with two-phase swap, copy, and undo"
```

---

### Task 5: PDF 探测、合并、删页

**Files:**
- Create: `src/office_assistant/pdf_ops.py`
- Create: `tests/conftest.py`
- Create: `tests/test_pdf_ops.py`

**Interfaces:**
- Consumes: `unique_path` 仅测试另存；本模块不负责对话框
- Produces:
  - `@dataclass PdfInfo`: `path: Path; ok: bool; encrypted: bool; needs_password: bool; page_count: int; error: str`
  - `probe_pdf(path: Path, password: str | None = None) -> PdfInfo`
  - `merge_pdfs(paths: list[Path], dest: Path, passwords: dict[str, str] | None = None, cancel_event: threading.Event | None = None) -> None`
    - `paths` 为绝对路径字符串键也可用 `dict[Path, str]`，统一 `dict[Path, str]`
    - 若 `dest.resolve()` 等于任一 `path.resolve()`，抛 `ValueError("输出路径不能与源文件相同")`
    - 取消时若已创建 `dest` 则删除
  - `delete_pages(src: Path, dest: Path, pages_to_delete: set[int], password: str | None = None, cancel_event: threading.Event | None = None) -> None`
    - `pages_to_delete` 从 1 起；若剩余 0 页抛 `ValueError("不能删除全部页面")`；`src==dest` 时先写临时文件再替换
  - 合并保留各页原尺寸与旋转（`writer.add_page(page)`，不重置 mediabox）

- [ ] **Step 1: 写夹具与失败测试**

`tests/conftest.py`：

```python
from pathlib import Path
import pytest
from pypdf import PdfWriter


def make_blank_pdf(path: Path, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


@pytest.fixture
def two_pdfs(tmp_path: Path) -> tuple[Path, Path]:
    a = make_blank_pdf(tmp_path / "a.pdf", 2)
    b = make_blank_pdf(tmp_path / "b.pdf", 3)
    return a, b
```

`tests/test_pdf_ops.py`：

```python
from pathlib import Path
import threading
from pypdf import PdfReader
from office_assistant.pdf_ops import delete_pages, merge_pdfs, probe_pdf
from conftest import make_blank_pdf


def test_probe_ok(tmp_path: Path):
    path = make_blank_pdf(tmp_path / "a.pdf", 4)
    info = probe_pdf(path)
    assert info.ok and info.page_count == 4 and not info.needs_password


def test_probe_missing():
    info = probe_pdf(Path("no-such.pdf"))
    assert not info.ok


def test_merge_concatenates_pages(two_pdfs, tmp_path: Path):
    a, b = two_pdfs
    dest = tmp_path / "a_合并.pdf"
    merge_pdfs([a, b], dest)
    assert len(PdfReader(dest).pages) == 5
    assert a.exists() and b.exists()


def test_merge_rejects_source_as_dest(two_pdfs):
    a, b = two_pdfs
    try:
        merge_pdfs([a, b], a)
        assert False, "should have raised"
    except ValueError as exc:
        assert "源文件" in str(exc)


def test_merge_cancel_removes_incomplete(two_pdfs, tmp_path: Path):
    a, b = two_pdfs
    dest = tmp_path / "out.pdf"
    ev = threading.Event()
    ev.set()
    merge_pdfs([a, b], dest, cancel_event=ev)
    assert not dest.exists()


def test_delete_pages_keeps_remaining(tmp_path: Path):
    src = make_blank_pdf(tmp_path / "src.pdf", 4)
    dest = tmp_path / "src_删页.pdf"
    delete_pages(src, dest, {1, 3})
    assert len(PdfReader(dest).pages) == 2
    assert src.exists()


def test_delete_all_pages_forbidden(tmp_path: Path):
    src = make_blank_pdf(tmp_path / "src.pdf", 2)
    try:
        delete_pages(src, tmp_path / "x.pdf", {1, 2})
        assert False
    except ValueError:
        pass
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_pdf_ops.py -v`

Expected: FAIL，无法导入 `pdf_ops`

- [ ] **Step 3: 实现 `pdf_ops.py`**

使用 `pypdf.PdfReader` / `PdfWriter`：

- `probe_pdf`：文件不存在 → `ok=False, error="找不到文件"`。打开后 `reader.is_encrypted`：无密码或密码失败 → `needs_password=True, encrypted=True, ok=False, error="需要密码"`。解密成功或未加密 → `ok=True, page_count=len(pages)`。其它异常 → `error="损坏"`。
- `merge_pdfs`：先检查 dest 与源；循环 `probe`+`add_page`；每页后检查 `cancel_event`；写出前若取消则不写；写出用临时 `dest.with_name(TEMP_PREFIX + dest.name)` 再 `replace` 到 dest，取消或异常删除临时文件。
- `delete_pages`：校验集合；`writer.add_page` 所有不在删除集中的页（注意 reader 页是 0 起，删除集 1 起）；`src.resolve()==dest.resolve()` 时写到同目录临时文件再 `os.replace`。

密码：`passwords.get(path)` 传给 `reader.decrypt`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_pdf_ops.py tests/test_naming.py tests/test_rename_ops.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/office_assistant/pdf_ops.py tests/conftest.py tests/test_pdf_ops.py
git commit -m "feat: add PDF probe, merge, and page deletion"
```

---

### Task 6: 缩略图与文件占用/清理

**Files:**
- Create: `src/office_assistant/fs_ops.py`
- Modify: `src/office_assistant/pdf_ops.py`
- Create: `tests/test_fs_ops.py`
- Modify: `tests/test_pdf_ops.py`

**Interfaces:**
- Consumes: `TEMP_PREFIX`（可在 `fs_ops` 再导出同一常量，避免循环导入：常量放到 `naming.py` 或新建 `src/office_assistant/constants.py`）。本任务创建 `src/office_assistant/constants.py`，把 `TEMP_PREFIX = ".~$oa$"` 从 `rename_ops` 移过去，两处引用。
- Produces:
  - `constants.TEMP_PREFIX: str`
  - `fs_ops.is_locked(path: Path) -> bool`
  - `fs_ops.replace_file(temp: Path, dest: Path) -> None`
  - `fs_ops.remove_incomplete(path: Path) -> None`
  - `pdf_ops.render_thumbnail(path: Path, page_index_zero: int, max_edge: int = 160, password: str | None = None) -> bytes`（PNG 字节；打开 pdfium 用非独占）

- [ ] **Step 1: 写失败测试**

`tests/test_fs_ops.py`：

```python
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
```

`tests/test_pdf_ops.py` 追加：

```python
from office_assistant.pdf_ops import render_thumbnail

def test_render_thumbnail_png_header(tmp_path: Path):
    src = make_blank_pdf(tmp_path / "a.pdf", 1)
    data = render_thumbnail(src, 0)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
```

另存重名加序号仍用 `naming.unique_path`，不在 `fs_ops` 重复实现。`is_locked` 在 Windows 上用 `CreateFileW(dwShareMode=0)` 探测；未占用返回 False。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_fs_ops.py tests/test_pdf_ops.py::test_render_thumbnail_png_header -v`

Expected: FAIL，缺少模块或函数

- [ ] **Step 3: 实现**

`constants.py`：

```python
TEMP_PREFIX = ".~$oa$"
```

`fs_ops.py`：`remove_incomplete` 即 `Path.unlink(missing_ok=True)`；`replace_file` 用 `os.replace` 后确保 temp 不存在；`is_locked`：Windows 下 `ctypes.windll.kernel32.CreateFileW` 以 `dwShareMode=0` 打开再关闭，失败则视为占用；非 Windows 返回 False。

`render_thumbnail`：`pdfium.PdfDocument(str(path), password=password or "")`，渲染 `page_index_zero`，按 `max_edge` 缩放，`pil_to_png` 或 pdfium 自带 `to_pil().save(BytesIO, format="PNG")`。`PdfDocument` 用完关闭。

把 `rename_ops.TEMP_PREFIX` 改为 `from office_assistant.constants import TEMP_PREFIX`。

- [ ] **Step 4: 跑全量单测**

Run: `python -m pytest -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/office_assistant/constants.py src/office_assistant/fs_ops.py src/office_assistant/pdf_ops.py src/office_assistant/rename_ops.py tests/test_fs_ops.py tests/test_pdf_ops.py
git commit -m "feat: add PDF thumbnails and file replace helpers"
```

---

### Task 7: 后台 Worker 与主窗口骨架

**Files:**
- Create: `src/office_assistant/tasks/__init__.py`
- Create: `src/office_assistant/tasks/worker.py`
- Create: `src/office_assistant/ui/__init__.py`
- Create: `src/office_assistant/ui/main_window.py`
- Create: `src/office_assistant/app.py`

**Interfaces:**
- Consumes: `execute_renames`, `merge_pdfs`, `delete_pages`, `snapshot_ok`
- Produces:
  - `class JobWorker(QObject)` 信号：`progress = Signal(int, str)`（0–100, 中文说明）；`finished = Signal(object)`；`failed = Signal(str)`
  - 槽 `run_job(self)` 读取构造传入的 `callable` 与 `threading.Event` `cancel_event`
  - `class MainWindow(QMainWindow)`：窗口标题 `办公文件助手`；左侧 `QListWidget` 三项 `合并 PDF` / `删除页面` / `重命名`；右侧 `QStackedWidget` 三个占位 `QLabel`（本任务先占位，下两任务替换）；底栏 `QProgressBar`、`QPushButton("取消")`、`QLabel` 摘要
  - `app.main()`：`QApplication`、`MainWindow.show()`、`app.exec()`
  - 取消按钮 `cancel_event.set()`

- [ ] **Step 1: 写可无界面导入的冒烟测试**

`tests/test_worker.py`：

```python
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
```

把 Qt 信号包在 `JobWorker`，纯函数 `run_callable_job` 供测试，避免 CI 无显示也能测。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_worker.py -v`

Expected: FAIL，无法导入

- [ ] **Step 3: 实现 worker 与主窗**

`tasks/worker.py`：

```python
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot


def run_callable_job(fn: Callable[[], Any], cancel_event: threading.Event) -> Any:
    if cancel_event.is_set():
        raise RuntimeError("已取消")
    return fn()


class JobWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any], cancel_event: threading.Event):
        super().__init__()
        self._fn = fn
        self.cancel_event = cancel_event

    @Slot()
    def run_job(self) -> None:
        try:
            result = run_callable_job(self._fn, self.cancel_event)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
```

`ui/main_window.py`：左侧宽度约 120px；`currentRowChanged` 切换 stack。底栏取消默认禁用，任务开始时启用。先不要启动真实 PDF 任务。

`app.py`：

```python
import sys
from PySide6.QtWidgets import QApplication
from office_assistant.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("办公文件助手")
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试并手工点开窗口**

Run: `python -m pytest tests/test_worker.py -v`

Expected: PASS

Run: `python -m office_assistant.app`

Expected: 窗口标题为「办公文件助手」，左侧三项可切换，右侧占位文字变化。

- [ ] **Step 5: Commit**

```bash
git add src/office_assistant/app.py src/office_assistant/tasks src/office_assistant/ui tests/test_worker.py
git commit -m "feat: add desktop shell and background job worker"
```

---

### Task 8: 重命名页

**Files:**
- Create: `src/office_assistant/ui/rename_page.py`
- Modify: `src/office_assistant/ui/main_window.py`

**Interfaces:**
- Consumes: `list_directory_files`, `parse_name_list`, `preview_list_rename`, `preview_template_rename`, `snapshot_ok`, `execute_renames`, `undo_renames`, `ExecuteResult`, `JobWorker`
- Produces: `class RenamePage(QWidget)`
  - 顶栏：目录 `QLineEdit`+浏览、扩展名勾选（默认 pdf，另有 dwg/dxf/jpg/jpeg/png/tif/tiff/doc/docx/xls/xlsx）、刷新
  - 模式切换：名单改名 | 规则改名
  - 名单：`QPlainTextEdit`；规则：模板（默认 `{原名}_{序号}`）、前缀、后缀
  - 复制保留原件 `QCheckBox`（默认关）
  - `QTableWidget` 列：参与（check）、当前文件名、新文件名；行可内部拖动排序
  - 表下方 `QLabel` 显示 `unused_names`（红色）
  - 按钮：确认重命名、撤销上次重命名（无批次时禁用）
  - 拖入文件夹：设为目录并刷新；拖入文件：必须同一目录，勾选对应扩展名并只勾选这些文件
  - 确认：`snapshot_ok` 失败则刷新并 `QMessageBox.warning`「文件已变化，请确认后重试」；成功则 `JobWorker` 调 `execute_renames`
  - 结果用中文摘要：`成功 N 个，跳过 N 个，失败 N 个`
  - 记住最近一次 `ExecuteResult` 供撤销

- [ ] **Step 1: 实现 `RenamePage`（无独立 GUI 自动化；逻辑复用已测函数）**

关键绑定：`textChanged` / 勾选 / 拖动结束后调用 `_rebuild_preview`：从表格收集 `files` 与 `checked`，`names=parse_name_list(edit.toPlainText())`，写入新文件名列；`ok` 绿、`missing_line/invalid/collision` 红、`unchanged` 灰。无 `ok` 行则确认按钮禁用。

把 `RenamePage` 放进 `MainWindow` stack 第 3 页（索引 2）。`MainWindow.start_job(fn, on_done)` 统一开 `QThread`+`JobWorker`，完成后回到主线程刷新摘要。

拖放：`setAcceptDrops(True)`，`urls` 转本地路径。

- [ ] **Step 2: 手工验收名单改名**

Run: `python -m office_assistant.app`

在临时文件夹放 `扫描1.pdf`、`扫描2.pdf`，粘贴：

```
水施-01_封皮
水施-01_图纸目录
```

确认对照表、改名、撤销。再测少一行标红、复制模式、规则 `{原名}_{序号}`。

Expected: 与规格 5.4 / 5.5 / 7.3 一致。

- [ ] **Step 3: Commit**

```bash
git add src/office_assistant/ui/rename_page.py src/office_assistant/ui/main_window.py
git commit -m "feat: add list and template rename workspace"
```

---

### Task 9: 合并页与删页页

**Files:**
- Create: `src/office_assistant/ui/merge_page.py`
- Create: `src/office_assistant/ui/delete_page.py`
- Modify: `src/office_assistant/ui/main_window.py`
- Modify: `src/office_assistant/pdf_ops.py`（若需按可见区域懒加载缩略图的取消令牌，把 `render_thumbnail` 已有签名接上 `cancel_event` 可选参数，默认 None）

**Interfaces:**
- Consumes: `probe_pdf`, `merge_pdfs`, `delete_pages`, `render_thumbnail`, `parse_page_ranges`, `format_page_ranges`, `unique_path`, `fs_ops.is_locked`, `JobWorker`
- Produces:
  - `MergePage`：添加/移除/上移/下移/清空；可拖动列表；拖入 PDF 或文件夹（不递归）；重复路径拒绝；每行显示 `probe_pdf` 状态；需要密码可点行弹出 `QInputDialog`；「合并其余完好文件」`QCheckBox`；完好 PDF&lt;2 时开始按钮禁用；开始后 `QFileDialog.getSaveFileName` 预填第一个完好文件目录与 `{主名}_合并.pdf`；输出等于源则警告；另存已存在则询问：自动加序号 / 覆盖该目标 / 取消
  - `DeletePage`：打开/拖入（多文件只取第一个并提示）；页码框与缩略图勾选同步；全选/反选；覆盖原文件勾选+二次确认；另存默认 `{源主名}_删页.pdf`；未选页或将删光则禁用执行；缩略图 `QListWidget` IconMode，不可见的不渲染，切换文件取消旧任务

- [ ] **Step 1: 实现 MergePage**

列表项 userRole 存路径。状态列：完好 / 需要密码 / 损坏 / 非 PDF。开始合并时构造 `paths`（若未勾选「其余完好」且存在非完好 → 禁用，已在按钮状态处理）。`passwords: dict[Path, str]` 存在 page 实例上。

- [ ] **Step 2: 实现 DeletePage**

维护 `set[int] selected_pages`。页码编辑结束调用 `parse_page_ranges`，有 errors 则在旁注显示「无效：…」。缩略图勾选改集合后 `format_page_ranges` 写回（用 `_syncing` 标志防循环）。用 `QThread` 队列渲染当前可见行。覆盖时若 `is_locked(src)` 提示先关闭。`src==dest` 走 `delete_pages` 同路径分支。

- [ ] **Step 3: 接入 MainWindow stack 索引 0、1**

- [ ] **Step 4: 手工验收**

Run: `python -m office_assistant.app`

- 两份空白/真实 PDF 合并，源仍在，页数相加
- 坏文件标红，不能开始；勾选其余完好且 ≥2 才能开始
- 删页输入 `1,3` 与勾选一致；另存；覆盖确认
- 取消进行中的合并，无残缺输出

Expected: 符合规格 5.2、5.3、6、7.1、7.2

- [ ] **Step 5: Commit**

```bash
git add src/office_assistant/ui/merge_page.py src/office_assistant/ui/delete_page.py src/office_assistant/ui/main_window.py src/office_assistant/pdf_ops.py
git commit -m "feat: add PDF merge and page-deletion workspaces"
```

---

### Task 10: 打包、说明、许可文本

**Files:**
- Create: `packaging/office_assistant.spec`
- Create: `使用说明.txt`
- Create: `packaging/licenses/README.txt`
- Modify: `pyproject.toml`（可选 scripts）

**Interfaces:**
- Consumes: `office_assistant.app:main`
- Produces: PyInstaller onedir 输出 `dist/OfficeAssistant/OfficeAssistant.exe`；窗口标题仍为办公文件助手

- [ ] **Step 1: 写 spec 与说明**

`packaging/office_assistant.spec`（PyInstaller）：

```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
pdfium_datas, pdfium_binaries, pdfium_hidden = collect_all("pypdfium2")

a = Analysis(
    ["../src/office_assistant/app.py"],
    pathex=["../src"],
    binaries=pyside_binaries + pdfium_binaries,
    datas=pyside_datas + pdfium_datas + [("licenses", "licenses")],
    hiddenimports=pyside_hidden + pdfium_hidden + ["pypdf", "office_assistant"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OfficeAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="OfficeAssistant")
```

`使用说明.txt`：解压整个 `OfficeAssistant` 文件夹；双击 `OfficeAssistant.exe`；三个功能简述；文件只在本机；合并不改源文件；重命名前看对照表；覆盖需确认。

`packaging/licenses/README.txt`：列出 Python / PySide6(Qt LGPL) / pypdf / pypdfium2，并写明 Qt 为动态库、许可文本见同目录（打包时用 `collect_all` 带上 PySide6 自带 LICENSE）。

`pyproject.toml` 增加：

```toml
[project.scripts]
office-assistant = "office_assistant.app:main"
```

- [ ] **Step 2: 本地打目录包**

Run:

```
python -m pip install pyinstaller
pyinstaller packaging/office_assistant.spec --noconfirm --distpath dist --workpath build
```

Expected: 生成 `dist/OfficeAssistant/OfficeAssistant.exe`

- [ ] **Step 3: 在无源码窗口运行 exe 走三条主路径**

Expected: 合并、删页、名单改名成功；中文提示正常；关闭控制台窗口（console=False）

- [ ] **Step 4: 全量 pytest 仍通过**

Run: `python -m pytest -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packaging/office_assistant.spec packaging/licenses/README.txt 使用说明.txt pyproject.toml
git commit -m "chore: add PyInstaller onedir package and user guide"
```

---

## Self-Review vs Spec

| 规格条目 | 任务 |
| --- | --- |
| 名单解析、净化、扩展名、保留名、自然排序、模板、页码 | Task 1–2 |
| 预览/碰撞/复制不腾挪/无需改名 | Task 3 |
| 两阶段、仅大小写、执行前 snapshot、撤销、取消部分成功 | Task 4 |
| 合并、删页、加密探测、输出≠源、取消删残缺 | Task 5 |
| 缩略图 160px、不独占锁、原子替换 | Task 6 |
| 左侧导航、进度取消、中文标题 | Task 7 |
| 重命名 UI、拖入、刷新、对照表 | Task 8 |
| 合并/删页 UI、密码、另存冲突三选一、覆盖确认 | Task 9 |
| onedir exe、使用说明、LGPL 说明 | Task 10 |
| 不包含 OCR/转 PDF/跨文件挑页/安装程序 | 全程不做 |

无 TBD/TODO。类型名以 Task 3–5 的 dataclass 为准：`RenameRow`、`PreviewResult`、`ExecuteResult`、`PdfInfo`、`PageRangeParse`。`TEMP_PREFIX` 最终以 `office_assistant.constants.TEMP_PREFIX` 为准（Task 6 迁移）。
