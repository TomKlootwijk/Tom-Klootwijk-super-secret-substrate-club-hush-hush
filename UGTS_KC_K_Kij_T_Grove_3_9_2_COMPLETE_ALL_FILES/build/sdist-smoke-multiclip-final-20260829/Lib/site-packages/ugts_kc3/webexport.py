"""Self-contained HTML5 Canvas exporter for UGTS-KC 3.9 game projects."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .project import GameProject, visual_graph_binding_ids, visual_graphs_from_rules
from .version import __codename__, __version__
from .visual_graph import BUILTIN_NODE_REGISTRY, PortDirection, PortKind


@dataclass(frozen=True)
class Html5BuildResult:
    output_dir: Path
    entrypoint: Path
    files: tuple[Path, ...]
    project_hash: str
    total_bytes: int
    single_file: bool
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "entrypoint": str(self.entrypoint),
            "files": [str(path) for path in self.files],
            "project_hash": self.project_hash,
            "total_bytes": self.total_bytes,
            "single_file": self.single_file,
            "warnings": list(self.warnings),
        }


def _safe_script_json(data: dict[str, Any]) -> str:
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


_WEB_VISUAL_GRAPH_NODE_TYPES = frozenset({
    "event.ready",
    "event.tick",
    "event.input_pressed",
    "event.trigger_enter",
    "event.trigger_exit",
    "event.timer",
    "event.message",
    "flow.branch",
    "value.constant",
    "value.seeded_number",
    "query.nearest_tag",
    "query.nearest_in_cone",
    "value.state",
    "value.component",
    "math.add",
    "math.subtract",
    "math.multiply",
    "math.divide",
    "compare",
    "action.set_state",
    "action.set_component",
    "action.play_animation",
    "action.stop_animation",
    "action.emit_event",
    "action.apply_force",
    "action.set_active",
    "action.despawn",
})

# The shared registry also contains Mobile 3D-only blocks.  Keep them in the
# explicit browser classification above so adding a builtin can never bypass
# the parity gate, then reject them during compilation with an honest message
# instead of emitting JavaScript that cannot own a 3D transform-animation
# component.
_WEB_MOBILE3D_ONLY_NODE_TYPES = frozenset({
    "action.play_animation",
    "action.stop_animation",
})


def _plain_json(value: Any) -> Any:
    """Turn frozen graph mappings/tuples back into ordinary JSON containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    return value


def _compile_web_visual_graphs(project: GameProject) -> dict[str, Any]:
    """Compile validated scene graphs into a deterministic browser execution plan.

    Keeping this step on the authoring side means an HTML5 build fails loudly if
    a future/custom node has no browser executor.  The runtime never guesses or
    silently skips authored logic.
    """
    scene_plans: dict[str, Any] = {}
    graph_count = 0
    binding_count = 0
    for scene_id, scene in sorted(project.scenes.items()):
        compiled_graphs: dict[str, Any] = {}
        graphs = visual_graphs_from_rules(scene.rules)
        for graph in graphs:
            graph.validate(BUILTIN_NODE_REGISTRY)
            mobile3d_only = sorted(
                {node.type for node in graph.nodes}
                & _WEB_MOBILE3D_ONLY_NODE_TYPES
            )
            if mobile3d_only:
                names = ", ".join(mobile3d_only)
                raise ValueError(
                    f"HTML5 visual graph {graph.id!r} in scene {scene_id!r} uses "
                    f"Mobile 3D-only node type(s): {names}"
                )
            unsupported = sorted({node.type for node in graph.nodes} - _WEB_VISUAL_GRAPH_NODE_TYPES)
            if unsupported:
                names = ", ".join(unsupported)
                raise ValueError(
                    f"HTML5 visual graph {graph.id!r} in scene {scene_id!r} uses "
                    f"unsupported node type(s): {names}"
                )

            nodes = {node.id: node for node in graph.nodes}
            order = graph.data_order(BUILTIN_NODE_REGISTRY)
            rank = {node_id: index for index, node_id in enumerate(order)}
            incoming: dict[str, dict[str, list[str]]] = {}
            outgoing: dict[tuple[str, str], list[list[str]]] = {}
            for link in graph.links:
                source_definition = BUILTIN_NODE_REGISTRY.definition(nodes[link.source_node].type)
                source_port = source_definition.port(PortDirection.OUTPUT, link.source_port)
                if source_port is not None and source_port.kind is PortKind.DATA:
                    incoming.setdefault(link.target_node, {})[link.target_port] = [
                        link.source_node,
                        link.source_port,
                    ]
                else:
                    outgoing.setdefault((link.source_node, link.source_port), []).append([
                        link.target_node,
                        link.target_port,
                    ])
            outgoing_document: dict[str, dict[str, list[list[str]]]] = {}
            for (node_id, port_name), links in sorted(outgoing.items()):
                outgoing_document.setdefault(node_id, {})[port_name] = sorted(
                    links,
                    key=lambda link: (rank.get(link[0], 0), link[0], link[1]),
                )

            roots: dict[str, list[str]] = {"ready": [], "tick": [], "input_pressed": []}
            node_documents: list[dict[str, Any]] = []
            for node in graph.nodes:
                definition = BUILTIN_NODE_REGISTRY.definition(node.type)
                properties = _plain_json(definition.default_properties)
                properties.update(node.to_dict()["properties"])
                node_documents.append({
                    "id": node.id,
                    "type": node.type,
                    "properties": properties,
                    "data_only": definition.is_data_node,
                })
                if definition.event is not None:
                    roots.setdefault(definition.event, []).append(node.id)
                    # Python's GraphRuntime polls Input Pressed nodes during Tick.
                    if definition.event in {"input_pressed", "timer"}:
                        roots["tick"].append(node.id)
            for trigger in roots:
                roots[trigger].sort(key=lambda node_id: (rank[node_id], node_id))

            compiled_graphs[graph.id] = {
                "id": graph.id,
                "max_steps": 1024,
                "nodes": node_documents,
                "incoming_data": {
                    node_id: dict(sorted(ports.items()))
                    for node_id, ports in sorted(incoming.items())
                },
                "outgoing_flow": outgoing_document,
                "roots": roots,
            }
        bindings: list[dict[str, str | None]] = []
        graph_ids = set(compiled_graphs)
        for entity in scene.entities:
            graph_bindings = visual_graph_binding_ids(
                entity.metadata.get("visual_graph"),
                f"entity {entity.id} visual_graph binding",
            )
            for graph_id in sorted(graph_bindings):
                if graph_id not in graph_ids:
                    raise ValueError(
                        f"HTML5 scene {scene_id!r} entity {entity.id!r} binds missing visual graph {graph_id!r}"
                    )
                bindings.append({"graph": graph_id, "entity": entity.id})
        world_bindings = visual_graph_binding_ids(
            scene.rules.get("world_graphs"), f"scene {scene_id} world_graphs"
        )
        for graph_id in sorted(world_bindings):
            if graph_id not in graph_ids:
                raise ValueError(
                    f"HTML5 scene {scene_id!r} binds missing world visual graph {graph_id!r}"
                )
            bindings.append({"graph": graph_id, "entity": None})
        graph_count += len(compiled_graphs)
        binding_count += len(bindings)
        scene_plans[scene_id] = {"graphs": compiled_graphs, "bindings": bindings}
    return {
        "schema": "ugts-kc-web-visual-graph-1",
        "graph_count": graph_count,
        "binding_count": binding_count,
        "scenes": scene_plans,
    }


