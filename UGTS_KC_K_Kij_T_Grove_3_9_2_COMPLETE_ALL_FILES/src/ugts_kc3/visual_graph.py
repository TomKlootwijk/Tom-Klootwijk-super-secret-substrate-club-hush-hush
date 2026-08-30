"""Serializable, typed and bounded visual scripting for :mod:`ugts_kc3.game`.

The graph format deliberately contains data only.  Runtime behaviour lives in a
registry, so saved projects never pickle or import user code.  Built-in nodes use
the small public ``GameWorld`` surface and this module does not import the game
runtime, which keeps it useful to editor and conversion tools on its own.
"""
from __future__ import annotations

from collections import deque
import copy
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Callable, ClassVar, Iterable, Iterator, Mapping, MutableMapping, Sequence

from .scatter import ScatterError, f32, repeatable_number


# Android scene packs currently preserve these five gameplay tags as native
# bits.  Spatial graph queries deliberately share that portable vocabulary so
# a graph cannot appear to work on desktop while silently missing on a phone.
PORTABLE_QUERY_TAGS = (
    "player",
    "collectible",
    "goal",
    "decorative",
    "hazard",
)
_PORTABLE_QUERY_TAG_SET = frozenset(PORTABLE_QUERY_TAGS)

# Saved message names are deliberately a tiny ASCII identifier.  The same
# literal contract is checked again by the Android graph-pack compiler and
# inspector so desktop-authored graphs cannot change meaning after deployment.
PORTABLE_MESSAGE_PATTERN = r"[a-z][a-z0-9_.-]{0,63}"
PORTABLE_ANIMATION_CLIP_PATTERN = r"[a-z][a-z0-9_.-]{0,31}"
GRAPH_MESSAGE_MAX_EVENTS = 64
GRAPH_MESSAGE_MAX_STEPS = 16384


def _is_portable_message(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(PORTABLE_MESSAGE_PATTERN, value) is not None


def _is_portable_animation_clip(value: Any) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(PORTABLE_ANIMATION_CLIP_PATTERN, value) is not None
    )


class FrozenDict(Mapping[str, Any]):
    """A tiny recursively-frozen mapping used by graph records.

    It prevents a caller from changing a frozen dataclass through a retained
    dictionary reference while remaining a normal ``Mapping`` to consumers.
    """

    __slots__ = ("_data", "_hash")

    def __init__(self, values: Mapping[str, Any] | None = None):
        self._data = dict(values or {})
        self._hash: int | None = None

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenDict({self._data!r})"

    def __hash__(self) -> int:
        if self._hash is None:
            self._hash = hash(tuple(sorted((key, _hashable(value)) for key, value in self._data.items())))
        return self._hash


def _hashable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _hashable(item)) for key, item in value.items()))
    if isinstance(value, (tuple, list)):
        return tuple(_hashable(item) for item in value)
    return value


def _freeze_json(value: Any, path: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must not contain NaN or infinity")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} uses a non-text key: {key!r}")
            frozen[key] = _freeze_json(item, f"{path}.{key}")
        return FrozenDict(frozen)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_json(item, f"{path}[{index}]") for index, item in enumerate(value))
    raise TypeError(f"{path} contains unsupported {type(value).__name__}; graph values must be JSON-compatible")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


