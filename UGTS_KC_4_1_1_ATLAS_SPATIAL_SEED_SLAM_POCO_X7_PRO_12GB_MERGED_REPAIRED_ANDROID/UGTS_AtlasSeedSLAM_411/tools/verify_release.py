#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

EXCLUDED = {"checksums/SHA256SUMS.txt", "checksums/CONTENT_ROOT_SHA256.txt"}
FORBIDDEN_PARTS = {"build", ".gradle", ".cxx", ".idea", "__pycache__"}


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_manifest(root: Path) -> dict[str, str]:
    result = {}
    for line in (root / "checksums/SHA256SUMS.txt").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        result[relative] = digest
    return result


def verify_directory(root: Path) -> dict:
    errors = []
    manifest = load_manifest(root)
    files = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    actual_manifest_scope = set(files) - EXCLUDED
    if actual_manifest_scope != set(manifest):
        errors.append(
            "manifest scope mismatch: missing="
            + repr(sorted(set(manifest) - actual_manifest_scope)[:10])
            + " extra="
            + repr(sorted(actual_manifest_scope - set(manifest))[:10])
        )
    for relative, expected in manifest.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing file: {relative}")
        elif sha256(path) != expected:
            errors.append(f"hash mismatch: {relative}")
    for relative in files:
        parts = PurePosixPath(relative).parts
        if any(part in FORBIDDEN_PARTS for part in parts):
            errors.append(f"forbidden generated path: {relative}")
        if relative == "local.properties" or relative.endswith(".iml"):
            errors.append(f"machine-specific file: {relative}")
    max_path = max((len(relative) for relative in files), default=0)
    if max_path > 180:
        errors.append(f"internal relative path exceeds 180 characters: {max_path}")
    scripts = [root / "gradlew", *sorted((root / "tools").glob("*.sh"))]
    for script in scripts:
        if script.exists() and not os.access(script, os.X_OK):
            errors.append(f"script not executable: {script.relative_to(root)}")
    content_root = hashlib.sha256((root / "checksums/SHA256SUMS.txt").read_bytes()).hexdigest()
    recorded = (root / "checksums/CONTENT_ROOT_SHA256.txt").read_text().split()[0]
    if content_root != recorded:
        errors.append("content-root checksum mismatch")
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "files": len(files),
        "manifested_files": len(manifest),
        "max_relative_path_characters": max_path,
        "content_root_sha256": content_root,
    }


def safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and "\\" not in name


def verify_zip(path: Path) -> dict:
    errors = []
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            errors.append(f"CRC failure: {bad}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            errors.append("duplicate member names")
        for info in archive.infolist():
            if not safe_member(info.filename):
                errors.append(f"unsafe member: {info.filename}")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                errors.append(f"non-portable compression method: {info.filename}")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                errors.append(f"symlink member: {info.filename}")
        roots = {PurePosixPath(name).parts[0] for name in names if name}
        if roots != {"UGTS_AtlasSeedSLAM_411"}:
            errors.append(f"unexpected ZIP roots: {sorted(roots)}")
        max_path = max(map(len, names), default=0)
        if max_path > 210:
            errors.append(f"ZIP member path exceeds 210 characters: {max_path}")
        with tempfile.TemporaryDirectory(prefix="ugts_zip_verify_") as temporary:
            archive.extractall(temporary)
            for info in archive.infolist():
                mode = (info.external_attr >> 16) & 0o777
                extracted = Path(temporary) / info.filename
                if mode and extracted.is_file():
                    extracted.chmod(mode)
            directory_result = verify_directory(Path(temporary) / "UGTS_AtlasSeedSLAM_411")
            if directory_result["status"] != "PASS":
                errors.extend("extracted: " + item for item in directory_result["errors"])
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "zip_sha256": sha256(path),
        "zip_bytes": path.stat().st_size,
        "members": len(names),
        "max_member_path_characters": max_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    result = verify_zip(args.path) if args.path.suffix.lower() == ".zip" else verify_directory(args.path)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
