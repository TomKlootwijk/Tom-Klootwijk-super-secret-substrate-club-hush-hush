"""Conservative memory planning for a 12 GiB laptop GPU."""

from __future__ import annotations

from dataclasses import asdict, dataclass

GIB = 1024**3


@dataclass(frozen=True, slots=True)
class MemoryPlan:
    free_vram_bytes: int
    usable_bytes: int
    safety_reserve_bytes: int
    transposition_cache_bytes: int
    frontier_bytes: int
    batch_workspace_bytes: int
    proof_staging_bytes: int
    optional_heuristic_bytes: int

    def as_dict(self) -> dict:
        result = asdict(self)
        result["gib"] = {
            key.removesuffix("_bytes"): round(value / GIB, 3)
            for key, value in result.items()
            if key.endswith("_bytes")
        }
        return result


def plan_memory(free_vram_bytes: int, reserve_fraction: float = 0.18) -> MemoryPlan:
    if free_vram_bytes <= 0:
        raise ValueError("free_vram_bytes must be positive")
    if not 0.10 <= reserve_fraction <= 0.50:
        raise ValueError("reserve_fraction must be between 0.10 and 0.50")
    reserve = int(free_vram_bytes * reserve_fraction)
    usable = free_vram_bytes - reserve
    # Fractions sum to 1.0 of usable. Runtime may reallocate the optional
    # heuristic pool to proof frontier when no learned ordering model is loaded.
    tt = int(usable * 0.46)
    frontier = int(usable * 0.23)
    workspace = int(usable * 0.16)
    staging = int(usable * 0.08)
    heuristic = usable - tt - frontier - workspace - staging
    return MemoryPlan(
        free_vram_bytes=free_vram_bytes,
        usable_bytes=usable,
        safety_reserve_bytes=reserve,
        transposition_cache_bytes=tt,
        frontier_bytes=frontier,
        batch_workspace_bytes=workspace,
        proof_staging_bytes=staging,
        optional_heuristic_bytes=heuristic,
    )
