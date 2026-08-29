"""Bounded durability tests for immutable exact-object segments."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import ugts_go19.segment_store as segment_store_module
from ugts_go19.digests import canonical_json_bytes
from ugts_go19.persistent_history import PersistentHistory
from ugts_go19.segment_store import (
    DigestCollisionError,
    ImmutableSegmentStore,
    SegmentStoreError,
)


def _all_store_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _constant_digest(_data: bytes) -> bytes:
    return bytes.fromhex("a5" * 32)


def _self_hash(payload: dict, field: str) -> str:
    unhashed = dict(payload)
    unhashed.pop(field, None)
    digest = hashlib.sha256(canonical_json_bytes(unhashed)).hexdigest()
    payload[field] = digest
    return digest


def test_deterministic_segment_manifest_and_restart_roundtrip(tmp_path: Path) -> None:
    objects = [
        ("board", bytes((0, 1, 2, 0))),
        ("board", bytes((2, 1, 0, 2))),
        (
            "history",
            canonical_json_bytes(
                {"format": "bounded-history-test-v1", "members": ["0000", "0102"]}
            )
            + b"\n",
        ),
    ]
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    lazy_root = tmp_path / "lazy"
    first = ImmutableSegmentStore(first_root)
    second = ImmutableSegmentStore(second_root)
    lazy = ImmutableSegmentStore(lazy_root, lazy_payloads=True)
    first_refs = [first.stage(kind, payload) for kind, payload in objects]
    second_refs = [second.stage(kind, payload) for kind, payload in reversed(objects)]
    lazy_refs = [lazy.stage(kind, payload) for kind, payload in reversed(objects)]

    first_snapshot = first.publish()
    second_snapshot = second.publish()
    lazy_snapshot = lazy.publish()

    assert first_snapshot == second_snapshot == lazy_snapshot
    assert _all_store_files(first_root) == _all_store_files(second_root)
    assert _all_store_files(first_root) == _all_store_files(lazy_root)
    assert lazy.resident_payload_bytes == 0
    assert first_snapshot.generation == 1
    assert first_snapshot.object_count == 3
    assert len(first_snapshot.segment_sha256s) == 1

    restarted = ImmutableSegmentStore(first_root)
    assert restarted.snapshot == first_snapshot
    assert restarted.object_count == 3
    for ref, (kind, payload) in zip(first_refs, objects):
        assert ref.kind == kind
        assert restarted.lookup_exact(kind, payload) == ref
        assert restarted.read(ref) == payload
    assert set(second_refs) == set(first_refs)
    assert set(lazy_refs) == set(first_refs)
    lazy.close()


def test_persistent_history_artifact_and_exact_boards_survive_restart(
    tmp_path: Path,
) -> None:
    history = PersistentHistory(2)
    first_board = bytes((0, 1, 2, 0))
    second_board = bytes((2, 1, 0, 2))
    root = history.insert(history.empty_root, first_board)
    root = history.insert(root, second_board)
    artifact = history.serialize_root(root)

    store = ImmutableSegmentStore(tmp_path / "store")
    board_refs = [store.stage_board(board) for board in history.members(root)]
    history_ref = store.stage_history(artifact)
    snapshot = store.publish()
    assert snapshot.object_count == 3

    restarted = ImmutableSegmentStore(tmp_path / "store")
    restored_artifact = restarted.read(history_ref)
    # Deserialize from the exact segment bytes, rather than trusting the
    # history object's SHA-256 reference.
    fresh_history = PersistentHistory(2)
    restored_root = fresh_history.deserialize_root(
        restored_artifact,
        expected_root_sha256=root.root_sha256,
    )
    assert fresh_history.members(restored_root) == history.members(root)
    assert [restarted.read(ref) for ref in board_refs] == list(history.members(root))


def test_deliberate_digest_collision_requires_exact_equality_after_restart(
    tmp_path: Path,
) -> None:
    first_payload = bytes((0, 0, 1, 2))
    second_payload = bytes((2, 1, 0, 0))
    store = ImmutableSegmentStore(
        tmp_path / "collisions",
        digest_fn=_constant_digest,
        digest_name="constant-a5-test",
    )
    first_ref = store.stage_board(first_payload)
    second_ref = store.stage_board(second_payload)
    assert first_ref == second_ref
    assert store.staged_count == 2
    assert store.collision_bucket_sizes() == (2,)
    assert store.lookup_exact("board", first_payload) == first_ref
    assert store.lookup_exact("board", second_payload) == second_ref
    with pytest.raises(DigestCollisionError, match="ambiguous"):
        store.read(first_ref)
    assert store.read(first_ref, expected_payload=first_payload) == first_payload
    assert store.read(second_ref, expected_payload=second_payload) == second_payload
    store.publish()

    restarted = ImmutableSegmentStore(
        tmp_path / "collisions",
        digest_fn=_constant_digest,
        digest_name="constant-a5-test",
    )
    assert restarted.collision_bucket_sizes() == (2,)
    with pytest.raises(DigestCollisionError, match="ambiguous"):
        restarted.read(first_ref)
    assert (
        restarted.read(first_ref, expected_payload=first_payload) == first_payload
    )
    with pytest.raises(KeyError, match="no exact object"):
        restarted.read(first_ref, expected_payload=b"not present")


def test_injected_digest_is_pinned_and_recomputed_on_restart(tmp_path: Path) -> None:
    root = tmp_path / "digest-envelope"
    store = ImmutableSegmentStore(
        root,
        digest_fn=_constant_digest,
        digest_name="constant-a5-test",
    )
    store.stage_board(bytes((0, 1, 2, 0)))
    store.publish()

    with pytest.raises(SegmentStoreError, match="algorithm mismatch"):
        ImmutableSegmentStore(root)

    def different_constant(_data: bytes) -> bytes:
        return bytes.fromhex("5a" * 32)

    with pytest.raises(SegmentStoreError, match="object digest"):
        ImmutableSegmentStore(
            root,
            digest_fn=different_constant,
            digest_name="constant-a5-test",
        )


def test_snapshot_verifies_and_reads_in_a_fresh_process(tmp_path: Path) -> None:
    root = tmp_path / "fresh-process"
    payload = bytes((0, 1, 2, 0))
    store = ImmutableSegmentStore(root)
    ref = store.stage_board(payload)
    expected = store.publish()
    script = (
        "import json,sys; "
        "from ugts_go19.segment_store import ImmutableSegmentStore,ObjectRef; "
        "store=ImmutableSegmentStore(sys.argv[1]); "
        "ref=ObjectRef('board',sys.argv[2]); "
        "payload=bytes.fromhex(sys.argv[3]); "
        "result={'generation':store.snapshot.generation,"
        "'manifest_sha256':store.snapshot.manifest_sha256,"
        "'object_count':store.snapshot.object_count,"
        "'payload_hex':store.read(ref,expected_payload=payload).hex()}; "
        "print(json.dumps(result,sort_keys=True,separators=(',',':')))"
    )
    environment = os.environ.copy()
    source = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = source + os.pathsep + environment.get(
        "PYTHONPATH", ""
    )
    process = subprocess.run(
        [sys.executable, "-c", script, str(root), ref.sha256, payload.hex()],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {
        "generation": expected.generation,
        "manifest_sha256": expected.manifest_sha256,
        "object_count": expected.object_count,
        "payload_hex": payload.hex(),
    }


def test_corrupt_segment_and_missing_segment_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "corrupt-segment"
    store = ImmutableSegmentStore(root)
    store.stage_board(bytes((0, 1, 2, 0)))
    snapshot = store.publish()
    segment_path = root / "segments" / f"{snapshot.segment_sha256s[0]}.seg"
    original = segment_path.read_bytes()

    corrupted = bytearray(original)
    corrupted[-1] ^= 1
    segment_path.write_bytes(corrupted)
    with pytest.raises(SegmentStoreError, match="SHA-256 mismatch"):
        ImmutableSegmentStore(root)

    segment_path.write_bytes(original)
    segment_path.unlink()
    with pytest.raises(SegmentStoreError, match="segment is missing"):
        ImmutableSegmentStore(root)


def test_torn_pointer_and_manifest_corruption_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "torn"
    store = ImmutableSegmentStore(root)
    store.stage_board(bytes((0, 1, 2, 0)))
    snapshot = store.publish()
    pointer_path = root / "CURRENT"
    pointer_original = pointer_path.read_bytes()

    pointer_path.write_bytes(pointer_original[: len(pointer_original) // 2])
    with pytest.raises(SegmentStoreError, match="canonical JSON|newline"):
        ImmutableSegmentStore(root)

    pointer_path.write_bytes(pointer_original)
    manifest_path = root / "manifests" / f"{snapshot.manifest_sha256}.json"
    manifest_original = manifest_path.read_bytes()
    corrupted = bytearray(manifest_original)
    marker = b'"object_count":1'
    marker_offset = corrupted.index(marker) + len(marker) - 1
    corrupted[marker_offset] = ord("2")
    manifest_path.write_bytes(corrupted)
    with pytest.raises(SegmentStoreError, match="content hash mismatch"):
        ImmutableSegmentStore(root)


def test_unreferenced_torn_temp_file_is_not_part_of_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "orphan-temp"
    store = ImmutableSegmentStore(root)
    payload = bytes((0, 1, 2, 0))
    ref = store.stage_board(payload)
    snapshot = store.publish()
    (root / ".CURRENT.tmp-torn").write_bytes(b'{"incomplete":')
    (root / "segments" / ".orphan.tmp-torn").write_bytes(b"partial")

    restarted = ImmutableSegmentStore(root)
    assert restarted.snapshot == snapshot
    assert restarted.read(ref) == payload


def test_missing_current_with_immutable_content_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "lost-current"
    store = ImmutableSegmentStore(root)
    store.stage_board(bytes((0, 1, 2, 0)))
    store.publish()
    (root / "CURRENT").unlink()

    with pytest.raises(SegmentStoreError, match="without a published CURRENT"):
        ImmutableSegmentStore(root)


def test_failed_current_replace_preserves_previous_verified_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "publication-failure"
    store = ImmutableSegmentStore(root)
    first_ref = store.stage_board(bytes((0, 1, 2, 0)))
    first_snapshot = store.publish()
    previous_pointer = (root / "CURRENT").read_bytes()
    store.stage_board(bytes((2, 1, 0, 2)))
    real_replace = os.replace

    def fail_current_replace(source: object, destination: object) -> None:
        if Path(destination) == root / "CURRENT":
            raise OSError("injected CURRENT publication failure")
        real_replace(source, destination)

    monkeypatch.setattr(segment_store_module.os, "replace", fail_current_replace)
    with pytest.raises(OSError, match="injected CURRENT"):
        store.publish()

    assert (root / "CURRENT").read_bytes() == previous_pointer
    assert not list(root.glob(".CURRENT.tmp-*"))
    restarted = ImmutableSegmentStore(root)
    assert restarted.snapshot == first_snapshot
    assert restarted.object_count == 1
    assert restarted.read(first_ref) == bytes((0, 1, 2, 0))


def test_append_manifest_lineage_and_previous_objects_verify(tmp_path: Path) -> None:
    root = tmp_path / "lineage"
    store = ImmutableSegmentStore(root)
    first_payload = bytes((0, 1, 2, 0))
    second_payload = bytes((2, 1, 0, 2))
    first_ref = store.stage_board(first_payload)
    first = store.publish()
    second_ref = store.stage_board(second_payload)
    second = store.publish()

    assert second.generation == 2
    assert second.object_count == 2
    assert second.segment_sha256s[:1] == first.segment_sha256s
    assert len(second.segment_sha256s) == 2
    restarted = ImmutableSegmentStore(root)
    assert restarted.read(first_ref) == first_payload
    assert restarted.read(second_ref) == second_payload

    first_manifest = root / "manifests" / f"{first.manifest_sha256}.json"
    first_manifest.unlink()
    with pytest.raises(SegmentStoreError, match="manifest is missing"):
        ImmutableSegmentStore(root)


def test_rehashed_manifest_cannot_truncate_append_only_lineage(tmp_path: Path) -> None:
    root = tmp_path / "lineage-tamper"
    store = ImmutableSegmentStore(root)
    store.stage_board(bytes((0, 1, 2, 0)))
    store.publish()
    store.stage_board(bytes((2, 1, 0, 2)))
    second = store.publish()

    manifest_path = root / "manifests" / f"{second.manifest_sha256}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["previous_manifest_sha256"] = None
    forged_manifest_digest = _self_hash(manifest, "manifest_sha256")
    forged_manifest_path = root / "manifests" / f"{forged_manifest_digest}.json"
    forged_manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")

    pointer_path = root / "CURRENT"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["manifest_file"] = forged_manifest_path.name
    pointer["manifest_sha256"] = forged_manifest_digest
    _self_hash(pointer, "pointer_sha256")
    pointer_path.write_bytes(canonical_json_bytes(pointer) + b"\n")

    with pytest.raises(SegmentStoreError, match="prematurely truncated"):
        ImmutableSegmentStore(root)


def test_external_manifest_pin_rejects_valid_rollback(tmp_path: Path) -> None:
    root = tmp_path / "externally-pinned-tip"
    store = ImmutableSegmentStore(root, lazy_payloads=True)
    store.stage_board(b"first")
    first = store.spill_staged()
    first_pointer = (root / "CURRENT").read_bytes()
    store.stage_board(b"second")
    second = store.spill_staged()
    store.close()

    # A rollback to a fully valid older pointer is internally consistent, so
    # it is detectable only when the caller supplies its independently kept
    # expected campaign tip.
    (root / "CURRENT").write_bytes(first_pointer)
    unpinned = ImmutableSegmentStore(root, lazy_payloads=True)
    assert unpinned.snapshot == first
    unpinned.close()
    with pytest.raises(SegmentStoreError, match="expected external tip"):
        ImmutableSegmentStore(
            root,
            lazy_payloads=True,
            expected_manifest_sha256=second.manifest_sha256,
        )

    with pytest.raises(ValueError, match="lowercase 256-bit"):
        ImmutableSegmentStore(
            tmp_path / "invalid-tip",
            expected_manifest_sha256="NOT-A-SHA256",
        )


def test_file_data_is_fsynced_before_successful_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        calls.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(segment_store_module.os, "fsync", recording_fsync)
    store = ImmutableSegmentStore(tmp_path / "fsync")
    store.stage_board(bytes((0, 1, 2, 0)))
    store.publish()

    # At minimum: immutable segment, immutable manifest, and CURRENT temp.
    # POSIX additionally fsyncs the affected directories.
    assert len(calls) >= 3


def test_empty_publish_and_noncanonical_inputs_fail_closed(tmp_path: Path) -> None:
    store = ImmutableSegmentStore(tmp_path / "empty")
    with pytest.raises(ValueError, match="empty"):
        store.publish()
    with pytest.raises(TypeError, match="immutable bytes"):
        store.stage_board(bytearray((0, 1, 2, 0)))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="explicit non-sha256"):
        ImmutableSegmentStore(
            tmp_path / "bad-digest-name",
            digest_fn=_constant_digest,
            digest_name="sha256",
        )
    with pytest.raises(SegmentStoreError, match="not valid canonical JSON"):
        segment_store_module._decode_canonical_json(
            b'{"x":"\\ud800"}\n', "adversarial input"
        )
    deeply_nested = b"[" * 10_000 + b"0" + b"]" * 10_000 + b"\n"
    with pytest.raises(SegmentStoreError, match="not valid canonical JSON"):
        segment_store_module._decode_canonical_json(
            deeply_nested, "adversarial input"
        )


def test_lazy_spill_drops_resident_payloads_and_supports_append_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lazy-spill"
    first_payload = b"first:" + bytes(range(256)) * 1024
    second_payload = b"second:" + bytes(reversed(range(256))) * 512
    store = ImmutableSegmentStore(root, lazy_payloads=True)
    first_ref = store.stage_history(first_payload)
    assert store.staged_payload_bytes == len(first_payload)
    assert store.resident_payload_bytes == len(first_payload)

    first_snapshot = store.spill_staged()
    assert first_snapshot.object_count == 1
    assert store.staged_payload_bytes == 0
    assert store.resident_payload_bytes == 0
    assert store.mapped_segment_count == 1
    assert all(
        isinstance(record, segment_store_module._DiskObjectRecord)
        for bucket in store._records.values()
        for record in bucket
    )
    assert store.read(first_ref, expected_payload=first_payload) == first_payload

    second_ref = store.stage_history(second_payload)
    assert store.resident_payload_bytes == len(second_payload)
    second_snapshot = store.spill_staged()
    assert second_snapshot.generation == 2
    assert second_snapshot.object_count == 2
    assert store.resident_payload_bytes == 0
    assert store.mapped_segment_count == 2
    store.close()
    with pytest.raises(ValueError, match="closed"):
        store.read(first_ref)

    restarted = ImmutableSegmentStore(root, lazy_payloads=True)
    assert restarted.snapshot == second_snapshot
    assert restarted.resident_payload_bytes == 0
    assert restarted.mapped_segment_count == 2
    assert all(
        isinstance(record, segment_store_module._DiskObjectRecord)
        for bucket in restarted._records.values()
        for record in bucket
    )
    assert restarted.lookup_exact("history", first_payload) == first_ref
    assert restarted.lookup_exact("history", second_payload) == second_ref
    assert restarted.read(first_ref, expected_payload=first_payload) == first_payload
    assert restarted.read(second_ref, expected_payload=second_payload) == second_payload
    restarted.close()


def test_lazy_mode_preserves_exact_collision_fallback_after_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lazy-collisions"
    first_payload = b"collision-a" * 1000
    second_payload = b"collision-b" * 1000
    store = ImmutableSegmentStore(
        root,
        lazy_payloads=True,
        digest_fn=_constant_digest,
        digest_name="constant-a5-test",
    )
    ref = store.stage_board(first_payload)
    assert store.stage_board(second_payload) == ref
    store.spill_staged()
    assert store.resident_payload_bytes == 0
    store.close()

    restarted = ImmutableSegmentStore(
        root,
        lazy_payloads=True,
        digest_fn=_constant_digest,
        digest_name="constant-a5-test",
    )
    assert restarted.resident_payload_bytes == 0
    assert restarted.collision_bucket_sizes() == (2,)
    with pytest.raises(DigestCollisionError, match="ambiguous"):
        restarted.read(ref)
    assert restarted.read(ref, expected_payload=first_payload) == first_payload
    assert restarted.read(ref, expected_payload=second_payload) == second_payload
    restarted.close()


def test_lazy_staged_threshold_performs_real_bounded_spills(tmp_path: Path) -> None:
    root = tmp_path / "lazy-threshold"
    store = ImmutableSegmentStore(
        root,
        lazy_payloads=True,
        staged_memory_limit_bytes=5,
    )
    first_ref = store.stage_board(b"12345")
    assert store.snapshot is None
    assert store.resident_payload_bytes == 5

    second_ref = store.stage_board(b"67890")
    assert store.snapshot is not None
    assert store.snapshot.generation == 1
    assert store.snapshot.object_count == 1
    assert store.staged_payload_bytes == 5
    assert store.resident_payload_bytes == 5

    final = store.spill_staged()
    assert final.generation == 2
    assert final.object_count == 2
    assert store.staged_payload_bytes == 0
    assert store.resident_payload_bytes == 0
    assert store.read(first_ref) == b"12345"
    assert store.read(second_ref) == b"67890"
    store.close()

    oversized = ImmutableSegmentStore(
        tmp_path / "oversized",
        lazy_payloads=True,
        staged_memory_limit_bytes=4,
    )
    with pytest.raises(ValueError, match="exceeds staged_memory"):
        oversized.stage_history(b"larger-than-limit")
    assert oversized.snapshot is None
    assert oversized.resident_payload_bytes == 0
    oversized.close()


def test_default_object_digest_does_not_build_a_payload_sized_preimage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbid_concatenated_preimage(_kind: str, _payload: bytes) -> bytes:
        raise AssertionError("default SHA-256 path copied the complete preimage")

    monkeypatch.setattr(
        segment_store_module, "_object_preimage", forbid_concatenated_preimage
    )
    store = ImmutableSegmentStore(
        tmp_path / "streamed-object-digest",
        lazy_payloads=True,
        staged_memory_limit_bytes=8,
    )
    ref = store.stage_board(b"12345678")
    store.spill_staged()
    assert store.read(ref) == b"12345678"
    store.close()


def test_lazy_corruption_rejects_and_releases_failed_mapping(tmp_path: Path) -> None:
    root = tmp_path / "lazy-corrupt"
    store = ImmutableSegmentStore(root, lazy_payloads=True)
    store.stage_board(b"disk-backed-board")
    snapshot = store.spill_staged()
    segment_path = root / "segments" / f"{snapshot.segment_sha256s[0]}.seg"
    original = segment_path.read_bytes()
    store.close()

    corrupted = bytearray(original)
    corrupted[-1] ^= 1
    segment_path.write_bytes(corrupted)
    with pytest.raises(SegmentStoreError, match="SHA-256 mismatch"):
        ImmutableSegmentStore(root, lazy_payloads=True)

    # On Windows this writable open also proves the failed constructor closed
    # its mmap/file handle rather than leaking a locked segment.
    with segment_path.open("r+b") as stream:
        stream.seek(0)
        stream.write(original)
        stream.truncate()
    reopened = ImmutableSegmentStore(root, lazy_payloads=True)
    assert reopened.resident_payload_bytes == 0
    reopened.close()


def test_lazy_read_rejects_post_validation_backing_file_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lazy-live-corruption"
    payload = b"proof-authoritative-payload"
    store = ImmutableSegmentStore(root, lazy_payloads=True)
    ref = store.stage_history(payload)
    snapshot = store.spill_staged()
    segment_path = root / "segments" / f"{snapshot.segment_sha256s[0]}.seg"
    original = segment_path.read_bytes()

    with segment_path.open("r+b") as stream:
        stream.seek(-1, os.SEEK_END)
        stream.write(bytes((original[-1] ^ 1,)))
        stream.flush()

    with pytest.raises(SegmentStoreError, match="changed after validation"):
        store.read(ref)
    with pytest.raises(SegmentStoreError, match="changed after validation"):
        store.lookup_exact("history", payload)
    store.close()
    segment_path.write_bytes(original)


def test_lazy_empty_referenced_segment_uses_store_error(tmp_path: Path) -> None:
    root = tmp_path / "lazy-empty-segment"
    store = ImmutableSegmentStore(root, lazy_payloads=True)
    store.stage_board(b"board")
    snapshot = store.spill_staged()
    segment_path = root / "segments" / f"{snapshot.segment_sha256s[0]}.seg"
    store.close()
    segment_path.write_bytes(b"")

    with pytest.raises(SegmentStoreError, match="cannot be mapped"):
        ImmutableSegmentStore(root, lazy_payloads=True)


def test_committed_publish_clears_staging_when_old_mapping_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "close-failure-after-commit"
    store = ImmutableSegmentStore(root, lazy_payloads=True)
    first_ref = store.stage_board(b"first")
    first = store.spill_staged()
    second_ref = store.stage_board(b"second")

    real_close = segment_store_module._MappedSegment.close
    close_calls = 0

    def close_then_fail_once(mapping: object) -> None:
        nonlocal close_calls
        close_calls += 1
        real_close(mapping)  # type: ignore[arg-type]
        if close_calls == 1:
            raise OSError("injected old-mapping cleanup failure")

    monkeypatch.setattr(
        segment_store_module._MappedSegment, "close", close_then_fail_once
    )
    with pytest.raises(OSError, match="injected"):
        store.spill_staged()

    committed = store.snapshot
    assert committed is not None
    assert committed.generation == first.generation + 1
    assert committed.object_count == 2
    assert store.staged_count == 0

    monkeypatch.setattr(segment_store_module._MappedSegment, "close", real_close)
    assert store.spill_staged() == committed
    store.close()

    restarted = ImmutableSegmentStore(root, lazy_payloads=True)
    assert restarted.snapshot == committed
    assert restarted.read(first_ref) == b"first"
    assert restarted.read(second_ref) == b"second"
    restarted.close()


def test_spill_configuration_and_close_refuse_silent_data_loss(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="requires disk-backed"):
        ImmutableSegmentStore(
            tmp_path / "eager-threshold",
            staged_memory_limit_bytes=1024,
        )
    eager = ImmutableSegmentStore(tmp_path / "eager")
    eager.stage_board(b"payload")
    with pytest.raises(ValueError, match="requires disk-backed"):
        eager.spill_staged()
    with pytest.raises(RuntimeError, match="staged objects"):
        eager.close()
    assert eager.staged_count == 1
    eager.publish()
    eager.close()

    discard = ImmutableSegmentStore(tmp_path / "discard", lazy_payloads=True)
    discard.stage_board(b"unpublished")
    discard.close(discard_staged=True)
    with pytest.raises(ValueError, match="closed"):
        discard.publish()
