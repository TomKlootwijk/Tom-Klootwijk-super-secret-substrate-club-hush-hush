"""Canonical cross-runtime conformance data for compact polar rendering."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


POLAR_SUBSTRATE_VECTOR_PATH = Path(__file__).with_name(
    "polar_substrate_vectors.tsv"
)
POLAR_SUBSTRATE_VECTOR_SCHEMA = "ugts-kc-polar-substrate-v1"


@dataclass(frozen=True)
class PolarSubstrateVector:
    """One packed pose/motion case and its canonical Cartesian expectations."""

    name: str
    input_x: float
    input_z: float
    core: bool
    pose_word: int
    motion_word: int
    next_pose_word: int
    next_motion_word: int
    direct_position: tuple[float, float]
    lut_position: tuple[float, float]
    direct_velocity: tuple[float, float]
    lut_velocity: tuple[float, float]
    direct_acceleration: tuple[float, float]
    lut_acceleration: tuple[float, float]
    heading_quaternion_wy: tuple[float, float]
    direct_heading_direction: tuple[float, float]
    lut_heading_direction: tuple[float, float]


@dataclass(frozen=True)
class PolarSubstrateConformance:
    """Strict parsed view of the shared TSV artifact."""

    metadata: Mapping[str, str]
    shader_snippets: Mapping[str, str]
    vectors: tuple[PolarSubstrateVector, ...]

    def number(self, key: str) -> float:
        try:
            return float(self.metadata[key])
        except KeyError as error:
            raise ValueError(f"polar conformance metadata is missing {key!r}") from error

    def integer(self, key: str) -> int:
        try:
            return int(self.metadata[key], 10)
        except KeyError as error:
            raise ValueError(f"polar conformance metadata is missing {key!r}") from error


_CASE_FIELDS = (
    "name",
    "input_x",
    "input_z",
    "core",
    "pose_word",
    "motion_word",
    "next_pose_word",
    "next_motion_word",
    "direct_x",
    "direct_z",
    "lut_x",
    "lut_z",
    "direct_velocity_x",
    "direct_velocity_z",
    "lut_velocity_x",
    "lut_velocity_z",
    "direct_acceleration_x",
    "direct_acceleration_z",
    "lut_acceleration_x",
    "lut_acceleration_z",
    "heading_w",
    "heading_y",
    "direct_heading_cos",
    "direct_heading_sin",
    "lut_heading_cos",
    "lut_heading_sin",
)


def _pair(values: Mapping[str, str], first: str, second: str) -> tuple[float, float]:
    return float(values[first]), float(values[second])


def _parse_case(values: Mapping[str, str]) -> PolarSubstrateVector:
    core = values["core"]
    if core not in {"true", "false"}:
        raise ValueError("polar conformance core field must be true or false")
    return PolarSubstrateVector(
        name=values["name"],
        input_x=float(values["input_x"]),
        input_z=float(values["input_z"]),
        core=core == "true",
        pose_word=int(values["pose_word"], 16),
        motion_word=int(values["motion_word"], 16),
        next_pose_word=int(values["next_pose_word"], 16),
        next_motion_word=int(values["next_motion_word"], 16),
        direct_position=_pair(values, "direct_x", "direct_z"),
        lut_position=_pair(values, "lut_x", "lut_z"),
        direct_velocity=_pair(
            values, "direct_velocity_x", "direct_velocity_z"
        ),
        lut_velocity=_pair(values, "lut_velocity_x", "lut_velocity_z"),
        direct_acceleration=_pair(
            values, "direct_acceleration_x", "direct_acceleration_z"
        ),
        lut_acceleration=_pair(
            values, "lut_acceleration_x", "lut_acceleration_z"
        ),
        heading_quaternion_wy=_pair(values, "heading_w", "heading_y"),
        direct_heading_direction=_pair(
            values, "direct_heading_cos", "direct_heading_sin"
        ),
        lut_heading_direction=_pair(
            values, "lut_heading_cos", "lut_heading_sin"
        ),
    )


def load_polar_substrate_conformance(
    path: str | Path = POLAR_SUBSTRATE_VECTOR_PATH,
) -> PolarSubstrateConformance:
    """Load the canonical TSV without deriving or rewriting expected values."""

    metadata: dict[str, str] = {}
    shader_snippets: dict[str, str] = {}
    vectors: list[PolarSubstrateVector] = []
    columns: tuple[str, ...] | None = None
    with Path(path).open("r", encoding="utf-8", newline="") as stream:
        for line_number, row in enumerate(csv.reader(stream, delimiter="\t"), 1):
            if not row or row[0].startswith("#"):
                continue
            record = row[0]
            if record in {"meta", "shader"}:
                if len(row) != 3 or not row[1] or not row[2]:
                    raise ValueError(
                        f"malformed {record} row at conformance line {line_number}"
                    )
                destination = metadata if record == "meta" else shader_snippets
                if row[1] in destination:
                    raise ValueError(
                        f"duplicate {record} key {row[1]!r} at line {line_number}"
                    )
                destination[row[1]] = row[2]
                continue
            if record == "columns":
                if len(row) < 3 or row[1] != "case":
                    raise ValueError(
                        f"malformed case columns at conformance line {line_number}"
                    )
                columns = tuple(row[2:])
                if columns != _CASE_FIELDS:
                    raise ValueError("polar conformance case columns changed")
                continue
            if record != "case" or columns is None or len(row) != len(columns) + 1:
                raise ValueError(
                    f"malformed polar conformance row at line {line_number}"
                )
            values = dict(zip(columns, row[1:], strict=True))
            vectors.append(_parse_case(values))

    if metadata.get("schema") != POLAR_SUBSTRATE_VECTOR_SCHEMA:
        raise ValueError("polar substrate conformance schema changed")
    if not shader_snippets:
        raise ValueError("polar conformance has no shader formula contract")
    if not vectors or len(vectors) != int(metadata.get("case_count", "-1")):
        raise ValueError("polar conformance case count does not match metadata")
    if len({vector.name for vector in vectors}) != len(vectors):
        raise ValueError("polar conformance case names must be unique")
    return PolarSubstrateConformance(
        MappingProxyType(metadata),
        MappingProxyType(shader_snippets),
        tuple(vectors),
    )


__all__ = (
    "POLAR_SUBSTRATE_VECTOR_PATH",
    "POLAR_SUBSTRATE_VECTOR_SCHEMA",
    "PolarSubstrateConformance",
    "PolarSubstrateVector",
    "load_polar_substrate_conformance",
)
