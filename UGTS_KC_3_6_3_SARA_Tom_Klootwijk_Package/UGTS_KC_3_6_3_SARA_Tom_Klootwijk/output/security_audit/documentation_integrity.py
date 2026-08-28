"""Compare policy-document metadata with the pristine source ZIP without restoring files."""

from __future__ import annotations

import difflib
import hashlib
import json
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
ARCHIVE = Path(
    r"C:\Users\Tom\Documents\TomKlootwijkVentureCorp\Klootwijk\UGTS_KC_3_6_3_SARA_Tom_Klootwijk_Package.zip"
)
OUTPUT = HERE.with_name("documentation_integrity.json")
FILES = {
    "README.md": [
        "Non-negotiable security boundary",
        "third-party wallet brute force",
    ],
    "SECURITY.md": [
        "Rejected capabilities",
        "Third-party key search",
        "Transaction signing",
    ],
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_entry_name(name: str) -> str:
    matches = [entry for entry in zipfile.ZipFile(ARCHIVE).namelist() if entry.endswith("/" + name)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one archive entry for {name}, found {len(matches)}")
    return matches[0]


def main() -> None:
    result: dict[str, object] = {
        "archive": str(ARCHIVE),
        "archive_sha256": sha256(ARCHIVE.read_bytes()),
        "files": {},
        "policy_guard_weakened": False,
    }
    with zipfile.ZipFile(ARCHIVE) as archive:
        for name, phrases in FILES.items():
            original = archive.read(archive_entry_name(name))
            current = (ROOT / name).read_bytes()
            original_text = original.decode("utf-8")
            current_text = current.decode("utf-8")
            changes = list(
                difflib.unified_diff(
                    original_text.splitlines(), current_text.splitlines(), lineterm=""
                )
            )
            removed_lines = sum(1 for line in changes if line.startswith("-") and not line.startswith("---"))
            added_lines = sum(1 for line in changes if line.startswith("+") and not line.startswith("+++"))
            phrase_status = {
                phrase: {
                    "present_in_archive": phrase.lower() in original_text.lower(),
                    "present_in_current": phrase.lower() in current_text.lower(),
                }
                for phrase in phrases
            }
            weakened = any(
                item["present_in_archive"] and not item["present_in_current"]
                for item in phrase_status.values()
            )
            result["files"][name] = {
                "archive_sha256": sha256(original),
                "current_sha256": sha256(current),
                "hash_match": original == current,
                "archive_bytes": len(original),
                "current_bytes": len(current),
                "diff_removed_lines": removed_lines,
                "diff_added_lines": added_lines,
                "policy_phrase_status": phrase_status,
                "policy_guard_weakened": weakened,
            }
            result["policy_guard_weakened"] = result["policy_guard_weakened"] or weakened

    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
