"""Immutable, content-addressed host/NVMe segments for exact objects.

This module is a bounded storage vertical slice.  It persists exact board bytes
and exact serialized history artifacts in deterministic binary segment files.
SHA-256 names every segment and, in the production/default configuration,
indexes every object.  Object lookup always checks the type tag and raw bytes;
an index digest is never treated as identity.

Publication is ordered as immutable segment, immutable manifest, then an atomic
``CURRENT`` pointer replacement.  Files and portable directory entries are
fsynced before publication returns.  The implementation intentionally assumes
one writer per store directory; readers and restart verification are supported,
but multi-writer locking, a WAL, compaction, and garbage collection are outside
this slice. Optional lazy mode keeps validated mmap offsets rather than
retaining every published payload as a Python ``bytes`` object.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import struct
import tempfile
from typing import Any, BinaryIO, Callable, Iterable, TypeAlias

from .digests import canonical_json_bytes


SEGMENT_FORMAT = "UGTS-GO-IMMUTABLE-SEGMENT-v1"
MANIFEST_FORMAT = "UGTS-GO-SEGMENT-MANIFEST-v1"
POINTER_FORMAT = "UGTS-GO-SEGMENT-POINTER-v1"
SEGMENT_ENCODING = {
    "endianness": "big",
    "manifest_counter_bits": 64,
    "object_digest_bits": 256,
    "payload_length_bits": 64,
    "record_count_bits": 64,
    "record_kind_bits": 8,
}

_SEGMENT_MAGIC = b"UGTSGOSEGMENT\x00\x01\x00"
_SEGMENT_HEADER = struct.Struct(">16sQ")
_RECORD_HEADER = struct.Struct(">B32sQ")
_OBJECT_DOMAIN = b"UGTS-GO-EXACT-OBJECT-v1\x00"
_KIND_TO_CODE = {"board": 1, "history": 2}
_CODE_TO_KIND = {value: key for key, value in _KIND_TO_CODE.items()}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_DIGEST_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_UINT64_MAX = (1 << 64) - 1
_IO_CHUNK_BYTES = 1 << 20

DigestFunction = Callable[[bytes], bytes | str]


class SegmentStoreError(ValueError):
    """Base class for a malformed or inconsistent segment store."""


class DigestCollisionError(SegmentStoreError):
    """A digest-only request is ambiguous between unequal exact objects."""


@dataclass(frozen=True, order=True, slots=True)
class ObjectRef:
    """Typed content-address index.

    ``sha256`` is the SHA-256 object index in a production store.  Tests may
    explicitly configure another named 256-bit digest to exercise collision
    buckets; manifests pin that non-production algorithm name.
    """

    kind: str
    sha256: str

    def __post_init__(self) -> None:
        if self.kind not in _KIND_TO_CODE:
            raise ValueError("object kind must be 'board' or 'history'")
        if type(self.sha256) is not str or _HEX64.fullmatch(self.sha256) is None:
            raise ValueError("object digest must be lowercase 256-bit hexadecimal")

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class SegmentStoreSnapshot:
    """Verified immutable view named by one published manifest."""

    generation: int
    manifest_sha256: str
    segment_sha256s: tuple[str, ...]
    object_count: int


@dataclass(frozen=True, slots=True)
class _MemoryObjectRecord:
    ref: ObjectRef
    payload: bytes


class _MappedSegment:
    """Read-only mapped immutable segment with bounded-copy accessors."""

    __slots__ = ("path", "expected_sha256", "_mapping", "_stream")

    def __init__(self, path: Path, *, expected_sha256: str) -> None:
        self.path = path
        self.expected_sha256 = expected_sha256
        self._stream: BinaryIO = path.open("rb")
        try:
            self._mapping = mmap.mmap(
                self._stream.fileno(),
                length=0,
                access=mmap.ACCESS_READ,
            )
        except BaseException:
            self._stream.close()
            raise

    @property
    def byte_length(self) -> int:
        return len(self._mapping)

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset > len(self._mapping) - length:
            raise SegmentStoreError("mapped segment read is outside validated bounds")
        return self._mapping[offset : offset + length]

    def sha256_hex(self) -> str:
        digest = hashlib.sha256()
        for offset in range(0, len(self._mapping), _IO_CHUNK_BYTES):
            digest.update(self.read(offset, min(_IO_CHUNK_BYTES, len(self._mapping) - offset)))
        return digest.hexdigest()

    def verified_read(self, offset: int, length: int) -> bytes:
        """Copy bytes, then verify the still-mapped immutable segment.

        Startup validation alone is insufficient: another process can modify
        a read-only mapping's backing file after it has been opened. Copying
        first and hashing second ensures a normal post-open mutation is never
        returned under the previously validated content-addressed segment.
        """

        payload = self.read(offset, length)
        if self.sha256_hex() != self.expected_sha256:
            raise SegmentStoreError(
                "mapped immutable segment changed after validation"
            )
        return payload

    def close(self) -> None:
        try:
            self._mapping.close()
        finally:
            self._stream.close()


@dataclass(frozen=True, slots=True)
class _DiskObjectRecord:
    ref: ObjectRef
    segment: _MappedSegment
    payload_offset: int
    payload_length: int


_ObjectRecord: TypeAlias = _MemoryObjectRecord | _DiskObjectRecord


def _record_length(record: _ObjectRecord) -> int:
    if isinstance(record, _MemoryObjectRecord):
        return len(record.payload)
    return record.payload_length


def _record_chunk(record: _ObjectRecord, offset: int, length: int) -> bytes:
    if offset < 0 or length < 0 or offset > _record_length(record) - length:
        raise SegmentStoreError("object record read is outside validated bounds")
    if isinstance(record, _MemoryObjectRecord):
        return record.payload[offset : offset + length]
    return record.segment.read(record.payload_offset + offset, length)


def _record_bytes(record: _ObjectRecord) -> bytes:
    if isinstance(record, _MemoryObjectRecord):
        return record.payload
    return record.segment.verified_read(
        record.payload_offset, record.payload_length
    )


def _record_equals_payload(record: _ObjectRecord, payload: bytes) -> bool:
    if _record_length(record) != len(payload):
        return False
    if isinstance(record, _DiskObjectRecord):
        return _record_bytes(record) == payload
    for offset in range(0, len(payload), _IO_CHUNK_BYTES):
        length = min(_IO_CHUNK_BYTES, len(payload) - offset)
        if _record_chunk(record, offset, length) != payload[offset : offset + length]:
            return False
    return True


def _records_equal(first: _ObjectRecord, second: _ObjectRecord) -> bool:
    length = _record_length(first)
    if length != _record_length(second):
        return False
    if isinstance(first, _DiskObjectRecord) or isinstance(
        second, _DiskObjectRecord
    ):
        return _record_bytes(first) == _record_bytes(second)
    for offset in range(0, length, _IO_CHUNK_BYTES):
        chunk_length = min(_IO_CHUNK_BYTES, length - offset)
        if _record_chunk(first, offset, chunk_length) != _record_chunk(
            second, offset, chunk_length
        ):
            return False
    return True


def _compare_record_payloads(first: _ObjectRecord, second: _ObjectRecord) -> int:
    if isinstance(first, _DiskObjectRecord) or isinstance(
        second, _DiskObjectRecord
    ):
        first_payload = _record_bytes(first)
        second_payload = _record_bytes(second)
        return (first_payload > second_payload) - (
            first_payload < second_payload
        )
    shared_length = min(_record_length(first), _record_length(second))
    for offset in range(0, shared_length, _IO_CHUNK_BYTES):
        chunk_length = min(_IO_CHUNK_BYTES, shared_length - offset)
        first_chunk = _record_chunk(first, offset, chunk_length)
        second_chunk = _record_chunk(second, offset, chunk_length)
        if first_chunk != second_chunk:
            return -1 if first_chunk < second_chunk else 1
    first_length = _record_length(first)
    second_length = _record_length(second)
    return (first_length > second_length) - (first_length < second_length)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SegmentStoreError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise SegmentStoreError(f"non-finite JSON constant: {value}")


def _decode_canonical_json(raw: bytes, label: str) -> dict[str, Any]:
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise SegmentStoreError(f"{label} must end in exactly one newline")
    body = raw[:-1]
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        SegmentStoreError,
    ) as exc:
        raise SegmentStoreError(f"{label} is not valid canonical JSON") from exc
    if not isinstance(value, dict):
        raise SegmentStoreError(f"{label} must be a JSON object")
    try:
        canonical = canonical_json_bytes(value)
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise SegmentStoreError(f"{label} is not valid canonical JSON") from exc
    if canonical != body:
        raise SegmentStoreError(f"{label} is not in canonical form")
    return value


def _require_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise SegmentStoreError(f"{label} has a noncanonical shape")
    return value


def _require_int(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if (
        type(value) is not int
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        bound = (
            f" in {minimum}..{maximum}"
            if maximum is not None
            else f" at least {minimum}"
        )
        raise SegmentStoreError(f"{label} must be an integer{bound}")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise SegmentStoreError(
            f"{label} must be lowercase 256-bit hexadecimal text"
        )
    return value


def _object_preimage(kind: str, payload: bytes) -> bytes:
    code = _KIND_TO_CODE[kind]
    return _OBJECT_DOMAIN + bytes((code,)) + len(payload).to_bytes(8, "big") + payload


def _fsync_directory(path: Path) -> None:
    """Persist directory metadata where Python/the platform exposes it."""

    if os.name == "nt":
        # CPython cannot open directories for fsync on Windows.  File handles
        # are still flushed before every ReplaceFile-style os.replace call.
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_fsynced_temp(directory: Path, prefix: str, data: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=prefix, dir=directory)
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    return path


def _atomic_replace_bytes(path: Path, data: bytes) -> None:
    temporary = _write_fsynced_temp(path.parent, f".{path.name}.tmp-", data)
    try:
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _publish_immutable(path: Path, data: bytes) -> None:
    """Atomically install immutable bytes or verify an existing equal file."""

    try:
        existing = path.read_bytes()
    except FileNotFoundError:
        _atomic_replace_bytes(path, data)
        # Detect storage faults and a concurrent non-cooperating writer before
        # allowing this file to become reachable from a manifest.
        if path.read_bytes() != data:
            raise SegmentStoreError(f"immutable file verification failed: {path.name}")
        return
    if existing != data:
        raise SegmentStoreError(
            f"immutable content-addressed file conflicts: {path.name}"
        )


class ImmutableSegmentStore:
    """Single-writer immutable segment store with independently verified loads.

    Board and history payloads are opaque immutable bytes at this layer.  A
    board payload is normally the exact one-byte-per-point board; a history
    payload is normally ``PersistentHistory.serialize_root(root)``.  Their
    higher-level semantic validators remain authoritative.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        digest_fn: DigestFunction | None = None,
        digest_name: str | None = None,
        lazy_payloads: bool = False,
        staged_memory_limit_bytes: int | None = None,
        expected_manifest_sha256: str | None = None,
    ) -> None:
        self.root = Path(root)
        if type(lazy_payloads) is not bool:
            raise TypeError("lazy_payloads must be a boolean")
        if staged_memory_limit_bytes is not None and (
            type(staged_memory_limit_bytes) is not int
            or staged_memory_limit_bytes < 0
        ):
            raise ValueError("staged_memory_limit_bytes must be a nonnegative integer")
        if staged_memory_limit_bytes is not None and not lazy_payloads:
            raise ValueError(
                "staged_memory_limit_bytes requires disk-backed lazy_payloads mode"
            )
        if expected_manifest_sha256 is not None and (
            type(expected_manifest_sha256) is not str
            or _HEX64.fullmatch(expected_manifest_sha256) is None
        ):
            raise ValueError(
                "expected_manifest_sha256 must be lowercase 256-bit hexadecimal"
            )
        self.lazy_payloads = lazy_payloads
        self.staged_memory_limit_bytes = staged_memory_limit_bytes
        if digest_fn is None:
            if digest_name not in (None, "sha256"):
                raise ValueError("a non-sha256 digest name requires digest_fn")
            self._raw_digest_fn: DigestFunction = (
                lambda raw: hashlib.sha256(raw).digest()
            )
            self.digest_name = "sha256"
            self._uses_builtin_sha256 = True
        else:
            if not callable(digest_fn):
                raise TypeError("digest_fn must be callable")
            if digest_name in (None, "sha256"):
                raise ValueError(
                    "an injected digest requires an explicit non-sha256 name"
                )
            if (
                type(digest_name) is not str
                or _SAFE_DIGEST_NAME.fullmatch(digest_name) is None
            ):
                raise ValueError("digest_name is not a safe nonempty identifier")
            self._raw_digest_fn = digest_fn
            self.digest_name = digest_name
            self._uses_builtin_sha256 = False

        self.segments_directory = self.root / "segments"
        self.manifests_directory = self.root / "manifests"
        self.pointer_path = self.root / "CURRENT"
        self.root.mkdir(parents=True, exist_ok=True)
        self.segments_directory.mkdir(exist_ok=True)
        self.manifests_directory.mkdir(exist_ok=True)

        self._records: dict[ObjectRef, list[_ObjectRecord]] = {}
        self._staged: dict[ObjectRef, list[_MemoryObjectRecord]] = {}
        self._mapped_segments: list[_MappedSegment] = []
        self._manifest: dict[str, Any] | None = None
        self.snapshot: SegmentStoreSnapshot | None = None
        self._closed = False
        if self.pointer_path.exists():
            self._load_current()
        elif any(self.segments_directory.glob("*.seg")) or any(
            self.manifests_directory.glob("*.json")
        ):
            raise SegmentStoreError(
                "immutable content exists without a published CURRENT pointer"
            )
        if expected_manifest_sha256 is not None and (
            self.snapshot is None
            or self.snapshot.manifest_sha256 != expected_manifest_sha256
        ):
            mappings = self._mapped_segments
            self._mapped_segments = []
            self._records.clear()
            try:
                self._close_mappings(mappings)
            except BaseException:
                pass
            raise SegmentStoreError(
                "CURRENT manifest does not match the expected external tip"
            )

    @property
    def object_count(self) -> int:
        self._ensure_open()
        return sum(len(bucket) for bucket in self._records.values())

    @property
    def staged_count(self) -> int:
        self._ensure_open()
        return sum(len(bucket) for bucket in self._staged.values())

    @property
    def staged_payload_bytes(self) -> int:
        self._ensure_open()
        return self._staged_payload_bytes_unchecked()

    @property
    def resident_payload_bytes(self) -> int:
        """Payload bytes retained by the store as Python in-memory objects.

        Read-only mmap pages are deliberately excluded: they are disk-backed,
        evictable by the OS, and no full payload copy is retained by the store.
        """

        self._ensure_open()
        published = sum(
            _record_length(record)
            for bucket in self._records.values()
            for record in bucket
            if isinstance(record, _MemoryObjectRecord)
        )
        return published + self._staged_payload_bytes_unchecked()

    @property
    def mapped_segment_count(self) -> int:
        self._ensure_open()
        return len(self._mapped_segments)

    def _staged_payload_bytes_unchecked(self) -> int:
        return sum(
            len(record.payload)
            for bucket in self._staged.values()
            for record in bucket
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("segment store is closed")

    @staticmethod
    def _close_mappings(mappings: Iterable[_MappedSegment]) -> None:
        first_error: BaseException | None = None
        for segment in mappings:
            try:
                segment.close()
            except BaseException as exc:  # pragma: no cover - OS-level fallback
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def close(self, *, discard_staged: bool = False) -> None:
        """Close mappings; refuse to silently discard unpublished objects."""

        if self._closed:
            return
        if self._staged and not discard_staged:
            raise RuntimeError(
                "cannot close with staged objects; publish or pass discard_staged=True"
            )
        if discard_staged:
            self._staged.clear()
        mappings = self._mapped_segments
        self._mapped_segments = []
        try:
            self._close_mappings(mappings)
        finally:
            self._records.clear()
            self._closed = True

    def __enter__(self) -> "ImmutableSegmentStore":
        self._ensure_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close(discard_staged=exc_type is not None)

    def __del__(self) -> None:  # pragma: no cover - defensive resource release
        mappings = getattr(self, "_mapped_segments", ())
        self._mapped_segments = []
        try:
            self._close_mappings(mappings)
        except BaseException:
            pass

    def collision_bucket_sizes(self, *, include_staged: bool = True) -> tuple[int, ...]:
        self._ensure_open()
        sizes: dict[ObjectRef, int] = {
            ref: len(bucket) for ref, bucket in self._records.items()
        }
        if include_staged:
            for ref, bucket in self._staged.items():
                sizes[ref] = sizes.get(ref, 0) + len(bucket)
        return tuple(sorted(sizes.values()))

    def _digest(self, preimage: bytes) -> str:
        value = self._raw_digest_fn(preimage)
        if type(value) is bytes:
            if len(value) != 32:
                raise ValueError("digest_fn must return exactly 32 bytes")
            digest = value.hex()
        elif type(value) is str:
            digest = value
        else:
            raise TypeError("digest_fn must return bytes or hexadecimal text")
        if _HEX64.fullmatch(digest) is None:
            raise ValueError(
                "digest_fn must return lowercase 256-bit hexadecimal text"
            )
        return digest

    def object_ref(self, kind: str, payload: bytes) -> ObjectRef:
        self._ensure_open()
        if kind not in _KIND_TO_CODE:
            raise ValueError("object kind must be 'board' or 'history'")
        if type(payload) is not bytes:
            raise TypeError("object payload must be immutable bytes")
        if len(payload) > _UINT64_MAX:
            raise OverflowError("object payload length exceeds uint64")
        return ObjectRef(kind, self._object_digest(kind, payload))

    def _object_digest(self, kind: str, payload: bytes) -> str:
        if not self._uses_builtin_sha256:
            return self._digest(_object_preimage(kind, payload))
        digest = hashlib.sha256()
        digest.update(_OBJECT_DOMAIN)
        digest.update(bytes((_KIND_TO_CODE[kind],)))
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        return digest.hexdigest()

    @staticmethod
    def _exact_in_bucket(
        bucket: Iterable[_ObjectRecord], payload: bytes
    ) -> _ObjectRecord | None:
        return next(
            (record for record in bucket if _record_equals_payload(record, payload)),
            None,
        )

    def stage(self, kind: str, payload: bytes) -> ObjectRef:
        """Stage one exact immutable object, deduplicating only equal bytes."""

        self._ensure_open()
        if kind not in _KIND_TO_CODE:
            raise ValueError("object kind must be 'board' or 'history'")
        if type(payload) is not bytes:
            raise TypeError("object payload must be immutable bytes")
        limit = self.staged_memory_limit_bytes
        if limit is not None and len(payload) > limit:
            raise ValueError(
                "object payload exceeds staged_memory_limit_bytes; "
                "increase the explicit bound"
            )
        ref = self.object_ref(kind, payload)
        for mapping in (self._records, self._staged):
            exact = self._exact_in_bucket(mapping.get(ref, ()), payload)
            if exact is not None:
                return exact.ref
        if (
            limit is not None
            and self._staged
            and self._staged_payload_bytes_unchecked() > limit - len(payload)
        ):
            self.spill_staged()
        record = _MemoryObjectRecord(ref, payload)
        bucket = self._staged.setdefault(ref, [])
        bucket.append(record)
        bucket.sort(key=lambda item: item.payload)
        if limit is not None and self._staged_payload_bytes_unchecked() > limit:
            raise AssertionError("staged-memory threshold was exceeded")
        return ref

    def stage_board(self, board: bytes) -> ObjectRef:
        return self.stage("board", board)

    def stage_history(self, serialized_history: bytes) -> ObjectRef:
        return self.stage("history", serialized_history)

    def lookup_exact(self, kind: str, payload: bytes) -> ObjectRef | None:
        """Look up by digest bucket followed by exact raw-byte equality."""

        self._ensure_open()
        ref = self.object_ref(kind, payload)
        for mapping in (self._records, self._staged):
            if self._exact_in_bucket(mapping.get(ref, ()), payload) is not None:
                return ref
        return None

    def read(
        self,
        ref: ObjectRef,
        *,
        expected_payload: bytes | None = None,
    ) -> bytes:
        """Read an object, refusing ambiguous digest-only collision lookups."""

        self._ensure_open()
        if not isinstance(ref, ObjectRef):
            raise TypeError("ref must be an ObjectRef")
        if expected_payload is not None and type(expected_payload) is not bytes:
            raise TypeError("expected_payload must be immutable bytes or None")
        candidates = [
            *self._records.get(ref, ()),
            *self._staged.get(ref, ()),
        ]
        if expected_payload is not None:
            exact = self._exact_in_bucket(candidates, expected_payload)
            if exact is None:
                raise KeyError("no exact object matches the supplied content")
            return _record_bytes(exact)
        if not candidates:
            raise KeyError("object reference is not present")
        if len(candidates) != 1:
            raise DigestCollisionError(
                "digest-only lookup is ambiguous; supply expected exact bytes"
            )
        return _record_bytes(candidates[0])

    def spill_staged(self) -> SegmentStoreSnapshot:
        """Publish staged bytes and replace them with lazy disk-backed offsets."""

        self._ensure_open()
        if not self.lazy_payloads:
            raise ValueError("spill_staged requires disk-backed lazy_payloads mode")
        return self.publish()

    def _serialize_segment(
        self, records: Iterable[_MemoryObjectRecord]
    ) -> bytes:
        ordered = sorted(
            records,
            key=lambda record: (
                bytes.fromhex(record.ref.sha256),
                _KIND_TO_CODE[record.ref.kind],
                record.payload,
            ),
        )
        if not ordered:
            raise ValueError("cannot seal an empty immutable segment")
        unique = {(record.ref.kind, record.payload) for record in ordered}
        if len(unique) != len(ordered):
            raise SegmentStoreError("segment contains duplicate exact objects")
        chunks = [_SEGMENT_HEADER.pack(_SEGMENT_MAGIC, len(ordered))]
        for record in ordered:
            chunks.append(
                _RECORD_HEADER.pack(
                    _KIND_TO_CODE[record.ref.kind],
                    bytes.fromhex(record.ref.sha256),
                    len(record.payload),
                )
            )
            chunks.append(record.payload)
        return b"".join(chunks)

    def _parse_segment(
        self,
        raw: bytes,
        *,
        expected_sha256: str,
        expected_record_count: int,
    ) -> list[_MemoryObjectRecord]:
        if _sha256_hex(raw) != expected_sha256:
            raise SegmentStoreError("segment SHA-256 mismatch")
        if len(raw) < _SEGMENT_HEADER.size:
            raise SegmentStoreError("segment is truncated before its header")
        magic, count = _SEGMENT_HEADER.unpack_from(raw, 0)
        if magic != _SEGMENT_MAGIC:
            raise SegmentStoreError("unsupported immutable segment format")
        if count != expected_record_count:
            raise SegmentStoreError("segment record count disagrees with manifest")
        offset = _SEGMENT_HEADER.size
        records: list[_MemoryObjectRecord] = []
        sort_keys: list[tuple[bytes, int, bytes]] = []
        exact_keys: set[tuple[str, bytes]] = set()
        for _ in range(count):
            if len(raw) - offset < _RECORD_HEADER.size:
                raise SegmentStoreError("segment is truncated in a record header")
            code, digest_bytes, payload_length = _RECORD_HEADER.unpack_from(raw, offset)
            offset += _RECORD_HEADER.size
            kind = _CODE_TO_KIND.get(code)
            if kind is None:
                raise SegmentStoreError("segment record has an unknown object kind")
            if payload_length > len(raw) - offset:
                raise SegmentStoreError("segment is truncated in a record payload")
            payload = raw[offset : offset + payload_length]
            offset += payload_length
            digest = digest_bytes.hex()
            calculated = self._object_digest(kind, payload)
            if digest != calculated:
                raise SegmentStoreError("object digest does not match exact content")
            exact_key = (kind, payload)
            if exact_key in exact_keys:
                raise SegmentStoreError("segment repeats an exact object")
            exact_keys.add(exact_key)
            ref = ObjectRef(kind, digest)
            records.append(_MemoryObjectRecord(ref, payload))
            sort_keys.append((digest_bytes, code, payload))
        if offset != len(raw):
            raise SegmentStoreError("segment has trailing noncanonical bytes")
        if sort_keys != sorted(sort_keys):
            raise SegmentStoreError("segment records are not in canonical order")
        return records

    def _mapped_object_digest(
        self,
        kind: str,
        segment: _MappedSegment,
        payload_offset: int,
        payload_length: int,
    ) -> str:
        if not self._uses_builtin_sha256:
            payload = segment.read(payload_offset, payload_length)
            return self._digest(_object_preimage(kind, payload))
        digest = hashlib.sha256()
        digest.update(_OBJECT_DOMAIN)
        digest.update(bytes((_KIND_TO_CODE[kind],)))
        digest.update(payload_length.to_bytes(8, "big"))
        for relative_offset in range(0, payload_length, _IO_CHUNK_BYTES):
            length = min(_IO_CHUNK_BYTES, payload_length - relative_offset)
            digest.update(segment.read(payload_offset + relative_offset, length))
        return digest.hexdigest()

    def _parse_mapped_segment(
        self,
        segment: _MappedSegment,
        *,
        expected_sha256: str,
        expected_record_count: int,
    ) -> list[_DiskObjectRecord]:
        if segment.sha256_hex() != expected_sha256:
            raise SegmentStoreError("segment SHA-256 mismatch")
        if segment.byte_length < _SEGMENT_HEADER.size:
            raise SegmentStoreError("segment is truncated before its header")
        header = segment.read(0, _SEGMENT_HEADER.size)
        magic, count = _SEGMENT_HEADER.unpack(header)
        if magic != _SEGMENT_MAGIC:
            raise SegmentStoreError("unsupported immutable segment format")
        if count != expected_record_count:
            raise SegmentStoreError("segment record count disagrees with manifest")

        offset = _SEGMENT_HEADER.size
        records: list[_DiskObjectRecord] = []
        previous_primary: tuple[bytes, int] | None = None
        previous_record: _DiskObjectRecord | None = None
        for _ in range(count):
            if segment.byte_length - offset < _RECORD_HEADER.size:
                raise SegmentStoreError("segment is truncated in a record header")
            header = segment.read(offset, _RECORD_HEADER.size)
            code, digest_bytes, payload_length = _RECORD_HEADER.unpack(header)
            offset += _RECORD_HEADER.size
            kind = _CODE_TO_KIND.get(code)
            if kind is None:
                raise SegmentStoreError("segment record has an unknown object kind")
            if payload_length > segment.byte_length - offset:
                raise SegmentStoreError("segment is truncated in a record payload")
            payload_offset = offset
            offset += payload_length
            digest = digest_bytes.hex()
            calculated = self._mapped_object_digest(
                kind,
                segment,
                payload_offset,
                payload_length,
            )
            if digest != calculated:
                raise SegmentStoreError("object digest does not match exact content")
            record = _DiskObjectRecord(
                ObjectRef(kind, digest),
                segment,
                payload_offset,
                payload_length,
            )
            primary = (digest_bytes, code)
            if previous_primary is not None:
                if primary < previous_primary:
                    raise SegmentStoreError(
                        "segment records are not in canonical order"
                    )
                if primary == previous_primary:
                    if previous_record is None:
                        raise AssertionError("previous mapped record is absent")
                    comparison = _compare_record_payloads(previous_record, record)
                    if comparison == 0:
                        raise SegmentStoreError("segment repeats an exact object")
                    if comparison > 0:
                        raise SegmentStoreError(
                            "segment records are not in canonical order"
                        )
            records.append(record)
            previous_primary = primary
            previous_record = record
        if offset != segment.byte_length:
            raise SegmentStoreError("segment has trailing noncanonical bytes")
        return records

    @staticmethod
    def _segment_entry(
        segment_sha256: str, byte_length: int, record_count: int
    ) -> dict[str, Any]:
        return {
            "byte_length": byte_length,
            "format": SEGMENT_FORMAT,
            "record_count": record_count,
            "segment_file": f"{segment_sha256}.seg",
            "segment_sha256": segment_sha256,
        }

    @staticmethod
    def _self_hashed_payload(
        payload: dict[str, Any], hash_field: str
    ) -> tuple[dict[str, Any], str]:
        digest = _sha256_hex(canonical_json_bytes(payload))
        complete = dict(payload)
        complete[hash_field] = digest
        return complete, digest

    @staticmethod
    def _verify_self_hash(
        payload: dict[str, Any], hash_field: str, label: str
    ) -> str:
        supplied = _require_sha256(payload[hash_field], f"{label} hash")
        unhashed = dict(payload)
        unhashed.pop(hash_field)
        if _sha256_hex(canonical_json_bytes(unhashed)) != supplied:
            raise SegmentStoreError(f"{label} content hash mismatch")
        return supplied

    def _read_manifest_file(self, digest: str) -> dict[str, Any]:
        path = self.manifests_directory / f"{digest}.json"
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise SegmentStoreError("referenced manifest is missing") from exc
        payload = _decode_canonical_json(raw, "segment manifest")
        _require_keys(
            payload,
            {
                "format",
                "generation",
                "manifest_sha256",
                "object_count",
                "object_digest_algorithm",
                "previous_manifest_sha256",
                "segment_encoding",
                "segments",
            },
            "segment manifest",
        )
        supplied = self._verify_self_hash(payload, "manifest_sha256", "manifest")
        if supplied != digest:
            raise SegmentStoreError("manifest filename digest mismatch")
        if payload["format"] != MANIFEST_FORMAT:
            raise SegmentStoreError("unsupported segment manifest format")
        if payload["object_digest_algorithm"] != self.digest_name:
            raise SegmentStoreError("manifest object digest algorithm mismatch")
        if payload["segment_encoding"] != SEGMENT_ENCODING:
            raise SegmentStoreError("manifest segment encoding mismatch")
        _require_int(
            payload["generation"],
            "manifest generation",
            minimum=1,
            maximum=_UINT64_MAX,
        )
        _require_int(
            payload["object_count"],
            "manifest object count",
            maximum=_UINT64_MAX,
        )
        previous = payload["previous_manifest_sha256"]
        if previous is not None:
            _require_sha256(previous, "previous manifest hash")
        if not isinstance(payload["segments"], list) or not payload["segments"]:
            raise SegmentStoreError("manifest segment list must be nonempty")
        return payload

    def _validate_manifest_chain(self, current: dict[str, Any]) -> None:
        manifest = current
        while True:
            generation = manifest["generation"]
            previous_digest = manifest["previous_manifest_sha256"]
            if generation == 1:
                if previous_digest is not None:
                    raise SegmentStoreError("first manifest cannot name a predecessor")
                if len(manifest["segments"]) != 1:
                    raise SegmentStoreError("first manifest must publish one segment")
                first_entry = self._validate_segment_entry(manifest["segments"][0])
                if manifest["object_count"] != first_entry["record_count"]:
                    raise SegmentStoreError("first manifest object count mismatch")
                return
            if previous_digest is None:
                raise SegmentStoreError("manifest lineage is prematurely truncated")
            previous = self._read_manifest_file(previous_digest)
            if previous["generation"] != generation - 1:
                raise SegmentStoreError("manifest generations are not contiguous")
            if manifest["segments"][:-1] != previous["segments"]:
                raise SegmentStoreError("manifest does not append exactly one segment")
            if manifest["object_count"] <= previous["object_count"]:
                raise SegmentStoreError("manifest object count did not increase")
            appended = self._validate_segment_entry(manifest["segments"][-1])
            if (
                manifest["object_count"]
                != previous["object_count"] + appended["record_count"]
            ):
                raise SegmentStoreError("manifest append object count mismatch")
            manifest = previous

    def _validate_segment_entry(self, raw_entry: Any) -> dict[str, Any]:
        entry = _require_keys(
            raw_entry,
            {
                "byte_length",
                "format",
                "record_count",
                "segment_file",
                "segment_sha256",
            },
            "segment entry",
        )
        if entry["format"] != SEGMENT_FORMAT:
            raise SegmentStoreError("unsupported segment entry format")
        byte_length = _require_int(
            entry["byte_length"],
            "segment byte length",
            minimum=1,
            maximum=_UINT64_MAX,
        )
        record_count = _require_int(
            entry["record_count"],
            "segment record count",
            minimum=1,
            maximum=_UINT64_MAX,
        )
        digest = _require_sha256(entry["segment_sha256"], "segment hash")
        if entry["segment_file"] != f"{digest}.seg":
            raise SegmentStoreError("segment filename is not derived from its hash")
        # Keep these reads here so bools and arbitrary-precision malformed
        # values cannot slip through manifest validation.
        if byte_length < _SEGMENT_HEADER.size + _RECORD_HEADER.size:
            raise SegmentStoreError("declared segment byte length is too small")
        if record_count > byte_length:
            raise SegmentStoreError("declared segment record count is impossible")
        return entry

    def _load_current(self) -> None:
        try:
            pointer_raw = self.pointer_path.read_bytes()
        except FileNotFoundError as exc:
            raise SegmentStoreError("published CURRENT pointer disappeared") from exc
        pointer = _decode_canonical_json(pointer_raw, "CURRENT pointer")
        _require_keys(
            pointer,
            {
                "format",
                "generation",
                "manifest_file",
                "manifest_sha256",
                "pointer_sha256",
            },
            "CURRENT pointer",
        )
        self._verify_self_hash(pointer, "pointer_sha256", "CURRENT pointer")
        if pointer["format"] != POINTER_FORMAT:
            raise SegmentStoreError("unsupported CURRENT pointer format")
        generation = _require_int(
            pointer["generation"],
            "CURRENT generation",
            minimum=1,
            maximum=_UINT64_MAX,
        )
        manifest_digest = _require_sha256(
            pointer["manifest_sha256"], "CURRENT manifest hash"
        )
        if pointer["manifest_file"] != f"{manifest_digest}.json":
            raise SegmentStoreError("CURRENT manifest filename is not canonical")

        manifest = self._read_manifest_file(manifest_digest)
        if manifest["generation"] != generation:
            raise SegmentStoreError("CURRENT and manifest generations disagree")
        self._validate_manifest_chain(manifest)

        records: dict[ObjectRef, list[_ObjectRecord]] = {}
        exact_object_count = 0
        segment_hashes: list[str] = []
        mapped_segments: list[_MappedSegment] = []
        entries = [
            self._validate_segment_entry(entry) for entry in manifest["segments"]
        ]
        try:
            for entry in entries:
                digest = entry["segment_sha256"]
                if digest in segment_hashes:
                    raise SegmentStoreError("manifest repeats an immutable segment")
                segment_hashes.append(digest)
                path = self.segments_directory / entry["segment_file"]
                if self.lazy_payloads:
                    try:
                        mapped = _MappedSegment(
                            path, expected_sha256=digest
                        )
                    except FileNotFoundError as exc:
                        raise SegmentStoreError(
                            "referenced immutable segment is missing"
                        ) from exc
                    except (OSError, ValueError) as exc:
                        raise SegmentStoreError(
                            "referenced immutable segment cannot be mapped"
                        ) from exc
                    mapped_segments.append(mapped)
                    if mapped.byte_length != entry["byte_length"]:
                        raise SegmentStoreError(
                            "segment byte length disagrees with manifest"
                        )
                    parsed: list[_ObjectRecord] = self._parse_mapped_segment(
                        mapped,
                        expected_sha256=digest,
                        expected_record_count=entry["record_count"],
                    )
                else:
                    try:
                        raw = path.read_bytes()
                    except FileNotFoundError as exc:
                        raise SegmentStoreError(
                            "referenced immutable segment is missing"
                        ) from exc
                    if len(raw) != entry["byte_length"]:
                        raise SegmentStoreError(
                            "segment byte length disagrees with manifest"
                        )
                    parsed = self._parse_segment(
                        raw,
                        expected_sha256=digest,
                        expected_record_count=entry["record_count"],
                    )
                for record in parsed:
                    bucket = records.setdefault(record.ref, [])
                    if any(_records_equal(existing, record) for existing in bucket):
                        raise SegmentStoreError("manifest repeats an exact object")
                    bucket.append(record)
                    exact_object_count += 1
        except BaseException:
            try:
                self._close_mappings(mapped_segments)
            except BaseException:
                pass
            raise

        if exact_object_count != manifest["object_count"]:
            self._close_mappings(mapped_segments)
            raise SegmentStoreError("manifest object count fails exact recount")
        previous_mappings = self._mapped_segments
        self._records = records
        self._mapped_segments = mapped_segments
        self._manifest = manifest
        self.snapshot = SegmentStoreSnapshot(
            generation=generation,
            manifest_sha256=manifest_digest,
            segment_sha256s=tuple(segment_hashes),
            object_count=exact_object_count,
        )
        self._close_mappings(previous_mappings)

    def publish(self) -> SegmentStoreSnapshot:
        """Seal staged records and atomically publish a new verified snapshot."""

        self._ensure_open()
        if not self._staged:
            if self.snapshot is None:
                raise ValueError("cannot publish an empty segment store")
            return self.snapshot
        records: list[_MemoryObjectRecord] = [
            record for bucket in self._staged.values() for record in bucket
        ]
        segment_raw = self._serialize_segment(records)
        segment_sha256 = _sha256_hex(segment_raw)
        segment_path = self.segments_directory / f"{segment_sha256}.seg"
        _publish_immutable(segment_path, segment_raw)

        previous_segments = [] if self._manifest is None else self._manifest["segments"]
        previous_count = 0 if self._manifest is None else self._manifest["object_count"]
        previous_hash = (
            None if self.snapshot is None else self.snapshot.manifest_sha256
        )
        generation = 1 if self.snapshot is None else self.snapshot.generation + 1
        if generation > _UINT64_MAX or previous_count > _UINT64_MAX - len(records):
            raise OverflowError("segment manifest uint64 counter exhausted")
        segment_entry = self._segment_entry(
            segment_sha256,
            len(segment_raw),
            len(records),
        )
        manifest_without_hash = {
            "format": MANIFEST_FORMAT,
            "generation": generation,
            "object_count": previous_count + len(records),
            "object_digest_algorithm": self.digest_name,
            "previous_manifest_sha256": previous_hash,
            "segment_encoding": dict(SEGMENT_ENCODING),
            "segments": [*previous_segments, segment_entry],
        }
        manifest, manifest_sha256 = self._self_hashed_payload(
            manifest_without_hash, "manifest_sha256"
        )
        manifest_raw = canonical_json_bytes(manifest) + b"\n"
        manifest_path = self.manifests_directory / f"{manifest_sha256}.json"
        _publish_immutable(manifest_path, manifest_raw)

        pointer_without_hash = {
            "format": POINTER_FORMAT,
            "generation": generation,
            "manifest_file": manifest_path.name,
            "manifest_sha256": manifest_sha256,
        }
        pointer, _pointer_sha256 = self._self_hashed_payload(
            pointer_without_hash, "pointer_sha256"
        )
        _atomic_replace_bytes(
            self.pointer_path,
            canonical_json_bytes(pointer) + b"\n",
        )
        _fsync_directory(self.root)

        # Re-open all reachable bytes through the same strict restart path.
        # Once the new snapshot has been adopted, a later failure while
        # releasing superseded mappings must not leave the committed records
        # staged for a duplicate retry.
        try:
            self._load_current()
        finally:
            if (
                self.snapshot is not None
                and self.snapshot.manifest_sha256 == manifest_sha256
            ):
                self._staged.clear()
        if self.snapshot is None:
            raise AssertionError("published snapshot was not loaded")
        return self.snapshot


SegmentStore = ImmutableSegmentStore

__all__ = [
    "DigestCollisionError",
    "ImmutableSegmentStore",
    "MANIFEST_FORMAT",
    "ObjectRef",
    "POINTER_FORMAT",
    "SEGMENT_FORMAT",
    "SEGMENT_ENCODING",
    "SegmentStore",
    "SegmentStoreError",
    "SegmentStoreSnapshot",
]
