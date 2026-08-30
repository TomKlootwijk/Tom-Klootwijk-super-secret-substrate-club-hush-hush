from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct


ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/ugts_kc3/android_template/project/app/src/main/cpp"
SHADER = CPP / "chrono_gsp4_full_substrate.comp"
SPIRV_HEADER = CPP / "chrono_gsp4_full_substrate_spv.hpp"


def _embedded_spirv() -> bytes:
    text = SPIRV_HEADER.read_text(encoding="utf-8")
    words = [int(value, 16) for value in re.findall(r"0x([0-9a-f]{8})u", text)]
    declared = re.search(
        r"array<std::uint32_t,(\d+)> ChronoGsp4FullSubstrateSpirv", text
    )
    assert declared is not None
    assert len(words) == int(declared.group(1))
    return b"".join(struct.pack("<I", word) for word in words)


def test_profile2_spirv_is_the_frozen_ndk_r29_shader_artifact() -> None:
    normalized_shader = SHADER.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert hashlib.sha256(normalized_shader.encode("utf-8")).hexdigest() == (
        "75b105f59616ead1ae7e9a1a83bbd8b0c9973cb0033aac2c"
        "0555940ee385c9eb"
    )
    spirv = _embedded_spirv()
    assert len(spirv) == 29_168
    assert spirv[:4] == b"\x03\x02#\x07"
    assert hashlib.sha256(spirv).hexdigest() == (
        "d5771e6e6f3ae51ae38bb9750dc36c3d64cc465d93ad53"
        "6abe404069f4a11d70"
    )


def test_profile2_shader_surface_matches_the_portable_receipt_abi() -> None:
    shader = SHADER.read_text(encoding="utf-8")
    compact = re.sub(r"\s+", "", shader)

    assert "local_size_x=256" in compact
    assert [int(value) for value in re.findall(r"binding\s*=\s*(\d+)", shader)] == [
        0,
        1,
        2,
        3,
        4,
    ]
    assert "uintluma_count;" in compact
    assert "uintframe_ordinal;" in compact
    assert "uintroot_seed_lo;" in compact
    assert "uintroot_seed_hi;" in compact
    assert "uintlineage_seed;" in compact
    assert "constuintRECEIPT_WORDS=20u;" in compact
    assert len(re.findall(r"writeReceipt\(lane,\s*\d+u,", shader)) == 20

    # Exact profile-2 state gates that previously regressed in provisional
    # implementations: recipe-bound GSP4 lineage, finite Pythagorean segment,
    # full heap-node high bit and cone triple index.
    assert "seed.lineage_seed^rotateLeft32(routedHash,11u)" in compact
    assert "constintsegmentDot=absX*coneRadius+down*coneHeight;" in compact
    assert "constintsegmentCross=absX*coneHeight-down*coneRadius;" in compact
    assert "uint(segmentDot)>slantSquared" in compact
    assert "magnitudeInt(segmentCross)<=uint(guard*coneSlant)" in compact
    assert "(((node>>16u)&1u)<<25u)" in compact
    assert "((tripleIndex&7u)<<26u)" in compact
    assert "klbLow^klbHigh^tag^generatedConstant(32u+depth)^node" in compact

    # The Mali path is deliberately 32-bit integer-only. The words below are
    # checked as tokens so comments cannot hide an accidental shader type.
    code_without_comments = re.sub(r"//.*?$|/\*.*?\*/", "", shader, flags=re.M | re.S)
    assert re.search(r"\b(float|double|int64_t|uint64_t)\b", code_without_comments) is None
