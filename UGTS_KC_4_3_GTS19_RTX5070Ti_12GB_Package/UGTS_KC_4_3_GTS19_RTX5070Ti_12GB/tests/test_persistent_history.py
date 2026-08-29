"""Bounded tests for the immutable host-RAM positional-superko set."""

from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path

import pytest

import ugts_go19.persistent_history as persistent_history_module
from ugts_go19.digests import canonical_json_bytes, sha256_hex
from ugts_go19.persistent_history import PersistentHistory, roots_exactly_equal


BOARDS_2X2 = (
    bytes((0, 0, 0, 0)),
    bytes((1, 0, 0, 0)),
    bytes((0, 2, 0, 0)),
    bytes((0, 0, 1, 0)),
)


def _payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_rehashed(path: Path, payload: dict) -> None:
    unhashed = dict(payload)
    unhashed.pop("artifact_sha256", None)
    payload["artifact_sha256"] = sha256_hex(canonical_json_bytes(unhashed))
    path.write_bytes(canonical_json_bytes(payload) + b"\n")


def _root_with_boards(history: PersistentHistory, boards: tuple[bytes, ...]):
    root = history.empty_root
    for board in boards:
        root = history.insert(root, board)
    return root


def test_root_and_serialization_are_independent_of_insertion_order() -> None:
    history = PersistentHistory(2)
    reference = _root_with_boards(history, BOARDS_2X2)
    reference_bytes = history.serialize_root(reference)

    # All 24 orders remain quick while proving collision-bucket and child order
    # are canonical rather than allocation/insertion order.
    for order in itertools.permutations(BOARDS_2X2):
        candidate = _root_with_boards(history, order)
        assert candidate == reference
        assert candidate.root_sha256 == reference.root_sha256
        assert history.roots_equal(candidate, reference)
        assert history.serialize_root(candidate) == reference_bytes


def test_canonical_roots_match_across_fresh_stores_and_all_insert_orders() -> None:
    reference_history = PersistentHistory(2)
    reference_root = _root_with_boards(reference_history, BOARDS_2X2[:3])
    reference_bytes = reference_history.serialize_root(reference_root)

    for order in itertools.permutations(BOARDS_2X2[:3]):
        candidate_history = PersistentHistory(2)
        candidate_root = _root_with_boards(candidate_history, order)
        assert candidate_history.serialize_root(candidate_root) == reference_bytes
        assert roots_exactly_equal(
            reference_history,
            reference_root,
            candidate_history,
            candidate_root,
        )

    different_history = PersistentHistory(2)
    different_root = _root_with_boards(different_history, BOARDS_2X2[:2])
    assert not roots_exactly_equal(
        reference_history,
        reference_root,
        different_history,
        different_root,
    )


def test_insertion_keeps_old_root_immutable_and_shares_untouched_subtries() -> None:
    history = PersistentHistory(2)
    old_root = _root_with_boards(history, BOARDS_2X2[:3])
    old_members = history.members(old_root)
    new_root = history.insert(old_root, BOARDS_2X2[3])

    assert history.members(old_root) == old_members
    assert not history.contains(old_root, BOARDS_2X2[3])
    assert history.contains(new_root, BOARDS_2X2[3])
    assert old_root.count == 3
    assert new_root.count == 4
    assert history.shared_node_count(old_root, new_root) > 0
    assert history.insert(new_root, BOARDS_2X2[3]) is new_root


def test_constant_digest_retains_distinct_exact_boards_and_deduplicates() -> None:
    def constant_digest(_board: bytes) -> bytes:
        return bytes(32)

    history = PersistentHistory(
        2,
        digest_fn=constant_digest,
        digest_name="constant-test",
    )
    root = _root_with_boards(history, BOARDS_2X2[:3])
    reverse = _root_with_boards(history, tuple(reversed(BOARDS_2X2[:3])))

    assert root == reverse
    assert root.count == 3
    assert history.board_object_count == 3
    assert history.digest_bucket_sizes() == (3,)
    for board in BOARDS_2X2[:3]:
        assert history.contains(root, board)
    assert not history.contains(root, BOARDS_2X2[3])
    assert history.insert(root, BOARDS_2X2[0]) is root


