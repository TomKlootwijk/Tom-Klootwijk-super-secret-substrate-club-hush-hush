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

from scripts.persistent_pndag_gate import (  # noqa: E402
    EVIDENCE_FORMAT,
    LIMITATIONS,
    generate_persistent_pndag_evidence,
    load_persistent_pndag_evidence,
    validate_persistent_pndag_evidence,
)
from ugts_go19.digests import canonical_json_bytes  # noqa: E402


ARCHIVED_EVIDENCE = ROOT / "evidence" / "local_m2_persistent_pndag_gate.json"
GATE = ROOT / "scripts" / "persistent_pndag_gate.py"


def _archived() -> dict:
    return load_persistent_pndag_evidence(ARCHIVED_EVIDENCE)


def test_archived_evidence_is_canonical_strict_and_explicitly_bounded() -> None:
    payload = _archived()
    validate_persistent_pndag_evidence(payload)

    assert payload["evidence_format"] == EVIDENCE_FORMAT
    assert payload["root_19x19_status"] == "UNKNOWN"
    assert payload["limitations"] == list(LIMITATIONS)
    assert "not archived" in payload["resource_accounting"]["runtime"]
    assert "not measured" in payload["resource_accounting"]["peak_rss"]
    assert payload["resource_accounting"]["archived_checkpoint_files"] == 0
    assert "lazy mmap" in payload["resource_accounting"]["segment_store_payload_mode"]
    assert (
        "temporary" in payload["resource_accounting"]["checkpoint_generation_retention"]
    )


def test_fresh_run_matches_archive_and_removes_bulky_checkpoints(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    generated = generate_persistent_pndag_evidence(work)

    assert generated == _archived()
    assert work.is_dir()
    assert list(work.iterdir()) == []


def test_archive_records_unknown_partials_exact_outcomes_and_restart_matches() -> None:
    payload = _archived()
    proven, disproven = payload["cases"]

    assert proven["threshold2"] == 1
    assert proven["partial"]["status"] == "UNKNOWN"
    assert proven["completed_after_restart"]["status"] == "PROVEN"
    assert proven["completed_after_restart"]["proof_number"] == 0

    assert disproven["threshold2"] == 3
    assert disproven["partial"]["status"] == "UNKNOWN"
    assert disproven["completed_after_restart"]["status"] == "DISPROVEN"
    assert disproven["completed_after_restart"]["disproof_number"] == 0

    for case in payload["cases"]:
        checkpoint = case["checkpoint"]
        match = case["uninterrupted_match"]
        assert checkpoint["atomic_failed_replace_preserved_prior_file"] is True
        assert checkpoint["fresh_dag_object"] is True
        assert checkpoint["fresh_history_object"] is True
        assert checkpoint["supplied_exact_root_bytes_pin"] is True
        assert checkpoint["supplied_exact_rules_pin"] is True
        assert checkpoint["supplied_exact_threshold_pin"] is True
        assert checkpoint["threshold2_pin"] == case["threshold2"]
        assert match["graph_sha256_matches"] is True
        assert match["proof_numbers_match"] is True
        assert match["counts_match"] is True


def test_archive_records_compact_segment_restart_and_two_phase_recovery() -> None:
    payload = _archived()

    for case in payload["cases"]:
        partial = case["partial"]
        compact = case["compact_checkpoint"]
        exact_load = compact["exact_load_match"]
        segment = compact["segment_store"]
        recovery = case["generation_recovery"]
        tip = recovery["retained_intended_tip"]

        assert compact["compact_byte_count"] < compact["legacy_byte_count"]
        assert compact["saved_byte_count"] == (
            compact["legacy_byte_count"] - compact["compact_byte_count"]
        )
        assert (
            compact["legacy_file_sha256"]
            == case["checkpoint"]["checkpoint_file_sha256"]
        )
        assert (
            compact["legacy_checkpoint_sha256"]
            == case["checkpoint"]["checkpoint_content_sha256"]
        )
        assert exact_load["status"] == "UNKNOWN"
        assert exact_load["graph_sha256"] == partial["graph_sha256"]
        assert exact_load["committed_expansions"] == partial["committed_expansions"]
        assert exact_load["node_count"] == partial["node_count"]
        assert exact_load["edge_count"] == partial["edge_count"]
        assert exact_load["graph_and_counts_match"] is True

        assert segment["forced_lazy_spill"] is True
        assert segment["lazy_payloads"] is True
        assert segment["object_ref"]["kind"] == "history"
        assert len(segment["object_ref"]["sha256"]) == 64
        assert segment["supplied_manifest_sha256_pin"] is True
        assert segment["supplied_exact_payload_pin"] is True
        assert segment["resident_payload_bytes_after_spill"] == 0
        assert segment["resident_payload_bytes_after_restart"] == 0
        assert segment["exact_read_byte_count"] == compact["compact_byte_count"]
        assert segment["exact_read_file_sha256"] == compact["compact_file_sha256"]

        assert recovery["previous_tip_is_null"] is True
        assert recovery["external_preparation_exact_file_roundtrip"] is True
        assert recovery["before_current"]["current_condition_observed"].startswith(
            "CURRENT absent"
        )
        assert recovery["after_current"]["current_condition_observed"].startswith(
            "intended CURRENT present"
        )
        for recovery_fact in (
            recovery["before_current"],
            recovery["after_current"],
        ):
            assert recovery_fact["status"] == "UNKNOWN"
            assert recovery_fact["exact_graph_and_counts_match"] is True
            assert recovery_fact["fresh_store_object"] is True
            assert recovery_fact["fresh_dag_object"] is True
            assert recovery_fact["fresh_history_object"] is True
            assert recovery_fact["proof_numbers_match"] is True
            assert recovery_fact["root_state_bytes_match"] is True
            assert recovery_fact["graph_sha256"] == partial["graph_sha256"]
        assert tip["generation"] == 1
        assert tip["committed_expansions"] == partial["committed_expansions"]
        assert tip["graph_sha256"] == partial["graph_sha256"]


def test_archive_records_deterministic_higher_counter_fork_rejection() -> None:
    fork = _archived()["fork_rejection_case"]

    assert fork["baseline_status"] == fork["fork_status"] == "UNKNOWN"
    assert fork["fork_committed_expansions"] > fork["baseline_committed_expansions"]
    assert fork["fork_had_higher_counter"] is True
    assert fork["dropped_committed_expansion"] is True
    assert fork["publication_rejected"] is True
    assert fork["current_pointer_preserved"] is True
    assert fork["published_tip_preserved"] is True


def test_archive_records_simultaneous_exact_checked_digest_collisions() -> None:
    collision = _archived()["collision_case"]

    assert collision["status"] == "UNKNOWN"
    assert collision["state_digest_bucket_size"] == collision["node_count"] == 6
    assert collision["distinct_exact_state_count"] == collision["node_count"]
    assert (
        collision["history_digest_bucket_size"]
        == collision["history_board_object_count"]
        == 5
    )
    assert collision["fresh_dag_object"] is True
    assert collision["fresh_history_object"] is True


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.pop("scope"),
        lambda value: value.__setitem__("claim", "Black wins"),
        lambda value: value.__setitem__("root_19x19_status", "PROVEN"),
        lambda value: value["fixture_rules"].__setitem__("komi2", 3),
        lambda value: value["limitations"].pop(),
        lambda value: value["cases"].reverse(),
        lambda value: value.pop("fork_rejection_case"),
    ),
)
def test_validator_rejects_noncanonical_or_unpinned_envelopes(mutation) -> None:
    payload = copy.deepcopy(_archived())
    mutation(payload)
    with pytest.raises(ValueError):
        validate_persistent_pndag_evidence(payload)


