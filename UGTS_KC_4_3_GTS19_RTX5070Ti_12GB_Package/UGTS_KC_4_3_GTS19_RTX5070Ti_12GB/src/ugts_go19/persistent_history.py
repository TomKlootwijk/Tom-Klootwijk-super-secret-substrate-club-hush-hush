"""Immutable host-RAM positional-superko history for bounded validation.

This is a deliberately small, non-production vertical slice.  It stores exact
one-byte-per-point Go boards in a persistent 256-way radix trie over a 256-bit
index digest.  Digests select a collision bucket; raw board bytes decide
membership.  Its compact multi-root forest is still a bounded host-RAM JSON
artifact; this module does not implement NVMe segments or a WAL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, Iterable, TypeAlias

from .digests import canonical_json_bytes, sha256_hex


SERIALIZATION_FORMAT = "UGTS-PY-PERSISTENT-PSK-v1"
FOREST_SERIALIZATION_FORMAT = "UGTS-PY-PERSISTENT-PSK-FOREST-v1"
BOARD_RECORD_FORMAT = "UGTS-PY-PSK-BOARD-v1"
BRANCH_RECORD_FORMAT = "UGTS-PY-PSK-BRANCH-v1"
LEAF_RECORD_FORMAT = "UGTS-PY-PSK-LEAF-v1"
ROOT_RECORD_FORMAT = "UGTS-PY-PSK-ROOT-v1"
_DIGEST_BYTES = 32
_LEAF_DEPTH = _DIGEST_BYTES
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")

DigestFunction = Callable[[bytes], bytes | str]


@dataclass(frozen=True, slots=True)
class _BoardObject:
    raw: bytes
    index_digest: str = field(compare=False)
    content_sha256: str = field(compare=False)


@dataclass(frozen=True, slots=True)
class _Branch:
    depth: int
    children: tuple[tuple[int, "_TrieNode"], ...]
    count: int
    content_sha256: str = field(compare=False)


@dataclass(frozen=True, slots=True)
class _Leaf:
    depth: int
    index_digest: str
    boards: tuple[_BoardObject, ...]
    count: int
    content_sha256: str = field(compare=False)


_TrieNode: TypeAlias = _Branch | _Leaf


@dataclass(frozen=True, slots=True)
class HistoryRoot:
    """Immutable value handle for one version of a persistent history."""

    board_size: int
    digest_name: str
    _node: _TrieNode | None = field(repr=False)
    _owner: object = field(repr=False, compare=False)

    @property
    def count(self) -> int:
        return 0 if self._node is None else self._node.count

    @property
    def root_sha256(self) -> str:
        return _root_content_sha256(
            self.board_size,
            self.digest_name,
            self._node,
        )


def _require_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} has a noncanonical shape")
    return value


def _require_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase 256-bit hexadecimal text")
    return value


def _board_content_payload(board_size: int, raw: bytes) -> dict[str, Any]:
    return {
        "board_size": board_size,
        "format": BOARD_RECORD_FORMAT,
        "raw_hex": raw.hex(),
    }


def _board_content_sha256(board_size: int, raw: bytes) -> str:
    return sha256_hex(canonical_json_bytes(_board_content_payload(board_size, raw)))


def _leaf_content_payload(
    index_digest: str, boards: tuple[_BoardObject, ...]
) -> dict[str, Any]:
    return {
        "boards": [
            {
                "content_sha256": board.content_sha256,
                "raw_hex": board.raw.hex(),
            }
            for board in boards
        ],
        "count": len(boards),
        "depth": _LEAF_DEPTH,
        "format": LEAF_RECORD_FORMAT,
        "index_digest": index_digest,
    }


def _branch_content_payload(
    depth: int, children: tuple[tuple[int, _TrieNode], ...]
) -> dict[str, Any]:
    return {
        "children": [
            {"child_sha256": child.content_sha256, "slot": slot}
            for slot, child in children
        ],
        "count": sum(child.count for _slot, child in children),
        "depth": depth,
        "format": BRANCH_RECORD_FORMAT,
    }


def _make_leaf(index_digest: str, boards: Iterable[_BoardObject]) -> _Leaf:
    ordered = tuple(sorted(boards, key=lambda board: board.raw))
    if not ordered:
        raise ValueError("collision leaf cannot be empty")
    if len({board.raw for board in ordered}) != len(ordered):
        raise ValueError("collision leaf contains duplicate exact boards")
    if any(board.index_digest != index_digest for board in ordered):
        raise ValueError("collision leaf mixes index digests")
    payload = _leaf_content_payload(index_digest, ordered)
    return _Leaf(
        depth=_LEAF_DEPTH,
        index_digest=index_digest,
        boards=ordered,
        count=len(ordered),
        content_sha256=sha256_hex(canonical_json_bytes(payload)),
    )


def _make_branch(depth: int, children: Iterable[tuple[int, _TrieNode]]) -> _Branch:
    ordered = tuple(sorted(children, key=lambda item: item[0]))
    if not 0 <= depth < _LEAF_DEPTH:
        raise ValueError("branch depth is outside the digest path")
    if not ordered:
        raise ValueError("branch cannot be empty")
    slots = [slot for slot, _child in ordered]
    if len(set(slots)) != len(slots) or any(not 0 <= slot <= 255 for slot in slots):
        raise ValueError("branch slots must be unique bytes")
    if any(child.depth != depth + 1 for _slot, child in ordered):
        raise ValueError("branch child depth mismatch")
    payload = _branch_content_payload(depth, ordered)
    return _Branch(
        depth=depth,
        children=ordered,
        count=sum(child.count for _slot, child in ordered),
        content_sha256=sha256_hex(canonical_json_bytes(payload)),
    )


def _root_content_sha256(
    board_size: int, digest_name: str, node: _TrieNode | None
) -> str:
    payload = {
        "board_size": board_size,
        "count": 0 if node is None else node.count,
        "digest_name": digest_name,
        "format": ROOT_RECORD_FORMAT,
        "node_sha256": None if node is None else node.content_sha256,
    }
    return sha256_hex(canonical_json_bytes(payload))


def _decode_json(raw: bytes) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ValueError("history artifact is not valid canonical JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("history artifact must be a JSON object")
    try:
        canonical = canonical_json_bytes(payload) + b"\n"
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ValueError("history artifact is not valid canonical JSON") from exc
    if canonical != raw:
        raise ValueError("history artifact is not in canonical form")
    return payload


def _atomic_save_bytes(path: str | Path, serialized: bytes) -> None:
    """Atomically publish already-serialized bytes for one sequential writer."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.tmp-{os.getpid()}-",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            written = stream.write(serialized)
            if written != len(serialized):
                raise OSError("short history artifact write")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        if os.name == "posix":
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(destination.parent, flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class PersistentHistory:
    """Persistent exact PSK set for host-RAM validation.

    ``board_size`` is the Go side length, so every board is exactly
    ``board_size * board_size`` bytes and every point is EMPTY/BLACK/WHITE
    (0/1/2).  The fixed-depth radix trie is canonical for a digest function;
    insertion copies only the digest path and shares all untouched subtries.
    """

    def __init__(
        self,
        board_size: int,
        *,
        digest_fn: DigestFunction | None = None,
        digest_name: str | None = None,
    ) -> None:
        """Create a store; an injected digest callback must be deterministic."""

        if type(board_size) is not int:
            raise TypeError("board_size must be an integer")
        if not 1 <= board_size <= 19:
            raise ValueError("board_size must be in 1..19")
        if digest_fn is None:
            if digest_name not in (None, "sha256"):
                raise ValueError("a non-sha256 digest name requires digest_fn")
            self._raw_digest_fn: DigestFunction = (
                lambda raw: hashlib.sha256(raw).digest()
            )
            self.digest_name = "sha256"
        else:
            if not callable(digest_fn):
                raise TypeError("digest_fn must be callable")
            if digest_name is None:
                digest_name = "injected"
            if type(digest_name) is not str or not digest_name:
                raise ValueError("digest_name must be nonempty text")
            self._raw_digest_fn = digest_fn
            self.digest_name = digest_name
        self.board_size = board_size
        self.board_bytes = board_size * board_size
        self._owner = object()
        self._digest_index: dict[str, list[_BoardObject]] = {}
        self._exact_index: dict[bytes, _BoardObject] = {}
        # Single-writer insertion journal used only while a caller has an
        # active speculative graph-expansion transaction.
        self._intern_journal: list[_BoardObject] = []
        self._intern_transaction_token: object | None = None

    @property
    def empty_root(self) -> HistoryRoot:
        return HistoryRoot(self.board_size, self.digest_name, None, self._owner)

    @property
    def board_object_count(self) -> int:
        return sum(len(bucket) for bucket in self._digest_index.values())

    def digest_bucket_sizes(self) -> tuple[int, ...]:
        return tuple(sorted(len(bucket) for bucket in self._digest_index.values()))

    def _validate_board(self, board: bytes) -> None:
        if type(board) is not bytes:
            raise TypeError("board must be immutable bytes")
        if len(board) != self.board_bytes:
            raise ValueError(
                f"board has {len(board)} points, expected {self.board_bytes}"
            )
        if any(point not in (0, 1, 2) for point in board):
            raise ValueError("board contains an invalid point value")

    def _digest(self, board: bytes) -> str:
        value = self._raw_digest_fn(board)
        if type(value) is bytes:
            if len(value) != _DIGEST_BYTES:
                raise ValueError("digest_fn must return exactly 32 bytes")
            digest = value.hex()
        elif type(value) is str:
            digest = value.lower()
        else:
            raise TypeError("digest_fn must return bytes or hexadecimal text")
        if _HEX64.fullmatch(digest) is None:
            raise ValueError("digest_fn must return a 256-bit hexadecimal digest")
        return digest

    def _intern_board(self, raw: bytes) -> _BoardObject:
        self._validate_board(raw)
        existing = self._exact_index.get(raw)
        if existing is not None:
            return existing
        digest = self._digest(raw)
        bucket = self._digest_index.get(digest)
        if bucket is not None:
            for board in bucket:
                if board.raw == raw:
                    return board
        board = _BoardObject(
            raw=raw,
            index_digest=digest,
            content_sha256=_board_content_sha256(self.board_size, raw),
        )
        new_bucket = bucket is None
        if new_bucket:
            # Construct the immutable object before publishing an empty bucket:
            # an allocation failure must not strand cache metadata.
            bucket = []
        insert_at = len(bucket)
        for index, candidate in enumerate(bucket):
            if raw < candidate.raw:
                insert_at = index
                break
        try:
            if new_bucket:
                self._digest_index[digest] = bucket
            # Insert directly at the canonical position.  Sorting the complete
            # collision bucket can allocate and may leave pre-existing entries
            # reordered if interrupted.
            bucket.insert(insert_at, board)
            self._exact_index[raw] = board
            if self._intern_transaction_token is not None:
                self._intern_journal.append(board)
        except BaseException:
            if self._intern_journal and self._intern_journal[-1] is board:
                self._intern_journal.pop()
            if self._exact_index.get(raw) is board:
                del self._exact_index[raw]
            for index, candidate in enumerate(bucket):
                if candidate is board:
                    del bucket[index]
                    break
            if not bucket and self._digest_index.get(digest) is bucket:
                del self._digest_index[digest]
            raise
        return board

    def _adopt_verified_board(self, board: _BoardObject) -> _BoardObject:
        """Intern a loader-verified record without re-calling an injected digest."""

        self._validate_board(board.raw)
        existing = self._exact_index.get(board.raw)
        if existing is not None:
            if (
                existing.index_digest != board.index_digest
                or existing.content_sha256 != board.content_sha256
            ):
                raise ValueError("exact board has conflicting verified metadata")
            return existing
        bucket = self._digest_index.get(board.index_digest)
        if bucket is not None:
            for candidate in bucket:
                if candidate.raw == board.raw:
                    raise ValueError("exact board index is internally inconsistent")
        new_bucket = bucket is None
        if new_bucket:
            bucket = []
        insert_at = len(bucket)
        for index, candidate in enumerate(bucket):
            if board.raw < candidate.raw:
                insert_at = index
                break
        try:
            if new_bucket:
                self._digest_index[board.index_digest] = bucket
            bucket.insert(insert_at, board)
            self._exact_index[board.raw] = board
            if self._intern_transaction_token is not None:
                self._intern_journal.append(board)
        except BaseException:
            if self._intern_journal and self._intern_journal[-1] is board:
                self._intern_journal.pop()
            if self._exact_index.get(board.raw) is board:
                del self._exact_index[board.raw]
            for index, candidate in enumerate(bucket):
                if candidate is board:
                    del bucket[index]
                    break
            if (
                not bucket
                and self._digest_index.get(board.index_digest) is bucket
            ):
                del self._digest_index[board.index_digest]
            raise
        return board

    def _begin_intern_transaction(self) -> object:
        """Begin one non-nested single-writer speculative cache transaction."""

        if self._intern_transaction_token is not None:
            raise RuntimeError("a history intern transaction is already active")
        if self._intern_journal:
            raise ValueError("history intern journal is internally inconsistent")
        token = object()
        self._intern_transaction_token = token
        return token

    def _commit_intern_transaction(self, token: object) -> None:
        """Keep transaction additions and release their temporary journal."""

        if token is not self._intern_transaction_token:
            raise ValueError("history intern transaction token is invalid")
        self._intern_journal.clear()
        self._intern_transaction_token = None

    def _rollback_intern_transaction(self, token: object) -> None:
        """Discard transaction cache objects in reverse insertion order.

        Callers must first discard every speculative root that could reference
        these objects. This is an internal single-writer transaction primitive,
        not a general concurrent cache API.
        """

        if token is not self._intern_transaction_token:
            raise ValueError("history intern transaction token is invalid")
        while self._intern_journal:
            board = self._intern_journal[-1]
            if self._exact_index.get(board.raw) is not board:
                raise ValueError("history intern journal is internally inconsistent")
            bucket = self._digest_index.get(board.index_digest)
            if bucket is None:
                raise ValueError("history digest bucket disappeared during rollback")
            bucket_index = None
            for index, candidate in enumerate(bucket):
                if candidate is board:
                    bucket_index = index
                    break
            if bucket_index is None:
                raise ValueError("history board disappeared from its digest bucket")
            del self._exact_index[board.raw]
            del bucket[bucket_index]
            if not bucket:
                del self._digest_index[board.index_digest]
            self._intern_journal.pop()
        self._intern_transaction_token = None

    def _require_root(self, root: HistoryRoot) -> None:
        if not isinstance(root, HistoryRoot):
            raise TypeError("root must be a HistoryRoot")
        if root._owner is not self._owner:
            raise ValueError("history root belongs to a different store")
        if root.board_size != self.board_size or root.digest_name != self.digest_name:
            raise ValueError("history root envelope mismatch")

    def _build_chain(
        self, depth: int, digest_bytes: bytes, board: _BoardObject
    ) -> _TrieNode:
        node: _TrieNode = _make_leaf(board.index_digest, (board,))
        for branch_depth in range(_LEAF_DEPTH - 1, depth - 1, -1):
            node = _make_branch(branch_depth, ((digest_bytes[branch_depth], node),))
        return node

    def _insert_node(
        self,
        node: _TrieNode | None,
        depth: int,
        digest_bytes: bytes,
        board: _BoardObject,
    ) -> _TrieNode:
        if node is None:
            return self._build_chain(depth, digest_bytes, board)
        if depth == _LEAF_DEPTH:
            if not isinstance(node, _Leaf) or node.index_digest != board.index_digest:
                raise ValueError("corrupt collision leaf")
            if any(existing.raw == board.raw for existing in node.boards):
                return node
            return _make_leaf(node.index_digest, (*node.boards, board))
        if not isinstance(node, _Branch) or node.depth != depth:
            raise ValueError("corrupt radix branch")
        slot = digest_bytes[depth]
        replacement: _TrieNode | None = None
        found = False
        children: list[tuple[int, _TrieNode]] = []
        for existing_slot, child in node.children:
            if existing_slot == slot:
                found = True
                replacement = self._insert_node(
                    child, depth + 1, digest_bytes, board
                )
                children.append((existing_slot, replacement))
            else:
                children.append((existing_slot, child))
        if not found:
            replacement = self._build_chain(depth + 1, digest_bytes, board)
            children.append((slot, replacement))
        elif replacement is next(
            child for existing_slot, child in node.children if existing_slot == slot
        ):
            return node
        return _make_branch(depth, children)

    def insert(self, root: HistoryRoot, board: bytes) -> HistoryRoot:
        """Return a new version containing ``board``; never mutate ``root``."""

        self._require_root(root)
        board_object = self._intern_board(board)
        return self._insert_board_object(root, board_object)

    def _insert_board_object(
        self, root: HistoryRoot, board_object: _BoardObject
    ) -> HistoryRoot:
        """Insert a board object whose exact bytes and digest were verified."""

        self._require_root(root)
        digest_bytes = bytes.fromhex(board_object.index_digest)
        new_node = self._insert_node(root._node, 0, digest_bytes, board_object)
        if new_node is root._node:
            return root
        return HistoryRoot(
            self.board_size,
            self.digest_name,
            new_node,
            self._owner,
        )

    def contains(self, root: HistoryRoot, board: bytes) -> bool:
        """Test membership by digest path followed by exact raw-byte equality."""

        self._require_root(root)
        self._validate_board(board)
        known = self._exact_index.get(board)
        digest = known.index_digest if known is not None else self._digest(board)
        digest_bytes = bytes.fromhex(digest)
        node = root._node
        depth = 0
        while node is not None and depth < _LEAF_DEPTH:
            if not isinstance(node, _Branch) or node.depth != depth:
                raise ValueError("corrupt radix branch")
            slot = digest_bytes[depth]
            node = next(
                (child for child_slot, child in node.children if child_slot == slot),
                None,
            )
            depth += 1
        if node is None:
            return False
        if not isinstance(node, _Leaf) or node.index_digest != digest:
            raise ValueError("corrupt collision leaf")
        return any(candidate.raw == board for candidate in node.boards)

    def members(self, root: HistoryRoot) -> tuple[bytes, ...]:
        """Return exact members in canonical byte order."""

        self._require_root(root)
        boards: list[bytes] = []
        stack: list[_TrieNode] = [] if root._node is None else [root._node]
        while stack:
            node = stack.pop()
            if isinstance(node, _Leaf):
                boards.extend(board.raw for board in node.boards)
            else:
                stack.extend(child for _slot, child in reversed(node.children))
        return tuple(sorted(boards))

    def roots_equal(self, first: HistoryRoot, second: HistoryRoot) -> bool:
        """Compare exact immutable tries, never only their Merkle roots.

        The digest and Merkle fields are safe negative filters: equal exact
        values necessarily produce equal metadata.  Equal metadata is never
        sufficient, however, so the final comparison walks branch slots and
        exact leaf board bytes.  This retains collision independence without
        materializing or sorting the complete member set.
        """

        self._require_root(first)
        self._require_root(second)
        if first._node is second._node:
            return True
        if first.count != second.count or first.root_sha256 != second.root_sha256:
            return False
        if first._node is None or second._node is None:
            return first._node is second._node

        stack: list[tuple[_TrieNode, _TrieNode]] = [
            (first._node, second._node)
        ]
        while stack:
            first_node, second_node = stack.pop()
            if first_node is second_node:
                continue
            if type(first_node) is not type(second_node):
                return False
            if isinstance(first_node, _Leaf):
                if not isinstance(second_node, _Leaf):
                    return False
                if (
                    first_node.depth != second_node.depth
                    or first_node.index_digest != second_node.index_digest
                    or first_node.count != second_node.count
                    or len(first_node.boards) != len(second_node.boards)
                ):
                    return False
                if any(
                    first_board.raw != second_board.raw
                    for first_board, second_board in zip(
                        first_node.boards,
                        second_node.boards,
                        strict=True,
                    )
                ):
                    return False
                continue
            if not isinstance(second_node, _Branch):
                return False
            if (
                first_node.depth != second_node.depth
                or first_node.count != second_node.count
                or len(first_node.children) != len(second_node.children)
            ):
                return False
            for (first_slot, first_child), (second_slot, second_child) in zip(
                first_node.children,
                second_node.children,
                strict=True,
            ):
                if first_slot != second_slot:
                    return False
                stack.append((first_child, second_child))
        return True

    def shared_node_count(self, first: HistoryRoot, second: HistoryRoot) -> int:
        """Count immutable trie node objects shared by two versions."""

        self._require_root(first)
        self._require_root(second)

        def identities(root: HistoryRoot) -> set[int]:
            result: set[int] = set()
            stack: list[_TrieNode] = [] if root._node is None else [root._node]
            while stack:
                node = stack.pop()
                if id(node) in result:
                    continue
                result.add(id(node))
                if isinstance(node, _Branch):
                    stack.extend(child for _slot, child in node.children)
            return result

        return len(identities(first) & identities(second))

    def _validate_root_content(
        self, root: HistoryRoot
    ) -> tuple[list[_TrieNode], list[_BoardObject]]:
        self._require_root(root)
        if root._node is None:
            if root.count != 0:
                raise ValueError("empty root has a nonzero member count")
            return [], []
        nodes: list[_TrieNode] = []
        boards: list[_BoardObject] = []
        node_identities: set[int] = set()
        exact_boards: set[bytes] = set()

        def visit(node: _TrieNode, depth: int, prefix: bytes) -> int:
            identity = id(node)
            if identity in node_identities:
                raise ValueError("history root contains a repeated node reference")
            node_identities.add(identity)
            nodes.append(node)
            if isinstance(node, _Leaf):
                if depth != _LEAF_DEPTH or node.depth != _LEAF_DEPTH:
                    raise ValueError("collision leaf appears before the full digest path")
                digest_bytes = bytes.fromhex(_require_sha256(
                    node.index_digest, "leaf index digest"
                ))
                if digest_bytes != prefix:
                    raise ValueError("leaf digest does not match its radix path")
                if not node.boards or tuple(
                    sorted(node.boards, key=lambda board: board.raw)
                ) != node.boards:
                    raise ValueError("collision bucket is empty or noncanonical")
                if len({board.raw for board in node.boards}) != len(node.boards):
                    raise ValueError("collision bucket contains duplicate exact boards")
                for board in node.boards:
                    self._validate_board(board.raw)
                    known = self._exact_index.get(board.raw)
                    if known is None or known.index_digest != node.index_digest:
                        raise ValueError("board index digest does not match its leaf")
                    if board.content_sha256 != _board_content_sha256(
                        self.board_size, board.raw
                    ):
                        raise ValueError("board content hash mismatch")
                    if board.raw in exact_boards:
                        raise ValueError("history contains a duplicate exact board")
                    exact_boards.add(board.raw)
                    boards.append(board)
                rebuilt = _make_leaf(node.index_digest, node.boards)
                if rebuilt.content_sha256 != node.content_sha256:
                    raise ValueError("leaf content hash mismatch")
                if node.count != len(node.boards):
                    raise ValueError("leaf member count mismatch")
                return node.count
            if node.depth != depth or not 0 <= depth < _LEAF_DEPTH:
                raise ValueError("branch depth mismatch")
            slots = [slot for slot, _child in node.children]
            if not slots or slots != sorted(set(slots)):
                raise ValueError("branch children are empty, duplicated, or unsorted")
            total = 0
            for slot, child in node.children:
                if not 0 <= slot <= 255:
                    raise ValueError("branch slot is outside one digest byte")
                total += visit(child, depth + 1, prefix + bytes((slot,)))
            rebuilt = _make_branch(depth, node.children)
            if rebuilt.content_sha256 != node.content_sha256:
                raise ValueError("branch content hash mismatch")
            if node.count != total:
                raise ValueError("branch member count mismatch")
            return total

        total = visit(root._node, 0, b"")
        if total != root.count:
            raise ValueError("root member count mismatch")
        return nodes, boards

    def _payload_without_hash(self, root: HistoryRoot) -> dict[str, Any]:
        nodes, boards = self._validate_root_content(root)
        boards = sorted(boards, key=lambda board: (board.index_digest, board.raw))
        board_ids = {board.raw: index for index, board in enumerate(boards)}
        node_ids = {id(node): index for index, node in enumerate(nodes)}
        node_records: list[dict[str, Any]] = []
        for node in nodes:
            if isinstance(node, _Leaf):
                record: dict[str, Any] = {
                    "boards": [
                        {
                            "board_id": board_ids[board.raw],
                            "content_sha256": board.content_sha256,
                            "raw_hex": board.raw.hex(),
                        }
                        for board in node.boards
                    ],
                    "content_sha256": node.content_sha256,
                    "count": node.count,
                    "depth": node.depth,
                    "id": node_ids[id(node)],
                    "index_digest": node.index_digest,
                    "kind": "leaf",
                }
            else:
                record = {
                    "children": [
                        {
                            "child_id": node_ids[id(child)],
                            "child_sha256": child.content_sha256,
                            "slot": slot,
                        }
                        for slot, child in node.children
                    ],
                    "content_sha256": node.content_sha256,
                    "count": node.count,
                    "depth": node.depth,
                    "id": node_ids[id(node)],
                    "kind": "branch",
                }
            node_records.append(record)
        root_ref = (
            None
            if root._node is None
            else {
                "content_sha256": root._node.content_sha256,
                "node_id": node_ids[id(root._node)],
            }
        )
        return {
            "board_bytes": self.board_bytes,
            "board_record_count": len(boards),
            "board_size": self.board_size,
            "boards": [
                {
                    "content_sha256": board.content_sha256,
                    "id": board_ids[board.raw],
                    "index_digest": board.index_digest,
                    "raw_hex": board.raw.hex(),
                }
                for board in boards
            ],
            "digest_index": {
                "collision_checked": True,
                "name": self.digest_name,
            },
            "format": SERIALIZATION_FORMAT,
            "member_count": root.count,
            "node_record_count": len(nodes),
            "nodes": node_records,
            "root_ref": root_ref,
            "root_sha256": root.root_sha256,
        }

    def serialize_root(self, root: HistoryRoot) -> bytes:
        """Return a deterministic, canonical, self-hashed root artifact."""

        payload = self._payload_without_hash(root)
        payload["artifact_sha256"] = sha256_hex(canonical_json_bytes(payload))
        return canonical_json_bytes(payload) + b"\n"

    def save_root(self, path: str | Path, root: HistoryRoot) -> None:
        """Atomically publish one root artifact for a sequential writer."""

        _atomic_save_bytes(path, self.serialize_root(root))

    def _forest_payload_without_hash(
        self, roots: Iterable[HistoryRoot]
    ) -> dict[str, Any]:
        """Build one exact table shared by an ordered sequence of roots."""

        root_sequence = tuple(roots)
        nodes_by_identity: dict[int, _TrieNode] = {}
        boards_by_raw: dict[bytes, _BoardObject] = {}
        for root in root_sequence:
            nodes, boards = self._validate_root_content(root)
            for node in nodes:
                nodes_by_identity.setdefault(id(node), node)
            for board in boards:
                previous = boards_by_raw.get(board.raw)
                if previous is not None and (
                    previous.index_digest != board.index_digest
                    or previous.content_sha256 != board.content_sha256
                ):
                    raise ValueError("exact board has conflicting forest metadata")
                boards_by_raw.setdefault(board.raw, board)

        boards = sorted(
            boards_by_raw.values(),
            key=lambda board: (board.index_digest, board.raw),
        )
        board_ids = {board.raw: board_id for board_id, board in enumerate(boards)}

        # Canonical node ids are assigned bottom-up.  Exact board ids and
        # already-canonical child ids form the key, so neither allocation nor
        # root traversal order can affect the shared node table.  Hashes remain
        # verification metadata and are never used as the deduplication key.
        nodes_at_depth: dict[int, list[_TrieNode]] = {}
        for node in nodes_by_identity.values():
            nodes_at_depth.setdefault(node.depth, []).append(node)
        node_ids_by_identity: dict[int, int] = {}
        node_records: list[dict[str, Any]] = []
        for depth in range(_LEAF_DEPTH, -1, -1):
            semantic_groups: dict[tuple[Any, ...], list[_TrieNode]] = {}
            for node in nodes_at_depth.get(depth, []):
                if isinstance(node, _Leaf):
                    key: tuple[Any, ...] = (
                        "leaf",
                        node.index_digest,
                        tuple(board_ids[board.raw] for board in node.boards),
                    )
                else:
                    try:
                        child_refs = tuple(
                            (slot, node_ids_by_identity[id(child)])
                            for slot, child in node.children
                        )
                    except KeyError as exc:
                        raise ValueError(
                            "forest branch references an unvalidated child"
                        ) from exc
                    key = ("branch", child_refs)
                semantic_groups.setdefault(key, []).append(node)

            for key in sorted(semantic_groups):
                equivalent_nodes = semantic_groups[key]
                representative = equivalent_nodes[0]
                node_id = len(node_records)
                for node in equivalent_nodes:
                    node_ids_by_identity[id(node)] = node_id
                if isinstance(representative, _Leaf):
                    record: dict[str, Any] = {
                        "boards": [
                            {
                                "board_id": board_ids[board.raw],
                                "content_sha256": board.content_sha256,
                                "raw_hex": board.raw.hex(),
                            }
                            for board in representative.boards
                        ],
                        "content_sha256": representative.content_sha256,
                        "count": representative.count,
                        "depth": representative.depth,
                        "id": node_id,
                        "index_digest": representative.index_digest,
                        "kind": "leaf",
                    }
                else:
                    record = {
                        "children": [
                            {
                                "child_id": node_ids_by_identity[id(child)],
                                "child_sha256": child.content_sha256,
                                "slot": slot,
                            }
                            for slot, child in representative.children
                        ],
                        "content_sha256": representative.content_sha256,
                        "count": representative.count,
                        "depth": representative.depth,
                        "id": node_id,
                        "kind": "branch",
                    }
                node_records.append(record)

        root_records: list[dict[str, Any]] = []
        for root_id, root in enumerate(root_sequence):
            root_records.append(
                {
                    "id": root_id,
                    "member_count": root.count,
                    "node_ref": (
                        None
                        if root._node is None
                        else {
                            "content_sha256": root._node.content_sha256,
                            "node_id": node_ids_by_identity[id(root._node)],
                        }
                    ),
                    "root_sha256": root.root_sha256,
                }
            )

        return {
            "board_bytes": self.board_bytes,
            "board_record_count": len(boards),
            "board_size": self.board_size,
            "boards": [
                {
                    "content_sha256": board.content_sha256,
                    "id": board_ids[board.raw],
                    "index_digest": board.index_digest,
                    "raw_hex": board.raw.hex(),
                }
                for board in boards
            ],
            "digest_index": {
                "collision_checked": True,
                "name": self.digest_name,
            },
            "format": FOREST_SERIALIZATION_FORMAT,
            "node_record_count": len(node_records),
            "nodes": node_records,
            "root_count": len(root_records),
            "roots": root_records,
        }

    def serialize_forest(self, roots: Iterable[HistoryRoot]) -> bytes:
        """Serialize ordered roots with globally deduplicated immutable records.

        The shared board/node tables are independent of input traversal and
        allocation order.  The root-reference array intentionally preserves
        caller order so a surrounding state table can use the same indexes.
        """

        payload = self._forest_payload_without_hash(roots)
        payload["artifact_sha256"] = sha256_hex(canonical_json_bytes(payload))
        return canonical_json_bytes(payload) + b"\n"

    def save_forest(
        self,
        path: str | Path,
        roots: Iterable[HistoryRoot],
    ) -> None:
        """Atomically publish one compact forest for a sequential writer."""

        _atomic_save_bytes(path, self.serialize_forest(roots))

    @staticmethod
    def _verify_envelope(payload: dict[str, Any]) -> None:
        _require_keys(
            payload,
            {
                "artifact_sha256",
                "board_bytes",
                "board_record_count",
                "board_size",
                "boards",
                "digest_index",
                "format",
                "member_count",
                "node_record_count",
                "nodes",
                "root_ref",
                "root_sha256",
            },
            "history artifact",
        )
        provided = _require_sha256(payload["artifact_sha256"], "artifact hash")
        unhashed = dict(payload)
        unhashed.pop("artifact_sha256")
        if provided != sha256_hex(canonical_json_bytes(unhashed)):
            raise ValueError("history artifact content hash mismatch")
        if payload["format"] != SERIALIZATION_FORMAT:
            raise ValueError("unsupported history serialization format")

    @staticmethod
    def _verify_forest_envelope(payload: dict[str, Any]) -> str:
        _require_keys(
            payload,
            {
                "artifact_sha256",
                "board_bytes",
                "board_record_count",
                "board_size",
                "boards",
                "digest_index",
                "format",
                "node_record_count",
                "nodes",
                "root_count",
                "roots",
            },
            "history forest artifact",
        )
        provided = _require_sha256(payload["artifact_sha256"], "artifact hash")
        unhashed = dict(payload)
        unhashed.pop("artifact_sha256")
        if provided != sha256_hex(canonical_json_bytes(unhashed)):
            raise ValueError("history forest artifact content hash mismatch")
        if payload["format"] != FOREST_SERIALIZATION_FORMAT:
            raise ValueError("unsupported history forest serialization format")
        return provided

    def _rehydrate_payload(
        self,
        payload: dict[str, Any],
        *,
        expected_root_sha256: str | None,
    ) -> HistoryRoot:
        self._verify_envelope(payload)
        size = _require_int(payload["board_size"], "board_size", minimum=1)
        board_bytes = _require_int(payload["board_bytes"], "board_bytes", minimum=1)
        if size != self.board_size or board_bytes != self.board_bytes:
            raise ValueError("history artifact board size mismatch")
        digest_index = _require_keys(
            payload["digest_index"],
            {"collision_checked", "name"},
            "digest_index",
        )
        if digest_index["collision_checked"] is not True:
            raise ValueError("history artifact requires collision-checked indexing")
        if digest_index["name"] != self.digest_name:
            raise ValueError("history artifact digest function mismatch")
        declared_members = _require_int(
            payload["member_count"], "member_count", minimum=0
        )
        declared_board_count = _require_int(
            payload["board_record_count"], "board_record_count", minimum=0
        )
        declared_node_count = _require_int(
            payload["node_record_count"], "node_record_count", minimum=0
        )
        stored_root_sha = _require_sha256(payload["root_sha256"], "root hash")
        if expected_root_sha256 is not None:
            expected_root_sha256 = _require_sha256(
                expected_root_sha256, "expected root hash"
            )
            if stored_root_sha != expected_root_sha256:
                raise ValueError("history artifact does not match the expected root")

        raw_board_records = payload["boards"]
        if not isinstance(raw_board_records, list):
            raise ValueError("board records must be an array")
        if len(raw_board_records) != declared_board_count:
            raise ValueError("board record count mismatch")
        board_objects: list[_BoardObject] = []
        board_sort_keys: list[tuple[str, bytes]] = []
        exact_raws: set[bytes] = set()
        fixed_hashes: dict[str, bytes] = {}
        for expected_id, raw_record in enumerate(raw_board_records):
            record = _require_keys(
                raw_record,
                {"content_sha256", "id", "index_digest", "raw_hex"},
                "board record",
            )
            board_id = _require_int(record["id"], "board id", minimum=0)
            if board_id != expected_id:
                raise ValueError("board record ids must be contiguous and ordered")
            if type(record["raw_hex"]) is not str:
                raise ValueError("board raw_hex must be text")
            try:
                raw = bytes.fromhex(record["raw_hex"])
            except ValueError as exc:
                raise ValueError("board raw_hex is invalid") from exc
            if record["raw_hex"] != raw.hex():
                raise ValueError("board raw_hex must be canonical lowercase hex")
            self._validate_board(raw)
            if raw in exact_raws:
                raise ValueError("duplicate exact board records are not permitted")
            exact_raws.add(raw)
            index_digest = _require_sha256(
                record["index_digest"], "board index digest"
            )
            if index_digest != self._digest(raw):
                raise ValueError("board index digest mismatch")
            content_hash = _require_sha256(
                record["content_sha256"], "board content hash"
            )
            if content_hash != _board_content_sha256(self.board_size, raw):
                raise ValueError("board content hash mismatch")
            previous_raw = fixed_hashes.get(content_hash)
            if previous_raw is not None and previous_raw != raw:
                raise ValueError("conflicting board content-hash records")
            fixed_hashes[content_hash] = raw
            board_objects.append(_BoardObject(raw, index_digest, content_hash))
            board_sort_keys.append((index_digest, raw))
        if board_sort_keys != sorted(board_sort_keys):
            raise ValueError("board records are not in canonical order")

        raw_node_records = payload["nodes"]
        if not isinstance(raw_node_records, list):
            raise ValueError("node records must be an array")
        if len(raw_node_records) != declared_node_count:
            raise ValueError("node record count mismatch")
        record_by_id: list[dict[str, Any]] = []
        for expected_id, raw_record in enumerate(raw_node_records):
            if not isinstance(raw_record, dict):
                raise ValueError("node record must be an object")
            kind = raw_record.get("kind")
            keys = (
                {
                    "boards",
                    "content_sha256",
                    "count",
                    "depth",
                    "id",
                    "index_digest",
                    "kind",
                }
                if kind == "leaf"
                else {
                    "children",
                    "content_sha256",
                    "count",
                    "depth",
                    "id",
                    "kind",
                }
                if kind == "branch"
                else set()
            )
            if not keys:
                raise ValueError("node record has an unknown kind")
            record = _require_keys(raw_record, keys, "node record")
            node_id = _require_int(record["id"], "node id", minimum=0)
            if node_id != expected_id:
                raise ValueError("node record ids must be contiguous and ordered")
            _require_int(record["depth"], "node depth", minimum=0)
            _require_int(record["count"], "node count", minimum=1)
            _require_sha256(record["content_sha256"], "node content hash")
            record_by_id.append(record)

        nodes: dict[int, _TrieNode] = {}
        prefixes: dict[int, bytes] = {}
        edges: dict[int, tuple[int, ...]] = {}
        board_refs: dict[int, tuple[int, ...]] = {}
        node_hash_payloads: dict[str, bytes] = {}
        ordered_for_build = sorted(
            record_by_id,
            key=lambda record: (record["depth"], record["id"]),
            reverse=True,
        )
        for record in ordered_for_build:
            node_id = record["id"]
            depth = record["depth"]
            declared_count = record["count"]
            declared_hash = record["content_sha256"]
            if record["kind"] == "leaf":
                if depth != _LEAF_DEPTH:
                    raise ValueError("leaf must occur at the complete digest depth")
                index_digest = _require_sha256(
                    record["index_digest"], "leaf index digest"
                )
                raw_refs = record["boards"]
                if not isinstance(raw_refs, list) or not raw_refs:
                    raise ValueError("leaf board references must be nonempty")
                selected: list[_BoardObject] = []
                selected_ids: list[int] = []
                selected_raws: list[bytes] = []
                for raw_ref in raw_refs:
                    ref = _require_keys(
                        raw_ref,
                        {"board_id", "content_sha256", "raw_hex"},
                        "leaf board reference",
                    )
                    board_id = _require_int(ref["board_id"], "board_id", minimum=0)
                    if not 0 <= board_id < len(board_objects):
                        raise ValueError("leaf references a missing board record")
                    board = board_objects[board_id]
                    if ref["raw_hex"] != board.raw.hex():
                        raise ValueError("leaf board reference raw bytes mismatch")
                    if ref["content_sha256"] != board.content_sha256:
                        raise ValueError("leaf board reference content hash mismatch")
                    if board.index_digest != index_digest:
                        raise ValueError("leaf board digest does not match its path")
                    selected.append(board)
                    selected_ids.append(board_id)
                    selected_raws.append(board.raw)
                if selected_raws != sorted(set(selected_raws)):
                    raise ValueError("leaf collision bucket is noncanonical or duplicated")
                if declared_count != len(selected):
                    raise ValueError("leaf member count mismatch")
                node = _make_leaf(index_digest, selected)
                prefix = bytes.fromhex(index_digest)
                board_refs[node_id] = tuple(selected_ids)
                edges[node_id] = ()
            else:
                if not 0 <= depth < _LEAF_DEPTH:
                    raise ValueError("branch depth is outside the digest path")
                raw_refs = record["children"]
                if not isinstance(raw_refs, list) or not raw_refs:
                    raise ValueError("branch child references must be nonempty")
                selected_children: list[tuple[int, _TrieNode]] = []
                selected_ids = []
                slots: list[int] = []
                child_prefixes: list[bytes] = []
                for raw_ref in raw_refs:
                    ref = _require_keys(
                        raw_ref,
                        {"child_id", "child_sha256", "slot"},
                        "branch child reference",
                    )
                    slot = _require_int(ref["slot"], "branch slot", minimum=0)
                    if slot > 255:
                        raise ValueError("branch slot exceeds one digest byte")
                    child_id = _require_int(ref["child_id"], "child_id", minimum=0)
                    child = nodes.get(child_id)
                    if child is None:
                        raise ValueError("branch references a missing or cyclic child")
                    if child.depth != depth + 1:
                        raise ValueError("branch child depth mismatch")
                    if ref["child_sha256"] != child.content_sha256:
                        raise ValueError("branch child content hash mismatch")
                    child_prefix = prefixes[child_id]
                    if len(child_prefix) != depth + 1 or child_prefix[depth] != slot:
                        raise ValueError("branch slot does not match child digest path")
                    selected_children.append((slot, child))
                    selected_ids.append(child_id)
                    slots.append(slot)
                    child_prefixes.append(child_prefix)
                if slots != sorted(set(slots)):
                    raise ValueError("branch slots must be sorted and unique")
                common = child_prefixes[0][:depth]
                if any(child_prefix[:depth] != common for child_prefix in child_prefixes):
                    raise ValueError("branch children do not share their radix prefix")
                node = _make_branch(depth, selected_children)
                if declared_count != node.count:
                    raise ValueError("branch member count mismatch")
                prefix = common
                edges[node_id] = tuple(selected_ids)
                board_refs[node_id] = ()
            if node.content_sha256 != declared_hash:
                raise ValueError("node content hash mismatch")
            semantic_bytes = canonical_json_bytes(
                _leaf_content_payload(node.index_digest, node.boards)
                if isinstance(node, _Leaf)
                else _branch_content_payload(node.depth, node.children)
            )
            previous_payload = node_hash_payloads.get(declared_hash)
            if previous_payload is not None:
                if previous_payload != semantic_bytes:
                    raise ValueError("conflicting node content-hash records")
                raise ValueError("duplicate immutable node records are not permitted")
            node_hash_payloads[declared_hash] = semantic_bytes
            nodes[node_id] = node
            prefixes[node_id] = prefix

        root_ref = payload["root_ref"]
        if root_ref is None:
            if nodes or board_objects or declared_members != 0:
                raise ValueError("empty root has reachable records or members")
            root_node: _TrieNode | None = None
            root_id: int | None = None
        else:
            ref = _require_keys(
                root_ref, {"content_sha256", "node_id"}, "root reference"
            )
            root_id = _require_int(ref["node_id"], "root node id", minimum=0)
            if root_id != 0 or root_id not in nodes:
                raise ValueError("root must reference canonical node zero")
            root_node = nodes[root_id]
            if root_node.depth != 0 or prefixes[root_id] != b"":
                raise ValueError("root node does not span the complete digest trie")
            if ref["content_sha256"] != root_node.content_sha256:
                raise ValueError("root reference content hash mismatch")
            if root_node.count != declared_members:
                raise ValueError("root member count mismatch")

        calculated_root_sha = _root_content_sha256(
            self.board_size, self.digest_name, root_node
        )
        if calculated_root_sha != stored_root_sha:
            raise ValueError("history root hash mismatch")

        reachable_nodes: set[int] = set()
        reachable_boards: set[int] = set()
        node_parent_counts = [0] * len(record_by_id)
        board_reference_counts = [0] * len(board_objects)
        preorder: list[int] = []
        stack = [] if root_id is None else [root_id]
        while stack:
            node_id = stack.pop()
            if node_id in reachable_nodes:
                raise ValueError("history trie contains a repeated node reference")
            reachable_nodes.add(node_id)
            preorder.append(node_id)
            for board_id in board_refs[node_id]:
                board_reference_counts[board_id] += 1
                reachable_boards.add(board_id)
            child_ids = edges[node_id]
            for child_id in child_ids:
                node_parent_counts[child_id] += 1
            stack.extend(reversed(child_ids))
        if reachable_nodes != set(range(len(record_by_id))):
            raise ValueError("history artifact contains unreachable node records")
        if reachable_boards != set(range(len(board_objects))):
            raise ValueError("history artifact contains unreachable board records")
        if preorder != list(range(len(record_by_id))):
            raise ValueError("node records are not in canonical preorder")
        if root_id is not None:
            if node_parent_counts[root_id] != 0 or any(
                count != 1
                for node_id, count in enumerate(node_parent_counts)
                if node_id != root_id
            ):
                raise ValueError("history node references do not form a tree")
        if any(count != 1 for count in board_reference_counts):
            raise ValueError("board records must each have one exact leaf reference")

        # Independently rebuild the canonical trie from exact boards.  Merkle
        # hashes are verification aids, never the definition of set equality.
        verifier = PersistentHistory(
            self.board_size,
            digest_fn=self._raw_digest_fn,
            digest_name=self.digest_name,
        )
        canonical_root = verifier.empty_root
        for raw in sorted(exact_raws):
            canonical_root = verifier.insert(canonical_root, raw)
        if canonical_root._node != root_node:
            raise ValueError("records do not encode the canonical exact history trie")
        if canonical_root.root_sha256 != stored_root_sha:
            raise ValueError("canonical history root does not match the stored root")

        verified_by_raw = {board.raw: board for board in board_objects}
        result = self.empty_root
        for raw in sorted(exact_raws):
            adopted = self._adopt_verified_board(verified_by_raw[raw])
            result = self._insert_board_object(result, adopted)
        if result.root_sha256 != stored_root_sha or result._node != root_node:
            raise ValueError("returned history root differs from the verified root")
        return result

    def _rehydrate_forest_payload(
        self,
        payload: dict[str, Any],
        *,
        expected_artifact_sha256: str | None,
        expected_root_sha256s: Iterable[str] | None,
    ) -> tuple[HistoryRoot, ...]:
        """Verify a shared forest completely before adopting any records."""

        stored_artifact_sha = self._verify_forest_envelope(payload)
        if expected_artifact_sha256 is not None:
            expected_artifact_sha256 = _require_sha256(
                expected_artifact_sha256,
                "expected artifact hash",
            )
            if stored_artifact_sha != expected_artifact_sha256:
                raise ValueError(
                    "history forest does not match the expected artifact"
                )

        size = _require_int(payload["board_size"], "board_size", minimum=1)
        board_bytes = _require_int(
            payload["board_bytes"], "board_bytes", minimum=1
        )
        if size != self.board_size or board_bytes != self.board_bytes:
            raise ValueError("history forest artifact board size mismatch")
        digest_index = _require_keys(
            payload["digest_index"],
            {"collision_checked", "name"},
            "digest_index",
        )
        if digest_index["collision_checked"] is not True:
            raise ValueError("history forest requires collision-checked indexing")
        if digest_index["name"] != self.digest_name:
            raise ValueError("history forest digest function mismatch")

        declared_board_count = _require_int(
            payload["board_record_count"],
            "board_record_count",
            minimum=0,
        )
        declared_node_count = _require_int(
            payload["node_record_count"],
            "node_record_count",
            minimum=0,
        )
        declared_root_count = _require_int(
            payload["root_count"], "root_count", minimum=0
        )

        raw_board_records = payload["boards"]
        if not isinstance(raw_board_records, list):
            raise ValueError("forest board records must be an array")
        if len(raw_board_records) != declared_board_count:
            raise ValueError("forest board record count mismatch")
        board_objects: list[_BoardObject] = []
        board_sort_keys: list[tuple[str, bytes]] = []
        exact_raws: set[bytes] = set()
        for expected_id, raw_record in enumerate(raw_board_records):
            record = _require_keys(
                raw_record,
                {"content_sha256", "id", "index_digest", "raw_hex"},
                "forest board record",
            )
            board_id = _require_int(record["id"], "board id", minimum=0)
            if board_id != expected_id:
                raise ValueError(
                    "forest board record ids must be contiguous and ordered"
                )
            if type(record["raw_hex"]) is not str:
                raise ValueError("forest board raw_hex must be text")
            try:
                raw = bytes.fromhex(record["raw_hex"])
            except ValueError as exc:
                raise ValueError("forest board raw_hex is invalid") from exc
            if record["raw_hex"] != raw.hex():
                raise ValueError(
                    "forest board raw_hex must be canonical lowercase hex"
                )
            self._validate_board(raw)
            if raw in exact_raws:
                raise ValueError(
                    "duplicate exact forest board records are not permitted"
                )
            exact_raws.add(raw)
            index_digest = _require_sha256(
                record["index_digest"], "forest board index digest"
            )
            if index_digest != self._digest(raw):
                raise ValueError("forest board index digest mismatch")
            content_hash = _require_sha256(
                record["content_sha256"], "forest board content hash"
            )
            if content_hash != _board_content_sha256(self.board_size, raw):
                raise ValueError("forest board content hash mismatch")
            board_objects.append(_BoardObject(raw, index_digest, content_hash))
            board_sort_keys.append((index_digest, raw))
        if board_sort_keys != sorted(board_sort_keys):
            raise ValueError("forest board records are not in canonical order")

        raw_node_records = payload["nodes"]
        if not isinstance(raw_node_records, list):
            raise ValueError("forest node records must be an array")
        if len(raw_node_records) != declared_node_count:
            raise ValueError("forest node record count mismatch")

        nodes: list[_TrieNode] = []
        prefixes: list[bytes] = []
        edges: list[tuple[int, ...]] = []
        board_refs: list[tuple[int, ...]] = []
        semantic_node_keys: set[tuple[Any, ...]] = set()
        canonical_order_keys: list[tuple[Any, ...]] = []
        for expected_id, raw_record in enumerate(raw_node_records):
            if not isinstance(raw_record, dict):
                raise ValueError("forest node record must be an object")
            kind = raw_record.get("kind")
            keys = (
                {
                    "boards",
                    "content_sha256",
                    "count",
                    "depth",
                    "id",
                    "index_digest",
                    "kind",
                }
                if kind == "leaf"
                else {
                    "children",
                    "content_sha256",
                    "count",
                    "depth",
                    "id",
                    "kind",
                }
                if kind == "branch"
                else set()
            )
            if not keys:
                raise ValueError("forest node record has an unknown kind")
            record = _require_keys(raw_record, keys, "forest node record")
            node_id = _require_int(record["id"], "node id", minimum=0)
            if node_id != expected_id:
                raise ValueError(
                    "forest node record ids must be contiguous and ordered"
                )
            depth = _require_int(record["depth"], "node depth", minimum=0)
            declared_count = _require_int(
                record["count"], "node count", minimum=1
            )
            declared_hash = _require_sha256(
                record["content_sha256"], "node content hash"
            )

            if kind == "leaf":
                if depth != _LEAF_DEPTH:
                    raise ValueError(
                        "forest leaf must occur at the complete digest depth"
                    )
                index_digest = _require_sha256(
                    record["index_digest"], "forest leaf index digest"
                )
                raw_refs = record["boards"]
                if not isinstance(raw_refs, list) or not raw_refs:
                    raise ValueError(
                        "forest leaf board references must be nonempty"
                    )
                selected: list[_BoardObject] = []
                selected_ids: list[int] = []
                selected_raws: list[bytes] = []
                for raw_ref in raw_refs:
                    ref = _require_keys(
                        raw_ref,
                        {"board_id", "content_sha256", "raw_hex"},
                        "forest leaf board reference",
                    )
                    board_id = _require_int(
                        ref["board_id"], "board_id", minimum=0
                    )
                    if not 0 <= board_id < len(board_objects):
                        raise ValueError(
                            "forest leaf references a missing board record"
                        )
                    board = board_objects[board_id]
                    if ref["raw_hex"] != board.raw.hex():
                        raise ValueError(
                            "forest leaf board reference raw bytes mismatch"
                        )
                    if ref["content_sha256"] != board.content_sha256:
                        raise ValueError(
                            "forest leaf board reference content hash mismatch"
                        )
                    if board.index_digest != index_digest:
                        raise ValueError(
                            "forest leaf board digest does not match its path"
                        )
                    selected.append(board)
                    selected_ids.append(board_id)
                    selected_raws.append(board.raw)
                if selected_raws != sorted(set(selected_raws)):
                    raise ValueError(
                        "forest leaf collision bucket is noncanonical or duplicated"
                    )
                node = _make_leaf(index_digest, selected)
                if declared_count != len(selected):
                    raise ValueError("forest leaf member count mismatch")
                prefix = bytes.fromhex(index_digest)
                child_ids: tuple[int, ...] = ()
                referenced_board_ids = tuple(selected_ids)
                semantic_key: tuple[Any, ...] = (
                    depth,
                    "leaf",
                    index_digest,
                    referenced_board_ids,
                )
                local_order_key: tuple[Any, ...] = (
                    "leaf",
                    index_digest,
                    referenced_board_ids,
                )
            else:
                if not 0 <= depth < _LEAF_DEPTH:
                    raise ValueError(
                        "forest branch depth is outside the digest path"
                    )
                raw_refs = record["children"]
                if not isinstance(raw_refs, list) or not raw_refs:
                    raise ValueError(
                        "forest branch child references must be nonempty"
                    )
                selected_children: list[tuple[int, _TrieNode]] = []
                selected_ids: list[int] = []
                slots: list[int] = []
                child_prefixes: list[bytes] = []
                for raw_ref in raw_refs:
                    ref = _require_keys(
                        raw_ref,
                        {"child_id", "child_sha256", "slot"},
                        "forest branch child reference",
                    )
                    slot = _require_int(
                        ref["slot"], "forest branch slot", minimum=0
                    )
                    if slot > 255:
                        raise ValueError(
                            "forest branch slot exceeds one digest byte"
                        )
                    child_id = _require_int(
                        ref["child_id"], "child_id", minimum=0
                    )
                    if not 0 <= child_id < len(nodes):
                        raise ValueError(
                            "forest branch references a missing or cyclic child"
                        )
                    child = nodes[child_id]
                    if child.depth != depth + 1:
                        raise ValueError("forest branch child depth mismatch")
                    if ref["child_sha256"] != child.content_sha256:
                        raise ValueError(
                            "forest branch child content hash mismatch"
                        )
                    child_prefix = prefixes[child_id]
                    if (
                        len(child_prefix) != depth + 1
                        or child_prefix[depth] != slot
                    ):
                        raise ValueError(
                            "forest branch slot does not match child digest path"
                        )
                    selected_children.append((slot, child))
                    selected_ids.append(child_id)
                    slots.append(slot)
                    child_prefixes.append(child_prefix)
                if slots != sorted(set(slots)):
                    raise ValueError(
                        "forest branch slots must be sorted and unique"
                    )
                common = child_prefixes[0][:depth]
                if any(
                    child_prefix[:depth] != common
                    for child_prefix in child_prefixes
                ):
                    raise ValueError(
                        "forest branch children do not share their radix prefix"
                    )
                node = _make_branch(depth, selected_children)
                if declared_count != node.count:
                    raise ValueError("forest branch member count mismatch")
                prefix = common
                child_ids = tuple(selected_ids)
                referenced_board_ids = ()
                child_key = tuple(zip(slots, selected_ids, strict=True))
                semantic_key = (depth, "branch", child_key)
                local_order_key = ("branch", child_key)

            if node.content_sha256 != declared_hash:
                raise ValueError("forest node content hash mismatch")
            if semantic_key in semantic_node_keys:
                raise ValueError(
                    "duplicate immutable forest node records are not permitted"
                )
            semantic_node_keys.add(semantic_key)
            canonical_order_keys.append((-depth, local_order_key))
            nodes.append(node)
            prefixes.append(prefix)
            edges.append(child_ids)
            board_refs.append(referenced_board_ids)

        if canonical_order_keys != sorted(canonical_order_keys):
            raise ValueError("forest node records are not in canonical order")

        raw_root_records = payload["roots"]
        if not isinstance(raw_root_records, list):
            raise ValueError("forest root records must be an array")
        if len(raw_root_records) != declared_root_count:
            raise ValueError("forest root record count mismatch")

        root_node_ids: list[int | None] = []
        stored_root_hashes: list[str] = []
        for expected_id, raw_record in enumerate(raw_root_records):
            record = _require_keys(
                raw_record,
                {"id", "member_count", "node_ref", "root_sha256"},
                "forest root record",
            )
            root_id = _require_int(record["id"], "root id", minimum=0)
            if root_id != expected_id:
                raise ValueError(
                    "forest root record ids must be contiguous and ordered"
                )
            declared_members = _require_int(
                record["member_count"], "root member_count", minimum=0
            )
            stored_root_sha = _require_sha256(
                record["root_sha256"], "forest root hash"
            )
            root_ref = record["node_ref"]
            if root_ref is None:
                if declared_members != 0:
                    raise ValueError("empty forest root has nonzero members")
                root_node: _TrieNode | None = None
                root_node_id: int | None = None
            else:
                ref = _require_keys(
                    root_ref,
                    {"content_sha256", "node_id"},
                    "forest root reference",
                )
                root_node_id = _require_int(
                    ref["node_id"], "root node id", minimum=0
                )
                if not 0 <= root_node_id < len(nodes):
                    raise ValueError("forest root references a missing node")
                root_node = nodes[root_node_id]
                if root_node.depth != 0 or prefixes[root_node_id] != b"":
                    raise ValueError(
                        "forest root node does not span the complete digest trie"
                    )
                if ref["content_sha256"] != root_node.content_sha256:
                    raise ValueError("forest root reference content hash mismatch")
                if root_node.count != declared_members:
                    raise ValueError("forest root member count mismatch")
            calculated_root_sha = _root_content_sha256(
                self.board_size, self.digest_name, root_node
            )
            if calculated_root_sha != stored_root_sha:
                raise ValueError("forest root hash mismatch")
            root_node_ids.append(root_node_id)
            stored_root_hashes.append(stored_root_sha)

        if expected_root_sha256s is not None:
            try:
                expected_roots = tuple(expected_root_sha256s)
            except TypeError as exc:
                raise TypeError("expected root hashes must be iterable") from exc
            validated_expected = tuple(
                _require_sha256(value, "expected forest root hash")
                for value in expected_roots
            )
            if tuple(stored_root_hashes) != validated_expected:
                raise ValueError(
                    "history forest does not match the expected ordered roots"
                )

        # The record checks above are compositional: child ids precede parents,
        # every child has the next depth and exact derived digest prefix, branch
        # slots are unique, and leaf boards exactly match the complete path.
        # Therefore a physical node (and hence an exact board) cannot occur
        # twice beneath one root: two paths would first diverge at distinct
        # slots, which require distinct prefixes.  One union traversal is thus
        # sufficient for reachability; retaining a member-id set and rebuilding
        # every growing root would make a version chain quadratic.
        reachable_nodes: set[int] = set()
        reachable_boards: set[int] = set()
        stack = [node_id for node_id in root_node_ids if node_id is not None]
        while stack:
            node_id = stack.pop()
            if node_id in reachable_nodes:
                continue
            reachable_nodes.add(node_id)
            reachable_boards.update(board_refs[node_id])
            stack.extend(edges[node_id])
        if reachable_nodes != set(range(len(nodes))):
            raise ValueError("history forest contains unreachable node records")
        if reachable_boards != set(range(len(board_objects))):
            raise ValueError("history forest contains unreachable board records")

        # Adopt only after every hostile input check has passed, then rebuild
        # the unique node table once so all returned roots retain its sharing.
        transaction = self._begin_intern_transaction()
        try:
            adopted_boards = [
                self._adopt_verified_board(board) for board in board_objects
            ]
            adopted_nodes: list[_TrieNode] = []
            for node_id, node in enumerate(nodes):
                if isinstance(node, _Leaf):
                    adopted_node = _make_leaf(
                        node.index_digest,
                        (adopted_boards[item] for item in board_refs[node_id]),
                    )
                else:
                    adopted_node = _make_branch(
                        node.depth,
                        (
                            (slot, adopted_nodes[child_id])
                            for (slot, _child), child_id in zip(
                                node.children,
                                edges[node_id],
                                strict=True,
                            )
                        ),
                    )
                if adopted_node != node:
                    raise ValueError(
                        "adopted forest node differs from its verified record"
                    )
                adopted_nodes.append(adopted_node)
            results = tuple(
                HistoryRoot(
                    self.board_size,
                    self.digest_name,
                    None if node_id is None else adopted_nodes[node_id],
                    self._owner,
                )
                for node_id in root_node_ids
            )
            if tuple(root.root_sha256 for root in results) != tuple(
                stored_root_hashes
            ):
                raise ValueError(
                    "returned forest roots differ from the verified roots"
                )
            self._commit_intern_transaction(transaction)
        except BaseException:
            self._rollback_intern_transaction(transaction)
            raise
        return results

    def deserialize_forest(
        self,
        raw: bytes,
        *,
        expected_artifact_sha256: str | None = None,
        expected_root_sha256s: Iterable[str] | None = None,
    ) -> tuple[HistoryRoot, ...]:
        """Load a canonical compact forest into this history store.

        ``expected_artifact_sha256`` pins the artifact's self-hashed canonical
        payload.  ``expected_root_sha256s`` pins the ordered root-reference
        sequence.  Exact records are still verified independently of hashes.
        """

        payload = _decode_json(raw)
        return self._rehydrate_forest_payload(
            payload,
            expected_artifact_sha256=expected_artifact_sha256,
            expected_root_sha256s=expected_root_sha256s,
        )

    def deserialize_root(
        self,
        raw: bytes,
        *,
        expected_root_sha256: str | None = None,
    ) -> HistoryRoot:
        payload = _decode_json(raw)
        return self._rehydrate_payload(
            payload,
            expected_root_sha256=expected_root_sha256,
        )

    def load_root(
        self,
        path: str | Path,
        *,
        expected_root_sha256: str | None = None,
    ) -> HistoryRoot:
        return self.deserialize_root(
            Path(path).read_bytes(),
            expected_root_sha256=expected_root_sha256,
        )

    @classmethod
    def load_forest(
        cls,
        path: str | Path,
        *,
        digest_fn: DigestFunction | None = None,
        digest_name: str | None = None,
        expected_board_size: int | None = None,
        expected_artifact_sha256: str | None = None,
        expected_root_sha256s: Iterable[str] | None = None,
    ) -> tuple["PersistentHistory", tuple[HistoryRoot, ...]]:
        """Construct a store and load one canonical compact forest artifact."""

        raw = Path(path).read_bytes()
        payload = _decode_json(raw)
        cls._verify_forest_envelope(payload)
        board_size = _require_int(payload["board_size"], "board_size", minimum=1)
        if expected_board_size is not None:
            if type(expected_board_size) is not int:
                raise TypeError("expected_board_size must be an integer")
            if board_size != expected_board_size:
                raise ValueError(
                    "history forest does not match expected board size"
                )
        digest_index = _require_keys(
            payload["digest_index"],
            {"collision_checked", "name"},
            "digest_index",
        )
        stored_digest_name = digest_index["name"]
        if type(stored_digest_name) is not str or not stored_digest_name:
            raise ValueError("history forest digest name must be nonempty text")
        if digest_fn is None:
            if stored_digest_name != "sha256":
                raise ValueError(
                    "history forest requires its injected digest function"
                )
            configured_name: str | None = "sha256"
        else:
            configured_name = (
                digest_name if digest_name is not None else "injected"
            )
            if configured_name != stored_digest_name:
                raise ValueError("history forest digest function name mismatch")
        history = cls(
            board_size,
            digest_fn=digest_fn,
            digest_name=configured_name,
        )
        roots = history._rehydrate_forest_payload(
            payload,
            expected_artifact_sha256=expected_artifact_sha256,
            expected_root_sha256s=expected_root_sha256s,
        )
        return history, roots

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        digest_fn: DigestFunction | None = None,
        digest_name: str | None = None,
        expected_board_size: int | None = None,
        expected_root_sha256: str | None = None,
    ) -> tuple["PersistentHistory", HistoryRoot]:
        raw = Path(path).read_bytes()
        payload = _decode_json(raw)
        cls._verify_envelope(payload)
        board_size = _require_int(payload["board_size"], "board_size", minimum=1)
        if expected_board_size is not None:
            if type(expected_board_size) is not int:
                raise TypeError("expected_board_size must be an integer")
            if board_size != expected_board_size:
                raise ValueError("history artifact does not match expected board size")
        digest_index = _require_keys(
            payload["digest_index"],
            {"collision_checked", "name"},
            "digest_index",
        )
        stored_digest_name = digest_index["name"]
        if type(stored_digest_name) is not str or not stored_digest_name:
            raise ValueError("history artifact digest name must be nonempty text")
        if digest_fn is None:
            if stored_digest_name != "sha256":
                raise ValueError("history artifact requires its injected digest function")
            configured_name: str | None = "sha256"
        else:
            configured_name = digest_name if digest_name is not None else "injected"
            if configured_name != stored_digest_name:
                raise ValueError("history artifact digest function name mismatch")
        history = cls(
            board_size,
            digest_fn=digest_fn,
            digest_name=configured_name,
        )
        root = history._rehydrate_payload(
            payload,
            expected_root_sha256=expected_root_sha256,
        )
        return history, root


PersistentPSKSet = PersistentHistory


def roots_exactly_equal(
    first_history: PersistentHistory,
    first_root: HistoryRoot,
    second_history: PersistentHistory,
    second_root: HistoryRoot,
) -> bool:
    """Compare roots from distinct stores by exact sorted member bytes."""

    if not isinstance(first_history, PersistentHistory) or not isinstance(
        second_history, PersistentHistory
    ):
        raise TypeError("both histories must be PersistentHistory instances")
    if first_history.board_size != second_history.board_size:
        return False
    return first_history.members(first_root) == second_history.members(second_root)

__all__ = [
    "FOREST_SERIALIZATION_FORMAT",
    "HistoryRoot",
    "PersistentHistory",
    "PersistentPSKSet",
    "SERIALIZATION_FORMAT",
    "roots_exactly_equal",
]
