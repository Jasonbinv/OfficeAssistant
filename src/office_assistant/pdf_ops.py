from __future__ import annotations

import io
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PasswordType, PdfReader, PdfWriter

from office_assistant.constants import TEMP_PREFIX


@dataclass
class PdfInfo:
    path: Path
    ok: bool
    encrypted: bool
    needs_password: bool
    page_count: int
    error: str


def probe_pdf(path: Path, password: str | None = None) -> PdfInfo:
    if not path.is_file():
        return PdfInfo(
            path=path,
            ok=False,
            encrypted=False,
            needs_password=False,
            page_count=0,
            error="找不到文件",
        )
    try:
        reader = PdfReader(path)
        encrypted = bool(reader.is_encrypted)
        if encrypted and not _unlock_encrypted_reader(reader, password):
            return PdfInfo(
                path=path,
                ok=False,
                encrypted=True,
                needs_password=True,
                page_count=0,
                error="需要密码",
            )
        return PdfInfo(
            path=path,
            ok=True,
            encrypted=encrypted,
            needs_password=False,
            page_count=len(reader.pages),
            error="",
        )
    except Exception:
        return PdfInfo(
            path=path,
            ok=False,
            encrypted=False,
            needs_password=False,
            page_count=0,
            error="损坏",
        )


def merge_pdfs(
    paths: list[Path],
    dest: Path,
    passwords: dict[Path, str] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    dest_resolved = dest.resolve()
    for path in paths:
        if path.resolve() == dest_resolved:
            raise ValueError("输出路径不能与源文件相同")

    writer = PdfWriter()
    for path in paths:
        if _cancelled(cancel_event):
            _remove_path(_temp_for(dest))
            return
        password = _lookup_password(path, passwords)
        info = probe_pdf(path, password)
        if not info.ok:
            raise ValueError(info.error)
        reader = _open_reader(path, password)
        for page in reader.pages:
            writer.add_page(page)
            if _cancelled(cancel_event):
                _remove_path(_temp_for(dest))
                return

    if _cancelled(cancel_event):
        _remove_path(_temp_for(dest))
        return
    _write_atomically(writer, dest, cancel_event)


def render_thumbnail(
    path: Path,
    page_index_zero: int,
    max_edge: int = 160,
    password: str | None = None,
) -> bytes:
    pdf = pdfium.PdfDocument(path.open("rb"), password=password or "", autoclose=True)
    try:
        page = pdf[page_index_zero]
        try:
            width, height = page.get_size()
            longest = max(width, height)
            scale = (max_edge / longest) if longest else 1.0
            bitmap = page.render(scale=scale)
            try:
                buffer = io.BytesIO()
                bitmap.to_pil().save(buffer, format="PNG")
                return buffer.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        pdf.close()


def delete_pages(
    src: Path,
    dest: Path,
    pages_to_delete: set[int],
    password: str | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    info = probe_pdf(src, password)
    if not info.ok:
        raise ValueError(info.error)

    keep = [index for index in range(1, info.page_count + 1) if index not in pages_to_delete]
    if not keep:
        raise ValueError("不能删除全部页面")

    if _cancelled(cancel_event):
        _remove_path(_temp_for(dest))
        return

    reader = _open_reader(src, password)
    writer = PdfWriter()
    for index in keep:
        writer.add_page(reader.pages[index - 1])
        if _cancelled(cancel_event):
            _remove_path(_temp_for(dest))
            return

    if _cancelled(cancel_event):
        _remove_path(_temp_for(dest))
        return
    _write_atomically(writer, dest, cancel_event)


def _cancelled(cancel_event: threading.Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _lookup_password(path: Path, passwords: dict[Path, str] | None) -> str | None:
    if not passwords:
        return None
    found = passwords.get(path)
    if found is not None:
        return found
    resolved = path.resolve()
    for key, value in passwords.items():
        if Path(key).resolve() == resolved:
            return value
    return None


def _unlock_encrypted_reader(reader: PdfReader, password: str | None) -> bool:
    if password is not None:
        try:
            decrypted = reader.decrypt(password)
        except Exception:
            return False
        return decrypted != PasswordType.NOT_DECRYPTED
    try:
        len(reader.pages)
    except Exception:
        return False
    return True


def _open_reader(path: Path, password: str | None) -> PdfReader:
    reader = PdfReader(path)
    if reader.is_encrypted and not _unlock_encrypted_reader(reader, password):
        raise ValueError("需要密码")
    return reader


def _temp_for(dest: Path) -> Path:
    return dest.with_name(TEMP_PREFIX + dest.name)


def _remove_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_atomically(
    writer: PdfWriter,
    dest: Path,
    cancel_event: threading.Event | None,
) -> None:
    dest_existed = dest.exists()
    temp = _temp_for(dest)
    try:
        if _cancelled(cancel_event):
            _remove_path(temp)
            if not dest_existed:
                _remove_path(dest)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        with temp.open("wb") as fh:
            writer.write(fh)
        if _cancelled(cancel_event):
            _remove_path(temp)
            if not dest_existed:
                _remove_path(dest)
            return
        os.replace(temp, dest)
    except Exception:
        _remove_path(temp)
        if not dest_existed:
            _remove_path(dest)
        raise