def _runtime_snapshot(value: Any, seen: set[int] | None = None) -> Any:
    """Make trace values JSON-safe without affecting values passed between nodes."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return "<recursive>"
    if isinstance(value, Mapping):
        seen.add(identity)
        result = {str(key): _runtime_snapshot(item, seen) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
        seen.remove(identity)
        return result
    if isinstance(value, (tuple, list, set, frozenset)):
        seen.add(identity)
        items = [_runtime_snapshot(item, seen) for item in value]
        seen.remove(identity)
        return items
    if is_dataclass(value):
        seen.add(identity)
        result = {item.name: _runtime_snapshot(getattr(value, item.name), seen) for item in fields(value)}
        seen.remove(identity)
        return result
    return f"<{type(value).__name__}>"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class GraphNode:
    """An editor node. ``properties`` are literals and editor configuration."""

    id: str
    type: str
    properties: Mapping[str, Any] = field(default_factory=FrozenDict)
    position: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self) -> None:
        node_id = str(self.id).strip()
        node_type = str(self.type).strip()
        if not node_id:
            raise ValueError("a graph node needs a non-empty id")
        if not node_type:
            raise ValueError(f"node {node_id!r} needs a node type")
        if len(self.position) != 2:
            raise ValueError(f"node {node_id!r} position needs x and y values")
        position = (float(self.position[0]), float(self.position[1]))
        if not all(math.isfinite(value) for value in position):
            raise ValueError(f"node {node_id!r} position must be finite")
        object.__setattr__(self, "id", node_id)
        object.__setattr__(self, "type", node_type)
        object.__setattr__(self, "properties", _freeze_json(dict(self.properties), f"node {node_id} properties"))
        object.__setattr__(self, "position", position)

    @property
    def type_id(self) -> str:
        return self.type

    @property
    def kind(self) -> str:
        return self.type

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "properties": _thaw(self.properties), "position": list(self.position)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GraphNode":
        node_type = data.get("type", data.get("type_id", data.get("kind")))
        if node_type is None:
            raise ValueError(f"node {data.get('id', '<unknown>')!r} is missing its type")
        properties = data.get("properties", data.get("parameters", {}))
        return cls(str(data["id"]), str(node_type), dict(properties), tuple(data.get("position", (0.0, 0.0))))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class GraphLink:
    """A directed connection from one output port to one input port."""

    source_node: str
    source_port: str
    target_node: str
    target_port: str

    def __post_init__(self) -> None:
        for field_name in ("source_node", "source_port", "target_node", "target_port"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"a graph link needs a non-empty {field_name.replace('_', ' ')}")
            object.__setattr__(self, field_name, value)

    @property
    def id(self) -> str:
        return f"{self.source_node}:{self.source_port}->{self.target_node}:{self.target_port}"

    def to_dict(self) -> dict[str, str]:
        return {
            "source_node": self.source_node,
            "source_port": self.source_port,
            "target_node": self.target_node,
            "target_port": self.target_port,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GraphLink":
        if isinstance(data.get("source"), Mapping) and isinstance(data.get("target"), Mapping):
            source, target = data["source"], data["target"]
            return cls(str(source["node"]), str(source["port"]), str(target["node"]), str(target["port"]))
        return cls(str(data["source_node"]), str(data["source_port"]), str(data["target_node"]), str(data["target_port"]))


@dataclass(frozen=True, slots=True)
class VisualGraph:
    """Immutable-ish graph document with canonical serialization hooks."""

    SCHEMA: ClassVar[str] = "ugts-visual-graph-1"

    id: str = "graph"
    nodes: tuple[GraphNode, ...] = ()
    links: tuple[GraphLink, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        graph_id = str(self.id).strip()
        if not graph_id:
            raise ValueError("a visual graph needs a non-empty id")
        nodes = tuple(sorted(
            (item if isinstance(item, GraphNode) else GraphNode.from_dict(item) for item in self.nodes),
            key=lambda item: item.id,
        ))
        links = tuple(sorted(
            (item if isinstance(item, GraphLink) else GraphLink.from_dict(item) for item in self.links),
            key=lambda item: (item.source_node, item.source_port, item.target_node, item.target_port),
        ))
        object.__setattr__(self, "id", graph_id)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "links", links)
        object.__setattr__(self, "metadata", _freeze_json(dict(self.metadata), "graph metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "id": self.id,
            "nodes": [node.to_dict() for node in self.nodes],
            "links": [link.to_dict() for link in self.links],
            "metadata": _thaw(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VisualGraph":
        schema = data.get("schema", cls.SCHEMA)
        if schema != cls.SCHEMA:
            raise ValueError(f"unsupported visual graph schema {schema!r}; expected {cls.SCHEMA!r}")
        return cls(
            str(data.get("id", "graph")),
            tuple(GraphNode.from_dict(item) for item in data.get("nodes", ())),
            tuple(GraphLink.from_dict(item) for item in data.get("links", ())),
            dict(data.get("metadata", {})),
        )

    def canonical_bytes(self) -> bytes:
        """Return the stable, whitespace-free UTF-8 representation."""

        return _canonical_bytes(self.canonical_dict())

    def canonical_dict(self) -> dict[str, Any]:
        """Return the deterministic document used for storage and hashing."""

        return self.to_dict()

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def to_json(self, *, pretty: bool = False) -> str:
        if pretty:
            return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_json(cls, text: str | bytes | bytearray) -> "VisualGraph":
        return cls.from_dict(json.loads(text))

    def with_node(self, node: GraphNode, *, replace_existing: bool = False) -> "VisualGraph":
        existing = {item.id for item in self.nodes}
        if node.id in existing and not replace_existing:
            raise ValueError(f"node id {node.id!r} already exists")
        nodes = tuple(item for item in self.nodes if item.id != node.id) + (node,)
        return replace(self, nodes=nodes)

    def without_node(self, node_id: str) -> "VisualGraph":
        if node_id not in {node.id for node in self.nodes}:
            raise KeyError(node_id)
        return replace(
            self,
            nodes=tuple(node for node in self.nodes if node.id != node_id),
            links=tuple(link for link in self.links if node_id not in (link.source_node, link.target_node)),
        )

    def with_link(self, link: GraphLink) -> "VisualGraph":
        if link in self.links:
            raise ValueError(f"link {link.id} already exists")
        return replace(self, links=self.links + (link,))

    def without_link(self, link: GraphLink) -> "VisualGraph":
        if link not in self.links:
            raise KeyError(link.id)
        return replace(self, links=tuple(item for item in self.links if item != link))

    def validation_issues(self, registry: "NodeRegistry | None" = None) -> tuple["GraphValidationIssue", ...]:
        return _validation_issues(self, registry or BUILTIN_NODE_REGISTRY)

    def validate(self, registry: "NodeRegistry | None" = None) -> None:
        issues = self.validation_issues(registry)
        if issues:
            raise GraphValidationError(issues)

    def data_order(self, registry: "NodeRegistry | None" = None) -> tuple[str, ...]:
        active_registry = registry or BUILTIN_NODE_REGISTRY
        self.validate(active_registry)
        return _data_order(self, active_registry)[0]


class PortDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"


class PortKind(str, Enum):
    FLOW = "flow"
    DATA = "data"


class _NoDefault:
    __slots__ = ()

    def __repr__(self) -> str:
        return "NO_DEFAULT"


NO_DEFAULT = _NoDefault()


@dataclass(frozen=True, slots=True)
class PortDefinition:
    name: str
    direction: PortDirection | str
    kind: PortKind | str
    data_type: str = "any"
    required: bool = False
    default: Any = NO_DEFAULT
    description: str = ""
    allow_multiple: bool = False

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        if not name:
            raise ValueError("a port needs a non-empty name")
        try:
            direction = PortDirection(self.direction)
        except ValueError as error:
            raise ValueError(f"port {name!r} direction must be 'input' or 'output'") from error
        try:
            kind = PortKind(self.kind)
        except ValueError as error:
            raise ValueError(f"port {name!r} kind must be 'flow' or 'data'") from error
        data_type = "flow" if kind is PortKind.FLOW else str(self.data_type).strip().lower()
        if not data_type:
            raise ValueError(f"data port {name!r} needs a type")
        if self.default is not NO_DEFAULT:
            object.__setattr__(self, "default", _freeze_json(self.default, f"port {name} default"))
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "data_type", data_type)

    @property
    def has_default(self) -> bool:
        return self.default is not NO_DEFAULT


@dataclass(frozen=True, slots=True)
class NodeResult:
    """Values and flow outputs returned by a registered node executor."""

    values: Mapping[str, Any] = field(default_factory=dict)
    flow: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", dict(self.values))
        object.__setattr__(self, "flow", tuple(str(item) for item in self.flow))


NodeExecutor = Callable[["GraphContext", GraphNode, Mapping[str, Any]], NodeResult | Mapping[str, Any] | None]


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    """Editor metadata, typed ports and runtime function for one node type."""

    type: str
    label: str
    category: str
    description: str
    ports: tuple[PortDefinition, ...]
    executor: NodeExecutor = field(repr=False, compare=False)
    default_properties: Mapping[str, Any] = field(default_factory=FrozenDict)
    event: str | None = None

    def __post_init__(self) -> None:
        type_id = str(self.type).strip()
        if not type_id:
            raise ValueError("a node definition needs a type id")
        if not str(self.label).strip():
            raise ValueError(f"node definition {type_id!r} needs an editor label")
        ports = tuple(self.ports)
        identities = [(port.direction, port.name) for port in ports]
        if len(identities) != len(set(identities)):
            raise ValueError(f"node definition {type_id!r} repeats a port name in the same direction")
        if not callable(self.executor):
            raise TypeError(f"node definition {type_id!r} needs an executor function")
        object.__setattr__(self, "type", type_id)
        object.__setattr__(self, "label", str(self.label).strip())
        object.__setattr__(self, "category", str(self.category).strip() or "Other")
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "ports", ports)
        object.__setattr__(self, "default_properties", _freeze_json(dict(self.default_properties), f"{type_id} defaults"))
        object.__setattr__(self, "event", None if self.event is None else str(self.event))

    @property
    def type_id(self) -> str:
        return self.type

    @property
    def inputs(self) -> tuple[PortDefinition, ...]:
        return tuple(port for port in self.ports if port.direction is PortDirection.INPUT)

    @property
    def outputs(self) -> tuple[PortDefinition, ...]:
        return tuple(port for port in self.ports if port.direction is PortDirection.OUTPUT)

    @property
    def is_data_node(self) -> bool:
        return not any(port.kind is PortKind.FLOW for port in self.ports)

    def port(self, direction: PortDirection | str, name: str) -> PortDefinition | None:
        wanted = PortDirection(direction)
        return next((port for port in self.ports if port.direction is wanted and port.name == name), None)


class NodeRegistry:
    """Mutable registry. Graph documents store type ids, never callables."""

    def __init__(self, definitions: Iterable[NodeDefinition] = ()):
        self._definitions: dict[str, NodeDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: NodeDefinition, *, replace_existing: bool = False) -> NodeDefinition:
        if definition.type in self._definitions and not replace_existing:
            raise ValueError(f"node type {definition.type!r} is already registered")
        self._definitions[definition.type] = definition
        return definition

    def definition(self, type_id: str) -> NodeDefinition:
        try:
            return self._definitions[type_id]
        except KeyError as error:
            raise KeyError(f"unknown node type {type_id!r}; register it before loading this graph") from error

    def get(self, type_id: str) -> NodeDefinition | None:
        return self._definitions.get(type_id)

    def __contains__(self, type_id: object) -> bool:
        return type_id in self._definitions

    def __iter__(self) -> Iterator[NodeDefinition]:
        for type_id in sorted(self._definitions):
            yield self._definitions[type_id]

    @property
    def types(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    @property
    def definitions(self) -> tuple[NodeDefinition, ...]:
        return tuple(iter(self))

    def copy(self) -> "NodeRegistry":
        return NodeRegistry(self)


@dataclass(frozen=True, slots=True)
class GraphValidationIssue:
    code: str
    message: str
    node_id: str | None = None
    link_index: int | None = None

    def __str__(self) -> str:
        return self.message


class GraphValidationError(ValueError):
    def __init__(self, issues: Sequence[GraphValidationIssue]):
        self.issues = tuple(issues)
        count = len(self.issues)
        lines = "\n".join(f"  - {issue.message}" for issue in self.issues)
        super().__init__(f"visual graph has {count} problem{'s' if count != 1 else ''}:\n{lines}")


class GraphCycleError(GraphValidationError):
    pass


def _types_connect(source: str, target: str) -> bool:
    return source == "any" or target == "any" or source == target


def _value_matches_type(value: Any, data_type: str) -> bool:
    if data_type == "any":
        return True
    if data_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
    if data_type in {"string", "entity"}:
        return isinstance(value, str) or (data_type == "entity" and (value is None or hasattr(value, "id")))
    if data_type == "boolean":
        return isinstance(value, bool)
    if data_type == "mapping":
        return isinstance(value, Mapping)
    vector_lengths = {"vector2": 2, "vector3": 3, "vector4": 4}
    if data_type in vector_lengths:
        return (
            isinstance(value, (tuple, list))
            and len(value) == vector_lengths[data_type]
            and all(isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(float(item)) for item in value)
        )
    return True  # Custom symbolic types are enforced by their registered executor.


def _node_property(definition: NodeDefinition, node: GraphNode, name: str, port: PortDefinition) -> tuple[bool, Any]:
    if name in node.properties:
        return True, node.properties[name]
    if name in definition.default_properties:
        return True, definition.default_properties[name]
    if port.has_default:
        return True, port.default
    return False, None


def _validation_issues(graph: VisualGraph, registry: NodeRegistry) -> tuple[GraphValidationIssue, ...]:
    issues: list[GraphValidationIssue] = []
    nodes: dict[str, GraphNode] = {}
    for node in graph.nodes:
        if node.id in nodes:
            issues.append(GraphValidationIssue("duplicate_node", f"Node id {node.id!r} is used more than once. Give every node a unique id.", node.id))
        else:
            nodes[node.id] = node
        if registry.get(node.type) is None:
            issues.append(GraphValidationIssue("unknown_node_type", f"Node {node.id!r} uses unknown type {node.type!r}.", node.id))

    incoming_data: dict[tuple[str, str], list[int]] = {}
    seen_links: dict[GraphLink, int] = {}
    valid_data_links: list[GraphLink] = []
    for index, link in enumerate(graph.links):
        if link in seen_links:
            issues.append(GraphValidationIssue("duplicate_link", f"Link {link.id} is duplicated (links {seen_links[link]} and {index}).", link_index=index))
            continue
        seen_links[link] = index
        source_node, target_node = nodes.get(link.source_node), nodes.get(link.target_node)
        if source_node is None:
            issues.append(GraphValidationIssue("missing_source", f"Link {index} starts at missing node {link.source_node!r}.", link_index=index))
        if target_node is None:
            issues.append(GraphValidationIssue("missing_target", f"Link {index} ends at missing node {link.target_node!r}.", link_index=index))
        if source_node is None or target_node is None:
            continue
        source_definition, target_definition = registry.get(source_node.type), registry.get(target_node.type)
        if source_definition is None or target_definition is None:
            continue
        source_port = source_definition.port(PortDirection.OUTPUT, link.source_port)
        target_port = target_definition.port(PortDirection.INPUT, link.target_port)
        if source_port is None:
            issues.append(GraphValidationIssue("missing_source_port", f"Node {source_node.id!r} has no output port named {link.source_port!r}.", source_node.id, index))
        if target_port is None:
            issues.append(GraphValidationIssue("missing_target_port", f"Node {target_node.id!r} has no input port named {link.target_port!r}.", target_node.id, index))
        if source_port is None or target_port is None:
            continue
        if source_port.kind is not target_port.kind:
            issues.append(
                GraphValidationIssue(
                    "port_kind_mismatch",
                    f"Link {link.id} connects a {source_port.kind.value} port to a {target_port.kind.value} port. Connect flow to flow or data to data.",
                    link_index=index,
                )
            )
            continue
        if source_port.kind is PortKind.DATA:
            if not _types_connect(source_port.data_type, target_port.data_type):
                issues.append(
                    GraphValidationIssue(
                        "data_type_mismatch",
                        f"Link {link.id} sends {source_port.data_type} into {target_port.data_type}; those data types do not match.",
                        link_index=index,
                    )
                )
                continue
            incoming_data.setdefault((link.target_node, link.target_port), []).append(index)
            valid_data_links.append(link)

    for (node_id, port_name), indexes in sorted(incoming_data.items()):
        node, definition = nodes[node_id], registry.get(nodes[node_id].type)
        port = None if definition is None else definition.port(PortDirection.INPUT, port_name)
        if port is not None and len(indexes) > 1 and not port.allow_multiple:
            issues.append(
                GraphValidationIssue(
                    "multiple_data_sources",
                    f"Input {node_id}.{port_name} has {len(indexes)} links. A data input accepts one source; remove all but one.",
                    node.id,
                    indexes[1],
                )
            )

    for node_id in sorted(nodes):
        node, definition = nodes[node_id], registry.get(nodes[node_id].type)
        if definition is None:
            continue
        for port in definition.inputs:
            if port.kind is not PortKind.DATA:
                continue
            linked = (node.id, port.name) in incoming_data
            supplied, literal = _node_property(definition, node, port.name, port)
            if port.required and not linked and not supplied:
                issues.append(
                    GraphValidationIssue(
                        "missing_input",
                        f"Node {node.id!r} needs a value for input {port.name!r}. Connect it or set it in the node properties.",
                        node.id,
                    )
                )
            if not linked and supplied and not _value_matches_type(literal, port.data_type):
                issues.append(
                    GraphValidationIssue(
                        "literal_type_mismatch",
                        f"Node {node.id!r} property {port.name!r} must be {port.data_type}, not {type(literal).__name__}.",
                        node.id,
                    )
                )

        if node.type == "value.seeded_number":
            static: dict[str, Any] = {}
            for name in ("world_number", "pick_number", "smallest", "largest"):
                if (node.id, name) in incoming_data:
                    continue
                port = definition.port(PortDirection.INPUT, name)
                assert port is not None
                supplied, literal = _node_property(definition, node, name, port)
                if supplied:
                    static[name] = literal
            for name, label in (
                ("world_number", "World number"),
                ("pick_number", "Pick number"),
            ):
                value = static.get(name)
                invalid = False
                if name in static and _value_matches_type(value, "number"):
                    try:
                        canonical = f32(value)
                    except ScatterError:
                        invalid = True
                    else:
                        invalid = (
                            canonical != math.trunc(canonical)
                            or not 0 <= canonical <= 65535
                        )
                if invalid:
                    issues.append(
                        GraphValidationIssue(
                            "repeatable_number_index",
                            f"Repeatable Random Number {label} must be a whole number from 0 to 65535.",
                            node.id,
                        )
                    )
            rounded: dict[str, float] = {}
            for name, label in (("smallest", "Smallest"), ("largest", "Largest")):
                value = static.get(name)
                if name not in static or not _value_matches_type(value, "number"):
                    continue
                try:
                    rounded[name] = f32(value)
                except ScatterError:
                    issues.append(
                        GraphValidationIssue(
                            "repeatable_number_bound",
                            f"Repeatable Random Number {label} must be a finite number that fits on this device.",
                            node.id,
                        )
                    )
            if (
                "smallest" in rounded
                and "largest" in rounded
                and rounded["smallest"] > rounded["largest"]
            ):
                issues.append(
                    GraphValidationIssue(
                        "repeatable_number_range",
                        "Repeatable Random Number Smallest must not be bigger than Largest.",
                        node.id,
                    )
                )

        if node.type == "event.message":
            indexes = incoming_data.get((node.id, "message"), ())
            if indexes:
                issues.append(
                    GraphValidationIssue(
                        "message_literal_only",
                        "When Message Heard Message must be saved on the block, not connected from another block.",
                        node.id,
                        indexes[0],
                    )
                )
            else:
                port = definition.port(PortDirection.INPUT, "message")
                assert port is not None
                supplied, literal = _node_property(
                    definition, node, "message", port
                )
                if supplied and _value_matches_type(literal, "string") and not _is_portable_message(literal):
                    issues.append(
                        GraphValidationIssue(
                            "message_name",
                            "When Message Heard Message must start with a lowercase letter, use only lowercase letters, digits, dot, underscore, or hyphen, and be at most 64 characters.",
                            node.id,
                        )
                    )

        if node.type == "event.timer":
            for name, label in (("seconds", "Seconds"), ("repeat", "Repeat")):
                indexes = incoming_data.get((node.id, name), ())
                if indexes:
                    issues.append(
                        GraphValidationIssue(
                            "timer_literal_only",
                            f"When Timer Rings {label} must be set on the block, not connected from another block.",
                            node.id,
                            indexes[0],
                        )
                    )
            if (node.id, "seconds") not in incoming_data:
                port = definition.port(PortDirection.INPUT, "seconds")
                assert port is not None
                supplied, literal = _node_property(
                    definition, node, "seconds", port
                )
                if supplied and _value_matches_type(literal, "number"):
                    invalid = False
                    try:
                        seconds = f32(literal)
                    except ScatterError:
                        invalid = True
                    else:
                        invalid = not 0.0 < seconds <= 86400.0
                    if invalid:
                        issues.append(
                            GraphValidationIssue(
                                "timer_seconds",
                                "When Timer Rings Seconds must be a finite positive number up to 86400.",
                                node.id,
                            )
                        )

        if node.type == "action.play_animation":
            clip_links = incoming_data.get((node.id, "clip"), ())
            if not clip_links:
                port = definition.port(PortDirection.INPUT, "clip")
                assert port is not None
                supplied, literal = _node_property(definition, node, "clip", port)
                if (
                    supplied
                    and _value_matches_type(literal, "string")
                    and not _is_portable_animation_clip(literal)
                ):
                    issues.append(
                        GraphValidationIssue(
                            "animation_clip_name",
                            "Play Animation Clip must start with a lowercase letter, use only lowercase letters, digits, dot, underscore, or hyphen, and be at most 32 characters.",
                            node.id,
                        )
                    )

        if node.type == "action.set_polar_population_visible":
            entity_links = incoming_data.get((node.id, "entity"), ())
            if entity_links:
                issues.append(
                    GraphValidationIssue(
                        "polar_population_target_literal_only",
                        "Show or Hide Extra Copies Object must be chosen on the block, not connected from another block.",
                        node.id,
                        entity_links[0],
                    )
                )

        if node.type == "query.nearest_tag":
            if (node.id, "tag") not in incoming_data:
                port = definition.port(PortDirection.INPUT, "tag")
                assert port is not None
                supplied, literal = _node_property(definition, node, "tag", port)
                if (
                    supplied
                    and _value_matches_type(literal, "string")
                    and literal not in _PORTABLE_QUERY_TAG_SET
                ):
                    issues.append(
                        GraphValidationIssue(
                            "nearest_tag_value",
                            "Find Nearby Object Tag must be player, collectible, goal, decorative, or hazard.",
                            node.id,
                        )
                    )
            if (node.id, "radius") not in incoming_data:
                port = definition.port(PortDirection.INPUT, "radius")
                assert port is not None
                supplied, literal = _node_property(definition, node, "radius", port)
                if supplied and _value_matches_type(literal, "number"):
                    invalid = False
                    try:
                        radius = f32(literal)
                        f32(radius * radius)
                    except ScatterError:
                        invalid = True
                    else:
                        invalid = radius < 0.0
                    if invalid:
                        issues.append(
                            GraphValidationIssue(
                                "nearest_tag_radius",
                                "Find Nearby Object Radius must be a finite non-negative number that fits on this device.",
                                node.id,
                            )
                        )

        if node.type == "query.nearest_in_cone":
            if (node.id, "tag") not in incoming_data:
                port = definition.port(PortDirection.INPUT, "tag")
                assert port is not None
                supplied, literal = _node_property(definition, node, "tag", port)
                if (
                    supplied
                    and _value_matches_type(literal, "string")
                    and literal not in _PORTABLE_QUERY_TAG_SET
                ):
                    issues.append(
                        GraphValidationIssue(
                            "nearest_in_cone_tag_value",
                            "Find Object Ahead Tag must be player, collectible, goal, decorative, or hazard.",
                            node.id,
                        )
                    )
            if (node.id, "radius") not in incoming_data:
                port = definition.port(PortDirection.INPUT, "radius")
                assert port is not None
                supplied, literal = _node_property(definition, node, "radius", port)
                if supplied and _value_matches_type(literal, "number"):
                    invalid = False
                    try:
                        radius = f32(literal)
                        f32(radius * radius)
                    except ScatterError:
                        invalid = True
                    else:
                        invalid = radius < 0.0
                    if invalid:
                        issues.append(
                            GraphValidationIssue(
                                "nearest_in_cone_radius",
                                "Find Object Ahead Radius must be a finite non-negative number that fits on this device.",
                                node.id,
                            )
                        )
            if (node.id, "cone") not in incoming_data:
                port = definition.port(PortDirection.INPUT, "cone")
                assert port is not None
                supplied, literal = _node_property(definition, node, "cone", port)
                if supplied and _value_matches_type(literal, "vector4"):
                    try:
                        _portable_cone(literal)
                    except ValueError as error:
                        issues.append(
                            GraphValidationIssue(
                                "nearest_in_cone_value",
                                f"Find Object Ahead Cone {error}.",
                                node.id,
                            )
                        )

    _, cyclic = _data_order(graph, registry, valid_data_links)
    if cyclic:
        names = ", ".join(repr(node_id) for node_id in cyclic)
        issues.append(GraphValidationIssue("data_cycle", f"Data links form a cycle through {names}. Insert state or remove a backward data link."))
    return tuple(issues)


def _data_order(
    graph: VisualGraph,
    registry: NodeRegistry,
    known_links: Sequence[GraphLink] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    node_ids = sorted({node.id for node in graph.nodes})
    node_map = {node.id: node for node in graph.nodes}
    dependencies: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    links = graph.links if known_links is None else known_links
    for link in links:
        source_node, target_node = node_map.get(link.source_node), node_map.get(link.target_node)
        if source_node is None or target_node is None:
            continue
        source_definition, target_definition = registry.get(source_node.type), registry.get(target_node.type)
        if source_definition is None or target_definition is None:
            continue
        source_port = source_definition.port(PortDirection.OUTPUT, link.source_port)
        target_port = target_definition.port(PortDirection.INPUT, link.target_port)
        if source_port is not None and target_port is not None and source_port.kind is target_port.kind is PortKind.DATA:
            dependencies[target_node.id].add(source_node.id)
    incoming = {node_id: set(items) for node_id, items in dependencies.items()}
    ready = sorted(node_id for node_id, items in incoming.items() if not items)
    result: list[str] = []
    while ready:
        node_id = ready.pop(0)
        result.append(node_id)
        for other in node_ids:
            if node_id in incoming[other]:
                incoming[other].remove(node_id)
                if not incoming[other] and other not in result and other not in ready:
                    ready.append(other)
                    ready.sort()
    cyclic = tuple(sorted(node_id for node_id, items in incoming.items() if items))
    return tuple(result), cyclic


@dataclass(frozen=True, slots=True)
class GraphContext:
    """Per-dispatch bridge to a ``GameWorld`` and its current entity/input."""

    world: Any
    entity_id: str | None = None
    input_frame: Any = None
    dt: float = 0.0
    event_name: str = ""
    payload: Mapping[str, Any] = field(default_factory=FrozenDict)
    active_step: int = 0

    def __post_init__(self) -> None:
        dt = float(self.dt)
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("graph context dt must be finite and non-negative")
        active_step = self.active_step
        if (
            not isinstance(active_step, int)
            or isinstance(active_step, bool)
            or active_step < 0
        ):
            raise ValueError("graph context active_step must be a non-negative integer")
        object.__setattr__(self, "entity_id", None if self.entity_id is None else str(self.entity_id))
        object.__setattr__(self, "dt", dt)
        object.__setattr__(self, "event_name", str(self.event_name))
        object.__setattr__(self, "payload", _freeze_json(dict(self.payload), "graph event payload"))
        object.__setattr__(self, "active_step", active_step)

    @property
    def entity(self) -> Any:
        if self.entity_id is None:
            return None
        return getattr(self.world, "entities", {}).get(self.entity_id)

    def for_event(self, event_name: str, payload: Mapping[str, Any] | None = None) -> "GraphContext":
        return replace(self, event_name=str(event_name), payload=self.payload if payload is None else payload)


@dataclass(frozen=True, slots=True)
class TraceEntry:
    step: int
    node_id: str
    node_type: str
    flow_input: str | None
    inputs: Mapping[str, Any]
    outputs: Mapping[str, Any]
    flow_outputs: tuple[str, ...]
    status: str = "ok"
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", _freeze_json(_runtime_snapshot(self.inputs), "trace inputs"))
        object.__setattr__(self, "outputs", _freeze_json(_runtime_snapshot(self.outputs), "trace outputs"))
        object.__setattr__(self, "flow_outputs", tuple(self.flow_outputs))

    def to_dict(self) -> dict[str, Any]:
        result = {
            "step": self.step,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "flow_input": self.flow_input,
            "inputs": _thaw(self.inputs),
            "outputs": _thaw(self.outputs),
            "flow_outputs": list(self.flow_outputs),
            "status": self.status,
        }
        if self.error is not None:
            result["error"] = self.error
        return result


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    trigger: str
    steps: int
    trace: tuple[TraceEntry, ...]
    completed: bool = True

    @property
    def traces(self) -> tuple[TraceEntry, ...]:
        return self.trace

    def to_dict(self) -> dict[str, Any]:
        return {"trigger": self.trigger, "steps": self.steps, "completed": self.completed, "trace": [item.to_dict() for item in self.trace]}


class GraphExecutionError(RuntimeError):
    def __init__(self, message: str, trace: Sequence[TraceEntry] = ()):
        self.trace = tuple(trace)
        super().__init__(message)


class GraphStepLimitError(GraphExecutionError):
    def __init__(self, limit: int, node_id: str, trace: Sequence[TraceEntry]):
        self.limit = int(limit)
        self.node_id = node_id
        super().__init__(
            f"Visual graph stopped before node {node_id!r}: it reached the {limit}-step safety limit. Check for a flow loop or raise max_steps deliberately.",
            trace,
        )


class GraphEventLimitError(GraphExecutionError):
    """A queued message cascade exceeded its deterministic event budget."""

    code = "EventLimit"

    def __init__(self, limit: int = GRAPH_MESSAGE_MAX_EVENTS):
        self.limit = int(limit)
        super().__init__(
            f"Visual graph message dispatch stopped with EventLimit after {limit} queued events. Check for messages that keep sending one another."
        )


class GraphTotalStepLimitError(GraphExecutionError):
    """All graph handlers in one queued message drain exhausted their budget."""

    code = "TotalStepLimit"

    def __init__(
        self,
        limit: int = GRAPH_MESSAGE_MAX_STEPS,
        trace: Sequence[TraceEntry] = (),
    ):
        self.limit = int(limit)
        super().__init__(
            f"Visual graph message dispatch stopped with TotalStepLimit after {limit} node steps.",
            trace,
        )


class GraphNodeExecutionError(GraphExecutionError):
    def __init__(self, node: GraphNode, reason: str, trace: Sequence[TraceEntry]):
        self.node_id = node.id
        self.node_type = node.type
        super().__init__(f"Node {node.id!r} ({node.type}) could not run: {reason}", trace)


@dataclass(slots=True)
class _RunState:
    trigger: str
    context: GraphContext
    max_steps: int
    steps: int = 0
    trace: list[TraceEntry] = field(default_factory=list)
    last_outputs: dict[str, Mapping[str, Any]] = field(default_factory=dict)


class GraphRuntime:
    """Validated graph plan with deterministic, bounded event dispatch."""

    def __init__(self, graph: VisualGraph, registry: NodeRegistry | None = None, *, max_steps: int = 1024):
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
        self.graph = graph
        self.registry = registry or BUILTIN_NODE_REGISTRY
        graph.validate(self.registry)
        self.max_steps = max_steps
        self.order = graph.data_order(self.registry)
        self._rank = {node_id: index for index, node_id in enumerate(self.order)}
        self._nodes = {node.id: node for node in graph.nodes}
        self._incoming_data: dict[tuple[str, str], GraphLink] = {}
        self._outgoing_flow: dict[tuple[str, str], tuple[GraphLink, ...]] = {}
        outgoing: dict[tuple[str, str], list[GraphLink]] = {}
        for link in graph.links:
            source = self.registry.definition(self._nodes[link.source_node].type).port(PortDirection.OUTPUT, link.source_port)
            if source is not None and source.kind is PortKind.DATA:
                self._incoming_data[(link.target_node, link.target_port)] = link
            elif source is not None:
                outgoing.setdefault((link.source_node, link.source_port), []).append(link)
        for key, links in outgoing.items():
            self._outgoing_flow[key] = tuple(sorted(links, key=lambda item: (self._rank.get(item.target_node, 0), item.target_node, item.target_port, item.id)))
        self.last_result: ExecutionResult | None = None
        self.last_trace: tuple[TraceEntry, ...] = ()
        # Direct GraphRuntime users get the same timer lifecycle as an attached
        # GraphBinding.  Bindings pass their own counter explicitly so one
        # runtime can still be shared safely by multiple entity owners.
        self._active_step = 0

    def _trigger_roots(
        self,
        trigger: str,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[str, ...]:
        roots: list[str] = []
        message = None if payload is None else payload.get("message")
        for node in self.graph.nodes:
            definition = self.registry.definition(node.type)
            event = definition.event
            if event != trigger and not (
                trigger == "tick" and event in {"input_pressed", "timer"}
            ):
                continue
            if event == "message":
                port = definition.port(PortDirection.INPUT, "message")
                assert port is not None
                _, saved_message = _node_property(
                    definition,
                    node,
                    "message",
                    port,
                )
                if saved_message != message:
                    continue
            roots.append(node.id)
        return tuple(
            sorted(roots, key=lambda item: (self._rank[item], item))
        )

    def has_trigger(
        self,
        trigger: str,
        payload: Mapping[str, Any] | None = None,
    ) -> bool:
        """Whether this runtime has at least one root for this exact dispatch."""

        return bool(self._trigger_roots(str(trigger), payload))

    def execute(self, trigger: str, context: GraphContext, *, max_steps: int | None = None) -> ExecutionResult:
        """Dispatch ``ready``, ``tick``, input, or another registered event."""

        trigger_name = str(trigger).strip()
        if not trigger_name:
            raise ValueError("graph trigger name must not be empty")
        limit = self.max_steps if max_steps is None else max_steps
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("max_steps must be a positive integer")
        if trigger_name == "ready":
            self._active_step = 0
        elif trigger_name == "tick" and context.active_step == 0:
            self._active_step += 1
            context = replace(context, active_step=self._active_step)
        state = _RunState(trigger_name, context.for_event(trigger_name), limit)
        queue: deque[tuple[str, str | None]] = deque()
        for node_id in self._trigger_roots(trigger_name, state.context.payload):
            queue.append((node_id, None))
        try:
            while queue:
                node_id, flow_input = queue.popleft()
                outcome = self._evaluate(node_id, flow_input, state, {})
                state.last_outputs[node_id] = outcome.values
                for flow_port in outcome.flow:
                    links = self._outgoing_flow.get((node_id, flow_port), ())
                    if len(queue) + len(links) > state.max_steps:
                        raise GraphStepLimitError(state.max_steps, links[0].target_node if links else node_id, state.trace)
                    for link in links:
                        queue.append((link.target_node, link.target_port))
        except GraphExecutionError:
            self.last_trace = tuple(state.trace)
            self.last_result = ExecutionResult(trigger_name, state.steps, self.last_trace, False)
            raise
        result = ExecutionResult(trigger_name, state.steps, tuple(state.trace), True)
        self.last_trace, self.last_result = result.trace, result
        return result

    dispatch = execute
    run = execute

    def ready(
        self,
        world: Any,
        *,
        entity_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        max_steps: int | None = None,
    ) -> ExecutionResult:
        return self.execute(
            "ready",
            GraphContext(world, entity_id, dt=0.0, payload=payload or {}),
            max_steps=max_steps,
        )

    def tick(
        self,
        world: Any,
        dt: float | None = None,
        input_frame: Any = None,
        *,
        entity_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        active_step: int | None = None,
        max_steps: int | None = None,
    ) -> ExecutionResult:
        step_dt = float(getattr(world, "fixed_dt", 0.0) if dt is None else dt)
        if active_step is None:
            self._active_step += 1
            step = self._active_step
        else:
            if (
                not isinstance(active_step, int)
                or isinstance(active_step, bool)
                or active_step < 1
            ):
                raise ValueError("active_step must be a positive integer during tick")
            step = active_step
        return self.execute(
            "tick",
            GraphContext(
                world,
                entity_id,
                input_frame,
                step_dt,
                payload=payload or {},
                active_step=step,
            ),
            max_steps=max_steps,
        )

    def event(
        self,
        trigger: str,
        world: Any,
        *,
        entity_id: str | None = None,
        input_frame: Any = None,
        dt: float = 0.0,
        payload: Mapping[str, Any] | None = None,
        max_steps: int | None = None,
    ) -> ExecutionResult:
        """Dispatch a named world event with an explicit, immutable payload."""
        return self.execute(
            trigger,
            GraphContext(world, entity_id, input_frame, dt, payload=payload or {}),
            max_steps=max_steps,
        )

    def _evaluate(
        self,
        node_id: str,
        flow_input: str | None,
        state: _RunState,
        data_cache: dict[str, NodeResult],
        stack: tuple[str, ...] = (),
    ) -> NodeResult:
        if node_id in data_cache:
            return data_cache[node_id]
        node = self._nodes[node_id]
        definition = self.registry.definition(node.type)
        if state.steps >= state.max_steps:
            raise GraphStepLimitError(state.max_steps, node_id, state.trace)
        if node_id in stack:
            raise GraphNodeExecutionError(node, "a data link recursively requested this node", state.trace)
        inputs: dict[str, Any] = {}
        try:
            for port in definition.inputs:
                if port.kind is PortKind.FLOW:
                    continue
                link = self._incoming_data.get((node_id, port.name))
                if link is not None:
                    source_node = self._nodes[link.source_node]
                    source_definition = self.registry.definition(source_node.type)
                    if source_node.id in state.last_outputs:
                        source_values = state.last_outputs[source_node.id]
                    elif source_definition.is_data_node:
                        source_values = self._evaluate(source_node.id, None, state, data_cache, stack + (node_id,)).values
                    else:
                        raise ValueError(
                            f"input {port.name!r} reads {source_node.id}.{link.source_port}, but that flow node has not run yet"
                        )
                    if link.source_port not in source_values:
                        raise ValueError(f"source {source_node.id}.{link.source_port} did not produce a value")
                    value = source_values[link.source_port]
                else:
                    supplied, value = _node_property(definition, node, port.name, port)
                    if not supplied:
                        if port.required:
                            raise ValueError(f"required input {port.name!r} has no value")
                        value = None
                if not _value_matches_type(value, port.data_type):
                    raise TypeError(f"input {port.name!r} expected {port.data_type}, received {type(value).__name__}")
                inputs[port.name] = value
            state.steps += 1
            raw_outcome = definition.executor(state.context, node, inputs)
            if raw_outcome is None:
                outcome = NodeResult()
            elif isinstance(raw_outcome, NodeResult):
                outcome = raw_outcome
            elif isinstance(raw_outcome, Mapping):
                outcome = NodeResult(raw_outcome)
            else:
                raise TypeError(f"executor returned unsupported {type(raw_outcome).__name__}")
            for name in outcome.values:
                port = definition.port(PortDirection.OUTPUT, name)
                if port is None or port.kind is not PortKind.DATA:
                    raise ValueError(f"executor produced undeclared data output {name!r}")
                if not _value_matches_type(outcome.values[name], port.data_type):
                    raise TypeError(f"output {name!r} promised {port.data_type}, produced {type(outcome.values[name]).__name__}")
            for name in outcome.flow:
                port = definition.port(PortDirection.OUTPUT, name)
                if port is None or port.kind is not PortKind.FLOW:
                    raise ValueError(f"executor activated undeclared flow output {name!r}")
            state.trace.append(
                TraceEntry(state.steps, node.id, node.type, flow_input, inputs, outcome.values, outcome.flow)
            )
            if definition.is_data_node:
                data_cache[node_id] = outcome
            return outcome
        except GraphExecutionError:
            raise
        except Exception as error:
            if state.steps == 0 or not state.trace or state.trace[-1].node_id != node.id:
                state.trace.append(TraceEntry(state.steps, node.id, node.type, flow_input, inputs, {}, (), "error", str(error)))
            raise GraphNodeExecutionError(node, str(error), state.trace) from error


@dataclass(frozen=True, slots=True)
class _QueuedGraphMessage:
    message: str
    source: str | None
    target: str | None


@dataclass(slots=True)
class _GraphMessageDispatcher:
    """Per-world, transient FIFO for graph-to-graph messages.

    The dispatcher is runtime state only: graph JSON and KCVG packs contain no
    queue or payload.  An outer graph finishes before this FIFO drains, and any
    nested sends are appended behind all recipients of the current message.
    """

    world: Any
    bindings: list[GraphBinding] = field(default_factory=list)
    queue: deque[_QueuedGraphMessage] = field(default_factory=deque)
    dispatch_depth: int = 0
    defer_depth: int = 0
    draining: bool = False
    pending_steps: int = 0
    enqueued_events: int = 0
    late_system_installed: bool = False
    trigger_routes_installed: bool = False
    suppress_trigger_routes: int = 0

    def register(self, binding: GraphBinding) -> None:
        if not any(existing is binding for existing in self.bindings):
            self.bindings.append(binding)

    def enqueue(
        self,
        message: str,
        source: str | None,
        target: str | None,
    ) -> None:
        if self.enqueued_events >= GRAPH_MESSAGE_MAX_EVENTS:
            self.abort_batch()
            raise GraphEventLimitError()
        self.queue.append(_QueuedGraphMessage(message, source, target))
        self.enqueued_events += 1

    def ensure_late_drain(self) -> None:
        if self.late_system_installed:
            return
        self.late_system_installed = True
        try:
            self.world.add_system(
                self._late_drain,
                phase="late",
                priority=(1 << 63) - 1,
                name="visual_graph:message_drain",
            )
        except Exception:
            self.late_system_installed = False
            raise

    def ensure_trigger_routes(self) -> None:
        """Install one canonical router instead of one listener per binding."""

        if self.trigger_routes_installed or not hasattr(self.world, "on"):
            return
        self.world.on("trigger_enter", self._route_trigger)
        self.world.on("trigger_exit", self._route_trigger)
        self.trigger_routes_installed = True

    def _route_trigger(self, event: Any) -> None:
        if self.suppress_trigger_routes:
            return
        for binding in self._binding_order():
            binding.handle_trigger(event)

    def _late_drain(self, world: Any, dt: float, input_frame: Any) -> None:
        del world, dt, input_frame
        self.drain()

    def abort_batch(self) -> None:
        self.queue.clear()
        self.pending_steps = 0
        self.enqueued_events = 0

    def step_limit(
        self,
        runtime: GraphRuntime,
        trigger: str,
        payload: Mapping[str, Any] | None = None,
    ) -> int:
        remaining = GRAPH_MESSAGE_MAX_STEPS - self.pending_steps
        if remaining < 1:
            if runtime.has_trigger(trigger, payload):
                self.abort_batch()
                raise GraphTotalStepLimitError()
            return 1
        return min(runtime.max_steps, remaining)

    def record(self, result: ExecutionResult) -> None:
        self.pending_steps += result.steps
        if self.pending_steps > GRAPH_MESSAGE_MAX_STEPS:
            self.abort_batch()
            raise GraphTotalStepLimitError(trace=result.trace)

    def begin_dispatch(self) -> None:
        self.dispatch_depth += 1

    def end_dispatch(self, *, drain_messages: bool = True) -> None:
        if self.dispatch_depth < 1:
            raise RuntimeError("visual graph message dispatch depth is unbalanced")
        self.dispatch_depth -= 1
        if drain_messages:
            self.drain()

    def _binding_order(self) -> tuple[GraphBinding, ...]:
        entities = getattr(self.world, "entities", {})
        entity_indexes = (
            {str(entity_id): index for index, entity_id in enumerate(entities)}
            if isinstance(entities, Mapping)
            else {}
        )
        world_index = len(entity_indexes)

        def key(binding: GraphBinding) -> tuple[int, bytes]:
            index = (
                world_index
                if binding.entity_id is None
                else entity_indexes.get(binding.entity_id, world_index + 1)
            )
            return index, binding.runtime.graph.id.encode("utf-8")

        return tuple(sorted(self.bindings, key=key))

    @staticmethod
    def _accepts(binding: GraphBinding, target: str | None) -> bool:
        if not binding.owner_is_active():
            return False
        return target is None or binding.entity_id is None or binding.entity_id == target

    def drain(self) -> None:
        if (
            self.draining
            or self.dispatch_depth
            or self.defer_depth
        ):
            return
        self.draining = True
        completed = False
        try:
            while self.queue:
                queued = self.queue.popleft()
                payload = {
                    "message": queued.message,
                    "source": queued.source,
                    "target": queued.target,
                }
                for binding in self._binding_order():
                    if (
                        not self._accepts(binding, queued.target)
                        or not binding.runtime.has_trigger("message", payload)
                    ):
                        continue
                    handler_limit = self.step_limit(
                        binding.runtime,
                        "message",
                        payload,
                    )
                    try:
                        result = binding._dispatch_message(
                            queued,
                            max_steps=handler_limit,
                        )
                    except GraphStepLimitError as error:
                        if handler_limit < binding.runtime.max_steps:
                            raise GraphTotalStepLimitError(
                                trace=error.trace
                            ) from error
                        raise
                    self.record(result)
            completed = True
        except Exception:
            # A failed cascade cannot leak stale messages into a later frame.
            self.abort_batch()
            raise
        finally:
            self.draining = False
            if completed:
                self.pending_steps = 0
                self.enqueued_events = 0


_GRAPH_MESSAGE_DISPATCHER_ATTRIBUTE = "_ugts_graph_message_dispatcher"


def _message_dispatcher(
    world: Any,
    *,
    create: bool = True,
) -> _GraphMessageDispatcher | None:
    dispatcher = getattr(world, _GRAPH_MESSAGE_DISPATCHER_ATTRIBUTE, None)
    if dispatcher is None and create:
        dispatcher = _GraphMessageDispatcher(world)
        setattr(world, _GRAPH_MESSAGE_DISPATCHER_ATTRIBUTE, dispatcher)
    if dispatcher is not None and not isinstance(dispatcher, _GraphMessageDispatcher):
        raise TypeError(
            f"world attribute {_GRAPH_MESSAGE_DISPATCHER_ATTRIBUTE!r} is reserved for visual graphs"
        )
    return dispatcher


@dataclass(slots=True)
class GraphBinding:
    """A graph registered as a normal ``GameWorld`` update system."""

    runtime: GraphRuntime
    world: Any
    entity_id: str | None
    phase: str
    name: str
    ready_result: ExecutionResult | None = None
    last_result: ExecutionResult | None = None
    last_input_frame: Any = None
    active_step: int = 0

    def run_ready(self, *, drain_messages: bool = True) -> ExecutionResult:
        self.active_step = 0
        dispatcher = _message_dispatcher(self.world)
        assert dispatcher is not None
        limit = dispatcher.step_limit(self.runtime, "ready")
        dispatcher.begin_dispatch()
        try:
            try:
                self.ready_result = self.runtime.ready(
                    self.world,
                    entity_id=self.entity_id,
                    max_steps=limit,
                )
            except GraphStepLimitError as error:
                dispatcher.abort_batch()
                if limit < self.runtime.max_steps:
                    raise GraphTotalStepLimitError(trace=error.trace) from error
                raise
            dispatcher.record(self.ready_result)
        except Exception:
            dispatcher.abort_batch()
            raise
        finally:
            dispatcher.end_dispatch(drain_messages=drain_messages)
        return self.ready_result

    def owner_is_active(self) -> bool:
        """World graphs always run; entity graphs follow their owner's lifecycle."""
        if self.entity_id is None:
            return True
        entities = getattr(self.world, "entities", None)
        if not isinstance(entities, Mapping):
            return False
        entity = entities.get(self.entity_id)
        return bool(
            entity is not None
            and getattr(entity, "alive", True)
            and getattr(entity, "active", True)
        )

    def update(self, world: Any, dt: float, input_frame: Any) -> None:
        dispatcher = _message_dispatcher(self.world)
        assert dispatcher is not None
        if self.owner_is_active():
            self.active_step += 1
            self.last_input_frame = input_frame
            limit = dispatcher.step_limit(self.runtime, "tick")
            dispatcher.begin_dispatch()
            try:
                try:
                    self.last_result = self.runtime.tick(
                        world,
                        dt,
                        input_frame,
                        entity_id=self.entity_id,
                        active_step=self.active_step,
                        max_steps=limit,
                    )
                except GraphStepLimitError as error:
                    dispatcher.abort_batch()
                    if limit < self.runtime.max_steps:
                        raise GraphTotalStepLimitError(
                            trace=error.trace
                        ) from error
                    raise
                dispatcher.record(self.last_result)
            except Exception:
                dispatcher.abort_batch()
                raise
            finally:
                dispatcher.end_dispatch(drain_messages=False)

    def handle_trigger(self, event: Any) -> None:
        """Dispatch player/sensor transitions to world or matching sensor graphs."""
        trigger = str(getattr(event, "kind", ""))
        if trigger not in {"trigger_enter", "trigger_exit"}:
            return
        sensor = getattr(event, "entity_a", getattr(event, "source", None))
        player = getattr(event, "entity_b", getattr(event, "target", None))
        if self.entity_id is not None and str(sensor) != self.entity_id:
            return
        if not self.owner_is_active():
            return
        raw_payload = getattr(event, "data", getattr(event, "payload", {}))
        payload = dict(raw_payload) if isinstance(raw_payload, Mapping) else {}
        payload.update({"sensor": None if sensor is None else str(sensor), "player": None if player is None else str(player)})
        settings = getattr(self.world, "settings", None)
        dt = float(getattr(settings, "fixed_dt", getattr(self.world, "fixed_dt", 0.0)))
        dispatcher = _message_dispatcher(self.world)
        assert dispatcher is not None
        limit = dispatcher.step_limit(self.runtime, trigger, payload)
        dispatcher.begin_dispatch()
        try:
            try:
                self.last_result = self.runtime.event(
                    trigger,
                    self.world,
                    entity_id=self.entity_id,
                    input_frame=self.last_input_frame,
                    dt=dt,
                    payload=payload,
                    max_steps=limit,
                )
            except GraphStepLimitError as error:
                dispatcher.abort_batch()
                if limit < self.runtime.max_steps:
                    raise GraphTotalStepLimitError(trace=error.trace) from error
                raise
            dispatcher.record(self.last_result)
        except Exception:
            dispatcher.abort_batch()
            raise
        finally:
            dispatcher.end_dispatch(drain_messages=False)

    def _dispatch_message(
        self,
        queued: _QueuedGraphMessage,
        *,
        max_steps: int,
    ) -> ExecutionResult:
        settings = getattr(self.world, "settings", None)
        dt = float(
            getattr(settings, "fixed_dt", getattr(self.world, "fixed_dt", 0.0))
        )
        self.last_result = self.runtime.event(
            "message",
            self.world,
            entity_id=self.entity_id,
            input_frame=self.last_input_frame,
            dt=dt,
            payload={
                "message": queued.message,
                "source": queued.source,
                "target": queued.target,
            },
            max_steps=max_steps,
        )
        return self.last_result


