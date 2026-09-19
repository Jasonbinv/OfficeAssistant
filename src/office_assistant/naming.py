from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

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


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def unique_path_excluding(path: Path, excluded: Iterable[Path]) -> Path:
    excluded_keys = {_resolved(item) for item in excluded}
    stem, suffix = path.stem, path.suffix
    n = 2
    candidate = unique_path(path)
    while True:
        if not candidate.exists() and _resolved(candidate) not in excluded_keys:
            return candidate
        candidate = path.with_name(f"{stem}_{n}{suffix}")
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
