from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable


class NodeType(IntEnum):
    """Compact node vocabulary used by the runtime graph.

    The vocabulary is deliberately small. Rich external ontology terms are
    mapped to these hot node classes and retained in node text/metadata.
    """

    SPATIAL_ENTITY = 0
    SENSOR = 1
    OBSERVATION = 2
    SPATIAL_CELL = 3
    CONCEPT = 4
    EVENT = 5
    LINEAGE_STATE = 6


class RelationType(IntEnum):
    """Versioned 4-bit relation vocabulary.

    Relation IDs 0..15 fit the UGTS compatibility mask. The model may learn
    relation likelihoods, but deterministic geometry and guard checks remain
    authoritative for relations marked as geometric/guarded below.
    """

    LOCATED_IN = 0
    ADJACENT_TO = 1
    NEAR = 2
    OBSERVES = 3
    MADE_BY_SENSOR = 4
    HAS_PROPERTY = 5
    INSTANCE_OF = 6
    AFFECTS = 7
    DESCENDS_FROM = 8
    SUPERSEDES = 9
    COMPATIBLE_WITH = 10
    CROSSED_GUARD = 11
    TRANSITIONED_TO = 12
    SAME_CELL = 13
    CONNECTED_TO = 14
    DERIVED_FROM = 15


class NoveltyOp(IntEnum):
    NODE_ADD = 1
    NODE_REMOVE = 2
    NODE_STATE_PATCH = 3
    EDGE_ADD = 4
    EDGE_REMOVE = 5
    OBSERVATION = 6
    VERIFIED_EVENT = 7
    IDENTITY_SPLIT = 8
    IDENTITY_MERGE = 9
    ONTOLOGY_RECLASSIFICATION = 10


NODE_TYPE_NAMES = {int(v): v.name.lower() for v in NodeType}
RELATION_TYPE_NAMES = {int(v): v.name.lower() for v in RelationType}
NOVELTY_OP_NAMES = {int(v): v.name.lower() for v in NoveltyOp}
NODE_TYPE_BY_NAME = {name: value for value, name in NODE_TYPE_NAMES.items()}
RELATION_TYPE_BY_NAME = {name: value for value, name in RELATION_TYPE_NAMES.items()}
NOVELTY_OP_BY_NAME = {name: value for value, name in NOVELTY_OP_NAMES.items()}

# Interoperability mappings. These are identifiers, not an embedded RDF
# reasoner. The GPU/student model consumes compact IDs; the mappings preserve
# the external semantic contract for import/export.
NODE_TYPE_URIS: dict[int, str] = {
    int(NodeType.SPATIAL_ENTITY): "http://www.opengis.net/ont/geosparql#Feature",
    int(NodeType.SENSOR): "http://www.w3.org/ns/sosa/Sensor",
    int(NodeType.OBSERVATION): "http://www.w3.org/ns/sosa/Observation",
    int(NodeType.SPATIAL_CELL): "urn:ugts:gsp4:SpatialCell",
    int(NodeType.CONCEPT): "http://www.w3.org/2004/02/skos/core#Concept",
    int(NodeType.EVENT): "urn:ugts:gsp4:VerifiedEvent",
    int(NodeType.LINEAGE_STATE): "urn:ugts:gsp4:LineageState",
}

RELATION_TYPE_URIS: dict[int, str] = {
    int(RelationType.LOCATED_IN): "http://www.opengis.net/ont/geosparql#sfWithin",
    int(RelationType.ADJACENT_TO): "http://www.opengis.net/ont/geosparql#sfTouches",
    int(RelationType.NEAR): "urn:ugts:gsp4:near",
    int(RelationType.OBSERVES): "http://www.w3.org/ns/sosa/observes",
    int(RelationType.MADE_BY_SENSOR): "http://www.w3.org/ns/sosa/madeBySensor",
    int(RelationType.HAS_PROPERTY): "http://www.w3.org/ns/sosa/observedProperty",
    int(RelationType.INSTANCE_OF): "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
    int(RelationType.AFFECTS): "urn:ugts:gsp4:affects",
    int(RelationType.DESCENDS_FROM): "urn:ugts:gsp4:descendsFrom",
    int(RelationType.SUPERSEDES): "urn:ugts:gsp4:supersedes",
    int(RelationType.COMPATIBLE_WITH): "urn:ugts:gsp4:compatibleWith",
    int(RelationType.CROSSED_GUARD): "urn:ugts:gsp4:crossedGuard",
    int(RelationType.TRANSITIONED_TO): "urn:ugts:gsp4:transitionedTo",
    int(RelationType.SAME_CELL): "urn:ugts:gsp4:sameCell",
    int(RelationType.CONNECTED_TO): "urn:ugts:gsp4:connectedTo",
    int(RelationType.DERIVED_FROM): "http://www.w3.org/ns/prov#wasDerivedFrom",
}


