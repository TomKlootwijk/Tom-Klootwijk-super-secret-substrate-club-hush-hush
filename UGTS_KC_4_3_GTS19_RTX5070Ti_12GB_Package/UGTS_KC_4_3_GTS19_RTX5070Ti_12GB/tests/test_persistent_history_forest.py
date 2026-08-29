"""Exact shared-forest tests for immutable positional-superko histories."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import ugts_go19.persistent_history as persistent_history_module
from ugts_go19.digests import canonical_json_bytes, sha256_hex
from ugts_go19.persistent_history import (
    FOREST_SERIALIZATION_FORMAT,
    PersistentHistory,
)


BOARDS_2X2 = (
    bytes((0, 0, 0, 0)),
    bytes((1, 0, 0, 0)),
    bytes((0, 2, 0, 0)),
    bytes((0, 0, 1, 0)),
)


def _root_with_boards(history: PersistentHistory, boards: tuple[bytes, ...]):
    root = history.empty_root
    for board in boards:
        root = history.insert(root, board)
    return root


def _payload(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))


def _rehashed(payload: dict) -> bytes:
    result = copy.deepcopy(payload)
    result.pop("artifact_sha256", None)
    result["artifact_sha256"] = sha256_hex(canonical_json_bytes(result))
    return canonical_json_bytes(result) + b"\n"


def test_forest_is_compact_canonical_and_preserves_ordered_roots() -> None:
    first = PersistentHistory(2)
    first_a = _root_with_boards(first, (BOARDS_2X2[0],))
    first_ab = first.insert(first_a, BOARDS_2X2[1])
    first_ac = first.insert(first_a, BOARDS_2X2[2])
    first_roots = (first.empty_root, first_a, first_ab, first_ac, first_a)
    first_raw = first.serialize_forest(first_roots)

    # Build equal values through different insertion/allocation paths.  The
    # ordered root references stay aligned with their surrounding state table,
    # while the global record ids remain canonical.
    second = PersistentHistory(2)
    second_ab = _root_with_boards(
        second, (BOARDS_2X2[1], BOARDS_2X2[0])
    )
    second_a = _root_with_boards(second, (BOARDS_2X2[0],))
    second_ac = _root_with_boards(
        second, (BOARDS_2X2[2], BOARDS_2X2[0])
    )
    second_roots = (
        second.empty_root,
        second_a,
        second_ab,
        second_ac,
        second_a,
    )
    assert second.serialize_forest(second_roots) == first_raw

    payload = _payload(first_raw)
    assert payload["format"] == FOREST_SERIALIZATION_FORMAT
    assert payload["root_count"] == len(first_roots)
    assert payload["board_record_count"] == 3
    separate_node_count = sum(
        _payload(first.serialize_root(root))["node_record_count"]
        for root in first_roots
    )
    assert payload["node_record_count"] < separate_node_count
    reordered = _payload(first.serialize_forest(tuple(reversed(first_roots))))
    assert reordered["boards"] == payload["boards"]
    assert reordered["nodes"] == payload["nodes"]
    assert [record["root_sha256"] for record in reordered["roots"]] == list(
        reversed([record["root_sha256"] for record in payload["roots"]])
    )


def test_roundtrip_preserves_exact_roots_and_structural_sharing() -> None:
    history = PersistentHistory(2)
    root_a = history.insert(history.empty_root, BOARDS_2X2[0])
    root_ab = history.insert(root_a, BOARDS_2X2[1])
    root_ac = history.insert(root_a, BOARDS_2X2[2])
    roots = (history.empty_root, root_a, root_ab, root_ac, root_a)
    raw = history.serialize_forest(roots)
    artifact_hash = _payload(raw)["artifact_sha256"]

    loaded = PersistentHistory(2)
    loaded_roots = loaded.deserialize_forest(
        raw,
        expected_artifact_sha256=artifact_hash,
        expected_root_sha256s=(root.root_sha256 for root in roots),
    )

    assert [loaded.members(root) for root in loaded_roots] == [
        history.members(root) for root in roots
    ]
    assert loaded_roots[1]._node is loaded_roots[4]._node
    assert loaded.shared_node_count(loaded_roots[2], loaded_roots[3]) > 0
    assert loaded.serialize_forest(loaded_roots) == raw


def test_forced_index_digest_collision_remains_exact_and_deterministic() -> None:
    def constant_digest(_board: bytes) -> bytes:
        return bytes(32)

    first = PersistentHistory(
        2,
        digest_fn=constant_digest,
        digest_name="constant-forest-test",
    )
    first_ab = _root_with_boards(first, BOARDS_2X2[:2])
    first_abc = first.insert(first_ab, BOARDS_2X2[2])
    raw = first.serialize_forest((first_ab, first_abc))

    second = PersistentHistory(
        2,
        digest_fn=constant_digest,
        digest_name="constant-forest-test",
    )
    second_abc = _root_with_boards(second, tuple(reversed(BOARDS_2X2[:3])))
    second_ab = _root_with_boards(second, tuple(reversed(BOARDS_2X2[:2])))
    assert second.serialize_forest((second_ab, second_abc)) == raw

    loaded = PersistentHistory(
        2,
        digest_fn=constant_digest,
        digest_name="constant-forest-test",
    )
    loaded_roots = loaded.deserialize_forest(
        raw,
        expected_root_sha256s=(first_ab.root_sha256, first_abc.root_sha256),
    )
    assert loaded.digest_bucket_sizes() == (3,)
    assert loaded.members(loaded_roots[0]) == tuple(sorted(BOARDS_2X2[:2]))
    assert loaded.members(loaded_roots[1]) == tuple(sorted(BOARDS_2X2[:3]))


def test_file_roundtrip_and_external_pins(tmp_path: Path) -> None:
    history = PersistentHistory(2)
    root_a = history.insert(history.empty_root, BOARDS_2X2[0])
    root_ab = history.insert(root_a, BOARDS_2X2[1])
    artifact = tmp_path / "history-forest.json"
    history.save_forest(artifact, (root_a, root_ab))
    payload = _payload(artifact.read_bytes())

    loaded, roots = PersistentHistory.load_forest(
        artifact,
        expected_board_size=2,
        expected_artifact_sha256=payload["artifact_sha256"],
        expected_root_sha256s=(root_a.root_sha256, root_ab.root_sha256),
    )
    assert loaded.serialize_forest(roots) == artifact.read_bytes()

    with pytest.raises(ValueError, match="expected artifact"):
        PersistentHistory.load_forest(
            artifact,
            expected_artifact_sha256="00" * 32,
        )
    with pytest.raises(ValueError, match="expected ordered roots"):
        PersistentHistory.load_forest(
            artifact,
            expected_root_sha256s=(root_ab.root_sha256, root_a.root_sha256),
        )
    with pytest.raises(ValueError, match="expected board size"):
        PersistentHistory.load_forest(artifact, expected_board_size=3)


def test_forced_index_digest_collision_file_roundtrip(tmp_path: Path) -> None:
    def constant_digest(_board: bytes) -> bytes:
        return bytes(32)

    history = PersistentHistory(
        2,
        digest_fn=constant_digest,
        digest_name="constant-forest-file-test",
    )
    root_ab = _root_with_boards(history, BOARDS_2X2[:2])
    root_abc = history.insert(root_ab, BOARDS_2X2[2])
    artifact = tmp_path / "collision-forest.json"
    history.save_forest(artifact, (root_ab, root_abc))

    with pytest.raises(ValueError, match="requires its injected digest"):
        PersistentHistory.load_forest(artifact)
    loaded, roots = PersistentHistory.load_forest(
        artifact,
        digest_fn=constant_digest,
        digest_name="constant-forest-file-test",
    )
    assert loaded.digest_bucket_sizes() == (3,)
    assert loaded.members(roots[0]) == tuple(sorted(BOARDS_2X2[:2]))
    assert loaded.members(roots[1]) == tuple(sorted(BOARDS_2X2[:3]))


def test_loader_requires_strict_canonical_json() -> None:
    history = PersistentHistory(2)
    root = history.insert(history.empty_root, BOARDS_2X2[0])
    raw = history.serialize_forest((root,))

    with pytest.raises(ValueError, match="not in canonical form"):
        history.deserialize_forest(raw[:-1])
    with pytest.raises(ValueError, match="not valid canonical JSON"):
        history.deserialize_forest(b'{"x":1,"x":2}\n')
    with pytest.raises(ValueError, match="not valid canonical JSON"):
        history.deserialize_forest(b"[" * 10_000 + b"0" + b"]" * 10_000 + b"\n")


def test_loader_rejects_duplicate_board_and_node_records() -> None:
    history = PersistentHistory(2)
    root = _root_with_boards(history, BOARDS_2X2[:2])
    original = _payload(history.serialize_forest((root,)))

    duplicate_board = copy.deepcopy(original)
    extra_board = copy.deepcopy(duplicate_board["boards"][0])
    extra_board["id"] = len(duplicate_board["boards"])
    duplicate_board["boards"].append(extra_board)
    duplicate_board["board_record_count"] += 1
    with pytest.raises(ValueError, match="duplicate exact forest board"):
        history.deserialize_forest(_rehashed(duplicate_board))

    duplicate_node = copy.deepcopy(original)
    extra_node = copy.deepcopy(duplicate_node["nodes"][0])
    extra_node["id"] = len(duplicate_node["nodes"])
    duplicate_node["nodes"].append(extra_node)
    duplicate_node["node_record_count"] += 1
    with pytest.raises(ValueError, match="duplicate immutable forest node"):
        history.deserialize_forest(_rehashed(duplicate_node))


def test_loader_rejects_unreachable_missing_and_malformed_records() -> None:
    history = PersistentHistory(2)
    root_ab = _root_with_boards(history, BOARDS_2X2[:2])
    root_c = _root_with_boards(history, (BOARDS_2X2[2],))
    original = _payload(history.serialize_forest((root_ab, root_c)))

    unreachable = copy.deepcopy(original)
    unreachable["roots"].pop()
    unreachable["root_count"] -= 1
    with pytest.raises(ValueError, match="unreachable node"):
        PersistentHistory(2).deserialize_forest(_rehashed(unreachable))

    only_ab = _payload(history.serialize_forest((root_ab,)))
    only_c = _payload(history.serialize_forest((root_c,)))
    unused_board = copy.deepcopy(only_ab)
    board_records = unused_board["boards"] + [
        copy.deepcopy(only_c["boards"][0])
    ]
    board_records.sort(
        key=lambda record: (record["index_digest"], record["raw_hex"])
    )
    raw_to_id: dict[str, int] = {}
    for board_id, record in enumerate(board_records):
        record["id"] = board_id
        raw_to_id[record["raw_hex"]] = board_id
    for node in unused_board["nodes"]:
        if node["kind"] == "leaf":
            for board_ref in node["boards"]:
                board_ref["board_id"] = raw_to_id[board_ref["raw_hex"]]
    unused_board["boards"] = board_records
    unused_board["board_record_count"] = len(board_records)
    with pytest.raises(ValueError, match="unreachable board"):
        PersistentHistory(2).deserialize_forest(_rehashed(unused_board))

    missing = copy.deepcopy(original)
    branch = next(node for node in missing["nodes"] if node["kind"] == "branch")
    branch["children"][0]["child_id"] = len(missing["nodes"]) + 10
    with pytest.raises(ValueError, match="missing or cyclic child"):
        PersistentHistory(2).deserialize_forest(_rehashed(missing))

    malformed = copy.deepcopy(original)
    malformed["roots"][0]["unexpected"] = True
    with pytest.raises(ValueError, match="noncanonical shape"):
        PersistentHistory(2).deserialize_forest(_rehashed(malformed))


def test_loader_rejects_shared_child_under_an_incompatible_radix_slot() -> None:
    def split_first_byte(board: bytes) -> bytes:
        return bytes((board[0],)) + bytes(31)

    history = PersistentHistory(
        2,
        digest_fn=split_first_byte,
        digest_name="forest-diamond-path-test",
    )
    root = _root_with_boards(history, BOARDS_2X2[:2])
    payload = _payload(history.serialize_forest((root,)))
    root_id = payload["roots"][0]["node_ref"]["node_id"]
    root_record = payload["nodes"][root_id]
    assert root_record["kind"] == "branch"
    assert len(root_record["children"]) == 2

    first, second = root_record["children"]
    assert first["slot"] != second["slot"]
    second["child_id"] = first["child_id"]
    second["child_sha256"] = first["child_sha256"]

    with pytest.raises(ValueError, match="slot does not match child digest path"):
        PersistentHistory(
            2,
            digest_fn=split_first_byte,
            digest_name="forest-diamond-path-test",
        ).deserialize_forest(_rehashed(payload))


def test_forest_adoption_memory_error_rolls_back_collision_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def constant_digest(_board: bytes) -> bytes:
        return bytes(32)

    source = PersistentHistory(
        2,
        digest_fn=constant_digest,
        digest_name="forest-adoption-oom-test",
    )
    source_root = _root_with_boards(source, BOARDS_2X2[1:])
    raw = source.serialize_forest((source_root,))

    destination = PersistentHistory(
        2,
        digest_fn=constant_digest,
        digest_name="forest-adoption-oom-test",
    )
    existing_root = destination.insert(destination.empty_root, BOARDS_2X2[0])

    def intern_snapshot() -> tuple[object, ...]:
        return (
            tuple(
                (digest, tuple(id(board) for board in bucket))
                for digest, bucket in sorted(destination._digest_index.items())
            ),
            tuple(
                sorted(
                    (raw_board, id(board))
                    for raw_board, board in destination._exact_index.items()
                )
            ),
            destination.board_object_count,
            tuple(id(board) for board in destination._intern_journal),
            destination._intern_transaction_token,
            destination.members(existing_root),
        )

    before = intern_snapshot()
    real_adopt = PersistentHistory._adopt_verified_board
    calls = 0

    def fail_second_adoption(
        self: PersistentHistory, board: object
    ) -> object:
        nonlocal calls
        if self is destination:
            calls += 1
            if calls == 2:
                raise MemoryError("injected forest board adoption failure")
        return real_adopt(self, board)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr(
        PersistentHistory,
        "_adopt_verified_board",
        fail_second_adoption,
    )
    with pytest.raises(MemoryError, match="injected forest board adoption failure"):
        destination.deserialize_forest(raw)
    assert intern_snapshot() == before

    monkeypatch.setattr(PersistentHistory, "_adopt_verified_board", real_adopt)
    loaded_roots = destination.deserialize_forest(raw)
    assert destination.members(loaded_roots[0]) == tuple(sorted(BOARDS_2X2[1:]))
    assert destination.members(existing_root) == (BOARDS_2X2[0],)


def test_forest_node_construction_memory_error_rolls_back_adopted_boards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = PersistentHistory(2)
    source_root = _root_with_boards(source, BOARDS_2X2[:3])
    raw = source.serialize_forest((source_root,))
    destination = PersistentHistory(2)
    existing_root = destination.insert(destination.empty_root, BOARDS_2X2[3])
    before_exact = dict(destination._exact_index)
    before_buckets = {
        digest: tuple(bucket) for digest, bucket in destination._digest_index.items()
    }
    real_make_branch = persistent_history_module._make_branch

    def fail_active_transaction(depth: int, children: object) -> object:
        if destination._intern_transaction_token is not None:
            raise MemoryError("injected forest node construction failure")
        return real_make_branch(depth, children)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr(
        persistent_history_module,
        "_make_branch",
        fail_active_transaction,
    )
    with pytest.raises(MemoryError, match="injected forest node construction failure"):
        destination.deserialize_forest(raw)

    assert destination._exact_index == before_exact
    assert {
        digest: tuple(bucket) for digest, bucket in destination._digest_index.items()
    } == before_buckets
    assert destination.members(existing_root) == (BOARDS_2X2[3],)
    assert destination._intern_journal == []
    assert destination._intern_transaction_token is None


def test_empty_forest_and_empty_roots_are_canonical() -> None:
    history = PersistentHistory(2)
    empty_forest = history.serialize_forest(())
    empty_roots = history.serialize_forest(
        (history.empty_root, history.empty_root)
    )

    loaded_empty = PersistentHistory(2).deserialize_forest(empty_forest)
    loaded_roots = PersistentHistory(2).deserialize_forest(empty_roots)
    assert loaded_empty == ()
    assert [root.count for root in loaded_roots] == [0, 0]
    assert _payload(empty_forest)["node_record_count"] == 0
    assert _payload(empty_roots)["board_record_count"] == 0


def test_failed_atomic_forest_publication_preserves_previous_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = PersistentHistory(2)
    first = history.insert(history.empty_root, BOARDS_2X2[0])
    second = history.insert(first, BOARDS_2X2[1])
    artifact = tmp_path / "atomic-forest.json"
    history.save_forest(artifact, (first,))
    previous = artifact.read_bytes()

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("injected forest publication failure")

    monkeypatch.setattr(persistent_history_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected forest publication failure"):
        history.save_forest(artifact, (first, second))
    assert artifact.read_bytes() == previous
    assert not list(tmp_path.glob(".atomic-forest.json.tmp-*"))
