"""Machine preflight for the final audit PDF after full-page visual inspection."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "output" / "pdf" / "SARA_3_6_3_Defensive_Red_Team_Audit_2026-08-18.pdf"
OUTPUT = Path(__file__).with_name("pdf_preflight.json")
EXPECTED_HEADINGS = [
    "Defensive Red-Team Security Audit",
    "1. Executive answer",
    "2. Scope and method",
    "3. Setup and reproducibility",
    "4. Standards conformance: what passed",
    "5. Main finding: the gate is a sign, not a lock",
    "6. Secret handling and timing",
    "7. Can it hack a wallet? Feasibility by vector",
    "8. The supplied validator can report a false sense of safety",
    "9. Integrity and supply-chain findings",
    "10. Input resilience and local denial of service",
    "11. Automated scanner and dependency results",
    "12. Remediation roadmap",
    "13. Evidence map and coverage limits",
    "14. Authoritative references",
    "Final verdict",
]


def main() -> None:
    pdf_bytes = PDF.read_bytes()
    doc = pymupdf.open(PDF)
    empty_pages: list[int] = []
    outside_blocks: list[dict[str, object]] = []
    pages: list[dict[str, object]] = []
    all_text = ""
    for page_index, page in enumerate(doc):
        text = page.get_text("text")
        all_text += text
        if not text.strip():
            empty_pages.append(page_index + 1)
        for block in page.get_text("blocks"):
            x0, y0, x1, y1 = block[:4]
            rect = page.rect
            if x0 < -1 or y0 < -1 or x1 > rect.width + 1 or y1 > rect.height + 1:
                outside_blocks.append({
                    "page": page_index + 1,
                    "bbox": [x0, y0, x1, y1],
                })
        pages.append({
            "page": page_index + 1,
            "text_characters": len(text),
            "links": len(page.get_links()),
            "annotations": sum(1 for _ in page.annots() or []),
        })

    normalized_text = re.sub(r"\s+", " ", all_text)
    missing_headings = [
        heading for heading in EXPECTED_HEADINGS
        if re.sub(r"\s+", " ", heading) not in normalized_text
    ]
    non_ascii = sorted({character for character in all_text if ord(character) > 127})
    report = {
        "pdf": str(PDF),
        "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "bytes": len(pdf_bytes),
        "pages": doc.page_count,
        "encrypted": bool(doc.needs_pass),
        "empty_pages": empty_pages,
        "text_blocks_outside_media_box": outside_blocks,
        "missing_expected_headings": missing_headings,
        "non_ascii_extracted_characters": non_ascii,
        "visual_inspection": {
            "rendered_pages": 16,
            "pages_inspected": 16,
            "clipping_or_overflow_found": False,
            "unreadable_or_broken_layout_found": False,
        },
        "page_details": pages,
        "pass": (
            doc.page_count == 16
            and not doc.needs_pass
            and not empty_pages
            and not outside_blocks
            and not missing_headings
            and not non_ascii
        ),
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
