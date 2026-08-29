from __future__ import annotations

import unittest

from ugts_go19.certificate import make_certificate, verify_certificate
from ugts_go19.digests import canonical_json_bytes, sha256_hex, state_digest
from ugts_go19.rules import Rules
from ugts_go19.state import State


class CertificateTests(unittest.TestCase):
    def test_tiny_certificate_recomputes(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="certificate-1x1")
        certificate = make_certificate(rules, State.initial(rules), node_budget=20_000)
        result = verify_certificate(certificate, node_budget=20_000)
        self.assertTrue(result["verified"])
        self.assertEqual(result["value2"], -1)

    def test_tamper_is_detected(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="certificate-1x1")
        certificate = make_certificate(rules, State.initial(rules), node_budget=20_000)
        certificate["result"]["value2"] = 99
        with self.assertRaises(ValueError):
            verify_certificate(certificate, node_budget=20_000)

    def test_certificate_generation_is_byte_deterministic(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="certificate-determinism")
        root = State.initial(rules)
        first = make_certificate(rules, root, node_budget=20_000)
        second = make_certificate(rules, root, node_budget=20_000)
        self.assertEqual(first, second)

    def test_rehashed_result_metadata_tamper_is_detected(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="certificate-metadata")
        certificate = make_certificate(rules, State.initial(rules), node_budget=20_000)
        certificate["result"]["winner"] = "black"
        unhashed = dict(certificate)
        unhashed.pop("certificate_sha256")
        certificate["certificate_sha256"] = sha256_hex(canonical_json_bytes(unhashed))
        with self.assertRaises(ValueError):
            verify_certificate(certificate, node_budget=20_000)

    def test_invalid_terminal_root_is_rejected(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="certificate-invalid-root")
        invalid = State(
            board=bytes((7,)),
            to_play=1,
            passes=2,
            seen=frozenset(),
            previous_board=None,
        )
        with self.assertRaises(ValueError):
            make_certificate(rules, invalid, node_budget=20_000)

    def test_state_digest_includes_previous_board(self) -> None:
        rules = Rules(
            size=2,
            komi2=1,
            superko="simple_ko",
            profile_id="digest-previous-board",
        )
        root = State.initial(rules)
        first = State(
            board=root.board,
            to_play=root.to_play,
            passes=0,
            seen=root.seen,
            previous_board=bytes(4),
        )
        second = State(
            board=root.board,
            to_play=root.to_play,
            passes=0,
            seen=root.seen,
            previous_board=bytes((1, 0, 0, 0)),
        )
        self.assertNotEqual(state_digest(first, rules), state_digest(second, rules))

    def test_verification_does_not_require_identical_pv_budget(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="certificate-pv-budget")
        certificate = make_certificate(rules, State.initial(rules), node_budget=3)
        self.assertEqual(
            set(certificate["result"]), {"value2", "value_points", "winner"}
        )
        result = verify_certificate(certificate, node_budget=20_000)
        self.assertTrue(result["verified"])

    def test_noncanonical_root_field_type_is_rejected(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="certificate-root-types")
        certificate = make_certificate(rules, State.initial(rules), node_budget=20_000)
        certificate["root"]["to_play"] = "1"
        unhashed = dict(certificate)
        unhashed.pop("certificate_sha256")
        certificate["certificate_sha256"] = sha256_hex(canonical_json_bytes(unhashed))
        with self.assertRaises(ValueError):
            verify_certificate(certificate, node_budget=20_000)


if __name__ == "__main__":
    unittest.main()
