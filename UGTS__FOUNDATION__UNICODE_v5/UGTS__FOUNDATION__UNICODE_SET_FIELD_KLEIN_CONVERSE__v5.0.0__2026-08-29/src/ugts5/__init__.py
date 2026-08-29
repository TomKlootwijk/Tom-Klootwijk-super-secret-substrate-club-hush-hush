"""UGTS Foundation 5.0 reference runtime."""

from .atlas import OperatorAtlas, HotCodebook
from .glyph_sdf import glyph_sdf, glyph_segments
from .klein import KleinState, apply_klein_converse, reflect_theta, reflect_theta8
from .packing import PackedNode32, PackedNodeFields, ParityError
from .set_fields import (
    FieldCapability,
    FiniteSetField,
    complement_value,
    difference_value,
    intersection_value,
    symmetric_difference_value,
    union_value,
)

__all__ = [
    "OperatorAtlas",
    "HotCodebook",
    "glyph_sdf",
    "glyph_segments",
    "KleinState",
    "apply_klein_converse",
    "reflect_theta",
    "reflect_theta8",
    "PackedNode32",
    "PackedNodeFields",
    "ParityError",
    "FieldCapability",
    "FiniteSetField",
    "complement_value",
    "difference_value",
    "intersection_value",
    "symmetric_difference_value",
    "union_value",
]

__version__ = "5.0.0"
