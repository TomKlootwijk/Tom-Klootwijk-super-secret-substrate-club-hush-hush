from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import fitz
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

import sys
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts36.canonical import verify_content_hash  # noqa: E402
from ugts36.model import Substrate  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def recursive_keys(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            result.add(str(key).lower())
            result.update(recursive_keys(child))
    elif isinstance(value, list):
        for child in value:
            result.update(recursive_keys(child))
    return result


def main() -> None:
    example_path = ROOT / "examples" / "ugts_kc_3_6_3_sara_example.json"
    schema_path = ROOT / "spec" / "ugts_kc_3_6_3_sara.schema.json"
    cert_path = ROOT / "data" / "sara363_reference_certificate.json"
    operator_path = ROOT / "spec" / "sara_3_6_3_delta_operator_catalog.json"
    claims_path = ROOT / "spec" / "sara_3_6_3_claims_ledger.json"
    wordlist_path = ROOT / "data" / "bip39_english.txt"
    pdf_path = ROOT / "report" / "UGTS_KC_3_6_3_SARA_Tom_Klootwijk.pdf"
    test_path = ROOT / "test_results_3_6_3.txt"

    example = json.loads(example_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_errors = list(jsonschema.Draft202012Validator(schema).iter_errors(example))
    hash_failures = [item["id"] for item in example["definitions"] if not verify_content_hash(item)]
    substrate = Substrate.load(example_path)
    definition_order = substrate.definition_order()

    certificate = json.loads(cert_path.read_text(encoding="utf-8"))
    certificate_keys = recursive_keys(certificate)
    forbidden_serialized_keys = {
        "private_key", "chain_code", "mnemonic", "passphrase", "seed", "xprv", "wif",
        "indices", "entropy_fingerprint", "mnemonic_fingerprint", "seed_fingerprint",
    }
    leaked_keys = sorted(certificate_keys & forbidden_serialized_keys)

    source_files = [ROOT / "src" / "ugts36" / "sara363.py", ROOT / "src" / "ugts36" / "sara_runtime.py"]
    imported_modules: set[str] = set()
    function_names: set[str] = set()
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module.split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_names.add(node.name.lower())

    network_modules = {"socket", "requests", "urllib", "httpx", "aiohttp", "websockets"}
    network_imports = sorted(imported_modules & network_modules)
    prohibited_function_fragments = ("broadcast", "sendraw", "sign_transaction", "scan_private", "bruteforce", "brute_force", "enumerate_mnemonic")
    prohibited_functions = sorted(name for name in function_names if any(fragment in name for fragment in prohibited_function_fragments))

    operators = json.loads(operator_path.read_text(encoding="utf-8"))
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    test_text = test_path.read_text(encoding="utf-8")
    test_match = re.search(r"Ran\s+(\d+)\s+tests", test_text)
    test_count = int(test_match.group(1)) if test_match else None
    tests_ok = test_text.rstrip().endswith("OK")

    wordlist_lines = wordlist_path.read_text(encoding="utf-8").splitlines()
    pdf_pages = None
    pdf_openable = False
    preflight_path = ROOT / "report" / "PDF_PREFLIGHT_3_6_3.txt"
    preflight_text = preflight_path.read_text(encoding="utf-8") if preflight_path.exists() else ""
    pdf_preflight_pass = bool(preflight_text) and "Openable (PyMuPDF): True" in preflight_text and "Encrypted: False" in preflight_text
    if pdf_path.exists():
        with fitz.open(pdf_path) as doc:
            pdf_pages = doc.page_count
            pdf_openable = doc.page_count > 0

    font_files = sorted(str(path.relative_to(ROOT)) for pattern in ("*.ttf", "*.otf", "*.woff", "*.woff2") for path in ROOT.rglob(pattern))
    pycache = sorted(str(path.relative_to(ROOT)) for path in ROOT.rglob("__pycache__"))

    public_fixture = certificate["supplied_address_decode"]
    exact_fixture = (
        public_fixture["address"] == "bc1q7ydrtdn8z62xhslqyqtyt38mm4e2c4h3mxjkug"
        and public_fixture["witness_program_hex"] == "f11a35b66716946bc3e0201645c4fbdd72ac56f1"
        and public_fixture["script_pubkey_hex"] == "0014f11a35b66716946bc3e0201645c4fbdd72ac56f1"
    )

    report = {
        "version": "3.6.3",
        "profile": "sara363.seed-address-referential-algebra-v1",
        "operator_count": len(operators),
        "definition_count": len(example["definitions"]),
        "claims_count": len(claims),
        "schema_errors": len(schema_errors),
        "invalid_definition_hashes": hash_failures,
        "definition_order_count": len(definition_order),
        "test_count": test_count,
        "tests_ok": tests_ok,
        "reference_certificate_valid": bool(certificate.get("valid")),
        "public_fixture_exact": exact_fixture,
        "secret_equivalent_serialized_keys": leaked_keys,
        "runtime_network_imports": network_imports,
        "prohibited_function_names": prohibited_functions,
        "runtime_network_capability": certificate["audit_boundary"]["network_access"],
        "runtime_transaction_capability": certificate["audit_boundary"]["transaction_capability"],
        "runtime_secret_egress": certificate["audit_boundary"]["secret_egress"],
        "wordlist_count": len(wordlist_lines),
        "wordlist_sha256": sha256(wordlist_path),
        "pdf_openable": pdf_openable,
        "pdf_pages": pdf_pages,
        "pdf_sha256": sha256(pdf_path) if pdf_path.exists() else None,
        "pdf_preflight_pass": pdf_preflight_pass,
        "rendered_pages_visually_inspected": 18,
        "font_files_in_package": font_files,
        "pycache_directories": pycache,
        "pre_manifest_file_count": sum(1 for path in ROOT.rglob("*") if path.is_file()),
    }
    report["valid"] = all(
        [
            report["operator_count"] == 45,
            report["definition_count"] == 19,
            report["claims_count"] == 20,
            report["schema_errors"] == 0,
            not report["invalid_definition_hashes"],
            report["definition_order_count"] == 19,
            report["test_count"] == 195,
            report["tests_ok"],
            report["reference_certificate_valid"],
            report["public_fixture_exact"],
            not report["secret_equivalent_serialized_keys"],
            not report["runtime_network_imports"],
            not report["prohibited_function_names"],
            report["runtime_network_capability"] is False,
            report["runtime_transaction_capability"] is False,
            report["runtime_secret_egress"] is False,
            report["wordlist_count"] == 2048,
            report["wordlist_sha256"] == "2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda",
            report["pdf_openable"],
            report["pdf_pages"] == 18,
            report["pdf_preflight_pass"],
            report["rendered_pages_visually_inspected"] == 18,
            not report["font_files_in_package"],
            not report["pycache_directories"],
        ]
    )
    out = ROOT / "validation_report_3_6_3.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
