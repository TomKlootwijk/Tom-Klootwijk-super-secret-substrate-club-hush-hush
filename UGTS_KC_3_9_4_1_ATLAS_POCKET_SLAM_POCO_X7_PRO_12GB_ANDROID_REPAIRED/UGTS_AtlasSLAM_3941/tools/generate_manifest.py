#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS = ROOT / "checksums"
CHECKSUMS.mkdir(exist_ok=True)
MANIFEST = CHECKSUMS / "SHA256SUMS.txt"
CONTENT_ROOT = CHECKSUMS / "CONTENT_ROOT_SHA256.txt"
EXCLUDED = {
    MANIFEST.relative_to(ROOT).as_posix(),
    CONTENT_ROOT.relative_to(ROOT).as_posix(),
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


lines = []
for path in sorted(ROOT.rglob("*")):
    if not path.is_file() or path.is_symlink():
        continue
    relative = path.relative_to(ROOT).as_posix()
    if relative in EXCLUDED:
        continue
    lines.append(f"{digest(path)}  {relative}")
MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
content_root = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
CONTENT_ROOT.write_text(content_root + "  SHA256SUMS.txt\n", encoding="utf-8")
print(f"manifest_files={len(lines)}")
print(f"content_root_sha256={content_root}")
