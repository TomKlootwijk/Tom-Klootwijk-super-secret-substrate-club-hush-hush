"""Independent fixed-vector check against the literal SARA 3.6.3 Python substrate.

This script has no input surface and performs no search. It only evaluates the
published BIP39 and BIP32 test vectors embedded below.
"""

from __future__ import annotations

import sys
from pathlib import Path


SARA_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SARA_ROOT / "src"))

from ugts36.sara363 import (  # noqa: E402
    ckd_private,
    compressed_public_key,
    master_node_from_seed,
    mnemonic_to_seed,
)


MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
PASSPHRASE = "TREZOR"
BIP39_SEED = (
    "c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e5349553"
    "1f09a6987599d18264c1e1c92f2cf141630c7a3c4ab7c81b2f001698e7463b04"
)
BIP32_SEED = "000102030405060708090a0b0c0d0e0f"
PATH = (0x80000000, 1, 0x80000002, 2, 1000000000)
PATH_NAMES = (
    "m",
    "m/0'",
    "m/0'/1",
    "m/0'/1/2'",
    "m/0'/1/2'/2",
    "m/0'/1/2'/2/1000000000",
)
EXPECTED_PRIVATE = (
    "e8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35",
    "edb2e14f9ee77d26dd93b4ecede8d16ed408ce149b6cd80b0715a2d911a0afea",
    "3c6cb8d0f6a264c91ea8b5030fadaa8e538b020f0a387421a12de9319dc93368",
    "cbce0d719ecf7431d88e6a89fa1483e02e35092af60c042b1df2ff59fa424dca",
    "0f479245fb19a38a1954c5c7c0ebab2f9bdfd96a17563ef28a6a4b1a2a764ef4",
    "471b76e389e528d6de6d816857e012c5455051cad6660850e58372a6c3e6e7c8",
)
EXPECTED_CHAIN = (
    "873dff81c02f525623fd1fe5167eac3a55a049de3d314bb42ee227ffed37d508",
    "47fdacbd0f1097043b78c63c20c34ef4ed9a111d980047ad16282c7ae6236141",
    "2a7857631386ba23dacac34180dd1983734e444fdbf774041578e9b6adb37c19",
    "04466b9cc8e161e966409ca52986c584f07e9dc81f735db683c3ff6ec7b1503f",
    "cfb71883f01676f587d023cc53a35bc7f88f724b1f8c2892ac1275ac822a3edd",
    "c783e67b921d2beb8f6b389cc646d7263b4145701dadd2161548a8b078e65e9e",
)
EXPECTED_PUBLIC = (
    "0339a36013301597daef41fbe593a02cc513d0b55527ec2df1050e2e8ff49c85c2",
    "035a784662a4a20a65bf6aab9ae98a6c068a81c52e4b032c0fb5400c706cfccc56",
    "03501e454bf00751f24b1b489aa925215d66af2234e3891c3b21a52bedb3cd711c",
    "0357bfe1e341d01c69fe5654309956cbea516822fba8a601743a012a7896ee8dc2",
    "02e8445082a72f29b75ca48748a914df60622a609cacfce8ed0e35804560741d29",
    "022a471424da5e657499d1ff51cb43c47481a03b1e77f951fe64cec9f5a48f7011",
)


def main() -> int:
    seed = mnemonic_to_seed(MNEMONIC, PASSPHRASE)
    bip39_pass = seed.hex() == BIP39_SEED
    print(f"literal SARA 3.6.3 BIP39 fixture: {'PASS' if bip39_pass else 'FAIL'}")

    node = master_node_from_seed(bytes.fromhex(BIP32_SEED))
    nodes = [node]
    for index in PATH:
        node = ckd_private(node, index)
        nodes.append(node)

    bip32_pass = True
    for name, value, expected_private, expected_chain, expected_public in zip(
        PATH_NAMES, nodes, EXPECTED_PRIVATE, EXPECTED_CHAIN, EXPECTED_PUBLIC, strict=True
    ):
        passed = (
            value.private_key.to_bytes(32, "big").hex() == expected_private
            and value.chain_code.hex() == expected_chain
            and compressed_public_key(value.private_key).hex() == expected_public
        )
        bip32_pass &= passed
        print(f"literal SARA 3.6.3 BIP32 {name}: {'PASS' if passed else 'FAIL'}")

    overall = bip39_pass and bip32_pass
    print(f"literal substrate cross-check: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 2


if __name__ == "__main__":
    raise SystemExit(main())