def attach_graph(
    world: Any,
    graph: VisualGraph | GraphRuntime,
    *,
    entity_id: str | None = None,
    phase: str = "update",
    priority: int | None = None,
    name: str | None = None,
    registry: NodeRegistry | None = None,
    max_steps: int = 1024,
    run_ready: bool = True,
) -> GraphBinding:
    """Attach a graph without changing ``GameWorld`` or requiring a component."""

    if not hasattr(world, "add_system"):
        raise TypeError("attach_graph needs a GameWorld-like object with add_system()")
    runtime = graph if isinstance(graph, GraphRuntime) else GraphRuntime(graph, registry, max_steps=max_steps)
    binding_name = name or f"visual_graph:{runtime.graph.id}:{entity_id or 'world'}"
    binding = GraphBinding(runtime, world, entity_id, phase, binding_name)
    dispatcher = _message_dispatcher(world)
    assert dispatcher is not None
    dispatcher.register(binding)
    dispatcher.ensure_late_drain()
    dispatcher.ensure_trigger_routes()
    if priority is None:
        entities = getattr(world, "entities", {})
        entity_indexes = (
            {str(key): index for index, key in enumerate(entities)}
            if isinstance(entities, Mapping)
            else {}
        )
        # A very late ordinary priority keeps world senders after entity senders
        # even if more entities are attached after the world graph.
        binding_priority = (
            (1 << 62)
            if entity_id is None
            else entity_indexes.get(entity_id, len(entity_indexes))
        )
    else:
        binding_priority = int(priority)
    world.add_system(
        binding.update,
        phase=phase,
        priority=binding_priority,
        name=binding_name,
    )
    if run_ready:
        # A direct attachment is one complete Ready batch.  Project loaders
        # register every binding with ``run_ready=False`` and then use the
        # multi-binding batch below.
        run_ready_batch((binding,))
    return binding


