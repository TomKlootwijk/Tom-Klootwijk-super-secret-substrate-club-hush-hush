from __future__ import annotations

import ast
import json
import os
import random
import socket
import statistics
import subprocess
import time
import urllib.request
from dataclasses import asdict
from pathlib import Path

from ugts36.sara363 import (
    authorize_audit,
    build_reference_sara363_certificate,
    decode_segwit_address,
    derive_bip84_public_certificate,
    estimate_uniform_search,
    load_bip39_wordlist,
    master_node_from_seed,
    mnemonic_to_seed,
    parse_derivation_path,
    validate_mnemonic,
)
from ugts36.sara_runtime import SARARuntime


ROOT = Path(__file__).resolve().parents[2]
WORDLIST = ROOT / "data" / "bip39_english.txt"
TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"


def timed_rate(callable_, count: int) -> tuple[float, float]:
    samples: list[float] = []
    for _ in range(5):
        start = time.perf_counter()
        for _ in range(count):
            callable_()
        samples.append(time.perf_counter() - start)
    median_seconds = statistics.median(samples)
    return count / median_seconds, median_seconds


def validator_scanner(source: str) -> dict[str, object]:
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    function_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_names.add(node.name.lower())
    network_modules = {"socket", "requests", "urllib", "httpx", "aiohttp", "websockets"}
    prohibited_fragments = (
        "broadcast",
        "sendraw",
        "sign_transaction",
        "scan_private",
        "bruteforce",
        "brute_force",
        "enumerate_mnemonic",
    )
    return {
        "network_imports": sorted(imported_modules & network_modules),
        "prohibited_function_names": sorted(
            name for name in function_names if any(fragment in name for fragment in prohibited_fragments)
        ),
    }


def runtime_capability_probe() -> dict[str, object]:
    calls: list[str] = []
    file_modes: list[str] = []
    original_socket = socket.socket
    original_popen = subprocess.Popen
    original_system = os.system
    original_urlopen = urllib.request.urlopen
    original_path_open = Path.open

    def blocked(name: str):
        def inner(*args, **kwargs):
            calls.append(name)
            raise RuntimeError(f"blocked capability invoked: {name}")

        return inner

    def observed_open(self: Path, mode: str = "r", *args, **kwargs):
        file_modes.append(mode)
        return original_path_open(self, mode, *args, **kwargs)

    socket.socket = blocked("socket.socket")
    subprocess.Popen = blocked("subprocess.Popen")
    os.system = blocked("os.system")
    urllib.request.urlopen = blocked("urllib.request.urlopen")
    Path.open = observed_open
    runtime_ok = False
    result: dict[str, object] | None = None
    try:
        result = SARARuntime(WORDLIST).run_reference()
        runtime_ok = True
    finally:
        socket.socket = original_socket
        subprocess.Popen = original_popen
        os.system = original_system
        urllib.request.urlopen = original_urlopen
        Path.open = original_path_open
    trace = result["trace"] if result else []
    return {
        "runtime_completed": runtime_ok,
        "blocked_capability_calls": calls,
        "file_open_modes": file_modes,
        "write_like_file_opens": [mode for mode in file_modes if any(flag in mode for flag in "wax+")],
        "trace_entries": len(trace),
        "absolute_path_disclosed_in_trace": bool(trace and Path(trace[0]["detail"]["path"]).is_absolute()),
    }


