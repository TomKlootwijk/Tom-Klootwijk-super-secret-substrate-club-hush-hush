#!/usr/bin/env python3
"""Black-box and independent framing tests for native PNDAG checkpoints."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
from typing import Any


__test__ = False

MAGIC = b"UGTS-CPP-PNDAG-CHECKPOINT-v1\x00"


def invoke(
    cli: Path, arguments: list[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(cli), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        cwd=cwd,
        timeout=90,
    )


def successful_payload(
    cli: Path, arguments: list[str], *, cwd: Path | None = None
) -> dict[str, Any]:
    process = invoke(cli, arguments, cwd=cwd)
    if process.returncode != 0:
        raise AssertionError(
            f"CLI failed with {process.returncode}: {process.stderr!r}"
        )
    if process.stderr:
        raise AssertionError(f"successful CLI wrote stderr: {process.stderr!r}")
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(f"CLI did not emit JSON: {process.stdout!r}") from error
    canonical = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )
    if process.stdout != canonical:
        raise AssertionError("checkpoint CLI result is not canonical JSON")
    return payload


def checkpoint_run(
    cli: Path,
    store: Path,
    *,
    size: int,
    komi2: int,
    threshold2: int,
    budget: int,
    prior: dict[str, Any] | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    arguments = [
        str(size),
        str(komi2),
        str(threshold2),
        str(budget),
        "--checkpoint-dir",
        str(store),
    ]
    if prior is not None:
        tip = prior["checkpoint_tip"]
        arguments += [
            "--resume-checkpoint",
            tip["path"],
            "--expected-checkpoint-sha256",
            tip["checkpoint_file_sha256"],
        ]
    payload = successful_payload(cli, arguments, cwd=cwd)
    if payload["format"] != "UGTS-CPP-PNDAG-CHECKPOINT-RESULT-v1":
        raise AssertionError("unexpected checkpoint result format")
    if payload["claim_boundary"] != {
        "certificate": False,
        "expansion_budget_stop_status": "UNKNOWN",
        "scope": "host-memory-exact-bounded-checkpoint-attempt",
    }:
        raise AssertionError("checkpoint result lost its non-certificate boundary")
    tip = payload["checkpoint_tip"]
    if tip["format"] != "UGTS-CPP-PNDAG-CHECKPOINT-TIP-v1":
        raise AssertionError("unexpected checkpoint tip format")
    path = Path(tip["path"])
    if not path.is_absolute():
        raise AssertionError("checkpoint tip path is not restart-stable and absolute")
    raw = path.read_bytes()
    if len(raw) != tip["byte_length"]:
        raise AssertionError("tip byte length does not match the immutable file")
    if hashlib.sha256(raw).hexdigest() != tip["checkpoint_file_sha256"]:
        raise AssertionError("tip file hash does not match immutable bytes")
    if raw[: len(MAGIC)] != MAGIC:
        raise AssertionError("native checkpoint magic changed")
    if hashlib.sha256(raw[:-32]).digest() != raw[-32:]:
        raise AssertionError("native checkpoint self hash is invalid")
    if raw[-32:].hex() != tip["checkpoint_payload_sha256"]:
        raise AssertionError("tip payload hash does not match footer")
    for field in ("graph_sha256", "committed_expansions", "node_count", "edge_count"):
        if tip[field] != payload[field]:
            raise AssertionError(f"tip {field} disagrees with exact result")
    if tip["status"] != payload["status"]:
        raise AssertionError("tip status was not derived from the exact root")
    return payload


def require_rejection(
    cli: Path,
    arguments: list[str],
    *,
    expected_code: int = 2,
    stderr_contains: str | None = None,
) -> None:
    process = invoke(cli, arguments)
    if (
        process.returncode != expected_code
        or process.stdout
        or not process.stderr
        or (stderr_contains is not None and stderr_contains not in process.stderr)
    ):
        raise AssertionError(
            "invalid checkpoint input did not fail closed: "
            f"code={process.returncode}, stdout={process.stdout!r}, "
            f"stderr={process.stderr!r}"
        )


def checkpoint_offsets(raw: bytes, points: int) -> dict[str, Any]:
    """Independently walk all v1 framing and return mutation offsets."""

    position = 0

    def take(count: int) -> bytes:
        nonlocal position
        result = raw[position : position + count]
        if len(result) != count:
            raise AssertionError("checkpoint framing truncated during test parse")
        position += count
        return result

    def u8() -> int:
        return take(1)[0]

    def u32() -> int:
        return struct.unpack("<I", take(4))[0]

    def i32() -> int:
        return struct.unpack("<i", take(4))[0]

    def u64() -> int:
        return struct.unpack("<Q", take(8))[0]

    def i64() -> int:
        return struct.unpack("<q", take(8))[0]

    if take(len(MAGIC)) != MAGIC:
        raise AssertionError("unexpected checkpoint magic")
    take(1 + 1 + 2)  # endian, flags, reserved
    encoded_size = u32()
    if encoded_size * encoded_size != points:
        raise AssertionError("test parser board-size mismatch")
    komi2 = i32()
    rule_tags = take(4)  # suicide, scoring, superko, symmetry
    passes_to_end = u32()
    threshold2 = i64()
    take(8)  # generation
    previous_hash_offset = None
    if u8():
        previous_hash_offset = position
        take(32)
    committed_offset = position
    committed_expansions = u64()
    root_id_offset = position
    root_id = u64()
    node_count_offset = position
    node_count = u64()
    edge_count_offset = position
    take(8)
    history_count_offset = position
    take(8)
    take(32)  # run hash
    take(32)  # root hash
    graph_hash_offset = position
    take(32)

    nodes: list[dict[str, Any]] = []
    for expected_id in range(node_count):
        node_id_offset = position
        if u64() != expected_id:
            raise AssertionError("checkpoint node IDs are not contiguous")
        board_offset = position
        board = take(points)
        to_play = u8()
        passes = u32()
        previous_marker_offset = position
        previous_board = None
        if u8():
            previous_board = take(points)
        seen_count_offset = position
        seen_count = u64()
        seen_offsets = []
        seen_boards = []
        for _ in range(seen_count):
            seen_offsets.append(position)
            seen_boards.append(take(points))
        rank_offset = position
        rank = u64()
        expansion_offset = position
        expansion = u8()
        proof_offset = position
        proof = u64()
        disproof_offset = position
        disproof = u64()
        child_count_offset = position
        child_count = u64()
        edges = []
        for _ in range(child_count):
            move_offset = position
            move = i32()
            child_id_offset = position
            child_id = u64()
            edges.append(
                {
                    "child_id": child_id,
                    "child_id_offset": child_id_offset,
                    "move": move,
                    "move_offset": move_offset,
                }
            )
        nodes.append(
            {
                "board": board,
                "board_offset": board_offset,
                "child_count_offset": child_count_offset,
                "committed_expansions": committed_expansions,
                "disproof": disproof,
                "disproof_offset": disproof_offset,
                "edges": edges,
                "expansion": expansion,
                "expansion_offset": expansion_offset,
                "node_id_offset": node_id_offset,
                "passes": passes,
                "previous_board": previous_board,
                "previous_marker_offset": previous_marker_offset,
                "proof": proof,
                "proof_offset": proof_offset,
                "rank": rank,
                "rank_offset": rank_offset,
                "seen_count_offset": seen_count_offset,
                "seen_boards": seen_boards,
                "seen_offsets": seen_offsets,
                "to_play": to_play,
            }
        )
    if position != len(raw) - 32:
        raise AssertionError("checkpoint test parser did not consume the payload")
    return {
        "allow_suicide": bool(rule_tags[0]),
        "committed_offset": committed_offset,
        "committed_expansions": committed_expansions,
        "encoded_size": encoded_size,
        "edge_count_offset": edge_count_offset,
        "graph_hash_offset": graph_hash_offset,
        "history_count_offset": history_count_offset,
        "komi2": komi2,
        "node_count_offset": node_count_offset,
        "nodes": nodes,
        "passes_to_end": passes_to_end,
        "previous_hash_offset": previous_hash_offset,
        "root_id": root_id,
        "root_id_offset": root_id_offset,
        "threshold2": threshold2,
    }


def rehashed_tamper(
    raw: bytes,
    mutation: Callable[[bytearray, dict[str, Any]], None],
    points: int,
) -> tuple[bytes, str]:
    payload = bytearray(raw[:-32])
    mutation(payload, checkpoint_offsets(raw, points))
    mutated = bytes(payload) + hashlib.sha256(payload).digest()
    return mutated, hashlib.sha256(mutated).hexdigest()


def increment_u64(payload: bytearray, offset: int) -> None:
    value = struct.unpack_from("<Q", payload, offset)[0]
    struct.pack_into("<Q", payload, offset, value + 1)


def canonical_state_bytes(
    node: dict[str, Any], checkpoint: dict[str, Any]
) -> bytes:
    state = {
        "board_hex": node["board"].hex(),
        "format": "UGTS-GO-STATE-v1",
        "passes": node["passes"],
        "previous_board_hex": (
            None
            if node["previous_board"] is None
            else node["previous_board"].hex()
        ),
        "rules": {
            "allow_suicide": checkpoint["allow_suicide"],
            "komi2": checkpoint["komi2"],
            "passes_to_end": checkpoint["passes_to_end"],
            "scoring": "area",
            "size": checkpoint["encoded_size"],
            "superko": "positional_superko",
        },
        "seen_hex": [board.hex() for board in node["seen_boards"]],
        "to_play": node["to_play"],
    }
    return json.dumps(state, sort_keys=True, separators=(",", ":")).encode()


def forged_terminal_truth(raw: bytes, points: int) -> tuple[bytes, str]:
    """Flip terminal truth, then consistently forge all caches and graph hash."""

    checkpoint = checkpoint_offsets(raw, points)
    payload = bytearray(raw[:-32])
    infinity = (1 << 64) - 1
    caches = [(node["proof"], node["disproof"]) for node in checkpoint["nodes"]]
    terminal_id = next(
        index
        for index, node in enumerate(checkpoint["nodes"])
        if node["expansion"] == 2
    )
    caches[terminal_id] = (
        (infinity, 0) if caches[terminal_id][0] == 0 else (0, infinity)
    )

    def saturating_sum(values: list[int]) -> int:
        return min(infinity, sum(values))

    ordered_ids = sorted(
        range(len(checkpoint["nodes"])),
        key=lambda node_id: checkpoint["nodes"][node_id]["rank"],
        reverse=True,
    )
    for node_id in ordered_ids:
        node = checkpoint["nodes"][node_id]
        if node["expansion"] == 0:
            caches[node_id] = (1, 1)
        elif node["expansion"] == 1:
            children = [caches[edge["child_id"]] for edge in node["edges"]]
            if node["to_play"] == 1:
                caches[node_id] = (
                    min(proof for proof, _ in children),
                    saturating_sum([disproof for _, disproof in children]),
                )
            else:
                caches[node_id] = (
                    saturating_sum([proof for proof, _ in children]),
                    min(disproof for _, disproof in children),
                )

    for node, (proof, disproof) in zip(checkpoint["nodes"], caches, strict=True):
        struct.pack_into("<Q", payload, node["proof_offset"], proof)
        struct.pack_into("<Q", payload, node["disproof_offset"], disproof)

    graph = bytearray(b"UGTS-CPP-PNDAG-GRAPH-v1;")

    def append_scalar(value: int) -> None:
        graph.extend(str(value).encode())
        graph.extend(b";")

    def append_bytes(value: bytes) -> None:
        graph.extend(str(len(value)).encode())
        graph.extend(b":")
        graph.extend(value)
        graph.extend(b";")

    append_scalar(checkpoint["threshold2"])
    append_scalar(checkpoint["committed_expansions"])
    append_scalar(checkpoint["root_id"])
    append_scalar(len(checkpoint["nodes"]))
    for node_id, node in enumerate(checkpoint["nodes"]):
        append_scalar(node_id)
        append_bytes(canonical_state_bytes(node, checkpoint))
        append_scalar(node["rank"])
        append_scalar(node["expansion"])
        append_scalar(caches[node_id][0])
        append_scalar(caches[node_id][1])
        append_scalar(len(node["edges"]))
        for edge in node["edges"]:
            append_scalar(edge["move"])
            append_scalar(edge["child_id"])
    graph_sha256 = hashlib.sha256(graph).digest()
    graph_offset = checkpoint["graph_hash_offset"]
    payload[graph_offset : graph_offset + 32] = graph_sha256
    mutated = bytes(payload) + hashlib.sha256(payload).digest()
    return mutated, hashlib.sha256(mutated).hexdigest()


def test_nineteen_resume_and_tamper(cli: Path, root: Path) -> None:
    store = root / "go19"
    first = checkpoint_run(
        cli, store, size=19, komi2=15, threshold2=1, budget=1
    )
    if (
        first["status"],
        first["proof_number"],
        first["disproof_number"],
        first["committed_expansions"],
        first["node_count"],
        first["edge_count"],
    ) != ("UNKNOWN", 1, 362, 1, 363, 362):
        raise AssertionError("first persisted 19x19 increment changed exact facts")
    if {
        "file": first["checkpoint_tip"]["checkpoint_file_sha256"],
        "graph": first["graph_sha256"],
        "payload": first["checkpoint_tip"]["checkpoint_payload_sha256"],
        "root": first["root_state_object_id"],
        "run": first["checkpoint_tip"]["run_sha256"],
    } != {
        "file": "074b6032b6c16f73aeaf06d467121f3a6a95db0d22bb57fc641ab28ef89ebe1f",
        "graph": "85389edf375dbf8385515edd92de54ae31c72f50bd638f5cd9570ba930d6ccdb",
        "payload": "31fb94c38c1e5550c2b6a95f230d49c2070aaf0a255b6eac32850e11b4d9a7bb",
        "root": "fe5c51acd1a92a9a99c8337dae006d594a637bf93cc3040f008a2d4f51781b8d",
        "run": "3e240003dc9b830320214b68768e8240893a20f102b01eb461892aae5e5c873f",
    }:
        raise AssertionError("canonical first-generation 19x19 checkpoint changed")

    repeated = checkpoint_run(
        cli, store, size=19, komi2=15, threshold2=1, budget=1
    )
    if repeated["checkpoint_tip"] != first["checkpoint_tip"]:
        raise AssertionError("identical immutable publication is not idempotent")

    different_store = root / "different-store"
    first_tip = first["checkpoint_tip"]
    require_rejection(
        cli,
        [
            "19",
            "15",
            "1",
            "1",
            "--checkpoint-dir",
            str(different_store),
            "--resume-checkpoint",
            first_tip["path"],
            "--expected-checkpoint-sha256",
            first_tip["checkpoint_file_sha256"],
        ],
        stderr_contains="must remain in the pinned predecessor store",
    )
    if different_store.exists():
        raise AssertionError("cross-store continuation wrote before rejecting")

    orphan = store / "checkpoints" / ("f" * 64 + ".pndag")
    orphan.write_bytes(b"unreported-content-addressed-orphan")

    second = checkpoint_run(
        cli,
        store,
        size=19,
        komi2=15,
        threshold2=1,
        budget=1,
        prior=first,
    )
    legacy_two = successful_payload(cli, ["19", "15", "1", "2"])
    exact_fields = (
        "status",
        "proof_number",
        "disproof_number",
        "committed_expansions",
        "node_count",
        "edge_count",
        "graph_sha256",
    )
    if tuple(second[field] for field in exact_fields) != tuple(
        legacy_two[field] for field in exact_fields
    ):
        raise AssertionError("persisted 1+1 run differs from uninterrupted 2")
    if second["graph_sha256"] != (
        "03dfd8263b423501147a0be09d2ccd1e23f51c2923992ed177da277740849618"
    ):
        raise AssertionError("canonical two-expansion 19x19 graph changed")
    if (
        second["checkpoint_tip"]["checkpoint_file_sha256"],
        second["checkpoint_tip"]["checkpoint_payload_sha256"],
    ) != (
        "e750ea07ba679a6e845df9fd3e8bfe5717ef6bf453785df7eb341a059c39674c",
        "12eb97ff437e60dea8b45e3cc78142fcee57d79259182ba3948bda9a462665b3",
    ):
        raise AssertionError("canonical resumed 19x19 checkpoint changed")
    if second["status"] != "UNKNOWN":
        raise AssertionError("bounded 19x19 resume was mislabeled solved")
    if second["checkpoint_tip"]["generation"] != 2 or second[
        "checkpoint_tip"
    ]["previous_checkpoint_file_sha256"] != first["checkpoint_tip"][
        "checkpoint_file_sha256"
    ]:
        raise AssertionError("checkpoint predecessor pin was not preserved")

    second_raw = Path(second["checkpoint_tip"]["path"]).read_bytes()

    def forge_predecessor(payload: bytearray, offsets: dict[str, Any]) -> None:
        predecessor_offset = offsets["previous_hash_offset"]
        if predecessor_offset is None:
            raise AssertionError("generation-two checkpoint omitted predecessor")
        payload[predecessor_offset] ^= 1

    forged_lineage, forged_lineage_sha256 = rehashed_tamper(
        second_raw, forge_predecessor, 361
    )
    forged_lineage_path = (
        store / "checkpoints" / f"{forged_lineage_sha256}.pndag"
    )
    forged_lineage_path.write_bytes(forged_lineage)
    require_rejection(
        cli,
        [
            "19",
            "15",
            "1",
            "0",
            "--checkpoint-dir",
            str(store),
            "--resume-checkpoint",
            str(forged_lineage_path),
            "--expected-checkpoint-sha256",
            forged_lineage_sha256,
        ],
        expected_code=1,
    )
    if orphan.read_bytes() != b"unreported-content-addressed-orphan":
        raise AssertionError("explicit resume unexpectedly scanned or changed an orphan")

    first_path = Path(first["checkpoint_tip"]["path"])
    first_bytes = first_path.read_bytes()
    blocked_store = root / "blocked-store"
    blocked_store.write_bytes(b"not-a-directory")
    require_rejection(
        cli,
        [
            "19",
            "15",
            "1",
            "1",
            "--checkpoint-dir",
            str(blocked_store),
        ],
        expected_code=1,
    )
    if first_path.read_bytes() != first_bytes:
        raise AssertionError("failed publication changed an existing immutable pin")

    tip = first["checkpoint_tip"]
    common = [
        "19",
        "15",
        "1",
        "1",
        "--checkpoint-dir",
        str(store),
        "--resume-checkpoint",
        tip["path"],
        "--expected-checkpoint-sha256",
    ]
    wrong_pin = ("0" if tip["checkpoint_file_sha256"][0] != "0" else "1") + tip[
        "checkpoint_file_sha256"
    ][1:]
    require_rejection(cli, [*common, wrong_pin])

    wrong_threshold = [
        "19",
        "15",
        "3",
        "1",
        "--checkpoint-dir",
        str(store),
        "--resume-checkpoint",
        tip["path"],
        "--expected-checkpoint-sha256",
        tip["checkpoint_file_sha256"],
    ]
    require_rejection(cli, wrong_threshold)

    wrong_komi = [
        "19",
        "13",
        "1",
        "1",
        "--checkpoint-dir",
        str(store),
        "--resume-checkpoint",
        tip["path"],
        "--expected-checkpoint-sha256",
        tip["checkpoint_file_sha256"],
    ]
    require_rejection(cli, wrong_komi)

    original = Path(tip["path"]).read_bytes()
    truncated = original[:-1]
    truncated_path = root / "truncated.pndag"
    truncated_path.write_bytes(truncated)
    truncated_hash = hashlib.sha256(truncated).hexdigest()
    require_rejection(
        cli,
        [
            "19",
            "15",
            "1",
            "1",
            "--checkpoint-dir",
            str(store),
            "--resume-checkpoint",
            str(truncated_path),
            "--expected-checkpoint-sha256",
            truncated_hash,
        ],
    )

    def change_cache(payload: bytearray, offsets: dict[str, Any]) -> None:
        increment_u64(payload, offsets["nodes"][0]["proof_offset"])

    def change_rank(payload: bytearray, offsets: dict[str, Any]) -> None:
        increment_u64(payload, offsets["nodes"][0]["rank_offset"])

    def change_edge(payload: bytearray, offsets: dict[str, Any]) -> None:
        edge = offsets["nodes"][0]["edges"][0]
        increment_u64(payload, edge["child_id_offset"])

    def change_edge_count(payload: bytearray, offsets: dict[str, Any]) -> None:
        increment_u64(payload, offsets["edge_count_offset"])

    def reorder_history(payload: bytearray, offsets: dict[str, Any]) -> None:
        node = next(
            item for item in offsets["nodes"] if len(item["seen_offsets"]) >= 2
        )
        first_seen, second_seen = node["seen_offsets"][:2]
        first_board = bytes(payload[first_seen : first_seen + 361])
        second_board = bytes(payload[second_seen : second_seen + 361])
        payload[first_seen : first_seen + 361] = second_board
        payload[second_seen : second_seen + 361] = first_board

    def inflate_node_count(payload: bytearray, offsets: dict[str, Any]) -> None:
        struct.pack_into("<Q", payload, offsets["node_count_offset"], 2_000_000)

    def inflate_history_count(payload: bytearray, offsets: dict[str, Any]) -> None:
        struct.pack_into(
            "<Q", payload, offsets["history_count_offset"], 1_000_000
        )
        struct.pack_into(
            "<Q", payload, offsets["nodes"][0]["seen_count_offset"], 1_000_000
        )

    mutations = {
        "cache": (change_cache, "proof caches fail independent recomputation"),
        "rank": (change_rank, "semantic rank mismatch"),
        "edge": (change_edge, "exact legal regeneration"),
        "edge-count": (change_edge_count, "aggregate counts mismatch"),
        "history-order": (reorder_history, "not strictly ordered"),
        "declared-node-bomb": (
            inflate_node_count,
            "declared records cannot fit",
        ),
        "declared-history-bomb": (
            inflate_history_count,
            "declared records cannot fit",
        ),
    }
    for name, (mutation, expected_error) in mutations.items():
        tampered, tampered_hash = rehashed_tamper(original, mutation, 361)
        tampered_path = root / f"rehashed-{name}-tamper.pndag"
        tampered_path.write_bytes(tampered)
        require_rejection(
            cli,
            [
                "19",
                "15",
                "1",
                "1",
                "--checkpoint-dir",
                str(store),
                "--resume-checkpoint",
                str(tampered_path),
                "--expected-checkpoint-sha256",
                tampered_hash,
            ],
            stderr_contains=expected_error,
        )


def test_tiny_solved_fixtures(cli: Path, root: Path) -> None:
    publish_cwd = root / "relative-publish-cwd"
    resume_cwd = root / "relative-resume-cwd"
    publish_cwd.mkdir()
    resume_cwd.mkdir()
    relative = checkpoint_run(
        cli,
        Path("relative-store"),
        size=1,
        komi2=1,
        threshold2=-1,
        budget=1,
        cwd=publish_cwd,
    )
    relative_resumed = checkpoint_run(
        cli,
        publish_cwd / "relative-store",
        size=1,
        komi2=1,
        threshold2=-1,
        budget=1,
        prior=relative,
        cwd=resume_cwd,
    )
    if relative_resumed["checkpoint_tip"]["generation"] != 2:
        raise AssertionError("absolute checkpoint tip failed across working directories")

    unicode_store = root / "unicode-α-測"
    unicode_result = checkpoint_run(
        cli,
        unicode_store,
        size=1,
        komi2=1,
        threshold2=-1,
        budget=1,
    )
    if not Path(unicode_result["checkpoint_tip"]["path"]).is_file():
        raise AssertionError("UTF-8 checkpoint path did not round-trip through JSON")

    one = checkpoint_run(
        cli, root / "one", size=1, komi2=1, threshold2=-1, budget=10
    )
    if one["status"] != "PROVEN" or one["checkpoint_tip"]["status"] != "PROVEN":
        raise AssertionError("solved 1x1 checkpoint status is not derived exactly")
    forged, forged_sha256 = forged_terminal_truth(
        Path(one["checkpoint_tip"]["path"]).read_bytes(), 1
    )
    forged_path = root / "forged-terminal-truth.pndag"
    forged_path.write_bytes(forged)
    require_rejection(
        cli,
        [
            "1",
            "1",
            "-1",
            "0",
            "--checkpoint-dir",
            str(root / "one"),
            "--resume-checkpoint",
            str(forged_path),
            "--expected-checkpoint-sha256",
            forged_sha256,
        ],
        stderr_contains="proof caches fail independent recomputation",
    )
    replay = checkpoint_run(
        cli,
        root / "one",
        size=1,
        komi2=1,
        threshold2=-1,
        budget=0,
        prior=one,
    )
    if replay["checkpoint_tip"] != one["checkpoint_tip"]:
        raise AssertionError("zero-work solved resume created a fake generation")

    for threshold, expected_status in ((1, "PROVEN"), (3, "DISPROVEN")):
        store = root / f"two-{threshold}"
        partial = checkpoint_run(
            cli, store, size=2, komi2=1, threshold2=threshold, budget=7
        )
        if partial["status"] != "UNKNOWN":
            raise AssertionError("2x2 interruption was not UNKNOWN")
        resumed = checkpoint_run(
            cli,
            store,
            size=2,
            komi2=1,
            threshold2=threshold,
            budget=10_000,
            prior=partial,
        )
        complete = successful_payload(
            cli, ["2", "1", str(threshold), "10000"]
        )
        exact_fields = (
            "status",
            "proof_number",
            "disproof_number",
            "committed_expansions",
            "node_count",
            "edge_count",
            "graph_sha256",
        )
        if resumed["status"] != expected_status or tuple(
            resumed[field] for field in exact_fields
        ) != tuple(complete[field] for field in exact_fields):
            raise AssertionError(
                "tiny solved checkpoint differs from uninterrupted proof"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", required=True, type=Path)
    args = parser.parse_args()
    cli = args.cli.resolve()

    with tempfile.TemporaryDirectory(prefix="ugts-native-pndag-cli-") as raw_dir:
        root = Path(raw_dir)
        test_nineteen_resume_and_tamper(cli, root)
        test_tiny_solved_fixtures(cli, root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
