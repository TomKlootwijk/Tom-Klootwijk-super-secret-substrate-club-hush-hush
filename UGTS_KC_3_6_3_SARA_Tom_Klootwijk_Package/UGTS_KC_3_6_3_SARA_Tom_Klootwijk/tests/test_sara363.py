from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts36.sara363 import (  # noqa: E402
    HARDENED,
    AddressDecode,
    authorize_audit,
    bech32_decode,
    build_reference_sara363_certificate,
    ckd_private,
    compressed_public_key,
    decode_segwit_address,
    derive_bip84_public_certificate,
    derive_private_path,
    encode_segwit_address,
    entropy_to_mnemonic,
    estimate_uniform_search,
    hash160,
    load_bip39_wordlist,
    master_node_from_seed,
    mnemonic_to_seed,
    parse_derivation_path,
    valid_bip39_keyspace_bits,
    validate_mnemonic,
    wordlist_fingerprint,
)
from ugts36.sara_runtime import SARARuntime  # noqa: E402
from ugts36.canonical import verify_content_hash  # noqa: E402
from ugts36.model import Substrate  # noqa: E402
import jsonschema  # noqa: E402

WORDLIST_PATH = ROOT / "data" / "bip39_english.txt"
MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
TARGET = "bc1q7ydrtdn8z62xhslqyqtyt38mm4e2c4h3mxjkug"


class WordlistAndMnemonicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.words = load_bip39_wordlist(WORDLIST_PATH)

    def test_wordlist_count(self):
        self.assertEqual(len(self.words), 2048)

    def test_wordlist_fingerprint(self):
        self.assertEqual(
            wordlist_fingerprint(self.words),
            "sha256:2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda",
        )

    def test_zero_entropy_mnemonic(self):
        self.assertEqual(entropy_to_mnemonic(bytes(16), self.words), MNEMONIC)

    def test_mnemonic_validation(self):
        result = validate_mnemonic(MNEMONIC, self.words)
        self.assertTrue(result.checksum_valid)
        self.assertEqual(result.word_count, 12)
        self.assertEqual(result.entropy_bits, 128)
        self.assertEqual(result.checksum_bits, 4)
        self.assertEqual(result.indices, (0,) * 11 + (3,))

    def test_invalid_checksum_is_detected(self):
        bad = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon ability"
        result = validate_mnemonic(bad, self.words)
        self.assertFalse(result.checksum_valid)

    def test_invalid_word_count_rejected(self):
        with self.assertRaises(ValueError):
            validate_mnemonic("abandon about", self.words)

    def test_unknown_word_rejected(self):
        with self.assertRaises(ValueError):
            validate_mnemonic("abandon " * 11 + "notaword", self.words)

    def test_bad_wordlist_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.txt"
            path.write_text("abandon\nabout\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_bip39_wordlist(path)

    def test_bip39_seed_vector_trezor(self):
        self.assertEqual(
            mnemonic_to_seed(MNEMONIC, "TREZOR").hex(),
            "c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e5349553"
            "1f09a6987599d18264c1e1c92f2cf141630c7a3c4ab7c81b2f001698e7463b04",
        )

    def test_bip39_keyspace_bits(self):
        self.assertEqual(valid_bip39_keyspace_bits(12), 128)
        self.assertEqual(valid_bip39_keyspace_bits(24), 256)
        with self.assertRaises(ValueError):
            valid_bip39_keyspace_bits(13)


class BIP32AndBIP84Tests(unittest.TestCase):
    def test_path_parser(self):
        self.assertEqual(
            parse_derivation_path("m/84'/0'/0'/0/0"),
            (84 | HARDENED, 0 | HARDENED, 0 | HARDENED, 0, 0),
        )
        self.assertEqual(parse_derivation_path("m"), ())

    def test_path_parser_rejects_bad_root(self):
        with self.assertRaises(ValueError):
            parse_derivation_path("84'/0'/0'")

    def test_path_parser_rejects_bad_component(self):
        with self.assertRaises(ValueError):
            parse_derivation_path("m/84'/x/0")

    def test_bip84_first_public_vector(self):
        cert = derive_bip84_public_certificate(MNEMONIC)
        self.assertEqual(
            cert.compressed_public_key_hex,
            "0330d54fd0dd420a6e5f8d3624f5f3482cae350f79d5f0753bf5beef9c2d91af3c",
        )
        self.assertEqual(cert.address, "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu")
        self.assertEqual(cert.path, "m/84'/0'/0'/0/0")
        self.assertFalse(cert.secrets_serialized)

    def test_bip84_second_public_vector(self):
        cert = derive_bip84_public_certificate(MNEMONIC, "m/84'/0'/0'/0/1")
        self.assertEqual(
            cert.compressed_public_key_hex,
            "03e775fd51f0dfb8cd865d9ff1cca2a158cf651fe997fdc9fee9c1d3b5e995ea77",
        )
        self.assertEqual(cert.address, "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g")

    def test_bip84_change_public_vector(self):
        cert = derive_bip84_public_certificate(MNEMONIC, "m/84'/0'/0'/1/0")
        self.assertEqual(
            cert.compressed_public_key_hex,
            "03025324888e429ab8e3dbaf1f7802648b9cd01e9b418485c5fa4c1b9b5700e1a6",
        )
        self.assertEqual(cert.address, "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el")

    def test_no_private_fields_in_public_certificate(self):
        cert_dict = asdict(derive_bip84_public_certificate(MNEMONIC))
        forbidden = {"private_key", "seed", "chain_code", "xprv", "wif", "mnemonic", "mnemonic_fingerprint", "seed_fingerprint"}
        self.assertTrue(forbidden.isdisjoint(cert_dict))

    def test_master_and_child_are_internal(self):
        root = master_node_from_seed(mnemonic_to_seed(MNEMONIC))
        child = ckd_private(root, 84 | HARDENED)
        self.assertEqual(child.depth, 1)
        self.assertEqual(len(compressed_public_key(child.private_key)), 33)

    def test_derive_path_depth(self):
        root = master_node_from_seed(mnemonic_to_seed(MNEMONIC))
        node = derive_private_path(root, "m/84'/0'/0'/0/0")
        self.assertEqual(node.depth, 5)
        self.assertEqual(node.child_number, 0)


class Bech32Tests(unittest.TestCase):
    def test_official_p2wpkh_vector(self):
        decoded = decode_segwit_address("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        self.assertEqual(decoded.address_type, "p2wpkh")
        self.assertEqual(decoded.script_pubkey_hex, "0014751e76e8199196d454941c45d1b3a323f1433bd6")

    def test_supplied_address_decode(self):
        decoded = decode_segwit_address(TARGET)
        self.assertEqual(decoded.hrp, "bc")
        self.assertEqual(decoded.checksum_family, "bech32")
        self.assertEqual(decoded.witness_version, 0)
        self.assertEqual(decoded.witness_program_bytes, 20)
        self.assertEqual(decoded.address_type, "p2wpkh")
        self.assertEqual(decoded.witness_program_hex, "f11a35b66716946bc3e0201645c4fbdd72ac56f1")
        self.assertEqual(decoded.script_pubkey_hex, "0014f11a35b66716946bc3e0201645c4fbdd72ac56f1")

    def test_roundtrip_supplied_program(self):
        decoded = decode_segwit_address(TARGET)
        self.assertEqual(
            encode_segwit_address("bc", 0, bytes.fromhex(decoded.witness_program_hex)), TARGET
        )

    def test_bech32m_v1_vector(self):
        address = "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0"
        decoded = decode_segwit_address(address)
        self.assertEqual(decoded.checksum_family, "bech32m")
        self.assertEqual(decoded.witness_version, 1)
        self.assertEqual(decoded.witness_program_bytes, 32)
        self.assertEqual(decoded.address_type, "p2tr-or-v1-32-byte-program")

    def test_mixed_case_rejected(self):
        with self.assertRaises(ValueError):
            decode_segwit_address("bC1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")

    def test_invalid_checksum_rejected(self):
        with self.assertRaises(ValueError):
            decode_segwit_address("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kemeawh")

    def test_program_length_rules(self):
        with self.assertRaises(ValueError):
            encode_segwit_address("bc", 0, b"\x00" * 21)


class AuthorizationAndMetricsTests(unittest.TestCase):
    def test_authorized_public_scope(self):
        cert = authorize_audit(
            "public fixture",
            ["bip_test_vector", "public_address_decode", "search_space_estimate"],
        )
        self.assertTrue(cert.authorized)
        self.assertTrue(cert.public_only)
        self.assertFalse(cert.secret_egress)
        self.assertFalse(cert.network_access)
        self.assertFalse(cert.transaction_capability)

    def test_private_key_search_rejected(self):
        cert = authorize_audit("third-party address", ["third_party_mainnet_key_search"])
        self.assertFalse(cert.authorized)
        self.assertIn("FORBIDDEN_PRIVATE_KEY_OR_FUNDS_ACCESS_SCOPE", cert.reason_codes)

    def test_unknown_scope_rejected(self):
        cert = authorize_audit("unknown", ["something_else"])
        self.assertFalse(cert.authorized)
        self.assertIn("UNRECOGNIZED_OR_UNAUTHORIZED_SCOPE", cert.reason_codes)

    def test_empty_scope_rejected(self):
        cert = authorize_audit("empty", [])
        self.assertFalse(cert.authorized)
        self.assertIn("EMPTY_SCOPE", cert.reason_codes)

    def test_search_estimate_128(self):
        estimate = estimate_uniform_search(128, 1e15)
        self.assertEqual(estimate.total_candidates, 1 << 128)
        self.assertAlmostEqual(estimate.expected_guesses, 2**127)
        self.assertGreater(estimate.expected_years, 5e15)

    def test_search_estimate_rejects_bad_rate(self):
        with self.assertRaises(ValueError):
            estimate_uniform_search(128, 0)
        with self.assertRaises(ValueError):
            estimate_uniform_search(0, 1)

    def test_toy_metric_is_small_only_by_declaration(self):
        estimate = estimate_uniform_search(20, 1e6)
        self.assertAlmostEqual(estimate.expected_seconds, 0.524288)


class IntegratedCertificateTests(unittest.TestCase):
    def test_reference_certificate(self):
        cert = build_reference_sara363_certificate(WORDLIST_PATH)
        self.assertTrue(cert.valid)
        self.assertEqual(cert.schema_version, "3.6.3")
        self.assertFalse(cert.bip84_public_derivation["secrets_serialized"])

    def test_runtime_trace(self):
        output = SARARuntime(WORDLIST_PATH).run_reference()
        self.assertTrue(output["certificate"]["valid"])
        self.assertEqual(output["trace"][-1]["operator"], "sara363.certificate.issue")
        self.assertEqual(output["trace"][-1]["status"], "pass")

    def test_reference_output_serializable(self):
        output = SARARuntime(WORDLIST_PATH).run_reference()
        text = json.dumps(output, sort_keys=True)
        self.assertNotIn("private_key", text)
        self.assertNotIn("chain_code", text)
        self.assertNotIn("mnemonic_fingerprint", text)
        self.assertNotIn("seed_fingerprint", text)
        self.assertNotIn('"indices"', text)
        self.assertNotIn("entropy_fingerprint", text)
        self.assertIn(TARGET, text)


class PackageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.example_path = ROOT / "examples" / "ugts_kc_3_6_3_sara_example.json"
        self.schema_path = ROOT / "spec" / "ugts_kc_3_6_3_sara.schema.json"

    def test_schema_validation(self):
        instance = json.loads(self.example_path.read_text(encoding="utf-8"))
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(instance))
        self.assertEqual(errors, [])

    def test_definition_hashes(self):
        instance = json.loads(self.example_path.read_text(encoding="utf-8"))
        self.assertTrue(all(verify_content_hash(item) for item in instance["definitions"]))

    def test_references_and_order(self):
        substrate = Substrate.load(self.example_path)
        self.assertEqual(len(substrate.definitions), 19)
        self.assertEqual(len(substrate.definition_order()), 19)

    def test_operator_catalog(self):
        rows = json.loads((ROOT / "spec" / "sara_3_6_3_delta_operator_catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 45)
        self.assertTrue(all(item["id"].startswith("sara363.") for item in rows))

    def test_claims_ledger(self):
        rows = json.loads((ROOT / "spec" / "sara_3_6_3_claims_ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 20)
        self.assertTrue(any(item["id"] == "SARA-C015" and item["disposition"] == "REJECT" for item in rows))

    def test_attribution(self):
        instance = json.loads(self.example_path.read_text(encoding="utf-8"))
        att = instance["metadata"]["requester_attribution"]
        self.assertEqual(att["name"], "Tom Klootwijk")
        self.assertEqual(att["identifier"], "NL200678942")


if __name__ == "__main__":
    unittest.main()