def main() -> None:
    words = load_bip39_wordlist(WORDLIST)
    validation = validate_mnemonic(TEST_MNEMONIC, words)
    seed = mnemonic_to_seed(TEST_MNEMONIC, "TREZOR")
    node = master_node_from_seed(seed)
    node_dict = asdict(node)
    node_repr = repr(node)

    forbidden = authorize_audit("public fixture", ["passphrase_spray"])
    self_asserted = authorize_audit("unverified ownership claim", ["self_owned_known_seed_derivation"])
    direct_certificate = derive_bip84_public_certificate(TEST_MNEMONIC, passphrase="TREZOR")

    public_certificate = build_reference_sara363_certificate(WORDLIST)
    public_json = json.dumps(asdict(public_certificate), sort_keys=True)
    secret_value_presence = {
        "mnemonic": TEST_MNEMONIC in public_json,
        "seed_hex": seed.hex() in public_json,
        "private_key_decimal": str(node.private_key) in public_json,
        "private_key_hex": f"{node.private_key:064x}" in public_json,
        "chain_code_hex": node.chain_code.hex() in public_json,
    }

    seed_rate, seed_batch_seconds = timed_rate(
        lambda: mnemonic_to_seed(TEST_MNEMONIC, "benchmark-passphrase"), 250
    )
    derivation_rate, derivation_batch_seconds = timed_rate(
        lambda: derive_bip84_public_certificate(TEST_MNEMONIC, passphrase="benchmark-passphrase"), 2
    )
    expected_128_years_at_measured_derivation = (2**127 / derivation_rate) / 31_557_600.0
    expected_million_dictionary_seconds = 500_000.0 / derivation_rate

    random_source = random.Random(363)
    fuzz_latencies: list[float] = []
    fuzz_accepted = 0
    for _ in range(10_000):
        length = random_source.randint(0, 120)
        candidate = "".join(chr(random_source.randint(32, 126)) for _ in range(length))
        start = time.perf_counter()
        try:
            decode_segwit_address(candidate)
            fuzz_accepted += 1
        except (ValueError, UnicodeError):
            pass
        fuzz_latencies.append(time.perf_counter() - start)

    path_components = 100_000
    huge_path = "m/" + "/".join("0" for _ in range(path_components))
    start = time.perf_counter()
    parsed = parse_derivation_path(huge_path)
    path_parse_seconds = time.perf_counter() - start

    start = time.perf_counter()
    estimate_exception = None
    try:
        estimate_uniform_search(1_000_000, 1.0)
    except Exception as exc:  # intentionally records failure behavior only
        estimate_exception = type(exc).__name__
    estimate_seconds = time.perf_counter() - start

    runtime = SARARuntime(WORDLIST)
    first_trace_count = len(runtime.run_reference()["trace"])
    second_trace_count = len(runtime.run_reference()["trace"])

    evasive_source = '''
def approve_transaction(payload):
    module = __import__("socket")
    return module
'''
    evasive_scan = validator_scanner(evasive_source)
    validator_source = (ROOT / "tools" / "validate_sara363_package.py").read_text(encoding="utf-8")

    report = {
        "scope": "non-destructive local defensive probes using only public test vectors",
        "authorization_gate": {
            "forbidden_scope_authorized": forbidden.authorized,
            "forbidden_reason_codes": list(forbidden.reason_codes),
            "self_asserted_scope_authorized_without_ownership_proof": self_asserted.authorized,
            "direct_derivation_succeeds_without_authorization_certificate": bool(direct_certificate.address),
            "direct_derivation_api_has_authorization_parameter": False,
        },
        "secret_boundary": {
            "hdnode_asdict_keys": sorted(node_dict),
            "hdnode_repr_contains_private_key": str(node.private_key) in node_repr,
            "hdnode_repr_contains_chain_code": repr(node.chain_code) in node_repr,
            "mnemonic_validation_asdict_keys": sorted(asdict(validation)),
            "public_certificate_contains_exact_secret_values": secret_value_presence,
            "hdnode_has_zeroize_method": hasattr(node, "zeroize"),
            "inputs_are_immutable_python_types": {"mnemonic": "str", "passphrase": "str", "seed": "bytes"},
        },
        "runtime_capabilities": runtime_capability_probe(),
        "validator_strength": {
            "evasive_dynamic_import_scan_result": evasive_scan,
            "evasive_source_actually_contains_dynamic_socket_import": '__import__("socket")' in evasive_source,
            "reads_stored_test_transcript_instead_of_running_tests": "test_path.read_text" in validator_source,
            "visual_inspection_count_is_hardcoded": '"rendered_pages_visually_inspected": 18' in validator_source,
            "runtime_capability_flags_are_read_from_certificate": 'certificate["audit_boundary"]["network_access"]' in validator_source,
            "source_files_scanned_for_imports": 2,
        },
        "performance": {
            "pbkdf2_seed_derivations_per_second": seed_rate,
            "pbkdf2_measurement_batch_seconds": seed_batch_seconds,
            "full_bip84_derivations_per_second": derivation_rate,
            "full_derivation_measurement_batch_seconds": derivation_batch_seconds,
            "expected_128_bit_search_years_at_measured_full_derivation_rate": expected_128_years_at_measured_derivation,
            "expected_half_of_one_million_passphrase_dictionary_seconds_at_measured_rate": expected_million_dictionary_seconds,
        },
        "input_resilience": {
            "random_bech32_cases": len(fuzz_latencies),
            "random_bech32_cases_accepted": fuzz_accepted,
            "bech32_latency_p95_microseconds": statistics.quantiles(fuzz_latencies, n=100)[94] * 1e6,
            "bech32_latency_max_microseconds": max(fuzz_latencies) * 1e6,
            "derivation_path_components_accepted": len(parsed),
            "derivation_path_parse_seconds": path_parse_seconds,
            "derivation_path_component_limit_enforced": False,
            "million_bit_estimate_exception": estimate_exception,
            "million_bit_estimate_seconds": estimate_seconds,
            "search_bits_upper_bound_enforced": False,
            "runtime_trace_count_after_first_run": first_trace_count,
            "runtime_trace_count_after_second_run": second_trace_count,
            "trace_is_reset_between_runs": second_trace_count == first_trace_count,
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
