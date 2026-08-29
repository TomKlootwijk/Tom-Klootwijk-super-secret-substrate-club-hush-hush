"""Packed Set-Field Node 32 reference codec."""

from __future__ import annotations

from dataclasses import dataclass, replace


class ParityError(ValueError):
    pass


@dataclass(frozen=True)
class PackedNodeFields:
    family: int
    kappa: int
    delta_rho: int
    delta_theta: int
    grammar_path: int
    local_flags: int = 0
    active: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.family <= 7:
            raise ValueError("family must fit 3 bits")
        if self.kappa not in (0, 1):
            raise ValueError("kappa must be 0 or 1")
        if not -128 <= self.delta_rho <= 127:
            raise ValueError("delta_rho must fit signed int8")
        if not 0 <= self.delta_theta <= 255:
            raise ValueError("delta_theta must fit uint8")
        if not 0 <= self.grammar_path <= 255:
            raise ValueError("grammar_path must fit uint8")
        if not 0 <= self.local_flags <= 3:
            raise ValueError("local_flags must fit 2 bits")

    @property
    def operator_id(self) -> int:
        return (self.family << 1) | self.kappa


class PackedNode32:
    PARITY_SHIFT = 31
    OP_SHIFT = 27
    RHO_SHIFT = 19
    THETA_SHIFT = 11
    PATH_SHIFT = 3
    FLAGS_SHIFT = 1

    PAYLOAD_MASK = 0x7FFF_FFFF

    @staticmethod
    def _payload_parity(payload: int) -> int:
        return (payload & PackedNode32.PAYLOAD_MASK).bit_count() & 1

    @classmethod
    def pack(cls, fields: PackedNodeFields) -> int:
        payload = 0
        payload |= (fields.operator_id & 0xF) << cls.OP_SHIFT
        payload |= (fields.delta_rho & 0xFF) << cls.RHO_SHIFT
        payload |= (fields.delta_theta & 0xFF) << cls.THETA_SHIFT
        payload |= (fields.grammar_path & 0xFF) << cls.PATH_SHIFT
        payload |= (fields.local_flags & 0x3) << cls.FLAGS_SHIFT
        payload |= int(fields.active)
        parity = cls._payload_parity(payload)
        return payload | (parity << cls.PARITY_SHIFT)

    @classmethod
    def verify_parity(cls, word: int) -> bool:
        word &= 0xFFFF_FFFF
        expected = (word >> cls.PARITY_SHIFT) & 1
        return cls._payload_parity(word) == expected

    @classmethod
    def unpack(cls, word: int, *, verify: bool = True) -> PackedNodeFields:
        word &= 0xFFFF_FFFF
        if verify and not cls.verify_parity(word):
            raise ParityError(f"integrity parity mismatch for 0x{word:08x}")
        op = (word >> cls.OP_SHIFT) & 0xF
        rho_u8 = (word >> cls.RHO_SHIFT) & 0xFF
        delta_rho = rho_u8 - 256 if rho_u8 >= 128 else rho_u8
        return PackedNodeFields(
            family=op >> 1,
            kappa=op & 1,
            delta_rho=delta_rho,
            delta_theta=(word >> cls.THETA_SHIFT) & 0xFF,
            grammar_path=(word >> cls.PATH_SHIFT) & 0xFF,
            local_flags=(word >> cls.FLAGS_SHIFT) & 0x3,
            active=bool(word & 1),
        )

    @classmethod
    def klein_flip(cls, word: int) -> int:
        fields = cls.unpack(word)
        flipped = replace(
            fields,
            kappa=fields.kappa ^ 1,
            delta_theta=(-fields.delta_theta) & 0xFF,
        )
        return cls.pack(flipped)

    @classmethod
    def corrupt_bit(cls, word: int, bit: int) -> int:
        if not 0 <= bit <= 31:
            raise ValueError("bit must be in [0,31]")
        return (word ^ (1 << bit)) & 0xFFFF_FFFF
