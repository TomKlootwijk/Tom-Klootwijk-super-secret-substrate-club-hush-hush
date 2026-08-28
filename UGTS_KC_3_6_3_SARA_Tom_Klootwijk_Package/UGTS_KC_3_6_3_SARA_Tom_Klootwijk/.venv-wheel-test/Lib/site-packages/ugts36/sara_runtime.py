"""Traceable runtime for the UGTS-KC 3.6.3 SARA certificate pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .sara363 import build_reference_sara363_certificate


@dataclass(frozen=True)
class SARATraceEntry:
    index: int
    operator: str
    status: str
    detail: dict[str, Any]


class SARARuntime:
    """A public-only, non-networked certificate runtime.

    This runtime deliberately has no search, signing, broadcasting or wallet
    mutation method.
    """

    def __init__(self, wordlist_path: str | Path):
        self.wordlist_path = Path(wordlist_path)
        self.trace: list[SARATraceEntry] = []

    def _record(self, operator: str, status: str, **detail: Any) -> None:
        self.trace.append(
            SARATraceEntry(
                index=len(self.trace), operator=operator, status=status, detail=dict(detail)
            )
        )

    def run_reference(self) -> dict[str, Any]:
        self._record("sara363.wordlist.commitment", "start", path=str(self.wordlist_path))
        certificate = build_reference_sara363_certificate(self.wordlist_path)
        self._record(
            "sara363.bip39.checksum_hinge",
            "pass" if certificate.bip39_validation["checksum_valid"] else "fail",
            word_count=certificate.bip39_validation["word_count"],
        )
        self._record(
            "sara363.bip84.public_projection",
            "pass",
            address=certificate.bip84_public_derivation["address"],
            path=certificate.bip84_public_derivation["path"],
        )
        self._record(
            "sara363.address.public_decode",
            "pass",
            address_type=certificate.supplied_address_decode["address_type"],
            witness_program_bytes=certificate.supplied_address_decode[
                "witness_program_bytes"
            ],
        )
        self._record(
            "sara363.authorization.gate",
            "pass" if certificate.audit_boundary["authorized"] else "fail",
            reason_codes=certificate.audit_boundary["reason_codes"],
        )
        self._record(
            "sara363.certificate.issue",
            "pass" if certificate.valid else "fail",
            valid=certificate.valid,
        )
        return {"certificate": asdict(certificate), "trace": [asdict(item) for item in self.trace]}