def run_ready_batch(
    bindings: Iterable[GraphBinding],
) -> tuple[ExecutionResult, ...]:
    """Run one canonical Ready batch, then drain all messages it emitted.

    Every binding is registered before the first Ready handler.  Entity-bound
    graphs run by scene insertion index then graph id; world graphs run last.
    """

    items = tuple(bindings)
    if not items:
        return ()
    world = items[0].world
    if any(binding.world is not world for binding in items):
        raise ValueError("a Ready batch can contain bindings from only one world")
    dispatcher = _message_dispatcher(world)
    assert dispatcher is not None
    for binding in items:
        dispatcher.register(binding)
    ordered = tuple(
        binding
        for binding in dispatcher._binding_order()
        if any(binding is item for item in items)
    )
    dispatcher.defer_depth += 1
    completed = False
    try:
        results = tuple(binding.run_ready() for binding in ordered)
        completed = True
    finally:
        dispatcher.defer_depth -= 1
        if completed:
            dispatcher.drain()
        else:
            dispatcher.abort_batch()
    return results


def _in_flow(name: str = "in", description: str = "Runs this node when a flow arrives.") -> PortDefinition:
    return PortDefinition(name, PortDirection.INPUT, PortKind.FLOW, description=description, allow_multiple=True)


def _out_flow(name: str = "out", description: str = "Continues to the next connected node.") -> PortDefinition:
    return PortDefinition(name, PortDirection.OUTPUT, PortKind.FLOW, description=description, allow_multiple=True)


