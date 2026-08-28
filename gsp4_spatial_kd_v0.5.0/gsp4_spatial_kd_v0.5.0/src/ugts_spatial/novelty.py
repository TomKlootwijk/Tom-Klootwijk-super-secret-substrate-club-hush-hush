from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
from pathlib import Path
import struct
from typing import Iterable, Iterator

from .schema import NoveltyOp

_HEADER = struct.Struct("<8sIIQQQ24s")  # 64 bytes
_RECORD = struct.Struct("<QdBBHQQffQQQI")  # 72 bytes
_MAGIC = b"UGNL3\0\0\0"
_VERSION = 3


@dataclass(frozen=True)
class NoveltyRecord:
    """One irreducible, hash-linked graph or event change.

    ``source`` and ``target`` are durable unsigned 64-bit node IDs rather than
    graph row indices. ``lineage_hash`` is a compact routing/validation value;
    the ordered record chain remains the durable history.
    """

    sequence: int
    timestamp: float
    op: int
    relation: int
    flags: int
    source: int
    target: int
    value: float
    confidence: float
    lineage_hash: int = 0
    prev_hash: int = 0
    self_hash: int = 0

    def validate(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be nonnegative")
        if not math.isfinite(self.timestamp):
            raise ValueError("timestamp must be finite")
        if not 0 <= int(self.op) <= 255:
            raise ValueError("op must fit uint8")
        if not 0 <= int(self.relation) <= 255:
            raise ValueError("relation must fit uint8")
        if not 0 <= int(self.flags) <= 0xFFFF:
            raise ValueError("flags must fit uint16")
        for name, value in (
            ("source", self.source),
            ("target", self.target),
            ("lineage_hash", self.lineage_hash),
            ("prev_hash", self.prev_hash),
            ("self_hash", self.self_hash),
        ):
            if not 0 <= int(value) <= 0xFFFFFFFFFFFFFFFF:
                raise ValueError(f"{name} must fit uint64")
        if not math.isfinite(self.value):
            raise ValueError("value must be finite")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be in [0,1]")

    def _packed(self, *, self_hash: int | None = None) -> bytes:
        return _RECORD.pack(
            int(self.sequence),
            float(self.timestamp),
            int(self.op),
            int(self.relation),
            int(self.flags),
            int(self.source),
            int(self.target),
            float(self.value),
            float(self.confidence),
            int(self.lineage_hash),
            int(self.prev_hash),
            int(self.self_hash if self_hash is None else self_hash),
            0,
        )

    def computed_hash(self, seed: int) -> int:
        key = int(seed).to_bytes(8, "little", signed=False)
        digest = hashlib.blake2b(
            self._packed(self_hash=0), digest_size=8, key=key
        ).digest()
        return int.from_bytes(digest, "little", signed=False)


class NoveltyLog:
    """Append-only, hash-linked exogenous novelty/event log (``.ugnl``)."""

    def __init__(self, path: str | Path, *, seed: int = 0x55475453474E3131):
        self.path = Path(path)
        self.seed = int(seed) & 0xFFFFFFFFFFFFFFFF

    @staticmethod
    def record_size() -> int:
        return _RECORD.size

    def create(self, *, overwrite: bool = False) -> None:
        if self.path.exists() and not overwrite:
            raise FileExistsError(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = _HEADER.pack(
            _MAGIC, _VERSION, _RECORD.size, 0, self.seed, 0, b"\0" * 24
        )
        with open(self.path, "wb") as fh:
            fh.write(header)

    def _read_header(self) -> tuple[int, int, int]:
        with open(self.path, "rb") as fh:
            payload = fh.read(_HEADER.size)
        if len(payload) != _HEADER.size:
            raise ValueError("truncated UGNL3 header")
        magic, version, record_size, count, seed, terminal_hash, _ = _HEADER.unpack(payload)
        if magic != _MAGIC or version != _VERSION or record_size != _RECORD.size:
            raise ValueError("unsupported UGNL novelty format")
        self.seed = int(seed)
        return int(count), int(seed), int(terminal_hash)

    def next_sequence(self) -> int:
        if not self.path.exists():
            return 0
        return self._read_header()[0]

    def append(self, record: NoveltyRecord) -> NoveltyRecord:
        if not self.path.exists():
            self.create()
        record.validate()
        count, seed, terminal_hash = self._read_header()
        if record.sequence != count:
            raise ValueError(
                f"record sequence {record.sequence} does not match next sequence {count}"
            )
        if record.prev_hash not in (0, terminal_hash):
            raise ValueError("record prev_hash does not match terminal hash")
        linked = replace(record, prev_hash=terminal_hash)
        linked = replace(linked, self_hash=linked.computed_hash(seed))
        with open(self.path, "r+b") as fh:
            fh.seek(0, 2)
            fh.write(linked._packed())
            fh.seek(0)
            fh.write(
                _HEADER.pack(
                    _MAGIC,
                    _VERSION,
                    _RECORD.size,
                    count + 1,
                    seed,
                    linked.self_hash,
                    b"\0" * 24,
                )
            )
            fh.flush()
        return linked

    def append_verified(
        self,
        *,
        timestamp: float,
        relation: int,
        source_id: int,
        target_id: int,
        value: float,
        confidence: float,
        lineage_hash: int,
        flags: int = 0,
    ) -> NoveltyRecord:
        return self.append(
            NoveltyRecord(
                sequence=self.next_sequence(),
                timestamp=float(timestamp),
                op=int(NoveltyOp.VERIFIED_EVENT),
                relation=int(relation),
                flags=int(flags),
                source=int(source_id),
                target=int(target_id),
                value=float(value),
                confidence=float(confidence),
                lineage_hash=int(lineage_hash),
            )
        )

    def append_many(self, records: Iterable[NoveltyRecord]) -> list[NoveltyRecord]:
        return [self.append(record) for record in records]

    def __iter__(self) -> Iterator[NoveltyRecord]:
        count, _, _ = self._read_header()
        with open(self.path, "rb") as fh:
            fh.seek(_HEADER.size)
            for _ in range(count):
                payload = fh.read(_RECORD.size)
                if len(payload) != _RECORD.size:
                    raise ValueError("truncated novelty record")
                values = _RECORD.unpack(payload)
                yield NoveltyRecord(
                    sequence=values[0],
                    timestamp=values[1],
                    op=values[2],
                    relation=values[3],
                    flags=values[4],
                    source=values[5],
                    target=values[6],
                    value=values[7],
                    confidence=values[8],
                    lineage_hash=values[9],
                    prev_hash=values[10],
                    self_hash=values[11],
                )

    def validate(self) -> dict[str, int | bool | str]:
        count, seed, terminal_hash = self._read_header()
        previous = 0
        seen = 0
        for record in self:
            record.validate()
            if record.sequence != seen:
                raise ValueError("novelty sequence is not contiguous")
            if record.prev_hash != previous:
                raise ValueError("novelty hash chain is broken")
            if record.computed_hash(seed) != record.self_hash:
                raise ValueError("novelty record hash mismatch")
            previous = record.self_hash
            seen += 1
        if seen != count or previous != terminal_hash:
            raise ValueError("novelty header totals do not match records")
        expected_size = _HEADER.size + count * _RECORD.size
        actual_size = self.path.stat().st_size
        if expected_size != actual_size:
            raise ValueError("novelty file size does not match header")
        return {
            "format": "UGNL3",
            "valid": True,
            "records": count,
            "terminal_hash": terminal_hash,
            "bytes": actual_size,
            "record_bytes": _RECORD.size,
        }
