"""Defensive scan of the pristine extracted package; never prints candidate values."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
PRISTINE = ROOT / "tmp" / "pristine_zip" / "UGTS_KC_3_6_3_SARA_Tom_Klootwijk"
OUTPUT = HERE.with_name("packaged_secret_scan.json")
TEXT_EXTENSIONS = {
    ".py", ".json", ".md", ".txt", ".toml", ".csv", ".yml", ".yaml",
}
FORBIDDEN_JSON_KEYS = {
    "private_key", "chain_code", "mnemonic", "passphrase", "seed", "xprv", "wif",
    "indices", "entropy_fingerprint", "mnemonic_fingerprint", "seed_fingerprint",
}
KNOWN_PUBLIC_VECTOR = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
)
XPRV_RE = re.compile(r"(?<![A-Za-z0-9])xprv[1-9A-HJ-NP-Za-km-z]{50,}(?![A-Za-z0-9])")
WIF_RE = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[5KL][1-9A-HJ-NP-Za-km-z]{50,51}(?![1-9A-HJ-NP-Za-km-z])")


def classify_json_hit(relative_path: str, json_path: str) -> str:
    if relative_path.endswith("sclp_example.json") and json_path.endswith("literal.jitter.seed"):
        return "non-cryptographic deterministic SCLP control seed"
    return "potential wallet-secret field requiring review"


def walk_json(
    value: object,
    path: str,
    relative_path: str,
    findings: list[dict[str, object]],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in FORBIDDEN_JSON_KEYS and child not in (None, "", [], {}):
                findings.append({
                    "json_path": next_path,
                    "value_type": type(child).__name__,
                    "classification": classify_json_hit(relative_path, next_path),
                })
            walk_json(child, next_path, relative_path, findings)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk_json(child, f"{path}[{index}]", relative_path, findings)


def main() -> None:
    if not PRISTINE.is_dir():
        raise SystemExit(f"Pristine package not found: {PRISTINE}")

    credential_hits: list[dict[str, object]] = []
    json_key_hits: list[dict[str, object]] = []
    public_fixture_hits: list[dict[str, object]] = []
    scanned_files = 0
    scanned_bytes = 0
    extension_counts: Counter[str] = Counter()

    for path in sorted(PRISTINE.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        rel = path.relative_to(PRISTINE).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned_files += 1
        scanned_bytes += len(text.encode("utf-8"))
        extension_counts[path.suffix.lower()] += 1

        xprv_count = len(XPRV_RE.findall(text))
        wif_count = len(WIF_RE.findall(text))
        if xprv_count or wif_count:
            credential_hits.append({
                "path": rel,
                "xprv_encoded_value_count": xprv_count,
                "wif_encoded_value_count": wif_count,
            })

        public_count = text.count(KNOWN_PUBLIC_VECTOR)
        if public_count:
            public_fixture_hits.append({
                "path": rel,
                "count": public_count,
                "classification": "official BIP39 public test vector",
            })

        if path.suffix.lower() == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            local_findings: list[dict[str, object]] = []
            walk_json(data, "", rel, local_findings)
            if local_findings:
                json_key_hits.append({"path": rel, "findings": local_findings})

    suspicious_json_hits = [
        {"path": item["path"], "finding": finding}
        for item in json_key_hits
        for finding in item["findings"]
        if finding["classification"] == "potential wallet-secret field requiring review"
    ]
    report = {
        "scope": "pristine ZIP extraction only",
        "scanned_files": scanned_files,
        "scanned_utf8_bytes": scanned_bytes,
        "file_extensions": dict(sorted(extension_counts.items())),
        "encoded_private_credential_hits": credential_hits,
        "forbidden_nonempty_json_key_hits": json_key_hits,
        "suspicious_wallet_secret_json_hits": suspicious_json_hits,
        "known_public_bip39_fixture_hits": public_fixture_hits,
        "unexpected_private_material_detected": bool(credential_hits or suspicious_json_hits),
        "limitations": [
            "Pattern scanning cannot prove absence of encrypted, obfuscated, binary, or novel secret encodings.",
            "Generic 64-hex strings were not classified as private keys because the package legitimately contains SHA-256 hashes and public test vectors.",
            "The well-known BIP39 vector is public test material, not a real wallet secret.",
        ],
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