def _in_data(
    name: str,
    data_type: str = "any",
    *,
    required: bool = False,
    default: Any = NO_DEFAULT,
    description: str = "",
) -> PortDefinition:
    return PortDefinition(name, PortDirection.INPUT, PortKind.DATA, data_type, required, default, description)


def _out_data(name: str, data_type: str = "any", description: str = "") -> PortDefinition:
    return PortDefinition(name, PortDirection.OUTPUT, PortKind.DATA, data_type, description=description, allow_multiple=True)


def _entity_id(context: GraphContext, value: Any) -> str:
    resolved = context.entity_id if value in (None, "") else getattr(value, "id", value)
    if resolved is None or not str(resolved):
        raise ValueError("no entity was supplied; set the entity input or bind this graph to an entity")
    entity_id = str(resolved)
    if entity_id not in getattr(context.world, "entities", {}):
        raise KeyError(f"entity {entity_id!r} does not exist")
    return entity_id


def _portable_f32(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number that fits on this device")
    try:
        return f32(value)
    except ScatterError as error:
        raise ValueError(
            f"{label} must be a finite number that fits on this device"
        ) from error


def _entity_position3(
    context: GraphContext,
    entity_id: str,
    *,
    required: bool,
) -> tuple[float, float, float] | None:
    getter = getattr(context.world, "get", None)
    transform = getter(entity_id, "transform") if callable(getter) else None
    if transform is None:
        if required:
            raise ValueError(f"entity {entity_id!r} has no transform position")
        return None
    if isinstance(transform, Mapping):
        position = transform.get("position", transform.get("translation"))
    else:
        position = getattr(transform, "position", None)
        if position is None:
            position = getattr(transform, "translation", None)
    if (
        not isinstance(position, Sequence)
        or isinstance(position, (str, bytes, bytearray))
        or len(position) not in (2, 3)
    ):
        if required:
            raise ValueError(f"entity {entity_id!r} has no 2D or 3D transform position")
        return None
    coordinates = tuple(
        _portable_f32(value, f"entity {entity_id!r} transform position")
        for value in position
    )
    if len(coordinates) == 2:
        return coordinates[0], coordinates[1], 0.0
    return coordinates[0], coordinates[1], coordinates[2]


def _portable_cone(
    value: Any,
) -> tuple[tuple[float, float, float], float]:
    """Canonicalize ``(axis xyz, minimum cosine)`` for portable cone queries.

    The axis is deliberately supplied in world space.  This keeps the saved
    graph compact (one Vector4), avoids platform-specific trigonometry, and
    gives the Python, browser, and native runtimes the same binary32 gate.
    """

    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) != 4
    ):
        raise ValueError("must contain a three-number Facing direction and View width")
    values = tuple(_portable_f32(item, "cone") for item in value)
    axis_squared = 0.0
    try:
        for component in values[:3]:
            axis_squared = f32(axis_squared + f32(component * component))
    except ScatterError as error:
        raise ValueError("is too large for deterministic device math") from error
    if axis_squared <= 0.0:
        raise ValueError("Facing direction must not be zero")
    if not -1.0 <= values[3] <= 1.0:
        raise ValueError("View width must use a minimum cosine from -1 to 1")
    try:
        axis_length = f32(math.sqrt(axis_squared))
        axis = tuple(f32(component / axis_length) for component in values[:3])
    except (ScatterError, ZeroDivisionError) as error:
        raise ValueError("Facing direction cannot be normalized on this device") from error
    return (axis[0], axis[1], axis[2]), values[3]


