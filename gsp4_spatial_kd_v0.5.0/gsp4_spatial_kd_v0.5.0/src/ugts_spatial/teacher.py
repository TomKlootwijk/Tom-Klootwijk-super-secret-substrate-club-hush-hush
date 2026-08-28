from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable
from urllib import error as urlerror
from urllib import request as urlrequest

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass(frozen=True)
class RelationCandidate:
    candidate_id: str
    source_index: int
    target_index: int
    source_id: int
    target_id: int
    source_type: str
    target_type: str
    source_text: str
    target_text: str
    distance_m: float | None
    allowed_relations: tuple[str, ...]
    deterministic_fields: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RelationCandidate":
        row = dict(value)
        row["allowed_relations"] = tuple(row.get("allowed_relations", []))
        return cls(**row)


@dataclass(frozen=True)
class TeacherLabel:
    candidate_id: str
    source_id: int
    target_id: int
    relation: str
    confidence: float
    abstain: bool
    requires_geometric_verification: bool
    evidence_fields: tuple[str, ...]
    rationale: str
    teacher_model: str

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        candidate: RelationCandidate,
        teacher_model: str,
    ) -> "TeacherLabel":
        relation = str(value.get("relation", "abstain")).strip().lower()
        allowed = set(candidate.allowed_relations)
        abstain = bool(value.get("abstain", False)) or relation == "abstain"
        if not abstain and relation not in allowed:
            raise ValueError(
                f"teacher returned relation {relation!r}, outside allowed set {sorted(allowed)}"
            )
        confidence = float(value.get("confidence", 0.0))
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("teacher confidence must be in [0,1]")
        evidence = tuple(str(item) for item in value.get("evidence_fields", []))
        return cls(
            candidate_id=candidate.candidate_id,
            source_id=int(candidate.source_id),
            target_id=int(candidate.target_id),
            relation="abstain" if abstain else relation,
            confidence=confidence,
            abstain=abstain,
            requires_geometric_verification=bool(
                value.get("requires_geometric_verification", True)
            ),
            evidence_fields=evidence,
            rationale=str(value.get("rationale", ""))[:1000],
            teacher_model=teacher_model,
        )


@dataclass
class OpenAICompatibleChatTeacher:
    base_url: str = "http://127.0.0.1:8081/v1"
    model: str = "teacher-model"
    timeout_s: float = 240.0
    api_key: str | None = None
    name: str = "openai-compatible-chat-teacher"

    SYSTEM_PROMPT = """You are an offline ontology teacher for a geospatial knowledge graph.
Return exactly one JSON object and no prose. Select only from allowed_relations or abstain.
Do not infer exact distance, containment, intersection, boundary crossing, or sensor physics from text.
Those are deterministic UGTS support and guard operations. Classify semantic compatibility only.
Required keys: relation, confidence, abstain, requires_geometric_verification, evidence_fields, rationale.
confidence must be between 0 and 1. Prefer abstain when evidence is insufficient."""

    def _call(self, candidate: RelationCandidate) -> dict[str, Any]:
        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        user_payload = {
            "candidate_id": candidate.candidate_id,
            "source": {
                "id": candidate.source_id,
                "type": candidate.source_type,
                "text": candidate.source_text,
            },
            "target": {
                "id": candidate.target_id,
                "type": candidate.target_type,
                "text": candidate.target_text,
            },
            "distance_m": candidate.distance_m,
            "allowed_relations": list(candidate.allowed_relations),
            "deterministic_fields": candidate.deterministic_fields,
        }
        payload = {
            "model": self.model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        token = self.api_key or os.getenv("UGTS_TEACHER_API_KEY")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urlrequest.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlrequest.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read()
        except urlerror.URLError as exc:
            raise RuntimeError(f"teacher request failed for {endpoint}: {exc}") from exc
        parsed = json.loads(raw.decode("utf-8"))
        content = parsed["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            )
        content = _FENCE_RE.sub("", str(content).strip())
        return json.loads(content)

    def label(self, candidate: RelationCandidate) -> TeacherLabel:
        return TeacherLabel.from_dict(
            self._call(candidate), candidate=candidate, teacher_model=self.model
        )


def write_teacher_labels(path: str | Path, labels: Iterable[TeacherLabel]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for label in labels:
            fh.write(json.dumps(asdict(label), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_teacher_labels(path: str | Path) -> list[TeacherLabel]:
    result: list[TeacherLabel] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            row["evidence_fields"] = tuple(row.get("evidence_fields", []))
            result.append(TeacherLabel(**row))
    return result
