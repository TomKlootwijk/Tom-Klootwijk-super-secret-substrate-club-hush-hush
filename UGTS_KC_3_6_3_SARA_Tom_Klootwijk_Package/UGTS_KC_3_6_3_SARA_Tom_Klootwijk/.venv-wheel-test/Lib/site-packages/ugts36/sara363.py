"""UGTS-KC 3.6.3 SARA: Seed-Address Referential Algebra.

This module formalizes the public, deterministic parts of BIP39/BIP32/BIP84
and Bech32/Bech32m as a typed substrate.  It intentionally contains no
candidate enumerator, mnemonic permutation engine, private-key scanner,
transaction signer, broadcaster, balance scraper or network client.

The code is a transparent reference implementation for public test vectors,
self-owned wallet validation, watch-only address decoding and search-space
measurement.  It is not production wallet software.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

# secp256k1 constants (SEC 2 / BIP32)
SECP256K1_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
SECP256K1_G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)
HARDENED = 0x80000000

BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32_CHARSET_REV = {char: index for index, char in enumerate(BECH32_CHARSET)}
BECH32_CONST = 1
BECH32M_CONST = 0x2BC830A3

ALLOWED_AUDIT_SCOPES = frozenset(
    {
        "bip_test_vector",
        "self_owned_mnemonic_validation",
        "self_owned_known_seed_derivation",
        "public_address_decode",
        "watch_only_descriptor_check",
        "regtest",
        "signet",
        "testnet",
        "search_space_estimate",
        "checksum_validation",
    }
)
FORBIDDEN_AUDIT_SCOPES = frozenset(
    {
        "third_party_mainnet_key_search",
        "mnemonic_enumeration",
        "mnemonic_permutation_search",
        "passphrase_spray",
        "private_key_scan",
        "address_targeted_preimage_search",
        "transaction_signing",
        "transaction_broadcast",
        "funds_transfer",
    }
)


@dataclass(frozen=True)
class MnemonicValidation:
    word_count: int
    entropy_bits: int
    checksum_bits: int
    indices: tuple[int, ...]
    checksum_expected: str
    checksum_observed: str
    checksum_valid: bool
    entropy_fingerprint: str
    wordlist_fingerprint: str


@dataclass(frozen=True)
class HDNode:
    """Sensitive internal BIP32 node.

    The private scalar and chain code must never be serialized in package
    certificates or logs.  They remain transient during known-seed tests.
    """

    private_key: int
    chain_code: bytes
    depth: int = 0
    parent_fingerprint: bytes = b"\x00\x00\x00\x00"
    child_number: int = 0


@dataclass(frozen=True)
class PublicDerivationCertificate:
    profile: str
    path: str
    node_depth: int
    parent_fingerprint_hex: str
    child_number: int
    compressed_public_key_hex: str
    key_hash160_hex: str
    script_pubkey_hex: str
    address: str
    secrets_serialized: bool


@dataclass(frozen=True)
class AddressDecode:
    address: str
    hrp: str
    checksum_family: str
    checksum_valid: bool
    witness_version: int
    witness_program_hex: str
    witness_program_bytes: int
    script_pubkey_hex: str
    address_type: str


@dataclass(frozen=True)
class SearchSpaceEstimate:
    bits: int
    guesses_per_second: float
    total_candidates: int
    expected_guesses: float
    expected_seconds: float
    expected_years: float
    assumption: str


@dataclass(frozen=True)
class AuthorizedAuditCertificate:
    subject: str
    requested_scopes: tuple[str, ...]
    authorized_scopes: tuple[str, ...]
    rejected_scopes: tuple[str, ...]
    authorized: bool
    public_only: bool
    secret_egress: bool
    network_access: bool
    transaction_capability: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class SARA363Certificate:
    schema_version: str
    profile: str
    bip39_validation: dict[str, Any]
    bip84_public_derivation: dict[str, Any]
    supplied_address_decode: dict[str, Any]
    audit_boundary: dict[str, Any]
    search_metrics: tuple[dict[str, Any], ...]
    invariants: tuple[str, ...]
    nonclaims: tuple[str, ...]
    valid: bool


def _nfkd(text: str) -> str:
    return unicodedata.normalize("NFKD", text)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_bip39_wordlist(path: str | Path) -> tuple[str, ...]:
    words = tuple(_nfkd(line.strip()) for line in Path(path).read_text(encoding="utf-8").splitlines())
    if len(words) != 2048:
        raise ValueError(f"BIP39 wordlist must contain exactly 2048 entries, got {len(words)}")
    if len(set(words)) != 2048:
        raise ValueError("BIP39 wordlist entries must be unique")
    if tuple(sorted(words)) != words:
        raise ValueError("BIP39 wordlist must be sorted")
    return words


def wordlist_fingerprint(words: Sequence[str]) -> str:
    canonical = "\n".join(words) + "\n"
    return "sha256:" + sha256_hex(canonical.encode("utf-8"))


def entropy_to_mnemonic(entropy: bytes, words: Sequence[str]) -> str:
    ent = len(entropy) * 8
    if ent not in {128, 160, 192, 224, 256}:
        raise ValueError("BIP39 entropy length must be one of 128, 160, 192, 224 or 256 bits")
    if len(words) != 2048:
        raise ValueError("BIP39 wordlist must contain 2048 words")
    cs = ent // 32
    entropy_bits = "".join(f"{byte:08b}" for byte in entropy)
    digest_bits = "".join(f"{byte:08b}" for byte in hashlib.sha256(entropy).digest())
    combined = entropy_bits + digest_bits[:cs]
    indices = [int(combined[offset : offset + 11], 2) for offset in range(0, len(combined), 11)]
    return " ".join(words[index] for index in indices)


def validate_mnemonic(mnemonic: str, words: Sequence[str]) -> MnemonicValidation:
    normalized = _nfkd(mnemonic).strip()
    tokens = tuple(token for token in normalized.split(" ") if token)
    allowed_counts = {12: 128, 15: 160, 18: 192, 21: 224, 24: 256}
    if len(tokens) not in allowed_counts:
        raise ValueError("BIP39 mnemonic must contain 12, 15, 18, 21 or 24 words")
    if len(words) != 2048:
        raise ValueError("BIP39 wordlist must contain 2048 words")
    index_map = {word: index for index, word in enumerate(words)}
    try:
        indices = tuple(index_map[token] for token in tokens)
    except KeyError as exc:
        raise ValueError(f"word not present in selected wordlist: {exc.args[0]}") from None

    total_bits = "".join(f"{index:011b}" for index in indices)
    ent = allowed_counts[len(tokens)]
    cs = ent // 32
    entropy_bits = total_bits[:ent]
    observed = total_bits[ent : ent + cs]
    entropy = int(entropy_bits, 2).to_bytes(ent // 8, "big")
    digest_bits = "".join(f"{byte:08b}" for byte in hashlib.sha256(entropy).digest())
    expected = digest_bits[:cs]
    return MnemonicValidation(
        word_count=len(tokens),
        entropy_bits=ent,
        checksum_bits=cs,
        indices=indices,
        checksum_expected=expected,
        checksum_observed=observed,
        checksum_valid=observed == expected,
        entropy_fingerprint="sha256:" + sha256_hex(entropy),
        wordlist_fingerprint=wordlist_fingerprint(words),
    )


def mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    password = _nfkd(mnemonic).encode("utf-8")
    salt = ("mnemonic" + _nfkd(passphrase)).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha512", password, salt, 2048, dklen=64)


def _mod_inverse(value: int, modulus: int) -> int:
    if value % modulus == 0:
        raise ZeroDivisionError("inverse of zero does not exist")
    return pow(value, modulus - 2, modulus)


def _point_add(
    left: tuple[int, int] | None, right: tuple[int, int] | None
) -> tuple[int, int] | None:
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 + y2) % SECP256K1_P == 0:
        return None
    if left == right:
        slope = (3 * x1 * x1) * _mod_inverse(2 * y1, SECP256K1_P) % SECP256K1_P
    else:
        slope = (y2 - y1) * _mod_inverse(x2 - x1, SECP256K1_P) % SECP256K1_P
    x3 = (slope * slope - x1 - x2) % SECP256K1_P
    y3 = (slope * (x1 - x3) - y1) % SECP256K1_P
    return x3, y3


def _scalar_mult(scalar: int, point: tuple[int, int] = SECP256K1_G) -> tuple[int, int] | None:
    if scalar % SECP256K1_N == 0 or point is None:
        return None
    if scalar < 0:
        return _scalar_mult(-scalar, (point[0], (-point[1]) % SECP256K1_P))
    result: tuple[int, int] | None = None
    addend: tuple[int, int] | None = point
    value = scalar
    while value:
        if value & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        value >>= 1
    return result


def compressed_public_key(private_key: int) -> bytes:
    if not 1 <= private_key < SECP256K1_N:
        raise ValueError("private key scalar outside secp256k1 range")
    point = _scalar_mult(private_key)
    if point is None:
        raise ValueError("invalid public point")
    x, y = point
    return bytes((2 + (y & 1),)) + x.to_bytes(32, "big")


def hash160(data: bytes) -> bytes:
    return hashlib.new("ripemd160", hashlib.sha256(data).digest()).digest()


def key_fingerprint(private_key: int) -> bytes:
    return hash160(compressed_public_key(private_key))[:4]


def master_node_from_seed(seed: bytes) -> HDNode:
    digest = hmac.new(b"Bitcoin seed", seed, hashlib.sha512).digest()
    scalar = int.from_bytes(digest[:32], "big")
    if scalar == 0 or scalar >= SECP256K1_N:
        raise ValueError("invalid BIP32 master scalar")
    return HDNode(private_key=scalar, chain_code=digest[32:])


def ckd_private(parent: HDNode, index: int) -> HDNode:
    if not 0 <= index <= 0xFFFFFFFF:
        raise ValueError("child index must fit uint32")
    if index >= HARDENED:
        data = b"\x00" + parent.private_key.to_bytes(32, "big") + index.to_bytes(4, "big")
    else:
        data = compressed_public_key(parent.private_key) + index.to_bytes(4, "big")
    digest = hmac.new(parent.chain_code, data, hashlib.sha512).digest()
    left = int.from_bytes(digest[:32], "big")
    child = (left + parent.private_key) % SECP256K1_N
    if left >= SECP256K1_N or child == 0:
        raise ValueError("invalid BIP32 child; caller must use another index")
    return HDNode(
        private_key=child,
        chain_code=digest[32:],
        depth=parent.depth + 1,
        parent_fingerprint=key_fingerprint(parent.private_key),
        child_number=index,
    )


def parse_derivation_path(path: str) -> tuple[int, ...]:
    if path == "m":
        return ()
    if not path.startswith("m/"):
        raise ValueError("derivation path must start with m/")
    result: list[int] = []
    for component in path[2:].split("/"):
        if not component:
            raise ValueError("empty derivation path component")
        hardened = component.endswith(("'", "h", "H"))
        number_text = component[:-1] if hardened else component
        if not number_text.isdigit():
            raise ValueError(f"invalid derivation component: {component}")
        number = int(number_text)
        if number >= HARDENED:
            raise ValueError("unhardened component exceeds 2^31-1")
        result.append(number | HARDENED if hardened else number)
    return tuple(result)


def derive_private_path(root: HDNode, path: str) -> HDNode:
    node = root
    for index in parse_derivation_path(path):
        node = ckd_private(node, index)
    return node


def _bech32_polymod(values: Iterable[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for bit, generator in enumerate(generators):
            if (top >> bit) & 1:
                checksum ^= generator
    return checksum


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]


def _convert_bits(
    data: Iterable[int], from_bits: int, to_bits: int, pad: bool
) -> list[int]:
    accumulator = 0
    bit_count = 0
    output: list[int] = []
    max_value = (1 << to_bits) - 1
    max_accumulator = (1 << (from_bits + to_bits - 1)) - 1
    for value in data:
        if value < 0 or value >> from_bits:
            raise ValueError("input value exceeds source bit width")
        accumulator = ((accumulator << from_bits) | value) & max_accumulator
        bit_count += from_bits
        while bit_count >= to_bits:
            bit_count -= to_bits
            output.append((accumulator >> bit_count) & max_value)
    if pad:
        if bit_count:
            output.append((accumulator << (to_bits - bit_count)) & max_value)
    elif bit_count >= from_bits or ((accumulator << (to_bits - bit_count)) & max_value):
        raise ValueError("non-zero or excessive padding")
    return output


def _create_bech32_checksum(hrp: str, data: Sequence[int], constant: int) -> list[int]:
    values = _hrp_expand(hrp) + list(data)
    polymod = _bech32_polymod(values + [0] * 6) ^ constant
    return [(polymod >> (5 * (5 - index))) & 31 for index in range(6)]


def bech32_encode(hrp: str, data: Sequence[int], family: str) -> str:
    if not hrp or any(ord(char) < 33 or ord(char) > 126 for char in hrp):
        raise ValueError("invalid Bech32 human-readable part")
    if hrp.lower() != hrp:
        raise ValueError("encoder requires lowercase HRP")
    constant = BECH32_CONST if family == "bech32" else BECH32M_CONST if family == "bech32m" else None
    if constant is None:
        raise ValueError("unknown checksum family")
    combined = list(data) + _create_bech32_checksum(hrp, data, constant)
    encoded = hrp + "1" + "".join(BECH32_CHARSET[value] for value in combined)
    if len(encoded) > 90:
        raise ValueError("Bech32 string exceeds 90 characters")
    return encoded


def bech32_decode(value: str) -> tuple[str, list[int], str]:
    if not value or len(value) > 90:
        raise ValueError("invalid Bech32 length")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValueError("Bech32 character outside printable ASCII")
    if value.lower() != value and value.upper() != value:
        raise ValueError("mixed-case Bech32 strings are invalid")
    normalized = value.lower()
    separator = normalized.rfind("1")
    if separator < 1 or separator + 7 > len(normalized):
        raise ValueError("invalid Bech32 separator/checksum placement")
    hrp = normalized[:separator]
    try:
        data = [BECH32_CHARSET_REV[char] for char in normalized[separator + 1 :]]
    except KeyError as exc:
        raise ValueError(f"invalid Bech32 character: {exc.args[0]}") from None
    polymod = _bech32_polymod(_hrp_expand(hrp) + data)
    if polymod == BECH32_CONST:
        family = "bech32"
    elif polymod == BECH32M_CONST:
        family = "bech32m"
    else:
        raise ValueError("invalid Bech32 checksum")
    return hrp, data[:-6], family


def encode_segwit_address(hrp: str, witness_version: int, program: bytes) -> str:
    if not 0 <= witness_version <= 16:
        raise ValueError("witness version must be between 0 and 16")
    if not 2 <= len(program) <= 40:
        raise ValueError("witness program must contain 2-40 bytes")
    if witness_version == 0 and len(program) not in {20, 32}:
        raise ValueError("witness version 0 program must contain 20 or 32 bytes")
    family = "bech32" if witness_version == 0 else "bech32m"
    data = [witness_version] + _convert_bits(program, 8, 5, pad=True)
    return bech32_encode(hrp, data, family)


def _scriptpubkey_for_witness(witness_version: int, program: bytes) -> bytes:
    opcode = 0x00 if witness_version == 0 else 0x50 + witness_version
    return bytes((opcode, len(program))) + program


def decode_segwit_address(address: str) -> AddressDecode:
    hrp, data, family = bech32_decode(address)
    if not data:
        raise ValueError("missing witness version")
    witness_version = data[0]
    if witness_version > 16:
        raise ValueError("invalid witness version")
    program = bytes(_convert_bits(data[1:], 5, 8, pad=False))
    if not 2 <= len(program) <= 40:
        raise ValueError("invalid witness program length")
    if witness_version == 0:
        if family != "bech32":
            raise ValueError("v0 witness addresses must use Bech32")
        if len(program) not in {20, 32}:
            raise ValueError("v0 witness program must be 20 or 32 bytes")
    elif family != "bech32m":
        raise ValueError("v1-v16 witness addresses must use Bech32m")

    if witness_version == 0 and len(program) == 20:
        address_type = "p2wpkh"
    elif witness_version == 0 and len(program) == 32:
        address_type = "p2wsh"
    elif witness_version == 1 and len(program) == 32:
        address_type = "p2tr-or-v1-32-byte-program"
    else:
        address_type = f"witness-v{witness_version}-{len(program)}-byte"
    return AddressDecode(
        address=address.lower(),
        hrp=hrp,
        checksum_family=family,
        checksum_valid=True,
        witness_version=witness_version,
        witness_program_hex=program.hex(),
        witness_program_bytes=len(program),
        script_pubkey_hex=_scriptpubkey_for_witness(witness_version, program).hex(),
        address_type=address_type,
    )


def derive_bip84_public_certificate(
    mnemonic: str,
    path: str = "m/84'/0'/0'/0/0",
    *,
    passphrase: str = "",
    hrp: str = "bc",
) -> PublicDerivationCertificate:
    """Derive public-only BIP84 evidence from a known mnemonic.

    No seed, chain code, private scalar, WIF or xprv is returned or written.
    """

    seed = mnemonic_to_seed(mnemonic, passphrase)
    root = master_node_from_seed(seed)
    node = derive_private_path(root, path)
    pubkey = compressed_public_key(node.private_key)
    key_hash = hash160(pubkey)
    address = encode_segwit_address(hrp, 0, key_hash)
    script_pubkey = _scriptpubkey_for_witness(0, key_hash)
    return PublicDerivationCertificate(
        profile="bip39+bip32+bip84+p2wpkh",
        path=path,
        node_depth=node.depth,
        parent_fingerprint_hex=node.parent_fingerprint.hex(),
        child_number=node.child_number,
        compressed_public_key_hex=pubkey.hex(),
        key_hash160_hex=key_hash.hex(),
        script_pubkey_hex=script_pubkey.hex(),
        address=address,
        secrets_serialized=False,
    )


def valid_bip39_keyspace_bits(word_count: int) -> int:
    mapping = {12: 128, 15: 160, 18: 192, 21: 224, 24: 256}
    try:
        return mapping[word_count]
    except KeyError:
        raise ValueError("word count must be 12, 15, 18, 21 or 24") from None


def estimate_uniform_search(bits: int, guesses_per_second: float) -> SearchSpaceEstimate:
    if bits <= 0:
        raise ValueError("bits must be positive")
    if guesses_per_second <= 0 or not math.isfinite(guesses_per_second):
        raise ValueError("guesses_per_second must be finite and positive")
    total = 1 << bits
    expected = total / 2.0
    seconds = expected / guesses_per_second
    years = seconds / 31_557_600.0
    return SearchSpaceEstimate(
        bits=bits,
        guesses_per_second=guesses_per_second,
        total_candidates=total,
        expected_guesses=expected,
        expected_seconds=seconds,
        expected_years=years,
        assumption="uniform independent candidates; ignores implementation overhead and therefore favors the attacker",
    )


def authorize_audit(subject: str, requested_scopes: Iterable[str]) -> AuthorizedAuditCertificate:
    normalized = tuple(dict.fromkeys(str(scope).strip() for scope in requested_scopes if str(scope).strip()))
    authorized = tuple(scope for scope in normalized if scope in ALLOWED_AUDIT_SCOPES)
    rejected = tuple(scope for scope in normalized if scope not in ALLOWED_AUDIT_SCOPES)
    reasons: list[str] = []
    if any(scope in FORBIDDEN_AUDIT_SCOPES for scope in normalized):
        reasons.append("FORBIDDEN_PRIVATE_KEY_OR_FUNDS_ACCESS_SCOPE")
    if rejected:
        reasons.append("UNRECOGNIZED_OR_UNAUTHORIZED_SCOPE")
    if not normalized:
        reasons.append("EMPTY_SCOPE")
    allowed = bool(normalized) and not rejected
    if allowed:
        reasons.append("AUTHORIZED_PUBLIC_OR_SELF_OWNED_AUDIT_ONLY")
    return AuthorizedAuditCertificate(
        subject=subject,
        requested_scopes=normalized,
        authorized_scopes=authorized,
        rejected_scopes=rejected,
        authorized=allowed,
        public_only=True,
        secret_egress=False,
        network_access=False,
        transaction_capability=False,
        reason_codes=tuple(reasons),
    )


def build_reference_sara363_certificate(wordlist_path: str | Path) -> SARA363Certificate:
    words = load_bip39_wordlist(wordlist_path)
    mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    validation = validate_mnemonic(mnemonic, words)
    public_derivation = derive_bip84_public_certificate(mnemonic)
    supplied_address = decode_segwit_address(
        "bc1q7ydrtdn8z62xhslqyqtyt38mm4e2c4h3mxjkug"
    )
    audit = authorize_audit(
        "user-supplied public address fixture",
        ("bip_test_vector", "public_address_decode", "checksum_validation", "search_space_estimate"),
    )
    metrics = (
        estimate_uniform_search(128, 1e15),
        estimate_uniform_search(160, 1e15),
        estimate_uniform_search(256, 1e15),
        estimate_uniform_search(20, 1e6),
    )
    invariants = (
        "ENT + CS = 11 * mnemonic_word_count",
        "CS = ENT / 32",
        "BIP39 word indices are 11-bit cells over a declared 2048-word list",
        "BIP32 hardened edges are not derivable from an extended public parent",
        "BIP84 mainnet receiving path is m/84'/0'/account'/0/index",
        "witness-v0 20-byte programs use Bech32 and map to P2WPKH scriptPubKey 0x0014{program}",
        "public address decoding does not reveal spend authority",
        "secret seed and private key material are never serialized by the certificate",
    )
    nonclaims = (
        "no third-party wallet access",
        "no mnemonic or passphrase enumeration",
        "no private-key or address-targeted preimage search",
        "no transaction signing, broadcasting or funds transfer",
        "no claim that a public address label proves legal ownership",
        "no claim that checksum validity authenticates a wallet owner",
    )
    valid = (
        validation.checksum_valid
        and validation.wordlist_fingerprint
        == "sha256:2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda"
        and public_derivation.address == "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
        and supplied_address.witness_program_hex == "f11a35b66716946bc3e0201645c4fbdd72ac56f1"
        and supplied_address.script_pubkey_hex == "0014f11a35b66716946bc3e0201645c4fbdd72ac56f1"
        and audit.authorized
        and not public_derivation.secrets_serialized
    )
    public_validation = {
        "word_count": validation.word_count,
        "entropy_bits": validation.entropy_bits,
        "checksum_bits": validation.checksum_bits,
        "checksum_valid": validation.checksum_valid,
        "wordlist_fingerprint": validation.wordlist_fingerprint,
        "test_vector_id": "bip39-zero-entropy-12-public",
        "secret_equivalent_cells_serialized": False,
    }
    return SARA363Certificate(
        schema_version="3.6.3",
        profile="sara363.seed-address-referential-algebra-v1",
        bip39_validation=public_validation,
        bip84_public_derivation=asdict(public_derivation),
        supplied_address_decode=asdict(supplied_address),
        audit_boundary=asdict(audit),
        search_metrics=tuple(asdict(metric) for metric in metrics),
        invariants=invariants,
        nonclaims=nonclaims,
        valid=valid,
    )
