from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "output" / "pdf" / "UGTOMS_AI_deterministic_knowledge_conduit.pdf"
RENDER_DIR = ROOT / "tmp" / "pdfs" / "ai_rendered"

REQUIRED_TEXT = (
    "Deterministic Knowledge Conduit",
    "UGTOMS",
    "UNKNOWN",
    "floating-point brute forcers",
    "Tests stay",
    "Human knowledge is the durable substrate",
    "LLMs remain valuable",
    "individual",
)
FORBIDDEN_DASHES = ("\u2013", "\u2014", "\u2011", "\u2212")


def render_pages(document: pymupdf.Document) -> list[Path]:
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    matrix = pymupdf.Matrix(1.6, 1.6)
    for page_number, page in enumerate(document, start=1):
        destination = RENDER_DIR / f"page-{page_number:02d}.png"
        page.get_pixmap(matrix=matrix, alpha=False).save(destination)
        rendered.append(destination)
    return rendered


def make_contact_sheet(rendered: list[Path]) -> Path:
    images = [Image.open(path).convert("RGB") for path in rendered]
    thumb_width = 520
    thumbs: list[Image.Image] = []
    for image in images:
        thumb_height = round(image.height * thumb_width / image.width)
        thumbs.append(image.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS))

    margin = 24
    label_height = 34
    columns = 2
    rows = (len(thumbs) + columns - 1) // columns
    cell_height = max(image.height for image in thumbs) + label_height
    sheet = Image.new(
        "RGB",
        (columns * thumb_width + (columns + 1) * margin, rows * cell_height + (rows + 1) * margin),
        "#DCE7EB",
    )
    draw = ImageDraw.Draw(sheet)
    for index, image in enumerate(thumbs):
        row, column = divmod(index, columns)
        x = margin + column * (thumb_width + margin)
        y = margin + row * cell_height
        draw.text((x, y), f"Page {index + 1}", fill="#071822")
        sheet.paste(image, (x, y + label_height))

    destination = RENDER_DIR / "contact-sheet.png"
    sheet.save(destination, optimize=True)
    return destination


def main() -> None:
    if not PDF.is_file():
        raise SystemExit(f"missing PDF: {PDF}")

    reader = PdfReader(PDF)
    if len(reader.pages) != 5:
        raise SystemExit(f"expected 5 pages, found {len(reader.pages)}")

    extracted_pages = [(page.extract_text() or "") for page in reader.pages]
    extracted = "\n".join(extracted_pages)
    normalized = " ".join(extracted.split())
    missing = [value for value in REQUIRED_TEXT if value not in normalized]
    if missing:
        raise SystemExit(f"required text missing: {missing}")
    if any(mark in extracted for mark in FORBIDDEN_DASHES):
        raise SystemExit("forbidden non-ASCII dash found in extracted PDF text")
    if any(len(text.strip()) < 100 for text in extracted_pages):
        raise SystemExit("one or more pages contain unexpectedly little extractable text")

    document = pymupdf.open(PDF)
    bounds_failures: list[str] = []
    for page_number, page in enumerate(document, start=1):
        page_rect = page.rect
        for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
            if not text.strip():
                continue
            if x0 < -0.5 or y0 < -0.5 or x1 > page_rect.width + 0.5 or y1 > page_rect.height + 0.5:
                bounds_failures.append(
                    f"page {page_number}: {text[:40]!r} at {(x0, y0, x1, y1)} outside {page_rect}"
                )
    if bounds_failures:
        raise SystemExit("out-of-bounds text blocks:\n" + "\n".join(bounds_failures))

    rendered = render_pages(document)
    contact_sheet = make_contact_sheet(rendered)
    digest = hashlib.sha256(PDF.read_bytes()).hexdigest().upper()
    print(f"PDF={PDF}")
    print(f"PAGES={len(reader.pages)}")
    print(f"BYTES={PDF.stat().st_size}")
    print(f"SHA256={digest}")
    print(f"RENDERED={len(rendered)}")
    print(f"CONTACT_SHEET={contact_sheet}")


if __name__ == "__main__":
    main()
