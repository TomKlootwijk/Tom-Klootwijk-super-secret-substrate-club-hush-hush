from __future__ import annotations

import pytest

from ugts_kc3.chrono_seed import (
    ChronoSeedError,
    ROOT_SEED_BYTES,
    derive_root_seed,
    pack_root_seed,
    unpack_root_seed,
)


SOURCE_SHA256 = "1867bafa7c80c31f18856525cbf580edaa36d524270b1fa59cc643b51964cbfd"


def test_supplied_fixture_seed_is_exact_eight_byte_payload() -> None:
    root = derive_root_seed(SOURCE_SHA256)
    payload = pack_root_seed(root)
    assert root == 0x1FC3807CFABA6718
    assert len(payload) == ROOT_SEED_BYTES == 8
    assert payload.hex() == "1867bafa7c80c31f"
    assert unpack_root_seed(payload) == root


@pytest.mark.parametrize("value", [-1, 1 << 64, True, 1.5])
def test_pack_rejects_noncanonical_seed(value: object) -> None:
    with pytest.raises(ChronoSeedError):
        pack_root_seed(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("payload", [b"", b"1234567", b"123456789"])
def test_unpack_requires_exact_size(payload: bytes) -> None:
    with pytest.raises(ChronoSeedError, match="exactly 8 bytes"):
        unpack_root_seed(payload)


@pytest.mark.parametrize(
    "digest",
    ["", "0" * 63, "A" * 64, "z" * 64],
)
def test_source_digest_must_be_canonical(digest: str) -> None:
    with pytest.raises(ChronoSeedError, match="lowercase hexadecimal"):
        derive_root_seed(digest)
