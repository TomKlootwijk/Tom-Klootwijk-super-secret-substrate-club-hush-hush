"""Compact, deterministic Android bytecode for :mod:`ugts_kc3.visual_graph`.

The authoring graph remains JSON.  This module deliberately exports only the
portable subset implemented by the dependency-free C++ runtime.  Rejecting an
unsupported node, literal, or component path here is preferable to shipping a
game which behaves differently from the editor.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import struct
from typing import Any, Iterable, Mapping, Sequence

from .mobile3d import Mobile3DProject
from .visual_graph import (
    BUILTIN_NODE_REGISTRY,
    GraphNode,
    PortDirection,
    PortKind,
    VisualGraph,
)


GRAPH_PACK_MAGIC = b"KCVG001\0"
GRAPH_PACK_ENDIAN = 0x01020304
GRAPH_PACK_VERSION = 1
GRAPH_PACK_ASSET = "visual_graphs.kcvg"

MAX_GRAPHS = 256
MAX_BINDINGS = 4096
MAX_NODES_PER_GRAPH = 1024
MAX_TOTAL_NODES = 8192
MAX_LINKS_PER_GRAPH = 4096
MAX_INPUT_REFS = 65535
MAX_FLOW_TARGETS = 65535
MAX_VALUES = 65535
MAX_STRINGS = 65535
MAX_STATE_KEYS = 4096
MAX_STRING_BYTES = 1024 * 1024
MAX_PACK_BYTES = 8 * 1024 * 1024
GRAPH_MAX_STEPS = 1024


class GraphPackError(ValueError):
    """A graph cannot be represented truthfully by the Android VM."""


# These numbers are a file-format ABI.  Add new opcodes; never reorder old ones.
NODE_OPCODES: dict[str, int] = {
    "event.ready": 1,
    "event.tick": 2,
    "event.input_pressed": 3,
    "flow.branch": 4,
    "value.constant": 5,
    "value.state": 6,
    "value.component": 7,
    "math.add": 8,
    "math.subtract": 9,
    "math.multiply": 10,
    "math.divide": 11,
    "compare": 12,
    "action.set_state": 13,
    "action.set_component": 14,
    "action.emit_event": 15,
    "action.set_active": 16,
    "action.despawn": 17,
}
OPCODE_TYPES = {opcode: type_id for type_id, opcode in NODE_OPCODES.items()}

NODE_INPUTS: dict[str, tuple[str, ...]] = {
    "event.ready": (),
    "event.tick": (),
    "event.input_pressed": ("action",),
    "flow.branch": ("condition",),
    # Constant's saved value is an internal VM input even though it is an output
    # property in the editor registry.
    "value.constant": ("value",),
    "value.state": ("key", "default"),
    "value.component": ("entity", "component", "field", "default"),
    "math.add": ("a", "b"),
    "math.subtract": ("a", "b"),
    "math.multiply": ("a", "b"),
    "math.divide": ("a", "b"),
    "compare": ("a", "b", "operator"),
    "action.set_state": ("key", "value"),
    "action.set_component": ("entity", "component", "field", "value"),
    "action.emit_event": ("kind", "source", "target", "payload"),
    "action.set_active": ("entity", "active"),
    "action.despawn": ("entity",),
}

NODE_DATA_OUTPUTS: dict[str, tuple[str, ...]] = {
    "event.ready": ("entity",),
    "event.tick": ("dt", "tick", "entity"),
    "event.input_pressed": ("action", "value", "entity"),
    "flow.branch": (),
    "value.constant": ("value",),
    "value.state": ("value",),
    "value.component": ("value",),
    "math.add": ("result",),
    "math.subtract": ("result",),
    "math.multiply": ("result",),
    "math.divide": ("result",),
    "compare": ("result",),
    "action.set_state": (),
    "action.set_component": (),
    # The Python event record is intentionally not faked on Android.  Emitting
    # and logging the event is supported, but consuming its record is not.
    "action.emit_event": ("event",),
    "action.set_active": (),
    "action.despawn": (),
}

NODE_FLOW_OUTPUTS: dict[str, tuple[str, ...]] = {
    "event.ready": ("out",),
    "event.tick": ("out",),
    "event.input_pressed": ("out",),
    "flow.branch": ("true", "false"),
    "value.constant": (),
    "value.state": (),
    "value.component": (),
    "math.add": (),
    "math.subtract": (),
    "math.multiply": (),
    "math.divide": (),
    "compare": (),
    "action.set_state": ("out",),
    "action.set_component": ("out",),
    "action.emit_event": ("out",),
    "action.set_active": ("out",),
    "action.despawn": ("out",),
}


VALUE_NULL = 0
VALUE_BOOL = 1
VALUE_NUMBER = 2
VALUE_STRING = 3
VALUE_VEC3 = 4
VALUE_VEC4 = 5
VALUE_TAG_NAMES = {
    VALUE_NULL: "null",
    VALUE_BOOL: "boolean",
    VALUE_NUMBER: "number",
    VALUE_STRING: "string",
    VALUE_VEC3: "vector3",
    VALUE_VEC4: "vector4",
}


@dataclass(frozen=True, slots=True)
class _ValueSpec:
    tag: int
    payload: Any = None

    def sort_key(self) -> bytes:
        if self.tag == VALUE_NULL:
            body = b""
        elif self.tag == VALUE_BOOL:
            body = bytes((1 if self.payload else 0,))
        elif self.tag == VALUE_NUMBER:
            body = struct.pack("<f", self.payload)
        elif self.tag == VALUE_STRING:
            body = self.payload.encode("utf-8")
        else:
            body = b"".join(struct.pack("<f", value) for value in self.payload)
        return bytes((self.tag,)) + body


@dataclass(frozen=True, slots=True)
class _InputSpec:
    literal: _ValueSpec | None = None
    source_node: int | None = None
    source_output: int = 0


@dataclass(frozen=True, slots=True)
class _NodeSpec:
    type_id: str
    inputs: tuple[_InputSpec, ...]
    flow_zero: tuple[int, ...]
    flow_one: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _GraphSpec:
    id: str
    nodes: tuple[_NodeSpec, ...]
    state_keys: tuple[str, ...]


class _Writer:
    def __init__(self) -> None:
        self.data = bytearray()

    def raw(self, value: bytes) -> None:
        self.data.extend(value)

    def u8(self, value: int) -> None:
        self.raw(struct.pack("<B", value))

    def u16(self, value: int) -> None:
        self.raw(struct.pack("<H", value))

    def u32(self, value: int) -> None:
        self.raw(struct.pack("<I", value))

    def f32(self, value: float) -> None:
        self.raw(struct.pack("<f", value))


def _fail(graph_id: str, node: GraphNode | None, message: str) -> GraphPackError:
    where = f"visual graph {graph_id!r}"
    if node is not None:
        where += f" node {node.id!r} ({node.type})"
    return GraphPackError(f"{where}: {message}")


def _f32(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GraphPackError(f"{path} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise GraphPackError(f"{path} must be finite")
    try:
        packed = struct.pack("<f", value)
    except (OverflowError, struct.error) as error:
        raise GraphPackError(f"{path} is outside Android's finite float32 range") from error
    result = struct.unpack("<f", packed)[0]
    if not math.isfinite(result):
        raise GraphPackError(f"{path} is outside Android's finite float32 range")
    return 0.0 if result == 0.0 else result


def _value_spec(value: Any, path: str) -> _ValueSpec:
    if value is None:
        return _ValueSpec(VALUE_NULL)
    if isinstance(value, bool):
        return _ValueSpec(VALUE_BOOL, value)
    if isinstance(value, (int, float)):
        return _ValueSpec(VALUE_NUMBER, _f32(value, path))
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        if len(encoded) > 65535:
            raise GraphPackError(f"{path} is longer than 65535 UTF-8 bytes")
        return _ValueSpec(VALUE_STRING, value)
    if isinstance(value, (tuple, list)) and len(value) in (3, 4):
        numbers = tuple(_f32(item, f"{path}[{index}]") for index, item in enumerate(value))
        return _ValueSpec(VALUE_VEC3 if len(numbers) == 3 else VALUE_VEC4, numbers)
    kind = type(value).__name__
    raise GraphPackError(
        f"{path} uses unsupported Android literal type {kind}; use null, boolean, "
        "number, text, Vector3, or Vector4"
    )


def _graphs_from_project(project: Mobile3DProject) -> tuple[VisualGraph, ...]:
    raw = project.metadata.get("visual_graphs")
    if raw is None:
        return ()
    entries: list[tuple[str | None, Any]] = []
    if isinstance(raw, VisualGraph):
        entries.append((None, raw))
    elif isinstance(raw, Mapping):
        if "nodes" in raw or "links" in raw or raw.get("schema") == VisualGraph.SCHEMA:
            entries.append((None, raw))
        else:
            entries.extend((str(key), value) for key, value in raw.items())
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        entries.extend((None, value) for value in raw)
    else:
        raise GraphPackError(
            "project metadata['visual_graphs'] must be a list of graph documents "
            "or a graph-id mapping"
        )

    result: list[VisualGraph] = []
    ids: set[str] = set()
    for keyed_id, item in entries:
        if isinstance(item, VisualGraph):
            graph = item
        elif isinstance(item, Mapping):
            document = dict(item)
            if keyed_id is not None and "id" not in document:
                document["id"] = keyed_id
            try:
                graph = VisualGraph.from_dict(document)
            except (KeyError, TypeError, ValueError) as error:
                label = keyed_id or document.get("id", "<unknown>")
                raise GraphPackError(f"visual graph {label!r} could not be loaded: {error}") from error
        else:
            raise GraphPackError(
                f"visual graph entry must be a graph document, not {type(item).__name__}"
            )
        if keyed_id is not None and graph.id != keyed_id:
            raise GraphPackError(
                f"visual graph mapping key {keyed_id!r} does not match document id {graph.id!r}"
            )
        if graph.id in ids:
            raise GraphPackError(f"visual graph id {graph.id!r} is used more than once")
        ids.add(graph.id)
        result.append(graph)
    if len(result) > MAX_GRAPHS:
        raise GraphPackError(f"Android graph pack supports at most {MAX_GRAPHS} graphs")
    return tuple(sorted(result, key=lambda graph: graph.id))


def _binding_ids(value: Any, node_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        graph_id = value.strip()
        if not graph_id:
            raise GraphPackError(f"scene node {node_id!r} has an empty visual_graph binding")
        return (graph_id,)
    if isinstance(value, Mapping):
        if value.get("enabled", True) is False:
            return ()
        choices = [value[key] for key in ("graph", "graph_id", "id") if key in value]
        if len(choices) != 1:
            raise GraphPackError(
                f"scene node {node_id!r} visual_graph mapping needs exactly one graph id"
            )
        return _binding_ids(choices[0], node_id)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        result: list[str] = []
        for item in value:
            result.extend(_binding_ids(item, node_id))
        return tuple(result)
    raise GraphPackError(
        f"scene node {node_id!r} visual_graph binding must be a graph id, not {type(value).__name__}"
    )


def _bindings_from_project(
    project: Mobile3DProject, graph_ids: set[str]
) -> tuple[tuple[int, str], ...]:
    result: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for node_index, scene_node in enumerate(project.nodes):
        if "visual_graph" not in scene_node.metadata:
            continue
        for graph_id in _binding_ids(scene_node.metadata.get("visual_graph"), scene_node.id):
            if graph_id not in graph_ids:
                raise GraphPackError(
                    f"scene node {scene_node.id!r} binds missing visual graph {graph_id!r}"
                )
            pair = (node_index, graph_id)
            if pair in seen:
                raise GraphPackError(
                    f"scene node {scene_node.id!r} binds visual graph {graph_id!r} more than once"
                )
            seen.add(pair)
            result.append(pair)
    if len(result) > MAX_BINDINGS:
        raise GraphPackError(f"Android graph pack supports at most {MAX_BINDINGS} bindings")
    return tuple(sorted(result, key=lambda item: (item[0], item[1])))


def _raw_literal(node: GraphNode, name: str) -> Any:
    if name in node.properties:
        return node.properties[name]
    definition = BUILTIN_NODE_REGISTRY.definition(node.type)
    if name in definition.default_properties:
        return definition.default_properties[name]
    port = definition.port(PortDirection.INPUT, name)
    if port is not None and port.has_default:
        return port.default
    raise KeyError(name)


_COMPARE_ALIASES = {
    "equal": "equal", "eq": "equal", "==": "equal",
    "not_equal": "not_equal", "ne": "not_equal", "!=": "not_equal",
    "less": "less", "lt": "less", "<": "less",
    "less_equal": "less_equal", "lte": "less_equal", "<=": "less_equal",
    "greater": "greater", "gt": "greater", ">": "greater",
    "greater_equal": "greater_equal", "gte": "greater_equal", ">=": "greater_equal",
}


def _component_result_tag(component: str, field: str) -> int:
    if component == "transform":
        whole = {
            "position": VALUE_VEC3,
            "translation": VALUE_VEC3,
            "scale": VALUE_VEC3,
            "rotation": VALUE_VEC4,
        }
        if field in whole:
            return whole[field]
        parts = field.split(".")
        if len(parts) == 2 and parts[0] in whole:
            valid = {"x", "y", "z", "0", "1", "2"}
            if parts[0] == "rotation":
                valid |= {"w", "3"}
            if parts[1] in valid:
                return VALUE_NUMBER
    elif component in {"velocity", "angular_velocity"}:
        if field == "":
            return VALUE_VEC3
        if field in {"x", "y", "z", "0", "1", "2"}:
            return VALUE_NUMBER
    elif component in {"alive", "active"} and field == "":
        return VALUE_BOOL
    raise GraphPackError(
        "Android NodeData supports transform.position/translation/scale (Vector3), "
        "transform.rotation (Vector4), their numeric fields, velocity/angular_velocity "
        "and fields, plus alive/active"
    )


def _literal_text(
    graph_id: str, node: GraphNode, name: str, spec: _InputSpec
) -> str:
    if spec.source_node is not None or spec.literal is None or spec.literal.tag != VALUE_STRING:
        raise _fail(graph_id, node, f"input {name!r} must be saved as text, not connected")
    return str(spec.literal.payload)


def _compile_graph(project: Mobile3DProject, graph: VisualGraph) -> _GraphSpec:
    try:
        graph.validate(BUILTIN_NODE_REGISTRY)
    except ValueError as error:
        raise GraphPackError(f"visual graph {graph.id!r} is invalid: {error}") from error
    if len(graph.nodes) > MAX_NODES_PER_GRAPH:
        raise GraphPackError(
            f"visual graph {graph.id!r} has {len(graph.nodes)} nodes; Android allows {MAX_NODES_PER_GRAPH}"
        )
    if len(graph.links) > MAX_LINKS_PER_GRAPH:
        raise GraphPackError(
            f"visual graph {graph.id!r} has {len(graph.links)} links; Android allows {MAX_LINKS_PER_GRAPH}"
        )
    for node in graph.nodes:
        if node.type not in NODE_OPCODES:
            raise _fail(
                graph.id,
                node,
                "is not in the portable Android subset (action.apply_force is editor/2D only)",
            )
        unknown = sorted(set(node.properties) - set(NODE_INPUTS[node.type]))
        if unknown:
            raise _fail(graph.id, node, f"unsupported properties: {', '.join(unknown)}")

    order = graph.data_order(BUILTIN_NODE_REGISTRY)
    node_map = {node.id: node for node in graph.nodes}
    local = {node_id: index for index, node_id in enumerate(order)}
    incoming: dict[tuple[str, str], Any] = {}
    outgoing: dict[tuple[str, str], list[Any]] = {}
    for link in graph.links:
        source = node_map[link.source_node]
        definition = BUILTIN_NODE_REGISTRY.definition(source.type)
        port = definition.port(PortDirection.OUTPUT, link.source_port)
        assert port is not None
        if port.kind is PortKind.DATA:
            if source.type == "action.emit_event" and link.source_port == "event":
                raise _fail(
                    graph.id,
                    source,
                    "the emitted Python event record cannot be consumed on Android; use the out flow",
                )
            incoming[(link.target_node, link.target_port)] = link
        else:
            outgoing.setdefault((link.source_node, link.source_port), []).append(link)

    scene_ids = {node.id for node in project.nodes}
    state_keys: set[str] = set()
    compiled: list[_NodeSpec] = []
    for node_id in order:
        node = node_map[node_id]
        input_specs: list[_InputSpec] = []
        input_names = NODE_INPUTS[node.type]
        for name in input_names:
            link = incoming.get((node.id, name))
            if link is not None:
                source_node = node_map[link.source_node]
                try:
                    output = NODE_DATA_OUTPUTS[source_node.type].index(link.source_port)
                except ValueError as error:
                    raise _fail(graph.id, source_node, f"unsupported data output {link.source_port!r}") from error
                input_specs.append(_InputSpec(source_node=local[source_node.id], source_output=output))
                continue
            try:
                raw = _raw_literal(node, name)
            except KeyError as error:
                raise _fail(graph.id, node, f"input {name!r} has no link or saved value") from error
            if node.type == "action.emit_event" and name == "payload":
                if raw is not None and not (isinstance(raw, Mapping) and len(raw) == 0):
                    raise _fail(
                        graph.id,
                        node,
                        "Android emit_event currently supports only an empty payload; encode data in state/components",
                    )
                literal = _ValueSpec(VALUE_NULL)
            else:
                try:
                    literal = _value_spec(raw, f"visual graph {graph.id!r} node {node.id!r} input {name!r}")
                except GraphPackError as error:
                    raise _fail(graph.id, node, str(error)) from error
            input_specs.append(_InputSpec(literal=literal))

        by_name = dict(zip(input_names, input_specs))
        if node.type == "event.input_pressed":
            if not _literal_text(graph.id, node, "action", by_name["action"]).strip():
                raise _fail(graph.id, node, "input action must not be empty")
        if node.type in {"value.state", "action.set_state"}:
            key = _literal_text(graph.id, node, "key", by_name["key"])
            if not key:
                raise _fail(graph.id, node, "state key must not be empty")
            state_keys.add(key)
        if node.type == "compare":
            operation = _literal_text(graph.id, node, "operator", by_name["operator"])
            canonical = _COMPARE_ALIASES.get(operation.lower().replace(" ", "_"))
            if canonical is None:
                raise _fail(
                    graph.id,
                    node,
                    "comparison must be equal, not_equal, less, less_equal, greater, or greater_equal",
                )
            index = input_names.index("operator")
            input_specs[index] = _InputSpec(literal=_ValueSpec(VALUE_STRING, canonical))
            by_name["operator"] = input_specs[index]
        if node.type in {"value.component", "action.set_component"}:
            component = _literal_text(graph.id, node, "component", by_name["component"])
            field = _literal_text(graph.id, node, "field", by_name["field"])
            try:
                expected_tag = _component_result_tag(component, field)
            except GraphPackError as error:
                raise _fail(graph.id, node, str(error)) from error
            if node.type == "action.set_component":
                value = by_name["value"]
                if value.literal is not None and value.literal.tag != expected_tag:
                    raise _fail(
                        graph.id,
                        node,
                        f"{component}.{field or '<whole>'} needs {VALUE_TAG_NAMES[expected_tag]}, "
                        f"not {VALUE_TAG_NAMES[value.literal.tag]}",
                    )
        if node.type == "action.emit_event":
            if by_name["payload"].source_node is not None:
                raise _fail(graph.id, node, "Android emit_event payload cannot be connected")
        for name, spec in zip(input_names, input_specs):
            if name not in {"entity", "source", "target"} or spec.literal is None:
                continue
            if spec.literal.tag == VALUE_STRING and spec.literal.payload:
                if spec.literal.payload not in scene_ids:
                    raise _fail(
                        graph.id,
                        node,
                        f"entity input {name!r} refers to missing scene node {spec.literal.payload!r}",
                    )
            elif spec.literal.tag != VALUE_NULL:
                raise _fail(graph.id, node, f"entity input {name!r} must be a scene-node id or null")

        flow_groups: list[tuple[int, ...]] = []
        for port_name in NODE_FLOW_OUTPUTS[node.type]:
            links = outgoing.get((node.id, port_name), ())
            ranked = sorted(
                links,
                key=lambda link: (
                    local[link.target_node], link.target_node, link.target_port, link.id,
                ),
            )
            flow_groups.append(tuple(local[link.target_node] for link in ranked))
        zero = flow_groups[0] if flow_groups else ()
        one = flow_groups[1] if len(flow_groups) > 1 else ()
        compiled.append(_NodeSpec(node.type, tuple(input_specs), zero, one))
    return _GraphSpec(graph.id, tuple(compiled), tuple(sorted(state_keys)))


def compile_graph_pack_bytes(project: Mobile3DProject) -> bytes:
    """Compile project graph metadata, returning ``b''`` when no graphs exist."""

    project.validate()
    graphs = _graphs_from_project(project)
    graph_ids = {graph.id for graph in graphs}
    bindings = _bindings_from_project(project, graph_ids)
    if not graphs:
        if bindings:
            raise GraphPackError("visual-graph bindings exist but the project has no visual_graphs")
        return b""
    graph_specs = tuple(_compile_graph(project, graph) for graph in graphs)
    total_nodes = sum(len(graph.nodes) for graph in graph_specs)
    if total_nodes > MAX_TOTAL_NODES:
        raise GraphPackError(f"Android graph pack supports at most {MAX_TOTAL_NODES} total nodes")

    literals = {
        spec.literal
        for graph in graph_specs
        for node in graph.nodes
        for spec in node.inputs
        if spec.literal is not None
    }
    values = tuple(sorted(literals, key=_ValueSpec.sort_key))
    if len(values) > MAX_VALUES:
        raise GraphPackError(f"Android graph pack supports at most {MAX_VALUES} distinct values")
    value_index = {value: index for index, value in enumerate(values)}

    state_keys = tuple(sorted({key for graph in graph_specs for key in graph.state_keys}))
    if len(state_keys) > MAX_STATE_KEYS:
        raise GraphPackError(f"Android graph pack supports at most {MAX_STATE_KEYS} state keys")
    strings_set = {graph.id for graph in graph_specs} | set(state_keys)
    strings_set.update(value.payload for value in values if value.tag == VALUE_STRING)
    strings = tuple(sorted(strings_set, key=lambda value: value.encode("utf-8")))
    if len(strings) > MAX_STRINGS:
        raise GraphPackError(f"Android graph pack supports at most {MAX_STRINGS} strings")
    string_bytes = sum(len(value.encode("utf-8")) for value in strings)
    if string_bytes > MAX_STRING_BYTES:
        raise GraphPackError(
            f"Android graph strings use {string_bytes} bytes; limit is {MAX_STRING_BYTES}"
        )
    string_index = {value: index for index, value in enumerate(strings)}

    input_count = sum(len(node.inputs) for graph in graph_specs for node in graph.nodes)
    flow_count = sum(
        len(node.flow_zero) + len(node.flow_one)
        for graph in graph_specs for node in graph.nodes
    )
    if input_count > MAX_INPUT_REFS:
        raise GraphPackError(f"Android graph pack supports at most {MAX_INPUT_REFS} input references")
    if flow_count > MAX_FLOW_TARGETS:
        raise GraphPackError(f"Android graph pack supports at most {MAX_FLOW_TARGETS} flow targets")

    graph_index = {graph.id: index for index, graph in enumerate(graph_specs)}
    writer = _Writer()
    writer.raw(GRAPH_PACK_MAGIC)
    writer.u32(GRAPH_PACK_ENDIAN)
    writer.u32(GRAPH_PACK_VERSION)
    for count in (
        len(strings), len(values), len(graph_specs), len(bindings), total_nodes,
        input_count, flow_count, len(state_keys),
    ):
        writer.u32(count)

    for value in strings:
        encoded = value.encode("utf-8")
        writer.u16(len(encoded))
        writer.raw(encoded)
    for value in values:
        writer.u8(value.tag)
        if value.tag == VALUE_BOOL:
            writer.u8(1 if value.payload else 0)
        elif value.tag == VALUE_NUMBER:
            writer.f32(value.payload)
        elif value.tag == VALUE_STRING:
            writer.u32(string_index[value.payload])
        elif value.tag in {VALUE_VEC3, VALUE_VEC4}:
            for item in value.payload:
                writer.f32(item)
    for key in state_keys:
        writer.u32(string_index[key])

    node_start = 0
    for graph in graph_specs:
        writer.u32(string_index[graph.id])
        writer.u32(node_start)
        writer.u16(len(graph.nodes))
        writer.u16(GRAPH_MAX_STEPS)
        node_start += len(graph.nodes)
    for scene_node, graph_id in bindings:
        writer.u32(graph_index[graph_id])
        writer.u32(scene_node)

    input_start = 0
    flow_start = 0
    for graph in graph_specs:
        for node in graph.nodes:
            writer.u32(input_start)
            writer.u32(flow_start)
            writer.u16(len(node.inputs))
            writer.u16(len(node.flow_zero))
            writer.u16(len(node.flow_one))
            writer.u8(NODE_OPCODES[node.type_id])
            writer.u8(0)
            input_start += len(node.inputs)
            flow_start += len(node.flow_zero) + len(node.flow_one)
    for graph in graph_specs:
        for node in graph.nodes:
            for spec in node.inputs:
                if spec.literal is not None:
                    token = value_index[spec.literal]
                else:
                    assert spec.source_node is not None
                    if spec.source_node > 0xFFFF or spec.source_output > 0xFF:
                        raise GraphPackError("internal graph reference exceeds packed range")
                    token = (1 << 30) | (spec.source_output << 16) | spec.source_node
                writer.u32(token)
    for graph in graph_specs:
        for node in graph.nodes:
            for target in node.flow_zero + node.flow_one:
                writer.u16(target)

    data = bytes(writer.data)
    if len(data) > MAX_PACK_BYTES:
        raise GraphPackError(f"Android graph pack is {len(data)} bytes; limit is {MAX_PACK_BYTES}")
    return data


def write_graph_pack(project: Mobile3DProject, path: str | Path) -> Path | None:
    """Write the graph asset, or return ``None`` for a graph-free project."""

    data = compile_graph_pack_bytes(project)
    if not data:
        return None
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return output


class _Reader:
    def __init__(self, data: bytes):
        self.data = memoryview(data)
        self.offset = 0

    def raw(self, count: int) -> bytes:
        if count < 0 or self.offset + count > len(self.data):
            raise GraphPackError("truncated visual-graph pack")
        result = self.data[self.offset:self.offset + count].tobytes()
        self.offset += count
        return result

    def u8(self) -> int:
        return struct.unpack("<B", self.raw(1))[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.raw(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.raw(4))[0]

    def f32(self) -> float:
        value = struct.unpack("<f", self.raw(4))[0]
        if not math.isfinite(value):
            raise GraphPackError("visual-graph pack contains a non-finite number")
        return value


def inspect_graph_pack(data_or_path: bytes | str | Path) -> dict[str, Any]:
    """Validate a packed graph completely and return a JSON-friendly summary."""

    data = Path(data_or_path).read_bytes() if isinstance(data_or_path, (str, Path)) else data_or_path
    if not isinstance(data, bytes):
        data = bytes(data)
    reader = _Reader(data)
    if reader.raw(8) != GRAPH_PACK_MAGIC:
        raise GraphPackError("visual-graph pack magic mismatch")
    if reader.u32() != GRAPH_PACK_ENDIAN:
        raise GraphPackError("visual-graph pack endian marker mismatch")
    if reader.u32() != GRAPH_PACK_VERSION:
        raise GraphPackError("unsupported visual-graph pack version")
    counts = tuple(reader.u32() for _ in range(8))
    (
        string_count, value_count, graph_count, binding_count, node_count,
        input_count, flow_count, state_count,
    ) = counts
    limits = (
        (string_count, MAX_STRINGS, "strings"),
        (value_count, MAX_VALUES, "values"),
        (graph_count, MAX_GRAPHS, "graphs"),
        (binding_count, MAX_BINDINGS, "bindings"),
        (node_count, MAX_TOTAL_NODES, "nodes"),
        (input_count, MAX_INPUT_REFS, "inputs"),
        (flow_count, MAX_FLOW_TARGETS, "flows"),
        (state_count, MAX_STATE_KEYS, "state keys"),
    )
    for count, limit, label in limits:
        if count > limit:
            raise GraphPackError(f"visual-graph pack exceeds {label} limit")
    strings = []
    for _ in range(string_count):
        try:
            strings.append(reader.raw(reader.u16()).decode("utf-8"))
        except UnicodeDecodeError as error:
            raise GraphPackError("visual-graph pack string is not valid UTF-8") from error
    if strings != sorted(set(strings), key=lambda value: value.encode("utf-8")):
        raise GraphPackError("visual-graph pack string table is not canonical")

    values: list[tuple[int, Any]] = []
    for _ in range(value_count):
        tag = reader.u8()
        if tag == VALUE_NULL:
            payload: Any = None
        elif tag == VALUE_BOOL:
            raw = reader.u8()
            if raw > 1:
                raise GraphPackError("visual-graph boolean is invalid")
            payload = bool(raw)
        elif tag == VALUE_NUMBER:
            payload = reader.f32()
        elif tag == VALUE_STRING:
            index = reader.u32()
            if index >= string_count:
                raise GraphPackError("visual-graph value has an invalid string reference")
            payload = strings[index]
        elif tag in {VALUE_VEC3, VALUE_VEC4}:
            payload = tuple(reader.f32() for _ in range(3 if tag == VALUE_VEC3 else 4))
        else:
            raise GraphPackError(f"visual-graph value has unknown tag {tag}")
        values.append((tag, payload))
    canonical_values = sorted(
        {_ValueSpec(tag, payload) for tag, payload in values}, key=_ValueSpec.sort_key
    )
    if len(canonical_values) != len(values) or [
        _ValueSpec(tag, payload) for tag, payload in values
    ] != canonical_values:
        raise GraphPackError("visual-graph value table is not canonical")

    state_indexes = [reader.u32() for _ in range(state_count)]
    if any(index >= string_count for index in state_indexes):
        raise GraphPackError("visual-graph state key has an invalid string reference")
    state_keys = [strings[index] for index in state_indexes]
    if state_keys != sorted(set(state_keys)):
        raise GraphPackError("visual-graph state key table is not canonical")

    graphs = []
    expected_start = 0
    for _ in range(graph_count):
        id_index, start = reader.u32(), reader.u32()
        count, max_steps = reader.u16(), reader.u16()
        if id_index >= string_count or start != expected_start or count > MAX_NODES_PER_GRAPH:
            raise GraphPackError("visual-graph table has an invalid node range")
        if max_steps < 1 or max_steps > GRAPH_MAX_STEPS:
            raise GraphPackError("visual-graph step limit is invalid")
        graphs.append({"id": strings[id_index], "node_start": start, "node_count": count, "max_steps": max_steps})
        expected_start += count
    if expected_start != node_count:
        raise GraphPackError("visual-graph node count does not match graph ranges")
    if [item["id"] for item in graphs] != sorted({item["id"] for item in graphs}):
        raise GraphPackError("visual-graph table is not sorted by unique id")

    bindings = []
    previous_binding: tuple[int, str] | None = None
    for _ in range(binding_count):
        graph_index, scene_node = reader.u32(), reader.u32()
        if graph_index >= graph_count:
            raise GraphPackError("visual-graph binding has an invalid graph reference")
        current = (scene_node, graphs[graph_index]["id"])
        if previous_binding is not None and current <= previous_binding:
            raise GraphPackError("visual-graph bindings are not canonical")
        previous_binding = current
        bindings.append({"graph": current[1], "scene_node_index": scene_node})

    nodes = []
    expected_input = expected_flow = 0
    for _ in range(node_count):
        input_start, flow_start = reader.u32(), reader.u32()
        inputs, flow_zero, flow_one = reader.u16(), reader.u16(), reader.u16()
        opcode, flags = reader.u8(), reader.u8()
        type_id = OPCODE_TYPES.get(opcode)
        if type_id is None or flags != 0:
            raise GraphPackError("visual-graph node opcode/flags are invalid")
        if input_start != expected_input or flow_start != expected_flow:
            raise GraphPackError("visual-graph node ranges are not contiguous")
        if inputs != len(NODE_INPUTS[type_id]):
            raise GraphPackError("visual-graph node has the wrong input count")
        flow_ports = len(NODE_FLOW_OUTPUTS[type_id])
        if (flow_ports < 1 and flow_zero) or (flow_ports < 2 and flow_one):
            raise GraphPackError("visual-graph node has targets on an unsupported flow output")
        nodes.append((type_id, input_start, inputs, flow_start, flow_zero, flow_one))
        expected_input += inputs
        expected_flow += flow_zero + flow_one
    if expected_input != input_count or expected_flow != flow_count:
        raise GraphPackError("visual-graph input/flow counts do not match node ranges")
    inputs = [reader.u32() for _ in range(input_count)]
    flows = [reader.u16() for _ in range(flow_count)]
    if reader.offset != len(data):
        raise GraphPackError(f"visual-graph pack has {len(data) - reader.offset} trailing bytes")
    if len(data) > MAX_PACK_BYTES:
        raise GraphPackError("visual-graph pack exceeds its byte limit")

    for graph in graphs:
        start, count = graph["node_start"], graph["node_count"]
        for node_index in range(start, start + count):
            _, input_start, node_inputs, flow_start, flow_zero, flow_one = nodes[node_index]
            for token in inputs[input_start:input_start + node_inputs]:
                kind = token >> 30
                payload = token & 0xFFFF
                output = (token >> 16) & 0xFF
                if kind == 0:
                    if token & 0x3FFF0000 or payload >= value_count:
                        raise GraphPackError("visual-graph literal input token is invalid")
                elif kind == 1:
                    if token & 0x3F000000 or payload >= count:
                        raise GraphPackError("visual-graph source input token is invalid")
                    source_type = nodes[start + payload][0]
                    if output >= len(NODE_DATA_OUTPUTS[source_type]):
                        raise GraphPackError("visual-graph source output ordinal is invalid")
                else:
                    raise GraphPackError("visual-graph input token kind is reserved")
            for target in flows[flow_start:flow_start + flow_zero + flow_one]:
                if target >= count:
                    raise GraphPackError("visual-graph flow target is invalid")

    return {
        "schema": "ugts-kc-android-visual-graph-pack-1",
        "format_version": GRAPH_PACK_VERSION,
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "string_count": string_count,
        "value_count": value_count,
        "graph_count": graph_count,
        "binding_count": binding_count,
        "node_count": node_count,
        "input_count": input_count,
        "flow_target_count": flow_count,
        "state_key_count": state_count,
        "state_keys": state_keys,
        "graphs": [{key: item[key] for key in ("id", "node_count", "max_steps")} for item in graphs],
        "bindings": bindings,
    }


__all__ = [
    "GRAPH_MAX_STEPS",
    "GRAPH_PACK_ASSET",
    "GRAPH_PACK_ENDIAN",
    "GRAPH_PACK_MAGIC",
    "GRAPH_PACK_VERSION",
    "GraphPackError",
    "NODE_OPCODES",
    "compile_graph_pack_bytes",
    "inspect_graph_pack",
    "write_graph_pack",
]
