from pathlib import Path
import threading
from pypdf import PdfReader
from office_assistant.pdf_ops import delete_pages, merge_pdfs, probe_pdf
from tests.conftest import make_blank_pdf


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