def _portable_cone_support(
    delta: tuple[float, float, float],
    squared: float,
    axis: tuple[float, float, float],
    cosine: float,
) -> bool:
    # Mirror GSP4's componentwise normalized direction and clamp_min(1e-6)
    # gate, with an explicit binary32 rounding point after every operation.
    try:
        distance = f32(math.sqrt(squared))
        denominator = max(distance, f32(1.0e-6))
        direction = tuple(f32(component / denominator) for component in delta)
        cosine_to_axis = 0.0
        for index in range(3):
            cosine_to_axis = f32(
                cosine_to_axis + f32(direction[index] * axis[index])
            )
    except ScatterError as error:
        raise ValueError("cone is too large for deterministic device math") from error
    return cosine_to_axis >= cosine


def _nearest_tag(
    context: GraphContext,
    node: GraphNode,
    inputs: Mapping[str, Any],
) -> NodeResult:
    tag = inputs["tag"]
    if not isinstance(tag, str) or tag not in _PORTABLE_QUERY_TAG_SET:
        raise ValueError(
            "tag must be player, collectible, goal, decorative, or hazard"
        )
    radius = _portable_f32(inputs["radius"], "radius")
    if radius < 0.0:
        raise ValueError("radius must be non-negative")
    try:
        radius_squared = f32(radius * radius)
    except ScatterError as error:
        raise ValueError(
            "radius must be a finite non-negative number that fits on this device"
        ) from error

    origin_id = _entity_id(context, inputs.get("origin"))
    origin = _entity_position3(context, origin_id, required=True)
    assert origin is not None
    entities = getattr(context.world, "entities", {})
    if not isinstance(entities, Mapping):
        raise TypeError("the graph world does not expose an entity mapping")

    best_id: str | None = None
    best_squared: float | None = None
    for raw_id in sorted(entities, key=lambda value: str(value).encode("utf-8")):
        candidate_id = str(raw_id)
        if candidate_id == origin_id:
            continue
        candidate = entities[raw_id]
        if (
            candidate is None
            or not bool(getattr(candidate, "alive", True))
            or not bool(getattr(candidate, "active", True))
            or tag not in getattr(candidate, "tags", ())
        ):
            continue
        position = _entity_position3(context, candidate_id, required=False)
        if position is None:
            continue
        squared = 0.0
        for axis in range(3):
            delta = f32(position[axis] - origin[axis])
            term = f32(delta * delta)
            squared = f32(squared + term)
        if squared > radius_squared:
            continue
        if (
            best_squared is None
            or squared < best_squared
            or (
                squared == best_squared
                and best_id is not None
                and candidate_id.encode("utf-8") < best_id.encode("utf-8")
            )
        ):
            best_id = candidate_id
            best_squared = squared

    if best_id is None or best_squared is None:
        return NodeResult({"found": False, "entity": None, "distance": None})
    return NodeResult(
        {
            "found": True,
            "entity": best_id,
            "distance": f32(math.sqrt(best_squared)),
        }
    )


def _nearest_in_cone(
    context: GraphContext,
    node: GraphNode,
    inputs: Mapping[str, Any],
) -> NodeResult:
    tag = inputs["tag"]
    if not isinstance(tag, str) or tag not in _PORTABLE_QUERY_TAG_SET:
        raise ValueError(
            "tag must be player, collectible, goal, decorative, or hazard"
        )
    radius = _portable_f32(inputs["radius"], "radius")
    if radius < 0.0:
        raise ValueError("radius must be non-negative")
    try:
        radius_squared = f32(radius * radius)
    except ScatterError as error:
        raise ValueError(
            "radius must be a finite non-negative number that fits on this device"
        ) from error
    axis, cosine = _portable_cone(inputs["cone"])

    origin_id = _entity_id(context, inputs.get("origin"))
    origin = _entity_position3(context, origin_id, required=True)
    assert origin is not None
    entities = getattr(context.world, "entities", {})
    if not isinstance(entities, Mapping):
        raise TypeError("the graph world does not expose an entity mapping")

    best_id: str | None = None
    best_squared: float | None = None
    for raw_id in sorted(entities, key=lambda value: str(value).encode("utf-8")):
        candidate_id = str(raw_id)
        if candidate_id == origin_id:
            continue
        candidate = entities[raw_id]
        if (
            candidate is None
            or not bool(getattr(candidate, "alive", True))
            or not bool(getattr(candidate, "active", True))
            or tag not in getattr(candidate, "tags", ())
        ):
            continue
        position = _entity_position3(context, candidate_id, required=False)
        if position is None:
            continue
        delta = tuple(f32(position[index] - origin[index]) for index in range(3))
        squared = 0.0
        try:
            for component in delta:
                squared = f32(squared + f32(component * component))
        except ScatterError as error:
            raise ValueError("candidate distance is too large for deterministic device math") from error
        if squared > radius_squared or not _portable_cone_support(
            delta, squared, axis, cosine
        ):
            continue
        if (
            best_squared is None
            or squared < best_squared
            or (
                squared == best_squared
                and best_id is not None
                and candidate_id.encode("utf-8") < best_id.encode("utf-8")
            )
        ):
            best_id = candidate_id
            best_squared = squared

    if best_id is None or best_squared is None:
        return NodeResult({"found": False, "entity": None, "distance": None})
    return NodeResult(
        {
            "found": True,
            "entity": best_id,
            "distance": f32(math.sqrt(best_squared)),
        }
    )


_VECTOR_FIELD_INDEX = {"x": 0, "y": 1, "z": 2, "w": 3}


def _sequence_field_index(part: str) -> int | None:
    if part.isdigit():
        return int(part)
    return _VECTOR_FIELD_INDEX.get(part)


def _read_field(value: Any, path: str, default: Any = NO_DEFAULT) -> Any:
    if not path:
        return value
    current = value
    try:
        for part in path.split("."):
            if not part or part.startswith("_"):
                raise ValueError("component field names cannot be empty or private")
            if isinstance(current, Mapping):
                current = current[part]
            elif isinstance(current, (tuple, list)):
                index = _sequence_field_index(part)
                if index is None:
                    raise AttributeError(part)
                current = current[index]
            else:
                current = getattr(current, part)
        return current
    except (KeyError, IndexError, AttributeError):
        if default is not NO_DEFAULT:
            return default
        raise


def _write_field(value: Any, path: str, new_value: Any) -> None:
    parts = path.split(".")
    if not parts or any(not part or part.startswith("_") for part in parts):
        raise ValueError("component field names cannot be empty or private")
    def replace_field(current: Any, remaining: list[str]) -> Any:
        part = remaining[0]
        if len(remaining) == 1:
            if isinstance(current, MutableMapping):
                current[part] = new_value
                return current
            if isinstance(current, list):
                index = _sequence_field_index(part)
                if index is None:
                    raise AttributeError(part)
                current[index] = new_value
                return current
            if isinstance(current, tuple):
                index = _sequence_field_index(part)
                if index is None:
                    raise AttributeError(part)
                updated = list(current)
                updated[index] = new_value
                return tuple(updated)
            setattr(current, part, new_value)
            return current

        if isinstance(current, Mapping):
            child = current[part]
        elif isinstance(current, (tuple, list)):
            index = _sequence_field_index(part)
            if index is None:
                raise AttributeError(part)
            child = current[index]
        else:
            child = getattr(current, part)
        replacement = replace_field(child, remaining[1:])
        if replacement is child:
            return current
        if isinstance(current, MutableMapping):
            current[part] = replacement
        elif isinstance(current, list):
            index = _sequence_field_index(part)
            if index is None:
                raise AttributeError(part)
            current[index] = replacement
        elif isinstance(current, tuple):
            index = _sequence_field_index(part)
            if index is None:
                raise AttributeError(part)
            updated = list(current)
            updated[index] = replacement
            return tuple(updated)
        else:
            setattr(current, part, replacement)
        return current

    replacement = replace_field(value, parts)
    if replacement is not value:
        raise TypeError("cannot replace an immutable root component field")