@dataclass(frozen=True)
class RelationSpec:
    relation: RelationType
    source_types: tuple[NodeType, ...]
    target_types: tuple[NodeType, ...]
    symmetric: bool = False
    requires_geometry: bool = False
    requires_guard: bool = False
    semantic_teacher_allowed: bool = True


RELATION_SPECS: dict[int, RelationSpec] = {
    int(RelationType.LOCATED_IN): RelationSpec(
        RelationType.LOCATED_IN,
        (NodeType.SPATIAL_ENTITY, NodeType.SENSOR, NodeType.OBSERVATION, NodeType.EVENT),
        (NodeType.SPATIAL_CELL, NodeType.SPATIAL_ENTITY),
        requires_geometry=True,
    ),
    int(RelationType.ADJACENT_TO): RelationSpec(
        RelationType.ADJACENT_TO,
        (NodeType.SPATIAL_CELL, NodeType.SPATIAL_ENTITY),
        (NodeType.SPATIAL_CELL, NodeType.SPATIAL_ENTITY),
        symmetric=True,
        requires_geometry=True,
    ),
    int(RelationType.NEAR): RelationSpec(
        RelationType.NEAR,
        (NodeType.SPATIAL_ENTITY, NodeType.SENSOR, NodeType.OBSERVATION),
        (NodeType.SPATIAL_ENTITY, NodeType.SENSOR, NodeType.OBSERVATION),
        symmetric=True,
        requires_geometry=True,
        requires_guard=True,
    ),
    int(RelationType.OBSERVES): RelationSpec(
        RelationType.OBSERVES,
        (NodeType.SENSOR,),
        (NodeType.CONCEPT,),
    ),
    int(RelationType.MADE_BY_SENSOR): RelationSpec(
        RelationType.MADE_BY_SENSOR,
        (NodeType.OBSERVATION,),
        (NodeType.SENSOR,),
    ),
    int(RelationType.HAS_PROPERTY): RelationSpec(
        RelationType.HAS_PROPERTY,
        (NodeType.OBSERVATION, NodeType.SPATIAL_ENTITY, NodeType.SENSOR),
        (NodeType.CONCEPT,),
    ),
    int(RelationType.INSTANCE_OF): RelationSpec(
        RelationType.INSTANCE_OF,
        (NodeType.SPATIAL_ENTITY, NodeType.SENSOR, NodeType.OBSERVATION, NodeType.EVENT),
        (NodeType.CONCEPT,),
    ),
    int(RelationType.AFFECTS): RelationSpec(
        RelationType.AFFECTS,
        (NodeType.OBSERVATION, NodeType.EVENT),
        (NodeType.SPATIAL_ENTITY, NodeType.SENSOR, NodeType.SPATIAL_CELL),
        requires_geometry=True,
    ),
    int(RelationType.DESCENDS_FROM): RelationSpec(
        RelationType.DESCENDS_FROM,
        (NodeType.EVENT, NodeType.LINEAGE_STATE, NodeType.OBSERVATION),
        (NodeType.EVENT, NodeType.LINEAGE_STATE, NodeType.OBSERVATION),
    ),
    int(RelationType.SUPERSEDES): RelationSpec(
        RelationType.SUPERSEDES,
        (NodeType.EVENT, NodeType.OBSERVATION, NodeType.LINEAGE_STATE),
        (NodeType.EVENT, NodeType.OBSERVATION, NodeType.LINEAGE_STATE),
    ),
    int(RelationType.COMPATIBLE_WITH): RelationSpec(
        RelationType.COMPATIBLE_WITH,
        tuple(NodeType),
        tuple(NodeType),
        symmetric=True,
    ),
    int(RelationType.CROSSED_GUARD): RelationSpec(
        RelationType.CROSSED_GUARD,
        (NodeType.EVENT, NodeType.OBSERVATION),
        (NodeType.SPATIAL_ENTITY, NodeType.SPATIAL_CELL, NodeType.SENSOR),
        requires_geometry=True,
        requires_guard=True,
        semantic_teacher_allowed=False,
    ),
    int(RelationType.TRANSITIONED_TO): RelationSpec(
        RelationType.TRANSITIONED_TO,
        (NodeType.EVENT, NodeType.LINEAGE_STATE, NodeType.OBSERVATION),
        (NodeType.EVENT, NodeType.LINEAGE_STATE, NodeType.OBSERVATION),
    ),
    int(RelationType.SAME_CELL): RelationSpec(
        RelationType.SAME_CELL,
        (NodeType.SPATIAL_ENTITY, NodeType.SENSOR, NodeType.OBSERVATION),
        (NodeType.SPATIAL_ENTITY, NodeType.SENSOR, NodeType.OBSERVATION),
        symmetric=True,
        requires_geometry=True,
        semantic_teacher_allowed=False,
    ),
    int(RelationType.CONNECTED_TO): RelationSpec(
        RelationType.CONNECTED_TO,
        (NodeType.SPATIAL_ENTITY, NodeType.SENSOR, NodeType.SPATIAL_CELL),
        (NodeType.SPATIAL_ENTITY, NodeType.SENSOR, NodeType.SPATIAL_CELL),
        symmetric=True,
    ),
    int(RelationType.DERIVED_FROM): RelationSpec(
        RelationType.DERIVED_FROM,
        (NodeType.OBSERVATION, NodeType.EVENT),
        (NodeType.SENSOR, NodeType.OBSERVATION, NodeType.EVENT),
    ),
}