def test_roots_equal_is_structural_and_never_materializes_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = PersistentHistory(
        2,
        digest_fn=lambda _board: bytes(32),
        digest_name="structural-root-equality-collision-test",
    )
    first = _root_with_boards(history, BOARDS_2X2[:3])
    equivalent = _root_with_boards(
        history,
        tuple(reversed(BOARDS_2X2[:3])),
    )
    different = _root_with_boards(
        history,
        (BOARDS_2X2[0], BOARDS_2X2[1], BOARDS_2X2[3]),
    )
    assert first._node is not equivalent._node

    def fail_if_materialized(
        _self: PersistentHistory,
        _root: object,
    ) -> tuple[bytes, ...]:
        raise AssertionError("roots_equal materialized exact members")

    monkeypatch.setattr(PersistentHistory, "members", fail_if_materialized)
    assert history.roots_equal(first, equivalent)
    assert not history.roots_equal(first, different)


def test_roundtrip_rehydrates_complete_exact_root_deterministically(
    tmp_path: Path,
) -> None:
    history = PersistentHistory(2)
    root = _root_with_boards(history, BOARDS_2X2)
    artifact = tmp_path / "history.json"
    roundtrip = tmp_path / "history-roundtrip.json"
    history.save_root(artifact, root)

    loaded_history, loaded_root = PersistentHistory.load(
        artifact,
        expected_board_size=2,
        expected_root_sha256=root.root_sha256,
    )
    assert loaded_root == root
    assert loaded_history.members(loaded_root) == history.members(root)
    assert loaded_root.root_sha256 == root.root_sha256
    loaded_history.save_root(roundtrip, loaded_root)
    assert roundtrip.read_bytes() == artifact.read_bytes()


