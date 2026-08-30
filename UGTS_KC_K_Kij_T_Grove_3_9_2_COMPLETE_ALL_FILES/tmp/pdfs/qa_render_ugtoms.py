from __future__ import annotations

import json
import shutil
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "output" / "pdf" / "UGTOMS_cross_domain_pilot_overview_review_draft.pdf"
RENDER_DIR = ROOT / "tmp" / "pdfs" / "rendered"
CONTACT_DIR = ROOT / "tmp" / "pdfs" / "contacts"

REQUIRED = [
    "UGTOMS",
    "The UGTOMS Claim",
    "Tom Klootwijk",
    "BSN (user-supplied): NL200678942",
    "10-07-1990",
    "Netherlands (NL)",
    "126",
    "8,064 B",
    "4,032 B",
    "4.364554 m",
    "25 m",
    "proposed",
    "not independently verified",
]


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def main() -> None:
    reset_dir(RENDER_DIR)
    reset_dir(CONTACT_DIR)

    reader = PdfReader(str(PDF))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    required = {item: item in extracted for item in REQUIRED}

    doc = pymupdf.open(PDF)
    page_info: list[dict] = []
    rendered_paths: list[Path] = []
    for index, page in enumerate(doc):
        rect = page.rect
        blocks = page.get_text("blocks")
        out_of_bounds = []
        for block in blocks:
            x0, y0, x1, y1 = block[:4]
            if x0 < -0.5 or y0 < -0.5 or x1 > rect.width + 0.5 or y1 > rect.height + 0.5:
                out_of_bounds.append([round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)])
        page_text = page.get_text("text")
        page_info.append(
            {
                "page": index + 1,
                "chars": len(page_text),
                "blocks": len(blocks),
                "images": len(page.get_images(full=True)),
                "out_of_bounds": out_of_bounds,
            }
        )
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        output = RENDER_DIR / f"page-{index + 1:02d}.png"
        pix.save(output)
        rendered_paths.append(output)

    for group_start in range(0, len(rendered_paths), 4):
        group = rendered_paths[group_start : group_start + 4]
        thumb_w, thumb_h = 600, 848
        canvas = Image.new("RGB", (thumb_w * 2 + 36, thumb_h * 2 + 60), "#CDD7DC")
        draw = ImageDraw.Draw(canvas)
        for slot, path in enumerate(group):
            with Image.open(path) as source:
                thumb = source.convert("RGB")
                thumb.thumbnail((thumb_w - 24, thumb_h - 32), Image.Resampling.LANCZOS)
            col, row = slot % 2, slot // 2
            x = 18 + col * thumb_w + (thumb_w - thumb.width) // 2
            y = 25 + row * thumb_h + (thumb_h - thumb.height) // 2
            canvas.paste(thumb, (x, y))
            draw.text((18 + col * thumb_w, 8 + row * thumb_h), f"Page {group_start + slot + 1}", fill="#102A36")
        contact = CONTACT_DIR / f"contact-{group_start // 4 + 1:02d}.png"
        canvas.save(contact, quality=95)

    source = (ROOT / "tmp" / "pdfs" / "build_ugtoms_cross_domain_overview.py").read_text(encoding="utf-8")
    forbidden_dashes = {
        "en_dash": "\u2013" in source,
        "em_dash": "\u2014" in source,
        "nonbreaking_hyphen": "\u2011" in source,
        "minus_sign": "\u2212" in source,
    }
    result = {
        "pdf": str(PDF),
        "bytes": PDF.stat().st_size,
        "pages": len(doc),
        "metadata": dict(reader.metadata or {}),
        "required": required,
        "forbidden_dashes_in_source": forbidden_dashes,
        "page_info": page_info,
        "render_dir": str(RENDER_DIR),
        "contact_dir": str(CONTACT_DIR),
    }
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
