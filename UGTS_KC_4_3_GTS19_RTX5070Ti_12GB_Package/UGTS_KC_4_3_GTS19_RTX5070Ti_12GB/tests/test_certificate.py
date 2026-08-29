from __future__ import annotations

import unittest

from ugts_go19.certificate import make_certificate, verify_certificate
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


if __name__ == "__main__":
    unittest.main()
