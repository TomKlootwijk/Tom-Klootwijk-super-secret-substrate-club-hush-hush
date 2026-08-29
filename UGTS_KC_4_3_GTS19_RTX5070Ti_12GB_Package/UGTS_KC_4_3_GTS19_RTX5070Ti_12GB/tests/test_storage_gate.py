from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.storage_gate import (
    COLLISION_DIGEST_HEX,
    EVIDENCE_FORMAT,
    generate_storage_evidence,
    load_storage_evidence,
    validate_storage_evidence,
)


ARCHIVED_EVIDENCE = ROOT / "evidence" / "local_m2_storage_gate.json"
GATE = ROOT / "scripts" / "storage_gate.py"


def _archived() -> dict:
    return load_storage_evidence(ARCHIVED_EVIDENCE)


def test_archived_evidence_is_canonical_and_strictly_accepted() -> None:
    payload = _archived()
    validate_storage_evidence(payload)
    assert payload["evidence_format"] == EVIDENCE_FORMAT
    assert payload["root_19x19_status"] == "UNKNOWN"


def test_fresh_runs_are_deterministic_and_match_the_archive(tmp_path: Path) -> None:
    first = generate_storage_evidence(tmp_path / "first")
    second = generate_storage_evidence(tmp_path / "second")
    assert first == second == _archived()


def test_archive_records_exact_restart_spill_pin_and_collision_checks() -> None:
    payload = _archived()
    case = payload["case"]
    history = case["persistent_history"]
    parity = case["persistent_engine_parity"]
    store = case["segment_store"]
    collision = payload["collision_case"]

    assert case["move"] == 180
    assert history["board_bytes"] == 361
    assert history["initial_member_count"] == 1
    assert history["one_move_member_count"] == 2
    assert history["canonical_across_fresh_stores"] is True
    assert history["trusted_root_pin_verifications"] == 2
    assert parity["matched_exact_field_count"] == 8
    assert parity["exact_history_members_equal"] is True

    assert store["lazy_payloads"] is True
    assert store["auto_spill_generation"] == 1
    assert store["final_generation"] == 2
    assert store["resident_payload_bytes_after_spill"] == 0
    assert store["resident_payload_bytes_after_restart"] == 0
    assert store["exact_reads_after_restart"] == 3
    assert store["pinned_history_rehydrate_root_sha256"] == history[
        "one_move_root_sha256"
    ]
    assert len(store["segment_sha256s"]) == 2

    assert collision["index_digest"] == COLLISION_DIGEST_HEX
    assert collision["collision_bucket_size_after_restart"] == 2
    assert collision["ambiguous_digest_only_read_rejected"] is True
    assert collision["exact_reads_after_restart"] == 2
    assert collision["resident_payload_bytes_after_restart"] == 0


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.pop("scope"),
        lambda value: value.__setitem__("claim", "Black wins"),
        lambda value: value.__setitem__("root_19x19_status", "PROVEN"),
        lambda value: value["rules"].__setitem__("komi2", 13),
        lambda value: value["limitations"].pop(),
    ),
)
def test_validator_rejects_noncanonical_or_unpinned_envelopes(mutation) -> None:
    payload = copy.deepcopy(_archived())
    mutation(payload)
    with pytest.raises(ValueError):
        validate_storage_evidence(payload)


@pytest.mark.parametrize(
    "path,value",
    (
        (("case", "move"), True),
        (("case", "persistent_history", "board_bytes"), True),
        (("case", "persistent_engine_parity", "captured"), False),
        (("case", "segment_store", "object_count"), True),
        (("collision_case", "object_count"), True),
    ),
)
def test_validator_does_not_accept_booleans_as_exact_integers(
    path: tuple[str, ...], value: bool
) -> None:
    payload = copy.deepcopy(_archived())
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError, match="integer"):
        validate_storage_evidence(payload)


def test_validator_rejects_broken_cross_field_and_collision_invariants() -> None:
    payload = copy.deepcopy(_archived())
    payload["case"]["segment_store"]["pinned_history_rehydrate_root_sha256"] = (
        "0" * 64
    )
    with pytest.raises(ValueError, match="trusted root pin"):
        validate_storage_evidence(payload)

    payload = copy.deepcopy(_archived())
    payload["case"]["segment_store"]["object_refs"]["history"]["kind"] = "board"
    with pytest.raises(ValueError, match="kind"):
        validate_storage_evidence(payload)

    payload = copy.deepcopy(_archived())
    payload["collision_case"]["index_digest"] = "a4" * 32
    with pytest.raises(ValueError, match="injected constant"):
        validate_storage_evidence(payload)

    payload = copy.deepcopy(_archived())
    payload["collision_case"]["payload_sha256s"].reverse()
    with pytest.raises(ValueError, match="canonically sorted"):
        validate_storage_evidence(payload)


def test_loader_rejects_duplicate_keys_and_noncanonical_json(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"root_19x19_status":"UNKNOWN","root_19x19_status":"PROVEN"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_storage_evidence(duplicate)

    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(_archived(), indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="canonical JSON form"):
        load_storage_evidence(pretty)

    missing_newline = tmp_path / "missing-newline.json"
    missing_newline.write_bytes(ARCHIVED_EVIDENCE.read_bytes().rstrip(b"\n"))
    with pytest.raises(ValueError, match="exactly one newline"):
        load_storage_evidence(missing_newline)


def test_cli_validates_archive_by_fresh_deterministic_execution() -> None:
    process = subprocess.run(
        [sys.executable, str(GATE), "--validate", str(ARCHIVED_EVIDENCE)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert "root status remains UNKNOWN" in process.stdout
    assert "solved" not in process.stdout.lower()


def test_cli_rejects_well_formed_hash_tamper_via_self_comparison(
    tmp_path: Path,
) -> None:
    payload = copy.deepcopy(_archived())
    payload["case"]["persistent_history"]["serialized_file_sha256"] = "0" * 64
    tampered = tmp_path / "tampered.json"
    from ugts_go19.digests import canonical_json_bytes

    tampered.write_bytes(canonical_json_bytes(payload) + b"\n")
    process = subprocess.run(
        [sys.executable, str(GATE), "--validate", str(tampered)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode != 0
    assert "differs from deterministic fresh execution" in process.stderr


def test_cli_generation_is_canonical_and_revalidates(tmp_path: Path) -> None:
    generated = tmp_path / "generated.json"
    generate = subprocess.run(
        [sys.executable, str(GATE), "--output", str(generated)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert generate.returncode == 0, generate.stderr
    assert generated.read_bytes() == ARCHIVED_EVIDENCE.read_bytes()

    validate = subprocess.run(
        [sys.executable, str(GATE), "--validate", str(generated)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert validate.returncode == 0, validate.stderr