def _event_ready(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    return NodeResult({"entity": context.entity_id}, ("out",))


def _event_message(
    context: GraphContext,
    node: GraphNode,
    inputs: Mapping[str, Any],
) -> NodeResult:
    source = context.payload.get("source")
    target = context.payload.get("target")
    outputs = {
        "source": None if source is None else str(source),
        "target": None if target is None else str(target),
        "entity": context.entity_id,
    }
    heard = context.payload.get("message") == inputs["message"]
    return NodeResult(outputs, ("out",) if heard else ())


def _event_tick(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    return NodeResult({"dt": context.dt, "tick": int(getattr(context.world, "tick", 0)), "entity": context.entity_id}, ("out",))


def _event_timer(
    context: GraphContext,
    node: GraphNode,
    inputs: Mapping[str, Any],
) -> NodeResult:
    """Poll a compact fixed-step timer without storing suspended graph state."""

    try:
        seconds = f32(inputs["seconds"])
    except ScatterError as error:
        raise ValueError(
            "When Timer Rings Seconds must be a finite positive number up to 86400."
        ) from error
    if not 0.0 < seconds <= 86400.0:
        raise ValueError(
            "When Timer Rings Seconds must be a finite positive number up to 86400."
        )
    repeat = inputs["repeat"]
    if not isinstance(repeat, bool):
        raise TypeError("When Timer Rings Repeat must be true or false.")
    try:
        step_dt = f32(context.dt)
    except ScatterError as error:
        raise ValueError(
            "When Timer Rings needs a positive fixed-step duration."
        ) from error
    if step_dt <= 0.0:
        raise ValueError("When Timer Rings needs a positive fixed-step duration.")
    try:
        period = max(1, math.ceil(f32(seconds / step_dt)))
    except (OverflowError, ScatterError) as error:
        raise ValueError(
            "When Timer Rings could not fit this duration into fixed updates."
        ) from error

    step = context.active_step
    if repeat:
        remainder = step % period
        rings = step // period
        ringing = step > 0 and remainder == 0
        remaining_steps = 0 if ringing else period - remainder
    else:
        ringing = step == period
        rings = 0 if step < period else 1
        remaining_steps = max(0, period - step)
    try:
        count = f32(rings)
        remaining = (
            0.0
            if remaining_steps == 0
            else f32(f32(remaining_steps) * step_dt)
        )
    except ScatterError as error:
        raise ValueError(
            "When Timer Rings could not fit this duration into fixed updates."
        ) from error
    return NodeResult(
        {"count": count, "remaining": remaining, "entity": context.entity_id},
        ("out",) if ringing else (),
    )


def _event_input_pressed(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    action = str(inputs["action"])
    frame = context.input_frame
    value = 0.0 if frame is None else float(frame.value(action)) if hasattr(frame, "value") else float(getattr(frame, "values", {}).get(action, 0.0))
    if frame is not None and hasattr(frame, "pressed"):
        active = bool(frame.pressed(action))
    else:
        active = context.event_name == "input_pressed" and context.payload.get("action", action) == action
    return NodeResult({"action": action, "value": value, "entity": context.entity_id}, ("out",) if active else ())


def _event_trigger(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    return NodeResult(
        {
            "sensor": context.payload.get("sensor"),
            "player": context.payload.get("player"),
            "entity": context.entity_id,
        },
        ("out",),
    )


def _branch(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    return NodeResult(flow=("true",) if inputs["condition"] else ("false",))


def _constant(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    return NodeResult({"value": _thaw(node.properties.get("value", 0))})


def _repeatable_number(
    context: GraphContext,
    node: GraphNode,
    inputs: Mapping[str, Any],
) -> NodeResult:
    return NodeResult(
        {
            "value": repeatable_number(
                inputs["world_number"],
                inputs["pick_number"],
                inputs["smallest"],
                inputs["largest"],
            )
        }
    )


def _state(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    key = str(inputs["key"])
    default = inputs.get("default")
    return NodeResult({"value": getattr(context.world, "state", {}).get(key, default)})


def _component(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    entity_id = _entity_id(context, inputs.get("entity"))
    component_name = str(inputs["component"])
    component = context.world.get(entity_id, component_name)
    default = inputs.get("default")
    if component is None:
        return NodeResult({"value": default})
    return NodeResult({"value": _read_field(component, str(inputs.get("field") or ""), default)})


def _polar_movement_value(
    context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]
) -> NodeResult:
    """Read one friendly packed-movement number without exposing its component name."""

    return _component(
        context,
        node,
        {**inputs, "component": "polar_movement"},
    )


def _math(operation: str) -> NodeExecutor:
    def execute(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
        a, b = inputs["a"], inputs["b"]
        if operation == "add":
            value = a + b
        elif operation == "subtract":
            value = a - b
        elif operation == "multiply":
            value = a * b
        else:
            if b == 0:
                raise ZeroDivisionError("cannot divide by zero")
            value = a / b
        if not math.isfinite(float(value)):
            raise ArithmeticError("math result is not finite")
        return NodeResult({"result": value})

    return execute


def _compare(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    operation = str(inputs.get("operator", "equal")).lower().replace(" ", "_")
    a, b = inputs["a"], inputs["b"]
    operations: dict[str, Callable[[Any, Any], bool]] = {
        "equal": lambda left, right: left == right,
        "eq": lambda left, right: left == right,
        "==": lambda left, right: left == right,
        "not_equal": lambda left, right: left != right,
        "ne": lambda left, right: left != right,
        "!=": lambda left, right: left != right,
        "less": lambda left, right: left < right,
        "lt": lambda left, right: left < right,
        "<": lambda left, right: left < right,
        "less_equal": lambda left, right: left <= right,
        "lte": lambda left, right: left <= right,
        "<=": lambda left, right: left <= right,
        "greater": lambda left, right: left > right,
        "gt": lambda left, right: left > right,
        ">": lambda left, right: left > right,
        "greater_equal": lambda left, right: left >= right,
        "gte": lambda left, right: left >= right,
        ">=": lambda left, right: left >= right,
    }
    if operation not in operations:
        raise ValueError(f"unknown comparison {operation!r}; use equal, not_equal, less, less_equal, greater or greater_equal")
    return NodeResult({"result": bool(operations[operation](a, b))})


def _set_state(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    key = str(inputs["key"])
    if not key:
        raise ValueError("state key cannot be empty")
    context.world.state[key] = copy.deepcopy(_thaw(inputs["value"]))
    return NodeResult(flow=("out",))


def _set_component(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    entity_id = _entity_id(context, inputs.get("entity"))
    component_name = str(inputs["component"])
    field_path = str(inputs.get("field") or "")
    new_value = copy.deepcopy(_thaw(inputs["value"]))
    ownership_validator = getattr(context.world, "validate_component_write", None)
    if callable(ownership_validator):
        ownership_validator(entity_id, component_name, field_path)
    if not field_path:
        if callable(ownership_validator):
            context.world.add_component(
                entity_id,
                new_value,
                component_name,
                replace_existing=True,
                _ownership_field_path=field_path,
            )
        else:
            context.world.add_component(
                entity_id, new_value, component_name, replace_existing=True
            )
    else:
        component = context.world.require(entity_id, component_name)
        updated = copy.deepcopy(component)
        _write_field(updated, field_path, new_value)
        validate = getattr(updated, "validate", None)
        if callable(validate):
            validate()
        if callable(ownership_validator):
            context.world.add_component(
                entity_id,
                updated,
                component_name,
                replace_existing=True,
                _ownership_field_path=field_path,
            )
        else:
            context.world.add_component(
                entity_id, updated, component_name, replace_existing=True
            )
    return NodeResult(flow=("out",))


def _set_polar_movement(
    context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]
) -> NodeResult:
    """Change one semantic packed-movement number through the normal ownership gate."""

    return _set_component(
        context,
        node,
        {**inputs, "component": "polar_movement"},
    )


def _set_polar_population_visible(
    context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]
) -> NodeResult:
    """Toggle only the render-only copies derived from one Make Many prototype."""

    visible = inputs.get("visible")
    if not isinstance(visible, bool):
        raise ValueError("Show or Hide Extra Copies must be set to Show or Hide.")
    entity_id = _entity_id(context, inputs.get("entity"))
    setter = getattr(context.world, "set_polar_population_copies_visible", None)
    if not callable(setter):
        raise ValueError("Show or Hide Extra Copies needs the Make Many runtime.")
    setter(entity_id, visible)
    return NodeResult(flow=("out",))


def _animation_component(context: GraphContext, entity_id: str, action: str) -> Any:
    try:
        component = context.world.require(entity_id, "transform_animation")
    except (KeyError, LookupError) as error:
        raise ValueError(
            f"{action} target {entity_id!r} has no transform animation."
        ) from error
    return component


def _play_animation(
    context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]
) -> NodeResult:
    entity_id = _entity_id(context, inputs.get("entity"))
    clip = inputs.get("clip")
    if not _is_portable_animation_clip(clip):
        raise ValueError(
            "Play Animation Clip must start with a lowercase letter, use only "
            "lowercase letters, digits, dot, underscore, or hyphen, and be at "
            "most 32 characters."
        )
    restart = inputs.get("restart")
    if not isinstance(restart, bool):
        raise TypeError("Play Animation Restart must be true or false.")
    component = _animation_component(context, entity_id, "Play Animation")
    play = getattr(component, "play", None)
    if not callable(play):
        raise TypeError(
            f"Play Animation target {entity_id!r} has an incompatible transform animation component."
        )
    previous_clip = getattr(component, "active_clip", None)
    play(clip, restart)
    if restart or previous_clip != clip:
        entity = context.world.require(entity_id)
        try:
            entity.position = tuple(component.base_translation)
            entity.rotation = tuple(component.base_rotation)
            entity.scale = tuple(component.base_scale)
        except (AttributeError, TypeError) as error:
            raise TypeError(
                f"Play Animation target {entity_id!r} cannot compose its time-zero pose."
            ) from error
    return NodeResult(flow=("out",))


def _stop_animation(
    context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]
) -> NodeResult:
    entity_id = _entity_id(context, inputs.get("entity"))
    reset = inputs.get("reset")
    if not isinstance(reset, bool):
        raise TypeError("Stop Animation Reset must be true or false.")
    component = _animation_component(context, entity_id, "Stop Animation")
    stop = getattr(component, "stop", None)
    if not callable(stop):
        raise TypeError(
            f"Stop Animation target {entity_id!r} has an incompatible transform animation component."
        )
    stop(reset)
    if reset:
        entity = context.world.require(entity_id)
        reset_pose = getattr(component, "reset_pose", None)
        if callable(reset_pose):
            reset_pose(entity)
        else:
            try:
                entity.position = tuple(component.base_translation)
                entity.rotation = tuple(component.base_rotation)
                entity.scale = tuple(component.base_scale)
            except (AttributeError, TypeError) as error:
                raise TypeError(
                    f"Stop Animation target {entity_id!r} cannot restore its base pose."
                ) from error
    return NodeResult(flow=("out",))


def _emit_event(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    source = context.entity_id if inputs.get("source") in (None, "") else str(inputs["source"])
    target = None if inputs.get("target") in (None, "") else str(inputs["target"])
    payload = inputs.get("payload") or {}
    if not isinstance(payload, Mapping):
        raise TypeError("event payload must be a mapping")
    message = str(inputs["kind"])
    dispatcher = _message_dispatcher(context.world, create=False)
    suppress_trigger_route = (
        dispatcher is not None
        and message in {"trigger_enter", "trigger_exit"}
    )
    if suppress_trigger_route:
        dispatcher.suppress_trigger_routes += 1
    try:
        event = context.world.emit(
            message,
            source=source,
            target=target,
            payload=_thaw(payload),
        )
    finally:
        if suppress_trigger_route:
            dispatcher.suppress_trigger_routes -= 1
    if dispatcher is not None:
        dispatcher.enqueue(message, source, target)
    return NodeResult({"event": event}, ("out",))


def _apply_force(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    context.world.apply_force(_entity_id(context, inputs.get("entity")), inputs["force"])
    return NodeResult(flow=("out",))


def _set_active(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    context.world.entities[_entity_id(context, inputs.get("entity"))].active = bool(inputs["active"])
    return NodeResult(flow=("out",))


def _despawn(context: GraphContext, node: GraphNode, inputs: Mapping[str, Any]) -> NodeResult:
    context.world.despawn(_entity_id(context, inputs.get("entity")))
    return NodeResult(flow=("out",))


def create_builtin_registry() -> NodeRegistry:
    """Create a fresh registry containing the dependency-free core node set."""

    flow_action_ports = (_in_flow(), _out_flow())
    definitions = [
        NodeDefinition(
            "event.ready", "Ready", "Events", "Runs once when this graph binding is attached.",
            (_out_flow(), _out_data("entity", "entity", "The bound entity id, if any.")), _event_ready, event="ready",
        ),
        NodeDefinition(
            "event.message",
            "When Message Heard",
            "Events",
            "Runs after another graph sends the exact saved message name.",
            (
                _in_data("message", "string", required=True),
                _out_flow(),
                _out_data("source", "entity", "The sending entity, or null for a world graph."),
                _out_data("target", "entity", "The addressed entity, or null for a broadcast."),
                _out_data("entity", "entity", "This graph's bound entity, if any."),
            ),
            _event_message,
            {"message": "graph_event"},
            event="message",
        ),
        NodeDefinition(
            "event.tick", "Tick", "Events", "Runs on every fixed GameWorld update.",
            (_out_flow(), _out_data("dt", "number", "Fixed step seconds."), _out_data("tick", "number"), _out_data("entity", "entity")),
            _event_tick, event="tick",
        ),
        NodeDefinition(
            "event.timer",
            "When Timer Rings",
            "Events",
            "Rings after a saved number of seconds; optionally repeats on the binding's active fixed updates.",
            (
                _in_data("seconds", "number", required=True),
                _in_data("repeat", "boolean", required=True),
                _out_flow(),
                _out_data("count", "number", "How many times this timer has rung."),
                _out_data("remaining", "number", "Fixed-step seconds until its next ring."),
                _out_data("entity", "entity", "The bound entity id, if any."),
            ),
            _event_timer,
            {"seconds": 1.0, "repeat": True},
            event="timer",
        ),
        NodeDefinition(
            "event.input_pressed", "Input Pressed", "Events", "Runs on the frame an input action crosses its pressed threshold.",
            (_in_data("action", "string", required=True), _out_flow(), _out_data("action", "string"), _out_data("value", "number"), _out_data("entity", "entity")),
            _event_input_pressed, {"action": "accept"}, event="input_pressed",
        ),
        NodeDefinition(
            "event.trigger_enter", "Trigger Enter", "Events", "Runs once when the active player enters this sensor area.",
            (_out_flow(), _out_data("sensor", "entity", "The sensor area."), _out_data("player", "entity", "The active player."), _out_data("entity", "entity", "The graph's bound sensor, if any.")),
            _event_trigger, event="trigger_enter",
        ),
        NodeDefinition(
            "event.trigger_exit", "Trigger Exit", "Events", "Runs once when the active player leaves this sensor area.",
            (_out_flow(), _out_data("sensor", "entity", "The sensor area."), _out_data("player", "entity", "The active player."), _out_data("entity", "entity", "The graph's bound sensor, if any.")),
            _event_trigger, event="trigger_exit",
        ),
        NodeDefinition(
            "flow.branch", "Branch", "Flow", "Continues through True or False based on a boolean condition.",
            (_in_flow(), _in_data("condition", "boolean", required=True), _out_flow("true"), _out_flow("false")), _branch, {"condition": True},
        ),
        NodeDefinition(
            "value.constant", "Constant", "Values", "Provides a saved literal value.",
            (_out_data("value"),), _constant, {"value": 0},
        ),
        NodeDefinition(
            "value.seeded_number",
            "Repeatable Random Number",
            "Values",
            "Picks the same number for the same World number and Pick number on desktop, web and phone.",
            (
                _in_data("world_number", "number", required=True),
                _in_data("pick_number", "number", required=True),
                _in_data("smallest", "number", required=True),
                _in_data("largest", "number", required=True),
                _out_data("value", "number"),
            ),
            _repeatable_number,
            {"world_number": 1, "pick_number": 0, "smallest": 0.0, "largest": 1.0},
        ),
        NodeDefinition(
            "value.state", "World State", "Values", "Reads a key from GameWorld.state.",
            (_in_data("key", "string", required=True), _in_data("default"), _out_data("value")), _state, {"key": "score", "default": None},
        ),
        NodeDefinition(
            "value.component", "Component Value", "Values", "Reads a component or a dotted component field from an entity.",
            (_in_data("entity", "entity"), _in_data("component", "string", required=True), _in_data("field", "string"), _in_data("default"), _out_data("value")),
            _component, {"entity": None, "component": "transform", "field": "position", "default": None},
        ),
        NodeDefinition(
            "value.polar_movement",
            "Read Movement",
            "Movement",
            (
                "Reads one friendly number from a compact Movement Pattern without "
                "showing component names or packed words."
            ),
            (
                _in_data("entity", "entity"),
                _in_data("field", "string", required=True),
                _in_data("default", "number"),
                _out_data("value", "number"),
            ),
            _polar_movement_value,
            {"entity": None, "field": "radius", "default": 0.0},
        ),
        NodeDefinition(
            "query.nearest_tag",
            "Find Nearby Object",
            "Sensing",
            "Finds the closest active object with a portable gameplay tag inside an inclusive radius.",
            (
                _in_data("origin", "entity"),
                _in_data("tag", "string", required=True),
                _in_data("radius", "number", required=True),
                _out_data("found", "boolean", "True when a matching object was found."),
                _out_data("entity", "entity", "The closest matching object, or null."),
                _out_data("distance", "any", "Binary32 center distance, or null."),
            ),
            _nearest_tag,
            {"origin": None, "tag": "goal", "radius": 10.0},
        ),
        NodeDefinition(
            "query.nearest_in_cone",
            "Find Object Ahead",
            "Sensing",
            (
                "Finds the closest active tagged object inside an inclusive radius "
                "and a saved world-space view cone."
            ),
            (
                _in_data("origin", "entity"),
                _in_data("tag", "string", required=True),
                _in_data("radius", "number", required=True),
                _in_data(
                    "cone",
                    "vector4",
                    required=True,
                    description="World-space Facing XYZ plus the minimum accepted cosine.",
                ),
                _out_data("found", "boolean", "True when a matching object was found."),
                _out_data("entity", "entity", "The closest matching object, or null."),
                _out_data("distance", "any", "Binary32 center distance, or null."),
            ),
            _nearest_in_cone,
            {"origin": None, "tag": "goal", "radius": 10.0, "cone": (0.0, 0.0, -1.0, 0.7071067690849304)},
        ),
        NodeDefinition(
            "math.add", "Add", "Math", "Adds two numbers.",
            (_in_data("a", "number", required=True), _in_data("b", "number", required=True), _out_data("result", "number")), _math("add"), {"a": 0, "b": 0},
        ),
        NodeDefinition(
            "math.subtract", "Subtract", "Math", "Subtracts B from A.",
            (_in_data("a", "number", required=True), _in_data("b", "number", required=True), _out_data("result", "number")), _math("subtract"), {"a": 0, "b": 0},
        ),
        NodeDefinition(
            "math.multiply", "Multiply", "Math", "Multiplies two numbers.",
            (_in_data("a", "number", required=True), _in_data("b", "number", required=True), _out_data("result", "number")), _math("multiply"), {"a": 1, "b": 1},
        ),
        NodeDefinition(
            "math.divide", "Divide", "Math", "Divides A by B and reports division by zero clearly.",
            (_in_data("a", "number", required=True), _in_data("b", "number", required=True), _out_data("result", "number")), _math("divide"), {"a": 0, "b": 1},
        ),
        NodeDefinition(
            "compare", "Compare", "Logic", "Compares A and B using the selected operator.",
            (_in_data("a", required=True), _in_data("b", required=True), _in_data("operator", "string"), _out_data("result", "boolean")),
            _compare, {"a": 0, "b": 0, "operator": "equal"},
        ),
        NodeDefinition(
            "action.set_state", "Set World State", "Actions", "Stores a value in GameWorld.state.",
            flow_action_ports + (_in_data("key", "string", required=True), _in_data("value", required=True)), _set_state, {"key": "score", "value": 0},
        ),
        NodeDefinition(
            "action.set_component", "Set Component", "Actions", "Replaces a component or updates one dotted field on a copied component.",
            flow_action_ports + (_in_data("entity", "entity"), _in_data("component", "string", required=True), _in_data("field", "string"), _in_data("value", required=True)),
            _set_component, {"entity": None, "component": "transform", "field": "position", "value": [0, 0]},
        ),
        NodeDefinition(
            "action.set_polar_movement",
            "Change Movement",
            "Movement",
            (
                "Changes one friendly number in a compact Movement Pattern and "
                "rebuilds the matching packed pose or motion immediately."
            ),
            flow_action_ports
            + (
                _in_data("entity", "entity"),
                _in_data("field", "string", required=True),
                _in_data("value", "number", required=True),
            ),
            _set_polar_movement,
            {"entity": None, "field": "turns_per_second", "value": 0.25},
        ),
        NodeDefinition(
            "action.set_polar_population_visible",
            "Show or Hide Extra Copies",
            "Looks",
            (
                "Shows or hides only the extra display copies made by Make Many. "
                "The real object stays visible and remains the Logic Blocks owner."
            ),
            flow_action_ports
            + (
                _in_data("entity", "entity"),
                _in_data("visible", "boolean", required=True),
            ),
            _set_polar_population_visible,
            {"entity": None, "visible": True},
        ),
        NodeDefinition(
            "action.play_animation",
            "Play Animation",
            "Actions",
            "Starts a named transform-animation clip on an animated object.",
            flow_action_ports
            + (
                _in_data("entity", "entity"),
                _in_data("clip", "string", required=True),
                _in_data("restart", "boolean", required=True),
            ),
            _play_animation,
            {"entity": None, "clip": "main", "restart": True},
        ),
        NodeDefinition(
            "action.stop_animation",
            "Stop Animation",
            "Actions",
            "Stops an object's transform animation and optionally restores its authored pose.",
            flow_action_ports
            + (
                _in_data("entity", "entity"),
                _in_data("reset", "boolean", required=True),
            ),
            _stop_animation,
            {"entity": None, "reset": True},
        ),
        NodeDefinition(
            "action.emit_event", "Emit Event", "Actions", "Emits a normal GameWorld event for audio, UI or gameplay listeners.",
            flow_action_ports + (_in_data("kind", "string", required=True), _in_data("source", "entity"), _in_data("target", "entity"), _in_data("payload", "mapping"), _out_data("event")),
            _emit_event, {"kind": "graph_event", "source": None, "target": None, "payload": {}},
        ),
        NodeDefinition(
            "action.apply_force", "Apply Force", "Physics", "Pushes a 2D body in XY or a 3D body across its XZ ground plane.",
            flow_action_ports + (_in_data("entity", "entity"), _in_data("force", "vector2", required=True)), _apply_force, {"entity": None, "force": [0, 0]},
        ),
        NodeDefinition(
            "action.set_active", "Set Active", "Actions", "Enables or disables an entity for queries and simulation systems.",
            flow_action_ports + (_in_data("entity", "entity"), _in_data("active", "boolean", required=True)), _set_active, {"entity": None, "active": True},
        ),
        NodeDefinition(
            "action.despawn", "Despawn", "Actions", "Removes the chosen entity (deferred safely while GameWorld is stepping).",
            flow_action_ports + (_in_data("entity", "entity"),), _despawn, {"entity": None},
        ),
    ]
    return NodeRegistry(definitions)


BUILTIN_NODE_REGISTRY = create_builtin_registry()
DEFAULT_NODE_REGISTRY = BUILTIN_NODE_REGISTRY


__all__ = [
    "BUILTIN_NODE_REGISTRY",
    "DEFAULT_NODE_REGISTRY",
    "ExecutionResult",
    "FrozenDict",
    "GraphBinding",
    "GraphContext",
    "GraphCycleError",
    "GraphEventLimitError",
    "GraphExecutionError",
    "GraphLink",
    "GraphNode",
    "GraphNodeExecutionError",
    "GraphRuntime",
    "GraphStepLimitError",
    "GraphTotalStepLimitError",
    "GraphValidationError",
    "GraphValidationIssue",
    "NO_DEFAULT",
    "NodeDefinition",
    "NodeRegistry",
    "NodeResult",
    "PortDefinition",
    "PortDirection",
    "PortKind",
    "PORTABLE_QUERY_TAGS",
    "PORTABLE_ANIMATION_CLIP_PATTERN",
    "PORTABLE_MESSAGE_PATTERN",
    "GRAPH_MESSAGE_MAX_EVENTS",
    "GRAPH_MESSAGE_MAX_STEPS",
    "TraceEntry",
    "VisualGraph",
    "attach_graph",
    "create_builtin_registry",
    "run_ready_batch",
]
