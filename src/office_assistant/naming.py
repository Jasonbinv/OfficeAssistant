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