def relation_is_type_compatible(relation: int, source_type: int, target_type: int) -> bool:
    spec = RELATION_SPECS.get(int(relation))
    if spec is None:
        return False
    try:
        source = NodeType(int(source_type))
        target = NodeType(int(target_type))
    except ValueError:
        return False
    return source in spec.source_types and target in spec.target_types


def allowed_relations_for_types(
    source_type: int,
    target_type: int,
    *,
    semantic_teacher_only: bool = False,
) -> tuple[int, ...]:
    result: list[int] = []
    for relation, spec in RELATION_SPECS.items():
        if semantic_teacher_only and not spec.semantic_teacher_allowed:
            continue
        if relation_is_type_compatible(relation, source_type, target_type):
            result.append(relation)
    return tuple(result)


def relation_mask(relations: Iterable[int | RelationType]) -> int:
    mask = 0
    for relation in relations:
        value = int(relation)
        if not 0 <= value < 16:
            raise ValueError("UGTS compatibility masks support relation IDs 0..15")
        mask |= 1 << value
    return mask


def relation_id(value: int | str | RelationType) -> int:
    if isinstance(value, RelationType):
        return int(value)
    if isinstance(value, int):
        if value not in RELATION_TYPE_NAMES:
            raise ValueError(f"unknown relation ID: {value}")
        return value
    text = str(value).strip().lower()
    if text.isdigit():
        return relation_id(int(text))
    if text not in RELATION_TYPE_BY_NAME:
        raise ValueError(f"unknown relation name: {value!r}")
    return RELATION_TYPE_BY_NAME[text]


def node_type_id(value: int | str | NodeType) -> int:
    if isinstance(value, NodeType):
        return int(value)
    if isinstance(value, int):
        if value not in NODE_TYPE_NAMES:
            raise ValueError(f"unknown node type ID: {value}")
        return value
    text = str(value).strip().lower()
    if text.isdigit():
        return node_type_id(int(text))
    if text not in NODE_TYPE_BY_NAME:
        raise ValueError(f"unknown node type name: {value!r}")
    return NODE_TYPE_BY_NAME[text]


def node_compatibility_mask(node_type: int | NodeType) -> int:
    """Return the 16-bit relation mask in which this node type may participate."""
    try:
        node = NodeType(int(node_type))
    except ValueError as exc:
        raise ValueError(f"unknown node type: {node_type}") from exc
    relations: list[int] = []
    for relation, spec in RELATION_SPECS.items():
        if node in spec.source_types or node in spec.target_types:
            relations.append(relation)
    return relation_mask(relations)
