from __future__ import annotations

import copy
import unittest

from _bootstrap import ROOT
from ugts5.atlas import AtlasError, HotCodebook, OperatorAtlas
from ugts5.canonical import load_json
from ugts5.set_fields import FiniteSetField


class AtlasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.atlas = OperatorAtlas.load(ROOT / "spec" / "operator_atlas.json")
        cls.codebook = HotCodebook.load(ROOT / "spec" / "hot_codebook_set_core_16.json", cls.atlas)

    def test_operator_count(self):
        self.assertEqual(len(self.atlas.literals), 20)

    def test_required_literals(self):
        for literal in ["∈", "∋", "∉", "∌", "⊂", "⊃", "⊆", "⊇", "⊄", "⊅", "⊈", "⊉", "⊊", "⊋", "∪", "∩", "∖", "∁", "∅", "="]:
            self.atlas.by_literal(literal)

    def test_unicode_scalar_and_utf8(self):
        cell = self.atlas.by_literal("∈")
        self.assertEqual(cell.record["unicode"]["scalars"], ["U+2208"])
        self.assertEqual(bytes.fromhex(cell.record["unicode"]["utf8_hex"]).decode("utf-8"), "∈")

    def test_converse_links_are_symmetric(self):
        for literal in ["∈", "∉", "⊂", "⊆", "⊄", "⊈", "⊊"]:
            cell = self.atlas.by_literal(literal)
            converse = self.atlas.by_id(cell.converse_id)
            self.assertEqual(self.atlas.by_id(converse.converse_id).id, cell.id)
            self.assertEqual(converse.kappa, cell.kappa ^ 1)

    def test_surface_and_canonical_port_maps(self):
        direct = self.atlas.by_literal("∈").record["syntax"]
        converse = self.atlas.by_literal("∋").record["syntax"]
        self.assertEqual(direct["surface_to_canonical"], [0, 1])
        self.assertEqual(converse["surface_to_canonical"], [1, 0])
        self.assertEqual(direct["canonical_argument_order"], converse["canonical_argument_order"])

    def test_semantic_converse_equivalence(self):
        U = ("x", "y")
        A = FiniteSetField.from_members(U, {"x"})
        self.assertEqual(self.atlas.by_literal("∈").evaluate("x", A), self.atlas.by_literal("∋").evaluate(A, "x"))

    def test_codebook_slots_follow_family_kappa(self):
        for slot in range(14):
            cell = self.codebook.resolve_slot(slot)
            self.assertEqual(slot, (cell.record["family_id"] << 1) | cell.kappa)

    def test_reserved_slots_reject(self):
        for slot in (14, 15):
            with self.assertRaises(AtlasError):
                self.codebook.resolve_slot(slot)

    def test_slot_lookup(self):
        self.assertEqual(self.codebook.slot_for_literal("⊇"), 7)

    def test_unknown_literal_rejects(self):
        with self.assertRaises(AtlasError):
            self.atlas.by_literal("?")

    def test_tampered_cell_hash_rejects(self):
        record = load_json(ROOT / "spec" / "operator_atlas.json")
        record["operators"][0]["semantic"]["kernel"] = "tampered"
        with self.assertRaises(AtlasError):
            OperatorAtlas(record).verify_hashes()

    def test_tampered_atlas_hash_rejects(self):
        record = load_json(ROOT / "spec" / "operator_atlas.json")
        record["atlas_hash"] = "0" * 64
        with self.assertRaises(AtlasError):
            OperatorAtlas(record).verify_hashes()

    def test_codebook_wrong_atlas_rejects(self):
        codebook = load_json(ROOT / "spec" / "hot_codebook_set_core_16.json")
        codebook["atlas_hash"] = "0" * 64
        with self.assertRaises(AtlasError):
            HotCodebook(codebook, self.atlas)


if __name__ == "__main__":
    unittest.main()
