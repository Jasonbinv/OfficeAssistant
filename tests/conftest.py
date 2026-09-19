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