def test_failed_atomic_root_publication_preserves_previous_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history = PersistentHistory(2)
    first = history.insert(history.empty_root, BOARDS_2X2[0])
    artifact = tmp_path / "atomic-history.json"
    history.save_root(artifact, first)
    previous = artifact.read_bytes()
    second = history.insert(first, BOARDS_2X2[1])

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("injected history publication failure")

    monkeypatch.setattr(persistent_history_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected history publication failure"):
        history.save_root(artifact, second)
    assert artifact.read_bytes() == previous
    assert not list(tmp_path.glob(".atomic-history.json.tmp-*"))


def test_deeply_nested_json_fails_closed_without_leaking_recursion_error() -> None:
    malformed = b"[" * 10_000 + b"0" + b"]" * 10_000 + b"\n"
    history = PersistentHistory(2)
    with pytest.raises(ValueError, match="not valid canonical JSON"):
        history.deserialize_root(malformed)


def test_lone_json_surrogate_fails_closed_without_unicode_error() -> None:
    history = PersistentHistory(1)
    with pytest.raises(ValueError, match="not valid canonical JSON"):
        history.deserialize_root(b'{"x":"\\ud800"}\n')


def test_constant_digest_roundtrip_requires_same_collision_index(tmp_path: Path) -> None:
    def constant_digest(_board: bytes) -> bytes:
        return bytes(32)

    history = PersistentHistory(
        2,
        digest_fn=constant_digest,
        digest_name="constant-test",
    )
    root = _root_with_boards(history, BOARDS_2X2[:3])
    artifact = tmp_path / "colliding-history.json"
    history.save_root(artifact, root)

    with pytest.raises(ValueError, match="requires its injected digest"):
        PersistentHistory.load(artifact)
    loaded, loaded_root = PersistentHistory.load(
        artifact,
        digest_fn=constant_digest,
        digest_name="constant-test",
        expected_root_sha256=root.root_sha256,
    )
    assert loaded.digest_bucket_sizes() == (3,)
    assert loaded.members(loaded_root) == tuple(sorted(BOARDS_2X2[:3]))


def test_load_never_returns_a_root_different_from_the_verified_digest_path(
    tmp_path: Path,
) -> None:
    constant_a = bytes.fromhex("a5" * 32)
    constant_b = bytes.fromhex("5a" * 32)

    def build_digest(_board: bytes) -> bytes:
        return constant_a

    source = PersistentHistory(
        2,
        digest_fn=build_digest,
        digest_name="stateful-regression",
    )
    source_root = source.insert(source.empty_root, BOARDS_2X2[0])
    artifact = tmp_path / "stateful-regression.json"
    source.save_root(artifact, source_root)

    calls = 0

    def changes_after_verification(_board: bytes) -> bytes:
        nonlocal calls
        calls += 1
        return constant_a if calls <= 2 else constant_b

    loaded, loaded_root = PersistentHistory.load(
        artifact,
        digest_fn=changes_after_verification,
        digest_name="stateful-regression",
        expected_root_sha256=source_root.root_sha256,
    )
    assert loaded_root.root_sha256 == source_root.root_sha256
    assert loaded.contains(loaded_root, BOARDS_2X2[0])


def test_loader_rejects_corruption_and_rehashed_missing_record(
    tmp_path: Path,
) -> None:
    history = PersistentHistory(2)
    root = _root_with_boards(history, BOARDS_2X2[:3])
    artifact = tmp_path / "history.json"
    history.save_root(artifact, root)

    corrupted = tmp_path / "corrupted.json"
    raw = bytearray(artifact.read_bytes())
    marker = b'"artifact_sha256":"'
    digest_start = raw.index(marker) + len(marker)
    raw[digest_start] = ord("1") if raw[digest_start] != ord("1") else ord("2")
    corrupted.write_bytes(raw)
    with pytest.raises(ValueError, match="content hash mismatch"):
        PersistentHistory.load(corrupted)

    missing = tmp_path / "missing-node.json"
    payload = _payload(artifact)
    payload["nodes"].pop()
    payload["node_record_count"] -= 1
    _write_rehashed(missing, payload)
    with pytest.raises(ValueError, match="missing or cyclic child"):
        PersistentHistory.load(missing)


def test_loader_rejects_rehashed_inner_tamper(tmp_path: Path) -> None:
    history = PersistentHistory(2)
    root = _root_with_boards(history, BOARDS_2X2[:2])
    artifact = tmp_path / "history.json"
    tampered = tmp_path / "tampered.json"
    history.save_root(artifact, root)

    payload = _payload(artifact)
    payload["nodes"][0]["count"] += 1
    payload["member_count"] += 1
    _write_rehashed(tampered, payload)
    with pytest.raises(ValueError, match="branch member count mismatch"):
        PersistentHistory.load(tampered)


def test_loader_rejects_duplicate_conflicting_unreachable_and_malformed_records(
    tmp_path: Path,
) -> None:
    history = PersistentHistory(2)
    root = _root_with_boards(history, BOARDS_2X2[:2])
    artifact = tmp_path / "history.json"
    history.save_root(artifact, root)
    original = _payload(artifact)

    duplicate = copy.deepcopy(original)
    duplicate_board = copy.deepcopy(duplicate["boards"][0])
    duplicate_board["id"] = len(duplicate["boards"])
    duplicate["boards"].append(duplicate_board)
    duplicate["board_record_count"] += 1
    duplicate_path = tmp_path / "duplicate.json"
    _write_rehashed(duplicate_path, duplicate)
    with pytest.raises(ValueError, match="duplicate exact board"):
        PersistentHistory.load(duplicate_path)

    conflicting = copy.deepcopy(original)
    duplicate_node = copy.deepcopy(conflicting["nodes"][0])
    duplicate_node["id"] = len(conflicting["nodes"])
    conflicting["nodes"].append(duplicate_node)
    conflicting["node_record_count"] += 1
    conflicting_path = tmp_path / "conflicting.json"
    _write_rehashed(conflicting_path, conflicting)
    with pytest.raises(ValueError, match="duplicate immutable node"):
        PersistentHistory.load(conflicting_path)

    # Add a valid, canonically sorted board record without adding a leaf ref.
    unused_board = BOARDS_2X2[3]
    singleton_history = PersistentHistory(2)
    singleton_root = singleton_history.insert(singleton_history.empty_root, unused_board)
    singleton_payload = json.loads(
        singleton_history.serialize_root(singleton_root).decode("utf-8")
    )
    unreachable = copy.deepcopy(original)
    records = unreachable["boards"] + [copy.deepcopy(singleton_payload["boards"][0])]
    records.sort(key=lambda record: (record["index_digest"], record["raw_hex"]))
    raw_to_id: dict[str, int] = {}
    for board_id, record in enumerate(records):
        record["id"] = board_id
        raw_to_id[record["raw_hex"]] = board_id
    for node in unreachable["nodes"]:
        if node["kind"] == "leaf":
            for board_ref in node["boards"]:
                board_ref["board_id"] = raw_to_id[board_ref["raw_hex"]]
    unreachable["boards"] = records
    unreachable["board_record_count"] = len(records)
    unreachable_path = tmp_path / "unreachable.json"
    _write_rehashed(unreachable_path, unreachable)
    with pytest.raises(ValueError, match="unreachable board"):
        PersistentHistory.load(unreachable_path)

    malformed = copy.deepcopy(original)
    malformed["nodes"][0]["unexpected"] = True
    malformed_path = tmp_path / "malformed.json"
    _write_rehashed(malformed_path, malformed)
    with pytest.raises(ValueError, match="noncanonical shape"):
        PersistentHistory.load(malformed_path)


def test_loader_rejects_wrong_board_size_and_root_pin(tmp_path: Path) -> None:
    history = PersistentHistory(2)
    root = _root_with_boards(history, BOARDS_2X2[:2])
    artifact = tmp_path / "history.json"
    history.save_root(artifact, root)

    with pytest.raises(ValueError, match="expected board size"):
        PersistentHistory.load(artifact, expected_board_size=3)
    with pytest.raises(ValueError, match="expected root"):
        PersistentHistory.load(
            artifact,
            expected_root_sha256="00" * 32,
        )
    wrong_store = PersistentHistory(3)
    with pytest.raises(ValueError, match="board size mismatch"):
        wrong_store.deserialize_root(artifact.read_bytes())

    wrong_size = tmp_path / "wrong-size.json"
    payload = _payload(artifact)
    payload["board_size"] = 3
    payload["board_bytes"] = 9
    _write_rehashed(wrong_size, payload)
    with pytest.raises(ValueError, match="expected 9"):
        PersistentHistory.load(wrong_size)


def test_external_pin_rejects_a_fully_valid_replacement_set(tmp_path: Path) -> None:
    trusted_history = PersistentHistory(2)
    trusted_root = _root_with_boards(trusted_history, BOARDS_2X2[:2])
    replacement_history = PersistentHistory(2)
    replacement_root = _root_with_boards(replacement_history, BOARDS_2X2[:3])
    replacement = tmp_path / "fully-valid-replacement.json"
    replacement_history.save_root(replacement, replacement_root)

    # The artifact is internally valid and therefore readable without a pin.
    loaded, loaded_root = PersistentHistory.load(replacement)
    assert roots_exactly_equal(
        replacement_history,
        replacement_root,
        loaded,
        loaded_root,
    )
    with pytest.raises(ValueError, match="expected root"):
        PersistentHistory.load(
            replacement,
            expected_root_sha256=trusted_root.root_sha256,
        )


def test_fixed_length_representation_supports_19x19_board_bytes() -> None:
    history = PersistentHistory(19)
    empty = bytes(19 * 19)
    one_stone = bytes((1,)) + bytes(19 * 19 - 1)
    root = history.insert(history.empty_root, empty)
    root = history.insert(root, one_stone)

    assert root.count == 2
    assert history.contains(root, empty)
    assert history.contains(root, one_stone)
    with pytest.raises(ValueError, match="expected 361"):
        history.insert(root, bytes(360))