_RUNTIME_JS = r'''(() => {
"use strict";
const PROJECT = JSON.parse(document.getElementById("kc-project").textContent);
const VERSION = "__KC_VERSION__";
const CODENAME = "__KC_CODENAME__";
const canvas = document.getElementById("kc-canvas");
const ctx = canvas.getContext("2d", {alpha: false, desynchronized: true});
const statusNode = document.getElementById("kc-status");
const touchNode = document.getElementById("kc-touch");
const display = PROJECT.display;
const baseWidth = display.width;
const baseHeight = display.height;
let dpr = 1;
let cssScale = 1;
let fixedDt = 1 / 60;
let accumulator = 0;
let previousTimestamp = performance.now();
let fps = 60;
let frameCounter = 0;
let fpsTime = previousTimestamp;
let debug = !!(PROJECT.build && PROJECT.build.debug);
let muted = false;
let audioContext = null;
let musicClock = null;
const keys = new Set();
const pointerButtons = new Set();
const touchAxes = Object.create(null);
const activePointers = new Map();
let joystickPointer = null;
let joystickStart = {x: 0, y: 0};
let joystickCurrent = {x: 0, y: 0};
let pointerPosition = {x: 0, y: 0};
let previousActions = Object.create(null);
let currentActions = Object.create(null);
let gamepadButtons = Object.create(null);
let gamepadAxes = Object.create(null);
let particles = [];
let contacts = new Set();
let triggerContacts = new Set();
let eventLog = [];
let tick = 0;
let gameTime = 0;
let paused = false;
let won = false;
let gameOver = false;
let scene = null;
let entities = [];
let entityMap = new Map();
let state = Object.create(null);
let camera = {position: [baseWidth / 2, baseHeight / 2], zoom: 1, rotation: 0, follow_entity: null, follow_smoothing: 8};
let worldSize = [baseWidth, baseHeight];
let sceneRules = Object.create(null);
let visualGraphScenePlan = {graphs: {}, bindings: []};
let visualGraphPlans = new Map();
let visualGraphBindings = [];
let pendingGraphDespawns = new Set();
let pendingGraphMessages = [];
let visualGraphBatch = null;
const GRAPH_BATCH_MAX_STEPS = 16384;
const GRAPH_MESSAGE_MAX_EVENTS = 64;
const assets = PROJECT.vector_assets || {};
const audioCues = new Map(((PROJECT.audio && PROJECT.audio.cues) || []).map(cue => [cue.id, cue]));
const audioSequences = new Map(((PROJECT.audio && PROJECT.audio.sequences) || []).map(sequence => [sequence.id, sequence]));
const actionDefinitions = new Map(((PROJECT.input && PROJECT.input.actions) || []).map(action => [action.name, action]));

function deepClone(value) { return JSON.parse(JSON.stringify(value)); }
function clamp(value, minimum, maximum) { return Math.max(minimum, Math.min(maximum, value)); }
function length(x, y) { return Math.hypot(x, y); }
function normalize(x, y) { const n = Math.hypot(x, y); return n > 1e-9 ? [x / n, y / n] : [0, 0]; }
function pairKey(a, b) { return a < b ? `${a}|${b}` : `${b}|${a}`; }
function component(entity, name) { return entity.components ? entity.components[name] : null; }
function hasTag(entity, tag) { return Array.isArray(entity.tags) && entity.tags.includes(tag); }
function entitiesWith(...names) { return entities.filter(entity => entity.active !== false && names.every(name => component(entity, name))); }
function emit(kind, source = null, target = null, payload = {}) {
  const event = {sequence: eventLog.length + 1, tick, time: gameTime, kind, source, target, payload};
  eventLog.push(event);
  if (eventLog.length > 512) eventLog.shift();
  return event;
}

function configureVisualGraphs() {
  const runtime = PROJECT.web_visual_graph_runtime || {};
  visualGraphScenePlan = runtime.scenes?.[scene.id] || {graphs: {}, bindings: []};
  visualGraphPlans = new Map();
  for (const [graphId, document] of Object.entries(visualGraphScenePlan.graphs || {})) {
    const plan = {...document};
    plan._nodes = new Map((plan.nodes || []).map(node => [node.id, node]));
    visualGraphPlans.set(graphId, plan);
  }
  visualGraphBindings = (visualGraphScenePlan.bindings || []).map(binding => ({
    graph: binding.graph,
    entity: binding.entity == null ? null : String(binding.entity),
    active_step: 0,
  }));
  pendingGraphDespawns = new Set();
  pendingGraphMessages = [];
  visualGraphBatch = null;
}

function graphError(binding, graph, nodeId, message) {
  const owner = binding.entity == null ? "world" : `entity ${binding.entity}`;
  return new Error(`Visual graph ${graph.id} (${owner}), node ${nodeId}: ${message}`);
}

function graphBatchStep(binding, graph, nodeId) {
  if (visualGraphBatch === null) return;
  if (visualGraphBatch.steps >= GRAPH_BATCH_MAX_STEPS) {
    throw graphError(
      binding,
      graph,
      nodeId,
      `Visual graph message dispatch stopped with TotalStepLimit after ${GRAPH_BATCH_MAX_STEPS} node steps`,
    );
  }
  visualGraphBatch.steps += 1;
}

function graphEventLimitError() {
  return new Error(
    `Visual graph message dispatch stopped with EventLimit after ${GRAPH_MESSAGE_MAX_EVENTS} queued events. Check for messages that keep sending one another.`,
  );
}

function queueGraphMessage(message, source, target) {
  if (typeof message !== "string") throw new Error("event message must be text");
  if (visualGraphBatch === null) throw new Error("messages need an outer graph batch");
  if (visualGraphBatch.queuedEvents >= GRAPH_MESSAGE_MAX_EVENTS) {
    throw graphEventLimitError();
  }
  visualGraphBatch.queuedEvents += 1;
  pendingGraphMessages.push({message, source, target});
}

function visualGraphBindingIsActive(binding) {
  if (binding.entity == null) return true;
  const owner = entityMap.get(binding.entity);
  return !!owner && owner.alive !== false && owner.active !== false;
}

function drainGraphMessages() {
  if (visualGraphBatch === null) throw new Error("message dispatch needs an outer graph batch");
  while (pendingGraphMessages.length) {
    if (visualGraphBatch.events >= GRAPH_MESSAGE_MAX_EVENTS) {
      throw graphEventLimitError();
    }
    const message = pendingGraphMessages.shift();
    visualGraphBatch.events += 1;
    for (const binding of visualGraphBindings) {
      if (!visualGraphBindingIsActive(binding)) continue;
      if (
        message.target != null
        && binding.entity != null
        && binding.entity !== message.target
      ) continue;
      dispatchVisualGraph(
        binding,
        "message",
        visualGraphBatch.dt,
        visualGraphBatch.deferDespawns,
        {message},
      );
    }
  }
}

function runVisualGraphBatch(label, dt, deferDespawns, callback) {
  if (visualGraphBatch !== null) throw new Error("visual graph batches cannot be nested");
  visualGraphBatch = {
    label,
    dt,
    deferDespawns,
    steps: 0,
    events: 0,
    queuedEvents: 0,
  };
  try {
    callback();
    drainGraphMessages();
  } catch (error) {
    pendingGraphMessages = [];
    const message = error instanceof Error ? error.message : String(error);
    updateStatus(`Logic stopped: ${message}`);
    console.error(error);
    throw error;
  } finally {
    visualGraphBatch = null;
  }
}

function graphEntity(binding, value) {
  let entityId = value;
  if (entityId && typeof entityId === "object" && "id" in entityId) entityId = entityId.id;
  if (entityId == null || entityId === "") entityId = binding.entity;
  if (entityId == null || String(entityId).length === 0) throw new Error("no entity was supplied; bind the graph or set its entity input");
  const resolved = String(entityId);
  const entity = entityMap.get(resolved);
  if (!entity) throw new Error(`entity ${resolved} does not exist`);
  return entity;
}

function graphReadField(value, path, fallback) {
  if (!path) return value;
  let current = value;
  try {
    for (const part of String(path).split(".")) {
      if (!part || part.startsWith("_")) throw new Error("component field names cannot be empty or private");
      if (Array.isArray(current) && /^\d+$/.test(part)) current = current[Number(part)];
      else if (current !== null && typeof current === "object" && Object.prototype.hasOwnProperty.call(current, part)) current = current[part];
      else return fallback;
    }
    return current;
  } catch (error) {
    if (error instanceof Error && error.message.includes("private")) throw error;
    return fallback;
  }
}

function graphWriteField(value, path, newValue) {
  const parts = String(path).split(".");
  if (!parts.length || parts.some(part => !part || part.startsWith("_"))) throw new Error("component field names cannot be empty or private");
  let current = value;
  for (const part of parts.slice(0, -1)) {
    if (Array.isArray(current) && /^\d+$/.test(part)) current = current[Number(part)];
    else if (current !== null && typeof current === "object" && Object.prototype.hasOwnProperty.call(current, part)) current = current[part];
    else throw new Error(`component field ${path} does not exist`);
  }
  const last = parts[parts.length - 1];
  if (Array.isArray(current) && /^\d+$/.test(last)) {
    const index = Number(last);
    if (index < 0 || index >= current.length) throw new Error(`component field ${path} does not exist`);
    current[index] = deepClone(newValue);
  } else if (current !== null && typeof current === "object") {
    current[last] = deepClone(newValue);
  } else throw new Error(`component field ${path} cannot be changed`);
}

function graphValuesEqual(a, b) {
  const numericA = typeof a === "number" || typeof a === "boolean";
  const numericB = typeof b === "number" || typeof b === "boolean";
  if (numericA && numericB) return Number(a) === Number(b);
  if (Array.isArray(a) || Array.isArray(b)) return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((value, index) => graphValuesEqual(value, b[index]));
  if (a !== null && b !== null && typeof a === "object" && typeof b === "object") {
    const keysA = Object.keys(a).sort(); const keysB = Object.keys(b).sort();
    return keysA.length === keysB.length && keysA.every((key, index) => key === keysB[index] && graphValuesEqual(a[key], b[key]));
  }
  return a === b;
}

function graphOrderedValues(a, b) {
  if ((typeof a === "number" || typeof a === "boolean") && (typeof b === "number" || typeof b === "boolean")) return [Number(a), Number(b)];
  if (typeof a === "string" && typeof b === "string") return [a, b];
  throw new Error("ordered comparisons need two numbers or two strings");
}

function graphComparison(operator, a, b) {
  const operation = String(operator ?? "equal").toLowerCase().replaceAll(" ", "_");
  if (["equal", "eq", "=="].includes(operation)) return graphValuesEqual(a, b);
  if (["not_equal", "ne", "!="].includes(operation)) return !graphValuesEqual(a, b);
  const orderedOperations = new Set(["less", "lt", "<", "less_equal", "lte", "<=", "greater", "gt", ">", "greater_equal", "gte", ">="]);
  if (!orderedOperations.has(operation)) throw new Error(`unknown comparison ${operation}`);
  const [left, right] = graphOrderedValues(a, b);
  if (["less", "lt", "<"].includes(operation)) return left < right;
  if (["less_equal", "lte", "<="].includes(operation)) return left <= right;
  if (["greater", "gt", ">"].includes(operation)) return left > right;
  if (["greater_equal", "gte", ">="].includes(operation)) return left >= right;
  throw new Error(`unknown comparison ${operation}`);
}

function despawnGraphEntity(entityId, defer) {
  const id = String(entityId);
  if (!entityMap.has(id)) throw new Error(`entity ${id} does not exist`);
  if (defer) { pendingGraphDespawns.add(id); return; }
  entityMap.delete(id);
  entities = entities.filter(entity => entity.id !== id);
  contacts = new Set([...contacts].filter(key => !key.split("|").includes(id)));
  emit("entity_despawned", id);
}

function flushGraphDespawns() {
  for (const entityId of [...pendingGraphDespawns].sort()) {
    if (entityMap.has(entityId)) despawnGraphEntity(entityId, false);
  }
  pendingGraphDespawns.clear();
}

const REPEATABLE_NUMBER_NAMESPACE = 0x7f1400acd2ebb3aen;
function graphSplitMix64(input) {
  let value = BigInt.asUintN(64, input + 0x9e3779b97f4a7c15n);
  value = BigInt.asUintN(64, (value ^ (value >> 30n)) * 0xbf58476d1ce4e5b9n);
  value = BigInt.asUintN(64, (value ^ (value >> 27n)) * 0x94d049bb133111ebn);
  return BigInt.asUintN(64, value ^ (value >> 31n));
}
function graphCombineSeed(seed, input) {
  seed = BigInt.asUintN(64, seed);
  const mixed = BigInt.asUintN(64, graphSplitMix64(input) + 0x9e3779b97f4a7c15n + BigInt.asUintN(64, seed << 6n) + (seed >> 2n));
  return graphSplitMix64(seed ^ mixed);
}
function repeatableRandomNumber(inputs) {
  const rawIndexes = [["World number", inputs.world_number], ["Pick number", inputs.pick_number]];
  const indexes = [];
  for (const [label, value] of rawIndexes) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new Error(`${label} must be a whole number from 0 to 65535`);
    }
    const canonical = Math.fround(value);
    if (!Number.isFinite(canonical) || !Number.isInteger(canonical) || canonical < 0 || canonical > 65535) {
      throw new Error(`${label} must be a whole number from 0 to 65535`);
    }
    indexes.push(canonical);
  }
  const smallest = Math.fround(inputs.smallest);
  const largest = Math.fround(inputs.largest);
  if (typeof inputs.smallest !== "number" || !Number.isFinite(smallest)) throw new Error("Smallest must be a finite number that fits on this device");
  if (typeof inputs.largest !== "number" || !Number.isFinite(largest)) throw new Error("Largest must be a finite number that fits on this device");
  if (smallest > largest) throw new Error("Smallest must not be bigger than Largest");
  const first = graphCombineSeed(BigInt(indexes[0]), REPEATABLE_NUMBER_NAMESPACE);
  const lineage = graphCombineSeed(first, BigInt(indexes[1]));
  const unit = Math.fround(Number(graphSplitMix64(lineage) >> 40n) / 16777216);
  const span = largest - smallest;
  const scaled = unit * span;
  return Math.fround(smallest + scaled);
}

const PORTABLE_QUERY_TAGS = new Set(["player", "collectible", "goal", "decorative", "hazard"]);
const graphTextEncoder = new TextEncoder();
function graphUtf8Less(left, right) {
  const a = graphTextEncoder.encode(String(left));
  const b = graphTextEncoder.encode(String(right));
  const count = Math.min(a.length, b.length);
  for (let index = 0; index < count; index += 1) {
    if (a[index] !== b[index]) return a[index] < b[index];
  }
  return a.length < b.length;
}
function graphPosition3(entity, required) {
  const transform = component(entity, "transform");
  const position = transform?.position ?? transform?.translation;
  if (!Array.isArray(position) || ![2, 3].includes(position.length)) {
    if (required) throw new Error(`entity ${entity.id} has no 2D or 3D transform position`);
    return null;
  }
  const result = [];
  for (const value of position) {
    if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`entity ${entity.id} transform position must be finite`);
    const canonical = Math.fround(value);
    if (!Number.isFinite(canonical)) throw new Error(`entity ${entity.id} transform position does not fit on this device`);
    result.push(canonical);
  }
  if (result.length === 2) result.push(0);
  return result;
}
function portableGraphCone(value) {
  if (!Array.isArray(value) || value.length !== 4) {
    throw new Error("cone must contain a three-number Facing direction and View width");
  }
  const cone = value.map(item => Math.fround(item));
  if (cone.some((item, index) => typeof value[index] !== "number" || !Number.isFinite(item))) {
    throw new Error("cone must contain finite numbers that fit on this device");
  }
  const ax2 = Math.fround(cone[0] * cone[0]);
  const ay2 = Math.fround(cone[1] * cone[1]);
  const az2 = Math.fround(cone[2] * cone[2]);
  const axisSquared = Math.fround(Math.fround(ax2 + ay2) + az2);
  if (!Number.isFinite(axisSquared) || axisSquared <= 0) {
    throw new Error("cone Facing direction must be finite and non-zero");
  }
  if (cone[3] < -1 || cone[3] > 1) {
    throw new Error("cone View width must use a minimum cosine from -1 to 1");
  }
  const axisLength = Math.fround(Math.sqrt(axisSquared));
  const axis = [
    Math.fround(cone[0] / axisLength),
    Math.fround(cone[1] / axisLength),
    Math.fround(cone[2] / axisLength),
  ];
  if (!Number.isFinite(axisLength) || axis.some(component => !Number.isFinite(component))) {
    throw new Error("cone Facing direction must be finite and non-zero");
  }
  return {axis, cosine: cone[3]};
}
function graphConeSupports(delta, squared, cone) {
  const distance = Math.fround(Math.sqrt(squared));
  const denominator = Math.max(distance, Math.fround(1e-6));
  const direction = [
    Math.fround(delta[0] / denominator),
    Math.fround(delta[1] / denominator),
    Math.fround(delta[2] / denominator),
  ];
  const tx = Math.fround(direction[0] * cone.axis[0]);
  const ty = Math.fround(direction[1] * cone.axis[1]);
  const tz = Math.fround(direction[2] * cone.axis[2]);
  const cosine = Math.fround(Math.fround(tx + ty) + tz);
  if (![distance, denominator, ...direction, cosine].every(Number.isFinite)) {
    throw new Error("cone does not fit deterministic float32 math");
  }
  return cosine >= cone.cosine;
}
function nearestTaggedEntity(binding, inputs, useCone = false) {
  if (typeof inputs.tag !== "string" || !PORTABLE_QUERY_TAGS.has(inputs.tag)) {
    throw new Error("tag must be player, collectible, goal, decorative, or hazard");
  }
  if (typeof inputs.radius !== "number" || !Number.isFinite(inputs.radius)) {
    throw new Error("radius must be a finite number that fits on this device");
  }
  const radius = Math.fround(inputs.radius);
  const radiusSquared = Math.fround(radius * radius);
  if (!Number.isFinite(radius) || radius < 0 || !Number.isFinite(radiusSquared)) {
    throw new Error("radius must be a finite non-negative number that fits on this device");
  }
  const cone = useCone ? portableGraphCone(inputs.cone) : null;
  const originEntity = graphEntity(binding, inputs.origin);
  const origin = graphPosition3(originEntity, true);
  let bestId = null;
  let bestSquared = null;
  for (const candidate of entities) {
    const candidateId = String(candidate.id);
    if (candidateId === String(originEntity.id) || candidate.alive === false || candidate.active === false || !hasTag(candidate, inputs.tag)) continue;
    const position = graphPosition3(candidate, false);
    if (position === null) continue;
    const delta = [];
    let squared = 0;
    for (let axis = 0; axis < 3; axis += 1) {
      delta.push(Math.fround(position[axis] - origin[axis]));
      const term = Math.fround(delta[axis] * delta[axis]);
      squared = Math.fround(squared + term);
      if (!Number.isFinite(squared)) throw new Error("entity distance does not fit deterministic float32 math");
    }
    if (squared > radiusSquared || (cone && !graphConeSupports(delta, squared, cone))) continue;
    if (bestSquared === null || squared < bestSquared || (squared === bestSquared && graphUtf8Less(candidateId, bestId))) {
      bestId = candidateId;
      bestSquared = squared;
    }
  }
  if (bestId === null) return {found: false, entity: null, distance: null};
  return {found: true, entity: bestId, distance: Math.fround(Math.sqrt(bestSquared))};
}

function timerEventValues(binding, inputs, run) {
  if (typeof inputs.seconds !== "number" || !Number.isFinite(inputs.seconds)) {
    throw new Error("When Timer Rings Seconds must be a finite positive number up to 86400");
  }
  const seconds = Math.fround(inputs.seconds);
  if (!Number.isFinite(seconds) || seconds <= 0 || seconds > 86400) {
    throw new Error("When Timer Rings Seconds must be a finite positive number up to 86400");
  }
  if (typeof inputs.repeat !== "boolean") {
    throw new Error("When Timer Rings Repeat must be true or false");
  }
  const stepDt = Math.fround(run.dt);
  if (!Number.isFinite(stepDt) || stepDt <= 0) {
    throw new Error("When Timer Rings needs a positive fixed-step duration");
  }
  const ratio = Math.fround(seconds / stepDt);
  if (!Number.isFinite(ratio)) {
    throw new Error("When Timer Rings could not fit this duration into fixed updates");
  }
  const period = Math.max(1, Math.ceil(ratio));
  const step = run.activeStep;
  let ringing;
  let rings;
  let remainingSteps;
  if (inputs.repeat) {
    const remainder = step % period;
    ringing = step > 0 && remainder === 0;
    rings = Math.floor(step / period);
    remainingSteps = ringing ? 0 : period - remainder;
  } else {
    ringing = step === period;
    rings = step < period ? 0 : 1;
    remainingSteps = Math.max(0, period - step);
  }
  const count = Math.fround(rings);
  const remaining = remainingSteps === 0
    ? 0
    : Math.fround(Math.fround(remainingSteps) * stepDt);
  if (!Number.isFinite(count) || !Number.isFinite(remaining)) {
    throw new Error("When Timer Rings could not fit this duration into fixed updates");
  }
  return {
    values: {count, remaining, entity: binding.entity},
    flow: ringing ? ["out"] : [],
  };
}

function executeGraphNode(binding, graph, node, inputs, run) {
  const entityOutput = binding.entity;
  switch (node.type) {
    case "event.ready": return {values: {entity: entityOutput}, flow: ["out"]};
    case "event.tick": return {values: {dt: run.dt, tick, entity: entityOutput}, flow: ["out"]};
    case "event.timer": return timerEventValues(binding, inputs, run);
    case "event.input_pressed": {
      const action = String(inputs.action);
      return {values: {action, value: actionValue(action), entity: entityOutput}, flow: actionPressed(action) ? ["out"] : []};
    }
    case "event.trigger_enter":
    case "event.trigger_exit":
      return {values: {sensor: run.triggerSensor, player: run.triggerPlayer, entity: entityOutput}, flow: ["out"]};
    case "event.message": {
      if (typeof inputs.message !== "string") throw new Error("When Message needs a saved text message");
      const received = run.triggerMessage;
      const matches = received !== null && inputs.message === received.message;
      return {
        values: {
          source: received?.source ?? null,
          target: received?.target ?? null,
          entity: entityOutput,
        },
        flow: matches ? ["out"] : [],
      };
    }
    case "flow.branch": {
      if (typeof inputs.condition !== "boolean") throw new Error("condition must be boolean");
      return {values: {}, flow: [inputs.condition ? "true" : "false"]};
    }
    case "value.constant": return {values: {value: deepClone(node.properties.value)}, flow: []};
    case "value.seeded_number": return {values: {value: repeatableRandomNumber(inputs)}, flow: []};
    case "query.nearest_tag": return {values: nearestTaggedEntity(binding, inputs), flow: []};
    case "query.nearest_in_cone": return {values: nearestTaggedEntity(binding, inputs, true), flow: []};
    case "value.state": {
      const key = String(inputs.key);
      const value = Object.prototype.hasOwnProperty.call(state, key) ? state[key] : inputs.default;
      return {values: {value}, flow: []};
    }
    case "value.component": {
      const entity = graphEntity(binding, inputs.entity);
      const name = String(inputs.component);
      const found = component(entity, name);
      const value = found == null ? inputs.default : graphReadField(found, String(inputs.field || ""), inputs.default);
      return {values: {value}, flow: []};
    }
    case "math.add":
    case "math.subtract":
    case "math.multiply":
    case "math.divide": {
      const a = inputs.a; const b = inputs.b;
      if (typeof a !== "number" || typeof b !== "number" || !Number.isFinite(a) || !Number.isFinite(b)) throw new Error("math inputs must be finite numbers");
      if (node.type === "math.divide" && b === 0) throw new Error("cannot divide by zero");
      let result = node.type === "math.add" ? a + b : node.type === "math.subtract" ? a - b : node.type === "math.multiply" ? a * b : a / b;
      if (!Number.isFinite(result)) throw new Error("math result is not finite");
      return {values: {result}, flow: []};
    }
    case "compare": return {values: {result: graphComparison(inputs.operator, inputs.a, inputs.b)}, flow: []};
    case "action.set_state": {
      const key = String(inputs.key);
      if (!key) throw new Error("state key cannot be empty");
      state[key] = deepClone(inputs.value);
      return {values: {}, flow: ["out"]};
    }
    case "action.set_component": {
      const entity = graphEntity(binding, inputs.entity);
      const name = String(inputs.component);
      const field = String(inputs.field || "");
      if (!field) entity.components[name] = deepClone(inputs.value);
      else {
        if (!Object.prototype.hasOwnProperty.call(entity.components, name)) throw new Error(`entity ${entity.id} lacks component ${name}`);
        const updated = deepClone(entity.components[name]);
        graphWriteField(updated, field, inputs.value);
        entity.components[name] = updated;
      }
      return {values: {}, flow: ["out"]};
    }
    case "action.emit_event": {
      if (typeof inputs.kind !== "string") throw new Error("event kind must be text");
      const source = inputs.source == null || inputs.source === "" ? binding.entity : String(inputs.source);
      const target = inputs.target == null || inputs.target === "" ? null : String(inputs.target);
      const payload = inputs.payload ?? {};
      if (payload === null || typeof payload !== "object" || Array.isArray(payload)) throw new Error("event payload must be an object");
      const event = emit(inputs.kind, source, target, deepClone(payload));
      queueGraphMessage(inputs.kind, source, target);
      return {values: {event}, flow: ["out"]};
    }
    case "action.apply_force": {
      const entity = graphEntity(binding, inputs.entity);
      const body = component(entity, "body");
      const force = inputs.force;
      if (!body) throw new Error(`entity ${entity.id} lacks component body`);
      if (!Array.isArray(force) || force.length !== 2 || !force.every(value => typeof value === "number" && Number.isFinite(value))) throw new Error("force must be a two-number vector");
      body.force = [(body.force?.[0] || 0) + force[0], (body.force?.[1] || 0) + force[1]];
      return {values: {}, flow: ["out"]};
    }
    case "action.set_active": {
      if (typeof inputs.active !== "boolean") throw new Error("active must be boolean");
      graphEntity(binding, inputs.entity).active = inputs.active;
      return {values: {}, flow: ["out"]};
    }
    case "action.despawn": {
      const entity = graphEntity(binding, inputs.entity);
      despawnGraphEntity(entity.id, run.deferDespawns);
      return {values: {}, flow: ["out"]};
    }
    default: throw new Error(`unsupported browser node type ${node.type}`);
  }
}

function evaluateGraphNode(binding, graph, nodeId, flowInput, run, dataCache, stack = []) {
  if (dataCache.has(nodeId)) return dataCache.get(nodeId);
  const node = graph._nodes.get(nodeId);
  if (!node) throw graphError(binding, graph, nodeId, "node does not exist");
  if (run.steps >= run.maxSteps) throw graphError(binding, graph, nodeId, `reached the ${run.maxSteps}-step safety limit`);
  if (stack.includes(nodeId)) throw graphError(binding, graph, nodeId, "a data link recursively requested this node");
  const inputs = deepClone(node.properties || {});
  const linkedInputs = graph.incoming_data?.[nodeId] || {};
  for (const [port, source] of Object.entries(linkedInputs)) {
    const [sourceId, sourcePort] = source;
    const sourceNode = graph._nodes.get(sourceId);
    let values;
    if (run.lastOutputs.has(sourceId)) values = run.lastOutputs.get(sourceId);
    else if (sourceNode?.data_only) values = evaluateGraphNode(binding, graph, sourceId, null, run, dataCache, [...stack, nodeId]).values;
    else throw graphError(binding, graph, nodeId, `input ${port} reads ${sourceId}.${sourcePort} before that flow node ran`);
    if (!Object.prototype.hasOwnProperty.call(values, sourcePort)) throw graphError(binding, graph, nodeId, `source ${sourceId}.${sourcePort} produced no value`);
    inputs[port] = values[sourcePort];
  }
  graphBatchStep(binding, graph, nodeId);
  run.steps += 1;
  let outcome;
  try { outcome = executeGraphNode(binding, graph, node, inputs, run); }
  catch (error) { throw graphError(binding, graph, nodeId, error instanceof Error ? error.message : String(error)); }
  if (node.data_only) dataCache.set(nodeId, outcome);
  return outcome;
}

function dispatchVisualGraph(binding, trigger, dt, deferDespawns, triggerContext = null) {
  const graph = visualGraphPlans.get(binding.graph);
  if (!graph) throw new Error(`Visual graph binding references missing graph ${binding.graph}`);
  const run = {
    dt,
    deferDespawns,
    maxSteps: graph.max_steps || 1024,
    steps: 0,
    lastOutputs: new Map(),
    triggerSensor: triggerContext?.sensor ?? null,
    triggerPlayer: triggerContext?.player ?? null,
    triggerMessage: triggerContext?.message ?? null,
    activeStep: binding.active_step,
  };
  let roots = graph.roots?.[trigger] || [];
  if (trigger === "message") {
    const message = triggerContext?.message?.message;
    roots = roots.filter(
      nodeId => graph._nodes.get(nodeId)?.properties?.message === message,
    );
  }
  const queue = roots.map(nodeId => [nodeId, null]);
  while (queue.length) {
    const [nodeId, flowInput] = queue.shift();
    const outcome = evaluateGraphNode(binding, graph, nodeId, flowInput, run, new Map());
    run.lastOutputs.set(nodeId, outcome.values);
    for (const flowPort of outcome.flow) {
      const links = graph.outgoing_flow?.[nodeId]?.[flowPort] || [];
      if (queue.length + links.length > run.maxSteps) throw graphError(binding, graph, nodeId, `flow queue reached the ${run.maxSteps}-step safety limit`);
      for (const link of links) queue.push(link);
    }
  }
  return run.steps;
}

function runVisualGraphs(trigger, dt = 0) {
  const deferDespawns = trigger === "tick";
  for (const binding of visualGraphBindings) {
    if (trigger === "ready") binding.active_step = 0;
    if (!visualGraphBindingIsActive(binding)) continue;
    if (trigger === "tick") binding.active_step += 1;
    dispatchVisualGraph(binding, trigger, dt, deferDespawns);
  }
}

function runTriggerVisualGraphs(trigger, sensor, player, dt = fixedDt) {
  const context = {sensor: String(sensor), player: String(player)};
  for (const binding of visualGraphBindings) {
    if (binding.entity != null && binding.entity !== context.sensor) continue;
    if (!visualGraphBindingIsActive(binding)) continue;
    dispatchVisualGraph(binding, trigger, dt, true, context);
  }
}

function resizeCanvas() {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const ratio = display.pixel_ratio === "1" ? 1 : display.pixel_ratio === "2" ? 2 : Math.min(window.devicePixelRatio || 1, 2.5);
  dpr = ratio;
  let width = vw;
  let height = vh;
  if (display.scaling !== "stretch") {
    const scaleFit = Math.min(vw / baseWidth, vh / baseHeight);
    const scaleFill = Math.max(vw / baseWidth, vh / baseHeight);
    cssScale = display.scaling === "fill" ? scaleFill : display.scaling === "integer" ? Math.max(1, Math.floor(scaleFit)) : scaleFit;
    width = Math.max(1, Math.round(baseWidth * cssScale));
    height = Math.max(1, Math.round(baseHeight * cssScale));
  } else {
    cssScale = vw / baseWidth;
  }
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  canvas.width = Math.max(1, Math.round(baseWidth * dpr));
  canvas.height = Math.max(1, Math.round(baseHeight * dpr));
  canvas.style.imageRendering = display.antialias === false ? "pixelated" : "auto";
}
window.addEventListener("resize", resizeCanvas);
resizeCanvas();

function canvasPoint(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) * baseWidth / rect.width,
    y: (event.clientY - rect.top) * baseHeight / rect.height,
  };
}

const blockedKeys = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"]);
window.addEventListener("keydown", event => {
  keys.add(event.code);
  if (blockedKeys.has(event.code)) event.preventDefault();
  if (event.code === "F3" && !event.repeat) { debug = !debug; event.preventDefault(); }
  unlockAudio();
});
window.addEventListener("keyup", event => { keys.delete(event.code); });
window.addEventListener("blur", () => { keys.clear(); pointerButtons.clear(); });
canvas.addEventListener("contextmenu", event => event.preventDefault());
canvas.addEventListener("pointerdown", event => {
  canvas.setPointerCapture(event.pointerId);
  unlockAudio();
  const point = canvasPoint(event);
  pointerPosition = point;
  activePointers.set(event.pointerId, {point, type: event.pointerType});
  pointerButtons.add(String(event.button));
  if (event.pointerType === "touch") {
    if (point.x < baseWidth * 0.58 && joystickPointer === null) {
      joystickPointer = event.pointerId;
      joystickStart = point;
      joystickCurrent = point;
    } else {
      touchAxes.dash = 1;
    }
  }
});
canvas.addEventListener("pointermove", event => {
  const point = canvasPoint(event);
  pointerPosition = point;
  const entry = activePointers.get(event.pointerId);
  if (entry) entry.point = point;
  if (joystickPointer === event.pointerId) joystickCurrent = point;
});
function releasePointer(event) {
  activePointers.delete(event.pointerId);
  pointerButtons.delete(String(event.button));
  if (joystickPointer === event.pointerId) {
    joystickPointer = null;
    touchAxes.move_x = 0;
    touchAxes.move_y = 0;
  } else if (event.pointerType === "touch") {
    touchAxes.dash = 0;
  }
}
canvas.addEventListener("pointerup", releasePointer);
canvas.addEventListener("pointercancel", releasePointer);

function pollGamepads() {
  gamepadButtons = Object.create(null);
  gamepadAxes = Object.create(null);
  const pads = navigator.getGamepads ? navigator.getGamepads() : [];
  for (let device = 0; device < pads.length; device += 1) {
    const pad = pads[device];
    if (!pad) continue;
    pad.buttons.forEach((button, index) => {
      gamepadButtons[`${device}:${index}`] = typeof button === "number" ? button : button.value;
    });
    pad.axes.forEach((value, index) => { gamepadAxes[`${device}:${index}`] = value; });
  }
}

function bindingValue(binding) {
  const scale = Number.isFinite(binding.scale) ? binding.scale : 1;
  const device = Number.isFinite(binding.device) ? binding.device : 0;
  let value = 0;
  if (binding.kind === "key") value = keys.has(binding.code) ? 1 : 0;
  else if (binding.kind === "pointer_button") value = pointerButtons.has(binding.code) ? 1 : 0;
  else if (binding.kind === "gamepad_button") value = gamepadButtons[`${device}:${binding.code}`] || 0;
  else if (binding.kind === "gamepad_axis") value = gamepadAxes[`${device}:${binding.code}`] || 0;
  else if (binding.kind === "touch_axis") value = touchAxes[binding.code] || 0;
  return clamp(value, -1, 1) * scale;
}

function sampleActions() {
  pollGamepads();
  if (joystickPointer !== null) {
    const dx = joystickCurrent.x - joystickStart.x;
    const dy = joystickCurrent.y - joystickStart.y;
    const radius = 70;
    touchAxes.move_x = clamp(dx / radius, -1, 1);
    touchAxes.move_y = clamp(dy / radius, -1, 1);
  }
  const result = Object.create(null);
  for (const action of actionDefinitions.values()) {
    const samples = action.bindings.map(bindingValue);
    let value = action.combine === "max" ? samples.reduce((best, sample) => Math.abs(sample) > Math.abs(best) ? sample : best, 0) : clamp(samples.reduce((sum, sample) => sum + sample, 0), -1, 1);
    const deadzone = action.deadzone ?? 0.15;
    if (Math.abs(value) < deadzone) value = 0;
    else value = Math.sign(value) * clamp((Math.abs(value) - deadzone) / (1 - deadzone), 0, 1);
    result[action.name] = value;
  }
  currentActions = result;
}
function actionValue(name) { return currentActions[name] || 0; }
function actionDown(name) { const def = actionDefinitions.get(name); return Math.abs(actionValue(name)) >= (def ? (def.threshold ?? 0.5) : 0.5); }
function actionPressed(name) { const def = actionDefinitions.get(name); const threshold = def ? (def.threshold ?? 0.5) : 0.5; return Math.abs(actionValue(name)) >= threshold && Math.abs(previousActions[name] || 0) < threshold; }

function unlockAudio() {
  if (muted) return;
  if (!audioContext) {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (AudioCtx) audioContext = new AudioCtx();
  }
  if (audioContext && audioContext.state === "suspended") audioContext.resume();
}

function playCue(id, gainScale = 1, pitchRatio = 1) {
  if (muted || !audioContext || !audioCues.has(id)) return;
  const cue = audioCues.get(id);
  const now = audioContext.currentTime;
  const end = now + cue.duration + (cue.envelope?.release || 0.08) + 0.02;
  const gain = audioContext.createGain();
  const envelope = cue.envelope || {attack: 0.005, decay: 0.04, sustain: 0.55, release: 0.08};
  const volume = clamp((cue.volume ?? 0.2) * gainScale, 0, 1);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(Math.max(0.0001, volume), now + Math.max(0.001, envelope.attack));
  gain.gain.exponentialRampToValueAtTime(Math.max(0.0001, volume * envelope.sustain), now + envelope.attack + Math.max(0.001, envelope.decay));
  gain.gain.setValueAtTime(Math.max(0.0001, volume * envelope.sustain), now + cue.duration);
  gain.gain.exponentialRampToValueAtTime(0.0001, end);
  gain.connect(audioContext.destination);
  const oscillator = audioContext.createOscillator();
  oscillator.type = cue.waveform || "sine";
  oscillator.frequency.setValueAtTime(cue.frequency * pitchRatio, now);
  if (cue.sweep_to) oscillator.frequency.exponentialRampToValueAtTime(cue.sweep_to * pitchRatio, now + cue.duration);
  oscillator.detune.setValueAtTime(cue.detune || 0, now);
  oscillator.connect(gain);
  oscillator.start(now);
  oscillator.stop(end);
  if ((cue.noise || 0) > 0) {
    const frames = Math.max(1, Math.floor(audioContext.sampleRate * cue.duration));
    const buffer = audioContext.createBuffer(1, frames, audioContext.sampleRate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < frames; i += 1) channel[i] = (Math.random() * 2 - 1) * cue.noise;
    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(gain);
    source.start(now);
  }
}

function scheduleMusic(dt) {
  const sequenceId = sceneRules.music;
  if (!sequenceId || !audioSequences.has(sequenceId) || muted || !audioContext) return;
  const sequence = audioSequences.get(sequenceId);
  const beatDuration = 60 / sequence.bpm;
  if (!musicClock) musicClock = {beat: 0, previous: -1};
  musicClock.beat += dt / beatDuration;
  let currentBeat = sequence.loop ? musicClock.beat % sequence.length_beats : Math.min(sequence.length_beats, musicClock.beat);
  let previousBeat = musicClock.previous;
  for (const note of sequence.notes) {
    const crossed = previousBeat < 0 ? note.beat <= currentBeat : currentBeat >= previousBeat ? note.beat > previousBeat && note.beat <= currentBeat : note.beat > previousBeat || note.beat <= currentBeat;
    if (crossed) playCue(note.cue_id, note.gain ?? 1, note.pitch_ratio ?? 1);
  }
  musicClock.previous = currentBeat;
}

function resetScene() {
  scene = deepClone(PROJECT.scenes[PROJECT.start_scene]);
  entities = scene.entities || [];
  entityMap = new Map(entities.map(entity => [entity.id, entity]));
  for (const entity of entities) {
    entity.active = entity.active !== false;
    entity.tags = entity.tags || [];
    entity.components = entity.components || {};
    const transform = component(entity, "transform");
    if (transform) {
      transform.position = transform.position || [0, 0];
      transform.scale = transform.scale || [1, 1];
      transform.rotation = transform.rotation || 0;
      transform._base_scale = [...transform.scale];
    }
    const body = component(entity, "body");
    if (body) {
      body.velocity = body.velocity || [0, 0];
      body.acceleration = body.acceleration || [0, 0];
      body.force = body.force || [0, 0];
    }
    const health = component(entity, "health");
    if (health) {
      health.current = health.current ?? health.maximum;
      health.invulnerable_remaining = 0;
    }
    const controller = component(entity, "player_controller");
    if (controller) {
      controller.dash_remaining = 0;
      controller.cooldown_remaining = 0;
      controller.last_direction = controller.last_direction || [1, 0];
    }
    const hazard = component(entity, "hazard");
    if (hazard) hazard._last_hits = Object.create(null);
  }
  state = deepClone(scene.initial_state || {});
  state.score = state.score || 0;
  state.scene = scene.id;
  state.best_score = Number(localStorage.getItem(`${PROJECT.metadata.id}:best`) || 0);
  worldSize = scene.world_size || [baseWidth, baseHeight];
  sceneRules = scene.rules || {};
  contacts = new Set();
  triggerContacts = new Set();
  particles = [];
  eventLog = [];
  tick = 0;
  gameTime = 0;
  paused = false;
  won = false;
  gameOver = false;
  musicClock = null;
  previousActions = Object.create(null);
  currentActions = Object.create(null);
  configureVisualGraphs();
  runVisualGraphBatch("Ready", 0, false, () => runVisualGraphs("ready", 0));
  const cameraEntity = entities.find(entity => entity.active !== false && component(entity, "camera"));
  camera = cameraEntity ? component(cameraEntity, "camera") : {position: [worldSize[0] / 2, worldSize[1] / 2], zoom: 1, rotation: 0, follow_entity: sceneRules.player_id || null, follow_smoothing: 8};
  camera.position = camera.position || [worldSize[0] / 2, worldSize[1] / 2];
  camera.zoom = camera.zoom || 1;
  camera.rotation = camera.rotation || 0;
  updateStatus("Ready");
}

function playerEntity() {
  if (sceneRules.player_id && entityMap.has(sceneRules.player_id)) return entityMap.get(sceneRules.player_id);
  return entities.find(entity => entity.active !== false && hasTag(entity, "player"));
}

function updateControllers(dt) {
  for (const entity of entitiesWith("transform", "player_controller")) {
    const controller = component(entity, "player_controller");
    const body = component(entity, "body");
    let x = actionValue(controller.x_action || "move_x");
    let y = actionValue(controller.y_action || "move_y");
    const magnitude = Math.hypot(x, y);
    if (magnitude > 1) { x /= magnitude; y /= magnitude; }
    if (magnitude > 0.001) controller.last_direction = normalize(x, y);
    controller.cooldown_remaining = Math.max(0, (controller.cooldown_remaining || 0) - dt);
    controller.dash_remaining = Math.max(0, (controller.dash_remaining || 0) - dt);
    let speed = controller.speed ?? 220;
    if (controller.dash_remaining > 0) {
      speed = controller.dash_speed ?? 520;
      [x, y] = controller.last_direction;
    } else if (controller.dash_action && actionPressed(controller.dash_action) && controller.cooldown_remaining <= 0) {
      controller.dash_remaining = controller.dash_duration ?? 0.12;
      controller.cooldown_remaining = controller.dash_cooldown ?? 0.65;
      speed = controller.dash_speed ?? 520;
      [x, y] = controller.last_direction;
      emit("dash", entity.id);
      playCue(sceneRules.dash_sound || "dash");
      spawnBurst(component(entity, "transform").position, "#7cf7ff", 12, 130);
    }
    if (body) body.velocity = [x * speed, y * speed];
    else {
      const transform = component(entity, "transform");
      transform.position[0] += x * speed * dt;
      transform.position[1] += y * speed * dt;
    }
  }
}

function updateBehaviors(dt) {
  for (const entity of entities) {
    if (entity.active === false) continue;
    const transform = component(entity, "transform");
    if (!transform) continue;
    const spin = component(entity, "spin");
    if (spin) transform.rotation += (spin.speed || 0) * dt;
    const pulse = component(entity, "pulse");
    if (pulse) {
      const base = transform._base_scale || [1, 1];
      const amount = pulse.amount ?? 0.12;
      const speed = pulse.speed ?? 3;
      const factor = 1 + Math.sin(gameTime * speed + (pulse.phase || 0)) * amount;
      transform.scale = [base[0] * factor, base[1] * factor];
    }
    const patrol = component(entity, "patrol");
    const body = component(entity, "body");
    if (patrol && body) {
      if (!patrol._initialized) {
        const direction = patrol.direction || [1, 0];
        const n = normalize(direction[0], direction[1]);
        body.velocity = [n[0] * (patrol.speed || 100), n[1] * (patrol.speed || 100)];
        patrol._initialized = true;
      }
    }
  }
}

function integratePhysics(dt) {
  const gravity = sceneRules.gravity || [0, 0];
  for (const entity of entitiesWith("transform", "body")) {
    const transform = component(entity, "transform");
    const body = component(entity, "body");
    if ((body.body_type || "dynamic") === "static") continue;
    if ((body.body_type || "dynamic") === "dynamic") {
      const mass = Math.max(1e-6, body.mass || 1);
      const ax = (body.acceleration?.[0] || 0) + gravity[0] * (body.gravity_scale ?? 1) + (body.force?.[0] || 0) / mass;
      const ay = (body.acceleration?.[1] || 0) + gravity[1] * (body.gravity_scale ?? 1) + (body.force?.[1] || 0) / mass;
      body.velocity[0] += ax * dt;
      body.velocity[1] += ay * dt;
      if ((body.damping || 0) > 0) {
        const damping = Math.exp(-body.damping * dt);
        body.velocity[0] *= damping;
        body.velocity[1] *= damping;
      }
      if (body.max_speed) {
        const speed = Math.hypot(body.velocity[0], body.velocity[1]);
        if (speed > body.max_speed) {
          body.velocity[0] = body.velocity[0] / speed * body.max_speed;
          body.velocity[1] = body.velocity[1] / speed * body.max_speed;
        }
      }
    }
    transform.position[0] += body.velocity[0] * dt;
    transform.position[1] += body.velocity[1] * dt;
    if (!body.fixed_rotation) transform.rotation += (body.angular_velocity || 0) * dt;
    body.force = [0, 0];
  }
}

function applyBounds() {
  for (const entity of entitiesWith("transform", "bounds_constraint")) {
    const transform = component(entity, "transform");
    const constraint = component(entity, "bounds_constraint");
    const shape = constraint.bounds;
    const minimum = shape.minimum || [0, 0];
    const maximum = shape.maximum || worldSize;
    const body = component(entity, "body");
    let [x, y] = transform.position;
    if (constraint.mode === "wrap") {
      if (x < minimum[0]) x = maximum[0]; else if (x > maximum[0]) x = minimum[0];
      if (y < minimum[1]) y = maximum[1]; else if (y > maximum[1]) y = minimum[1];
    } else {
      const cx = clamp(x, minimum[0], maximum[0]);
      const cy = clamp(y, minimum[1], maximum[1]);
      if (body && constraint.mode === "bounce") {
        if (cx !== x) body.velocity[0] = -body.velocity[0] * (body.restitution ?? 1);
        if (cy !== y) body.velocity[1] = -body.velocity[1] * (body.restitution ?? 1);
      }
      x = cx; y = cy;
    }
    transform.position = [x, y];
  }
}

function worldShape(entity) {
  const transform = component(entity, "transform");
  const collider = component(entity, "collider");
  if (!transform || !collider || collider.enabled === false) return null;
  const shape = collider.shape || {type: "circle", radius: 0.5};
  const offset = collider.offset || [0, 0];
  const ox = transform.position[0] + offset[0] * transform.scale[0];
  const oy = transform.position[1] + offset[1] * transform.scale[1];
  if (shape.type === "circle") {
    return {type: "circle", x: ox + (shape.center?.[0] || 0), y: oy + (shape.center?.[1] || 0), radius: (shape.radius || 0) * Math.max(Math.abs(transform.scale[0]), Math.abs(transform.scale[1]))};
  }
  let minimum = shape.minimum;
  let maximum = shape.maximum;
  if (shape.half_extents) {
    const center = shape.center || [0, 0];
    minimum = [center[0] - shape.half_extents[0], center[1] - shape.half_extents[1]];
    maximum = [center[0] + shape.half_extents[0], center[1] + shape.half_extents[1]];
  }
  if (shape.type === "polygon") {
    const points = shape.points || [];
    minimum = [Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1]))];
    maximum = [Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))];
  }
  minimum = minimum || [-0.5, -0.5];
  maximum = maximum || [0.5, 0.5];
  const sx = Math.abs(transform.scale[0]);
  const sy = Math.abs(transform.scale[1]);
  const localHalfX = (maximum[0] - minimum[0]) * 0.5 * sx;
  const localHalfY = (maximum[1] - minimum[1]) * 0.5 * sy;
  const localCenterX = (minimum[0] + maximum[0]) * 0.5 * transform.scale[0];
  const localCenterY = (minimum[1] + maximum[1]) * 0.5 * transform.scale[1];
  const c = Math.abs(Math.cos(transform.rotation || 0));
  const s = Math.abs(Math.sin(transform.rotation || 0));
  const halfX = localHalfX * c + localHalfY * s;
  const halfY = localHalfX * s + localHalfY * c;
  const x = ox + localCenterX;
  const y = oy + localCenterY;
  return {type: "aabb", minX: x - halfX, minY: y - halfY, maxX: x + halfX, maxY: y + halfY, x, y};
}

function collisionFilter(entity) {
  const filter = component(entity, "collider")?.filter || {};
  return {layer: filter.layer ?? 1, mask: filter.mask ?? 0xffffffff, sensor: !!filter.sensor};
}
function filtersAllow(a, b) { return !!((a.mask & b.layer) && (b.mask & a.layer)); }
function collideShapes(a, b) {
  if (a.type === "circle" && b.type === "circle") {
    const dx = b.x - a.x; const dy = b.y - a.y; const d = Math.hypot(dx, dy); const r = a.radius + b.radius;
    if (d > r) return null;
    const n = d > 1e-9 ? [dx / d, dy / d] : [1, 0];
    return {normal: n, penetration: Math.max(0, r - d)};
  }
  if (a.type === "aabb" && b.type === "aabb") {
    const ox = Math.min(a.maxX, b.maxX) - Math.max(a.minX, b.minX);
    const oy = Math.min(a.maxY, b.maxY) - Math.max(a.minY, b.minY);
    if (ox < 0 || oy < 0) return null;
    if (ox <= oy) return {normal: [b.x >= a.x ? 1 : -1, 0], penetration: ox};
    return {normal: [0, b.y >= a.y ? 1 : -1], penetration: oy};
  }
  if (a.type === "circle") {
    const hit = collideCircleAabb(a, b);
    return hit;
  }
  if (b.type === "circle") {
    const hit = collideCircleAabb(b, a);
    return hit ? {normal: [-hit.normal[0], -hit.normal[1]], penetration: hit.penetration} : null;
  }
  return null;
}
function collideCircleAabb(circle, box) {
  const closestX = clamp(circle.x, box.minX, box.maxX);
  const closestY = clamp(circle.y, box.minY, box.maxY);
  let dx = closestX - circle.x;
  let dy = closestY - circle.y;
  let d = Math.hypot(dx, dy);
  if (d > circle.radius) return null;
  if (d < 1e-9) {
    const choices = [
      [Math.abs(circle.x - box.minX), -1, 0], [Math.abs(box.maxX - circle.x), 1, 0],
      [Math.abs(circle.y - box.minY), 0, -1], [Math.abs(box.maxY - circle.y), 0, 1],
    ].sort((x, y) => x[0] - y[0]);
    return {normal: [choices[0][1], choices[0][2]], penetration: circle.radius + choices[0][0]};
  }
  // Normal must point from circle (a) toward box (b).
  return {normal: [dx / d, dy / d], penetration: circle.radius - d};
}

function inverseMass(entity) {
  const body = component(entity, "body");
  return body && (body.body_type || "dynamic") === "dynamic" ? 1 / Math.max(1e-6, body.mass || 1) : 0;
}
function resolveCollision(a, b, manifold) {
  const filterA = collisionFilter(a); const filterB = collisionFilter(b);
  if (filterA.sensor || filterB.sensor) return;
  const invA = inverseMass(a); const invB = inverseMass(b); const total = invA + invB;
  if (total <= 0) return;
  const correction = Math.max(0, manifold.penetration - 0.001) * 0.82 / total;
  const ta = component(a, "transform"); const tb = component(b, "transform");
  if (invA > 0) { ta.position[0] -= manifold.normal[0] * correction * invA; ta.position[1] -= manifold.normal[1] * correction * invA; }
  if (invB > 0) { tb.position[0] += manifold.normal[0] * correction * invB; tb.position[1] += manifold.normal[1] * correction * invB; }
  const ba = component(a, "body"); const bb = component(b, "body");
  const va = ba ? ba.velocity : [0, 0]; const vb = bb ? bb.velocity : [0, 0];
  const rvx = vb[0] - va[0]; const rvy = vb[1] - va[1];
  const normalVelocity = rvx * manifold.normal[0] + rvy * manifold.normal[1];
  if (normalVelocity >= 0) return;
  const restitution = Math.min(ba?.restitution || 0, bb?.restitution || 0);
  const impulse = -(1 + restitution) * normalVelocity / total;
  if (ba && invA > 0) { ba.velocity[0] -= manifold.normal[0] * impulse * invA; ba.velocity[1] -= manifold.normal[1] * impulse * invA; }
  if (bb && invB > 0) { bb.velocity[0] += manifold.normal[0] * impulse * invB; bb.velocity[1] += manifold.normal[1] * impulse * invB; }
}

function processGameplayContact(a, b, manifold, entered) {
  const arrangements = [[a, b, manifold.normal], [b, a, [-manifold.normal[0], -manifold.normal[1]]]];
  for (const [special, other, normal] of arrangements) {
    const collectible = component(special, "collectible");
    if (entered && collectible && hasTag(other, "player") && special.active !== false) {
      const key = collectible.state_key || "score";
      state[key] = (state[key] || 0) + (collectible.points || 1);
      special.active = false;
      emit("collected", other.id, special.id, {points: collectible.points || 1});
      playCue(collectible.sound || sceneRules.collect_sound || "collect");
      spawnBurst(component(special, "transform").position, "#ffe56f", 18, 180);
      state.best_score = Math.max(state.best_score || 0, state[key]);
      localStorage.setItem(`${PROJECT.metadata.id}:best`, String(state.best_score));
    }
    const hazard = component(special, "hazard");
    const health = component(other, "health");
    if (hazard && health && hasTag(other, "player")) {
      hazard._last_hits = hazard._last_hits || Object.create(null);
      const last = hazard._last_hits[other.id] ?? -Infinity;
      if (gameTime - last >= (hazard.cooldown ?? 0.5) && (health.invulnerable_remaining || 0) <= 0) {
        hazard._last_hits[other.id] = gameTime;
        health.current = Math.max(0, health.current - (hazard.damage ?? 1));
        health.invulnerable_remaining = health.invulnerability || 0;
        const body = component(other, "body");
        if (body) {
          body.velocity[0] -= normal[0] * (hazard.knockback || 220);
          body.velocity[1] -= normal[1] * (hazard.knockback || 220);
        }
        emit("damaged", special.id, other.id, {damage: hazard.damage || 1, health: health.current});
        playCue(hazard.sound || sceneRules.damage_sound || "damage");
        spawnBurst(component(other, "transform").position, "#ff6b7c", 12, 140);
      }
    }
  }
}

function collisionStep() {
  const colliders = entitiesWith("transform", "collider").filter(entity => component(entity, "collider").enabled !== false);
  const nextContacts = new Set();
  const nextTriggerContacts = new Set();
  for (let i = 0; i < colliders.length; i += 1) {
    const a = colliders[i]; const shapeA = worldShape(a); const filterA = collisionFilter(a);
    for (let j = i + 1; j < colliders.length; j += 1) {
      const b = colliders[j]; const filterB = collisionFilter(b);
      if (!filtersAllow(filterA, filterB)) continue;
      const manifold = collideShapes(shapeA, worldShape(b));
      if (!manifold) continue;
      const key = pairKey(a.id, b.id);
      const entered = !contacts.has(key);
      nextContacts.add(key);
      emit(entered ? "collision_enter" : "collision_stay", a.id, b.id, manifold);
      const triggerPair = filterA.sensor && !filterB.sensor && hasTag(b, "player")
        ? [a, b]
        : filterB.sensor && !filterA.sensor && hasTag(a, "player")
          ? [b, a]
          : null;
      if (triggerPair) {
        const [sensor, player] = triggerPair;
        const triggerKey = `${sensor.id}|${player.id}`;
        nextTriggerContacts.add(triggerKey);
        if (!triggerContacts.has(triggerKey)) {
          emit("trigger_enter", sensor.id, player.id);
          runTriggerVisualGraphs("trigger_enter", sensor.id, player.id);
        }
      }
      resolveCollision(a, b, manifold);
      processGameplayContact(a, b, manifold, entered);
    }
  }
  for (const key of contacts) if (!nextContacts.has(key)) emit("collision_exit", key.split("|")[0], key.split("|")[1]);
  for (const key of triggerContacts) {
    if (nextTriggerContacts.has(key)) continue;
    const [sensor, player] = key.split("|");
    emit("trigger_exit", sensor, player);
    runTriggerVisualGraphs("trigger_exit", sensor, player);
  }
  contacts = nextContacts;
  triggerContacts = nextTriggerContacts;
}

function updateHealth(dt) {
  for (const entity of entitiesWith("health")) {
    const health = component(entity, "health");
    health.invulnerable_remaining = Math.max(0, (health.invulnerable_remaining || 0) - dt);
  }
}

function updateCamera(dt) {
  if (!camera.follow_entity) return;
  const target = entityMap.get(camera.follow_entity);
  if (!target || target.active === false || !component(target, "transform")) return;
  const p = component(target, "transform").position;
  const smoothing = camera.follow_smoothing ?? 8;
  const alpha = smoothing <= 0 ? 1 : 1 - Math.exp(-smoothing * dt);
  camera.position[0] += (p[0] - camera.position[0]) * alpha;
  camera.position[1] += (p[1] - camera.position[1]) * alpha;
  const halfW = baseWidth * 0.5 / (camera.zoom || 1);
  const halfH = baseHeight * 0.5 / (camera.zoom || 1);
  if (worldSize[0] > halfW * 2) camera.position[0] = clamp(camera.position[0], halfW, worldSize[0] - halfW);
  else camera.position[0] = worldSize[0] * 0.5;
  if (worldSize[1] > halfH * 2) camera.position[1] = clamp(camera.position[1], halfH, worldSize[1] - halfH);
  else camera.position[1] = worldSize[1] * 0.5;
}

function checkGameState() {
  const scoreTarget = sceneRules.score_to_win;
  if (!won && scoreTarget != null && (state.score || 0) >= scoreTarget) {
    won = true;
    emit("game_won", null, null, {score: state.score});
    playCue(sceneRules.win_sound || "win");
    const player = playerEntity();
    if (player) spawnBurst(component(player, "transform").position, "#9dffb0", 56, 260);
    updateStatus("Victory");
  }
  const player = playerEntity();
  const health = player ? component(player, "health") : null;
  if (!gameOver && health && health.current <= 0) {
    gameOver = true;
    emit("game_over", null, player.id);
    playCue(sceneRules.game_over_sound || "game_over");
    updateStatus("Game over");
  }
}

function update(dt) {
  sampleActions();
  if (actionPressed(sceneRules.pause_action || "pause")) paused = !paused;
  if (actionPressed(sceneRules.restart_action || "restart")) resetScene();
  if (actionPressed("mute")) muted = !muted;
  if (actionPressed("save")) saveGame();
  if (actionPressed("load")) loadGame();
  if (!paused && !won && !gameOver) {
    runVisualGraphBatch("fixed-step", dt, true, () => {
      updateControllers(dt);
      updateBehaviors(dt);
      integratePhysics(dt);
      applyBounds();
      collisionStep();
      updateHealth(dt);
      runVisualGraphs("tick", dt);
      updateCamera(dt);
      scheduleMusic(dt);
      checkGameState();
    });
    flushGraphDespawns();
    gameTime += dt;
    tick += 1;
  }
  updateParticles(dt);
  previousActions = {...currentActions};
  touchAxes.dash = 0;
}

function spawnBurst(position, color, count, speed) {
  for (let i = 0; i < count; i += 1) {
    const angle = Math.random() * Math.PI * 2;
    const magnitude = speed * (0.35 + Math.random() * 0.65);
    particles.push({x: position[0], y: position[1], vx: Math.cos(angle) * magnitude, vy: Math.sin(angle) * magnitude, life: 0.35 + Math.random() * 0.5, maxLife: 0.85, color, size: 2 + Math.random() * 4});
  }
}
function updateParticles(dt) {
  for (const particle of particles) {
    particle.life -= dt;
    particle.x += particle.vx * dt;
    particle.y += particle.vy * dt;
    particle.vx *= Math.exp(-2.5 * dt);
    particle.vy *= Math.exp(-2.5 * dt);
  }
  particles = particles.filter(particle => particle.life > 0);
}

function worldToScreen(point) {
  const zoom = camera.zoom || 1;
  const dx = point[0] - camera.position[0];
  const dy = point[1] - camera.position[1];
  const c = Math.cos(-(camera.rotation || 0)); const s = Math.sin(-(camera.rotation || 0));
  return [baseWidth * 0.5 + (dx * c - dy * s) * zoom, baseHeight * 0.5 + (dx * s + dy * c) * zoom];
}

function resolvePaint(value, asset, path) {
  if (!value) return null;
  if (value === "currentColor") return path?.paint?.color || "#ffffff";
  if (!value.startsWith("@")) return value;
  const id = value.slice(1);
  const gradient = (asset.gradients || []).find(item => item.id === id);
  if (!gradient) return "#ff00ff";
  let paint;
  if (gradient.type === "linear") paint = ctx.createLinearGradient(gradient.start[0], gradient.start[1], gradient.end[0], gradient.end[1]);
  else {
    const focal = gradient.focal || gradient.center;
    paint = ctx.createRadialGradient(focal[0], focal[1], 0, gradient.center[0], gradient.center[1], gradient.radius);
  }
  for (const stop of gradient.stops) paint.addColorStop(stop.offset, stop.color);
  return paint;
}

function drawVectorEntity(entity) {
  const transform = component(entity, "transform");
  const renderer = component(entity, "vector_renderer");
  if (!transform || !renderer || renderer.visible === false || entity.active === false) return;
  const asset = assets[renderer.asset_id];
  if (!asset) return;
  const screen = worldToScreen(transform.position);
  const zoom = camera.zoom || 1;
  const extent = Math.max(asset.size?.[0] || 0, asset.size?.[1] || 0) * zoom * Math.max(Math.abs(transform.scale[0]), Math.abs(transform.scale[1]));
  if (screen[0] + extent < -80 || screen[1] + extent < -80 || screen[0] - extent > baseWidth + 80 || screen[1] - extent > baseHeight + 80) return;
  ctx.save();
  ctx.translate(screen[0], screen[1]);
  ctx.rotate((transform.rotation || 0) - (camera.rotation || 0));
  ctx.scale(transform.scale[0] * zoom, transform.scale[1] * zoom);
  if (renderer.shadow_blur) {
    ctx.shadowBlur = renderer.shadow_blur;
    ctx.shadowColor = renderer.shadow_color || "rgba(0,0,0,.55)";
  }
  ctx.globalAlpha = renderer.opacity ?? 1;
  ctx.translate(-(asset.pivot?.[0] || 0), -(asset.pivot?.[1] || 0));
  for (const path of asset.paths || []) {
    ctx.beginPath();
    for (const command of path.commands || []) {
      const op = command[0];
      if (op === "M") ctx.moveTo(command[1], command[2]);
      else if (op === "L") ctx.lineTo(command[1], command[2]);
      else if (op === "Q") ctx.quadraticCurveTo(command[1], command[2], command[3], command[4]);
      else if (op === "C") ctx.bezierCurveTo(command[1], command[2], command[3], command[4], command[5], command[6]);
      else if (op === "Z") ctx.closePath();
    }
    const paint = path.paint || {};
    ctx.lineCap = paint.line_cap || "round";
    ctx.lineJoin = paint.line_join || "round";
    ctx.lineWidth = paint.stroke_width ?? 1;
    const priorAlpha = ctx.globalAlpha;
    ctx.globalAlpha = priorAlpha * (paint.opacity ?? 1);
    const fill = resolvePaint(paint.fill, asset, path);
    if (fill) { ctx.fillStyle = fill; ctx.fill(path.fill_rule === "evenodd" ? "evenodd" : "nonzero"); }
    const stroke = resolvePaint(paint.stroke, asset, path);
    if (stroke && ctx.lineWidth > 0) { ctx.strokeStyle = stroke; ctx.stroke(); }
    ctx.globalAlpha = priorAlpha;
  }
  ctx.restore();
}

function drawBackground() {
  ctx.fillStyle = scene.background || display.background;
  ctx.fillRect(0, 0, baseWidth, baseHeight);
  const grid = sceneRules.grid || {};
  if (grid.enabled !== false) {
    const spacing = grid.spacing || 80;
    const zoom = camera.zoom || 1;
    const left = camera.position[0] - baseWidth * 0.5 / zoom;
    const top = camera.position[1] - baseHeight * 0.5 / zoom;
    ctx.save();
    ctx.strokeStyle = grid.color || "rgba(255,255,255,.055)";
    ctx.lineWidth = 1;
    const startX = Math.floor(left / spacing) * spacing;
    const startY = Math.floor(top / spacing) * spacing;
    for (let x = startX; x <= left + baseWidth / zoom + spacing; x += spacing) {
      const sx = worldToScreen([x, 0])[0];
      ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, baseHeight); ctx.stroke();
    }
    for (let y = startY; y <= top + baseHeight / zoom + spacing; y += spacing) {
      const sy = worldToScreen([0, y])[1];
      ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(baseWidth, sy); ctx.stroke();
    }
    ctx.restore();
  }
  if (sceneRules.vignette !== false) {
    const gradient = ctx.createRadialGradient(baseWidth / 2, baseHeight / 2, baseHeight * 0.2, baseWidth / 2, baseHeight / 2, baseWidth * 0.72);
    gradient.addColorStop(0, "rgba(0,0,0,0)"); gradient.addColorStop(1, "rgba(0,0,0,.42)");
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, baseWidth, baseHeight);
  }
}

function drawParticles() {
  for (const particle of particles) {
    const screen = worldToScreen([particle.x, particle.y]);
    ctx.globalAlpha = clamp(particle.life / particle.maxLife, 0, 1);
    ctx.fillStyle = particle.color;
    ctx.beginPath(); ctx.arc(screen[0], screen[1], particle.size * (camera.zoom || 1), 0, Math.PI * 2); ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function drawDebug() {
  ctx.save();
  ctx.lineWidth = 1;
  for (const entity of entitiesWith("transform", "collider")) {
    const shape = worldShape(entity);
    if (!shape) continue;
    ctx.strokeStyle = collisionFilter(entity).sensor ? "#50f0ff" : "#ff4f8b";
    if (shape.type === "circle") {
      const p = worldToScreen([shape.x, shape.y]);
      ctx.beginPath(); ctx.arc(p[0], p[1], shape.radius * (camera.zoom || 1), 0, Math.PI * 2); ctx.stroke();
    } else {
      const p0 = worldToScreen([shape.minX, shape.minY]); const p1 = worldToScreen([shape.maxX, shape.maxY]);
      ctx.strokeRect(p0[0], p0[1], p1[0] - p0[0], p1[1] - p0[1]);
    }
  }
  ctx.fillStyle = "rgba(0,0,0,.72)"; ctx.fillRect(10, baseHeight - 100, 320, 88);
  ctx.fillStyle = "#c7ffe9"; ctx.font = "13px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.fillText(`KC ${VERSION} ${CODENAME}`, 22, baseHeight - 76);
  ctx.fillText(`fps ${fps.toFixed(1)} | tick ${tick} | active ${entities.filter(e => e.active !== false).length}`, 22, baseHeight - 56);
  ctx.fillText(`camera ${camera.position[0].toFixed(1)}, ${camera.position[1].toFixed(1)} | events ${eventLog.length}`, 22, baseHeight - 36);
  ctx.restore();
}

function resolveTemplate(text) {
  const player = playerEntity();
  const health = player ? component(player, "health") : null;
  return String(text)
    .replaceAll("{score}", String(state.score || 0))
    .replaceAll("{target}", String(sceneRules.score_to_win || 0))
    .replaceAll("{health}", health ? String(Math.ceil(health.current)) : "-")
    .replaceAll("{best}", String(state.best_score || 0));
}

function drawHud() {
  const player = playerEntity();
  const health = player ? component(player, "health") : null;
  ctx.save();
  ctx.fillStyle = "rgba(7,10,25,.72)";
  ctx.beginPath(); ctx.roundRect(18, 16, 280, 74, 14); ctx.fill();
  ctx.fillStyle = "#f7fbff"; ctx.font = "700 18px system-ui, sans-serif"; ctx.fillText(PROJECT.metadata.title, 34, 44);
  ctx.fillStyle = "#a9bad9"; ctx.font = "13px system-ui, sans-serif";
  const target = sceneRules.score_to_win;
  ctx.fillText(target ? `Crystals ${state.score || 0} / ${target}` : `Score ${state.score || 0}`, 34, 68);
  if (health) {
    const ratio = clamp(health.current / health.maximum, 0, 1);
    ctx.fillStyle = "rgba(255,255,255,.12)"; ctx.fillRect(160, 58, 116, 10);
    ctx.fillStyle = ratio > 0.45 ? "#75f0a5" : ratio > 0.2 ? "#ffd66f" : "#ff6b7c"; ctx.fillRect(160, 58, 116 * ratio, 10);
  }
  for (const item of scene.ui || []) {
    if (item.type !== "text") continue;
    ctx.font = item.font || "14px system-ui, sans-serif";
    ctx.textAlign = item.align || "left";
    ctx.fillStyle = item.color || "#ffffff";
    ctx.globalAlpha = item.opacity ?? 1;
    ctx.fillText(resolveTemplate(item.text || ""), item.position?.[0] || 0, item.position?.[1] || 0);
  }
  ctx.restore();
}

function drawOverlay() {
  if (!(paused || won || gameOver)) return;
  ctx.save();
  ctx.fillStyle = "rgba(5,7,18,.76)"; ctx.fillRect(0, 0, baseWidth, baseHeight);
  ctx.textAlign = "center";
  ctx.fillStyle = won ? "#9dffb0" : gameOver ? "#ff7d8d" : "#f4f7ff";
  ctx.font = "800 48px system-ui, sans-serif";
  ctx.fillText(won ? "Vector Garden Complete" : gameOver ? "Signal Lost" : "Paused", baseWidth / 2, baseHeight / 2 - 28);
  ctx.fillStyle = "#d4def2"; ctx.font = "18px system-ui, sans-serif";
  ctx.fillText(won ? `You collected all ${state.score || 0} crystals.` : gameOver ? "Press R or the restart action to try again." : "Press P / Escape to continue.", baseWidth / 2, baseHeight / 2 + 16);
  if (won || gameOver) {
    ctx.fillStyle = "#8fa5c8"; ctx.font = "14px system-ui, sans-serif";
    ctx.fillText("R: restart • F3: diagnostics • M: mute", baseWidth / 2, baseHeight / 2 + 54);
  }
  ctx.restore();
}

function drawTouchControls() {
  const touchCapable = navigator.maxTouchPoints > 0;
  touchNode.hidden = !touchCapable;
  if (!touchCapable) return;
  ctx.save();
  ctx.globalAlpha = 0.2;
  const center = joystickPointer === null ? {x: 104, y: baseHeight - 104} : joystickStart;
  ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.arc(center.x, center.y, 62, 0, Math.PI * 2); ctx.stroke();
  const knob = joystickPointer === null ? center : {x: center.x + clamp(joystickCurrent.x - center.x, -52, 52), y: center.y + clamp(joystickCurrent.y - center.y, -52, 52)};
  ctx.fillStyle = "#ffffff"; ctx.beginPath(); ctx.arc(knob.x, knob.y, 24, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.arc(baseWidth - 94, baseHeight - 94, 46, 0, Math.PI * 2); ctx.stroke();
  ctx.font = "700 13px system-ui"; ctx.textAlign = "center"; ctx.fillText("DASH", baseWidth - 94, baseHeight - 89);
  ctx.restore();
}

function render() {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.imageSmoothingEnabled = display.antialias !== false;
  drawBackground();
  const renderables = entitiesWith("transform", "vector_renderer").sort((a, b) => {
    const za = component(a, "vector_renderer").z_index || 0;
    const zb = component(b, "vector_renderer").z_index || 0;
    return za - zb || a.id.localeCompare(b.id);
  });
  for (const entity of renderables) drawVectorEntity(entity);
  drawParticles();
  drawHud();
  drawTouchControls();
  if (debug) drawDebug();
  drawOverlay();
}

function saveGame() {
  const payload = {
    schema: "ugts-kc-html5-save-1",
    project: PROJECT.metadata.id,
    project_version: PROJECT.metadata.version,
    state,
    gameTime,
    tick,
    entities: entities.map(entity => ({
      id: entity.id,
      active: entity.active !== false,
      transform: deepClone(component(entity, "transform")),
      body: deepClone(component(entity, "body")),
      health: deepClone(component(entity, "health")),
    })),
  };
  localStorage.setItem(`${PROJECT.metadata.id}:save`, JSON.stringify(payload));
  updateStatus("Game saved");
  playCue(sceneRules.save_sound || "save");
  return payload;
}
function loadGame() {
  const raw = localStorage.getItem(`${PROJECT.metadata.id}:save`);
  if (!raw) { updateStatus("No saved game"); return false; }
  try {
    const payload = JSON.parse(raw);
    if (payload.schema !== "ugts-kc-html5-save-1" || payload.project !== PROJECT.metadata.id) throw new Error("incompatible save");
    state = payload.state || {};
    gameTime = payload.gameTime || 0;
    tick = payload.tick || 0;
    for (const saved of payload.entities || []) {
      const entity = entityMap.get(saved.id);
      if (!entity) continue;
      entity.active = saved.active;
      if (saved.transform) entity.components.transform = saved.transform;
      if (saved.body) entity.components.body = saved.body;
      if (saved.health) entity.components.health = saved.health;
    }
    won = false; gameOver = false; paused = false; contacts.clear(); triggerContacts.clear();
    updateStatus("Game loaded");
    return true;
  } catch (error) {
    console.error(error); updateStatus("Save could not be loaded"); return false;
  }
}

function updateStatus(message) {
  statusNode.textContent = message;
}

function frame(timestamp) {
  const elapsed = Math.min(0.25, Math.max(0, (timestamp - previousTimestamp) / 1000));
  previousTimestamp = timestamp;
  accumulator += elapsed;
  let steps = 0;
  while (accumulator >= fixedDt && steps < 8) {
    update(fixedDt);
    accumulator -= fixedDt;
    steps += 1;
  }
  render();
  frameCounter += 1;
  if (timestamp - fpsTime >= 500) {
    fps = frameCounter * 1000 / (timestamp - fpsTime);
    frameCounter = 0; fpsTime = timestamp;
  }
  requestAnimationFrame(frame);
}

window.KCGame = {
  version: VERSION,
  codename: CODENAME,
  project: PROJECT,
  state: () => deepClone(state),
  entities: () => deepClone(entities),
  events: () => deepClone(eventLog),
  pause: value => { paused = value == null ? !paused : !!value; },
  restart: resetScene,
  save: saveGame,
  load: loadGame,
  step: count => {
    const steps = count == null ? 1 : Number(count);
    if (!Number.isInteger(steps) || steps < 1 || steps > 600) throw new Error("step count must be an integer from 1 to 600");
    for (let index = 0; index < steps; index += 1) update(fixedDt);
    return deepClone(state);
  },
  playCue,
  setDebug: value => { debug = !!value; },
};

resetScene();
requestAnimationFrame(frame);
})();
'''


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="__THEME_COLOR__">
<title>__TITLE__</title>
<style>
:root{color-scheme:dark;background:#050712;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}html,body{width:100%;height:100%;margin:0;overflow:hidden;background:#050712;overscroll-behavior:none}
body{display:grid;place-items:center}#kc-shell{position:relative;display:grid;place-items:center;width:100%;height:100%;isolation:isolate}
#kc-canvas{display:block;max-width:none;max-height:none;touch-action:none;outline:none;box-shadow:0 24px 90px rgba(0,0,0,.55)}
#kc-status{position:fixed;left:-10000px;width:1px;height:1px;overflow:hidden}
#kc-touch[hidden]{display:none}#kc-credit{position:fixed;right:12px;bottom:8px;color:rgba(255,255,255,.35);font-size:10px;pointer-events:none;letter-spacing:.04em}
@media (prefers-reduced-motion:reduce){#kc-canvas{scroll-behavior:auto}}
</style>
</head>
<body>
<main id="kc-shell">
<canvas id="kc-canvas" tabindex="0" role="application" aria-label="__TITLE__ game canvas"></canvas>
<div id="kc-touch" aria-hidden="true"></div>
<div id="kc-status" role="status" aria-live="polite">Loading</div>
<div id="kc-credit">UGTS-KC __KC_VERSION__ · KC Elizabeth</div>
</main>
<script id="kc-project" type="application/json">__PROJECT_JSON__</script>
__RUNTIME_SCRIPT__
</body>
</html>
'''


def build_html5(
    project: GameProject,
    output_dir: str | Path,
    *,
    single_file: bool | None = None,
    clean: bool = True,
) -> Html5BuildResult:
    """Build a browser-playable Canvas game with no external dependencies."""
    report = project.validate()
    graph_runtime = _compile_web_visual_graphs(project)
    output = Path(output_dir)
    if clean and output.exists():
        for child in output.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                import shutil
                shutil.rmtree(child)
    output.mkdir(parents=True, exist_ok=True)
    if single_file is None:
        single_file = bool(project.build.get("single_file", True))
    runtime = _RUNTIME_JS.replace("__KC_VERSION__", __version__).replace("__KC_CODENAME__", __codename__)
    project_dict = project.to_dict()
    project_dict["web_visual_graph_runtime"] = graph_runtime
    project_json = _safe_script_json(project_dict)
    title = project.metadata.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    if single_file:
        runtime_script = f"<script>\n{runtime}\n</script>"
    else:
        runtime_path = output / "kc-runtime.js"
        runtime_path.write_text(runtime + "\n", encoding="utf-8")
        runtime_script = '<script src="kc-runtime.js"></script>'
    html = (
        _HTML_TEMPLATE.replace("__TITLE__", title)
        .replace("__THEME_COLOR__", project.display.background)
        .replace("__PROJECT_JSON__", project_json)
        .replace("__RUNTIME_SCRIPT__", runtime_script)
        .replace("__KC_VERSION__", __version__)
    )
    entrypoint = output / "index.html"
    entrypoint.write_text(html, encoding="utf-8")
    (output / "project.json").write_text(json.dumps(project_dict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    readme = f"""{project.metadata.title}\n{'=' * len(project.metadata.title)}\n\nBuilt with UGTS-KC {__version__} — {__codename__}.\n\nOpen index.html in a modern browser. The build is self-contained and does not require a network connection.\nFor browsers that restrict local-file features, run: python -m http.server 8000\nThen open http://localhost:8000/ in the browser.\n\nDefault controls are defined in project.json. This build also exposes window.KCGame for pause, restart, save, load, state and diagnostics.\n"""
    (output / "README.txt").write_text(readme, encoding="utf-8")
    files = tuple(sorted(path for path in output.iterdir() if path.is_file()))
    total_bytes = sum(path.stat().st_size for path in files)
    warnings = tuple(issue.message for issue in report.issues if issue.severity == "warning")
    build_report = {
        "schema": "ugts-kc-html5-build-3.9",
        "runtime_version": __version__,
        "codename": __codename__,
        "project_id": project.metadata.id,
        "project_version": project.metadata.version,
        "project_hash": project.content_hash(),
        "single_file": single_file,
        "visual_graph_runtime": {
            "schema": graph_runtime["schema"],
            "graph_count": graph_runtime["graph_count"],
            "binding_count": graph_runtime["binding_count"],
            "supported_node_types": sorted(_WEB_VISUAL_GRAPH_NODE_TYPES),
        },
        "files": [{"name": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files],
        "validation": report.to_dict(),
        "warnings": list(warnings),
    }
    report_path = output / "build-report.json"
    report_path.write_text(json.dumps(build_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = tuple(sorted(path for path in output.iterdir() if path.is_file()))
    total_bytes = sum(path.stat().st_size for path in files)
    return Html5BuildResult(output, entrypoint, files, project.content_hash(), total_bytes, single_file, warnings)