@pytest.mark.parametrize(
    "path",
    (
        ("resource_accounting", "archived_checkpoint_files"),
        ("cases", 0, "threshold2"),
        ("cases", 0, "partial", "committed_expansions"),
        ("cases", 1, "checkpoint", "byte_count"),
        ("cases", 0, "compact_checkpoint", "compact_byte_count"),
        (
            "cases",
            1,
            "compact_checkpoint",
            "segment_store",
            "final_generation",
        ),
        (
            "cases",
            0,
            "generation_recovery",
            "retained_intended_tip",
            "generation",
        ),
        ("collision_case", "node_count"),
        ("fork_rejection_case", "fork_committed_expansions"),
    ),
)
def test_validator_never_accepts_boolean_as_an_exact_integer(
    path: tuple[str | int, ...],
) -> None:
    payload = copy.deepcopy(_archived())
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = True
    with pytest.raises(ValueError):
        validate_persistent_pndag_evidence(payload)


def test_validator_rejects_broken_result_and_collision_invariants() -> None:
    payload = copy.deepcopy(_archived())
    payload["cases"][0]["partial"]["status"] = "PROVEN"
    with pytest.raises(ValueError, match="status"):
        validate_persistent_pndag_evidence(payload)

    payload = copy.deepcopy(_archived())
    payload["cases"][1]["uninterrupted_match"]["counts_match"] = False
    with pytest.raises(ValueError, match="boolean true"):
        validate_persistent_pndag_evidence(payload)

    payload = copy.deepcopy(_archived())
    payload["collision_case"]["distinct_exact_state_count"] = 5
    with pytest.raises(ValueError):
        validate_persistent_pndag_evidence(payload)

    payload = copy.deepcopy(_archived())
    payload["cases"][0]["compact_checkpoint"]["segment_store"][
        "resident_payload_bytes_after_restart"
    ] = 1
    with pytest.raises(ValueError, match="resident_payload_bytes_after_restart"):
        validate_persistent_pndag_evidence(payload)

    payload = copy.deepcopy(_archived())
    payload["cases"][1]["generation_recovery"]["after_current"]["status"] = "PROVEN"
    with pytest.raises(ValueError, match="UNKNOWN"):
        validate_persistent_pndag_evidence(payload)

    payload = copy.deepcopy(_archived())
    payload["fork_rejection_case"]["publication_rejected"] = False
    with pytest.raises(ValueError, match="boolean true"):
        validate_persistent_pndag_evidence(payload)


def test_loader_rejects_duplicate_keys_and_noncanonical_json(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"root_19x19_status":"UNKNOWN","root_19x19_status":"PROVEN"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_persistent_pndag_evidence(duplicate)

    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(_archived(), indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="canonical JSON form"):
        load_persistent_pndag_evidence(pretty)

    missing_newline = tmp_path / "missing-newline.json"
    missing_newline.write_bytes(ARCHIVED_EVIDENCE.read_bytes().rstrip(b"\n"))
    with pytest.raises(ValueError, match="exactly one newline"):
        load_persistent_pndag_evidence(missing_newline)


def test_cli_validate_reproduces_archive_and_keeps_19x19_unknown() -> None:
    process = subprocess.run(
        [sys.executable, str(GATE), "--validate", str(ARCHIVED_EVIDENCE)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    assert "root status remains UNKNOWN" in process.stdout
    assert "19x19" in process.stdout


def test_loader_roundtrip_bytes_are_exactly_canonical(tmp_path: Path) -> None:
    archived = _archived()
    roundtrip = tmp_path / "roundtrip.json"
    roundtrip.write_bytes(canonical_json_bytes(archived) + b"\n")

    assert load_persistent_pndag_evidence(roundtrip) == archived
