"""Minimal referential evaluator for the UGTS-KC 3.6 example substrate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .geometry import active_bit_positions, digit_count, regular_polygon
from .model import Substrate
from .phonetics_nl import lexeme


@dataclass(frozen=True)
class TraceEntry:
    step_id: str
    kind: str
    output: Any


class Runtime:
    def __init__(self, substrate: Substrate):
        self.substrate = substrate
        self._operators: dict[str, Callable[[dict[str, Any], dict[str, Any]], Any]] = {
            "radix_encode": self._radix_encode,
            "active_bit_filter": self._active_bit_filter,
            "nl_number_lexeme": self._nl_number_lexeme,
            "syllable_pulse": self._syllable_pulse,
            "feature_count_compare": self._feature_count_compare,
            "regular_polygon_embedding": self._regular_polygon_embedding,
        }

    def execute(self, pipeline_id: str, instance_id: str) -> list[TraceEntry]:
        pipeline = next((item for item in self.substrate.pipelines if item.get("id") == pipeline_id), None)
        if pipeline is None:
            raise KeyError(pipeline_id)
        instance = next((item for item in self.substrate.instances if item.get("id") == instance_id), None)
        if instance is None:
            raise KeyError(instance_id)

        context: dict[str, Any] = {"instance": instance, "value": instance["literal"]["value"]}
        trace: list[TraceEntry] = []
        for step_id in pipeline.get("steps", []):
            node = self.substrate.definition(step_id)
            operator = self._operators.get(node.kind)
            if operator is None:
                raise NotImplementedError(node.kind)
            output = operator(context, dict(node.record))
            context[step_id] = output
            context["last"] = output
            trace.append(TraceEntry(step_id=step_id, kind=node.kind, output=output))
        return trace

    @staticmethod
    def _radix_encode(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        value = int(context["value"])
        base = int(record.get("parameters", {}).get("base", 2))
        numeral = format(value, "b") if base == 2 else _encode_base(value, base)
        return {"base": base, "numeral": numeral, "digit_count": digit_count(value, base)}

    @staticmethod
    def _active_bit_filter(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        value = int(context["value"])
        positions = active_bit_positions(value)
        return {"positions_lsb0": list(positions), "count": len(positions)}

    @staticmethod
    def _nl_number_lexeme(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        return lexeme(int(context["value"])).to_dict()

    @staticmethod
    def _syllable_pulse(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        lexeme_step = str(record["parameters"]["lexeme_step"])
        item = context[lexeme_step]
        return {"segments": item["pronunciation_segments"], "pulses": [1] * item["syllable_count"], "count": item["syllable_count"]}

    @staticmethod
    def _feature_count_compare(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        left_step = str(record["parameters"]["left_step"])
        right_step = str(record["parameters"]["right_step"])
        left = int(context[left_step]["count"])
        right = int(context[right_step]["count"])
        return {
            "left_count": left,
            "right_count": right,
            "equal": left == right,
            "semantics": "feature-count coincidence; no numeric identity",
        }

    @staticmethod
    def _regular_polygon_embedding(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        source_step = str(record["parameters"]["count_step"])
        count = int(context[source_step]["count"])
        points = regular_polygon(max(count, 1), radius=float(record.get("parameters", {}).get("radius", 1.0)))
        return {"vertex_count": count, "points": [[x, y] for x, y in points]}


def _encode_base(value: int, base: int) -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if not 2 <= base <= len(alphabet):
        raise ValueError("base out of supported range")
    if value == 0:
        return "0"
    out: list[str] = []
    n = value
    while n:
        n, rem = divmod(n, base)
        out.append(alphabet[rem])
    return "".join(reversed(out))
