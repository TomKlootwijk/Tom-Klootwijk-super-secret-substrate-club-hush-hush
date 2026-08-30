from pathlib import Path
import re
import sys

from pypdf import PdfReader

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


path = Path(sys.argv[1])
terms = [term.lower() for term in sys.argv[2:]]
reader = PdfReader(str(path))
print(f"FILE={path.name} PAGES={len(reader.pages)}")
for index, page in enumerate(reader.pages):
    text = page.extract_text() or ""
    lowered = text.lower()
    if not terms or any(term in lowered for term in terms):
        clean = re.sub(r"[ \t]+", " ", text)
        print(f"\n===== PAGE {index + 1} =====\n{clean}")
