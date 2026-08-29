from __future__ import annotations

import unittest

from _bootstrap import ROOT
from ugts5.set_fields import (
    FieldCapability,
    FiniteSetField,
    complement_value,
    difference_value,
    evaluate_relation,
    field_truth_table,
    inside,
    intersection_value,
    metric_signed_set_field,
    symmetric_difference_value,
    union_value,
)


class SetFieldAlgebraTests(unittest.TestCase):
    def test_sign_convention(self):
        self.assertTrue(inside(-1.0))
        self.assertTrue(inside(0.0))
        self.assertFalse(inside(1.0))

    def test_union_truth_table(self):
        for a_in in (False, True):
            for b_in in (False, True):
                a = -1.0 if a_in else 1.0
                b = -1.0 if b_in else 1.0
                self.assertEqual(inside(union_value(a, b)), a_in or b_in)

    def test_intersection_truth_table(self):
        for a_in in (False, True):
            for b_in in (False, True):
                a = -1.0 if a_in else 1.0
                b = -1.0 if b_in else 1.0
                self.assertEqual(inside(intersection_value(a, b)), a_in and b_in)

    def test_complement_truth_table(self):
        self.assertFalse(inside(complement_value(-1.0)))
        self.assertTrue(inside(complement_value(1.0)))

    def test_difference_truth_table(self):
        for a_in in (False, True):
            for b_in in (False, True):
                a = -1.0 if a_in else 1.0
                b = -1.0 if b_in else 1.0
                self.assertEqual(inside(difference_value(a, b)), a_in and not b_in)

    def test_symmetric_difference_truth_table(self):
        for a_in in (False, True):
            for b_in in (False, True):
                a = -1.0 if a_in else 1.0
                b = -1.0 if b_in else 1.0
                self.assertEqual(inside(symmetric_difference_value(a, b)), a_in ^ b_in)

    def test_field_truth_table_keys(self):
        result = field_truth_table(-1.0, 1.0)
        self.assertEqual(result["symmetric_difference"], True)
        self.assertEqual(result["intersection"], False)

    def test_metric_signed_set_field(self):
        f = metric_signed_set_field(0.0, [-1.0, 0.0], [2.0, 3.0], lambda a, b: abs(a-b))
        self.assertLess(f, 0.0)

    def test_metric_field_requires_both_supports(self):
        with self.assertRaises(ValueError):
            metric_signed_set_field(0.0, [], [1.0], lambda a, b: abs(a-b))


class FiniteSetFieldTests(unittest.TestCase):
    def setUp(self):
        self.U = (0, 1, 2, 3, 4)
        self.A = FiniteSetField.from_members(self.U, {1, 2}, label="A")
        self.B = FiniteSetField.from_members(self.U, {1, 2, 3}, label="B")

    def test_capability(self):
        self.assertEqual(self.A.capability, FieldCapability.SIGNED_MEMBERSHIP_FIELD)

    def test_membership_values(self):
        self.assertEqual(self.A.value(1), -1.0)
        self.assertEqual(self.A.value(4), 1.0)

    def test_outside_universe_rejects(self):
        with self.assertRaises(KeyError):
            self.A.value(99)

    def test_duplicate_universe_rejects(self):
        with self.assertRaises(ValueError):
            FiniteSetField.from_members((1, 1, 2), {1})

    def test_member_outside_universe_rejects(self):
        with self.assertRaises(ValueError):
            FiniteSetField.from_members((1, 2), {3})

    def test_subset_and_proper_subset(self):
        self.assertTrue(self.A.subset_of(self.B))
        self.assertTrue(self.A.proper_subset_of(self.B))
        self.assertFalse(self.B.proper_subset_of(self.B))

    def test_equality(self):
        A2 = FiniteSetField.from_members(self.U, {1, 2})
        self.assertTrue(self.A.equals(A2))

    def test_union(self):
        self.assertEqual(self.A.union(self.B).members, frozenset({1, 2, 3}))

    def test_intersection(self):
        self.assertEqual(self.A.intersection(self.B).members, frozenset({1, 2}))

    def test_complement(self):
        self.assertEqual(self.A.complement().members, frozenset({0, 3, 4}))

    def test_difference(self):
        self.assertEqual(self.B.difference(self.A).members, frozenset({3}))

    def test_symmetric_difference(self):
        self.assertEqual(self.A.symmetric_difference(self.B).members, frozenset({3}))

    def test_different_universe_rejects(self):
        other = FiniteSetField.from_members((0, 1), {1})
        with self.assertRaises(ValueError):
            self.A.subset_of(other)

    def test_membership_relations_direct_and_converse(self):
        self.assertTrue(evaluate_relation("∈", 1, self.A))
        self.assertTrue(evaluate_relation("∋", self.A, 1))
        self.assertTrue(evaluate_relation("∉", 4, self.A))
        self.assertTrue(evaluate_relation("∌", self.A, 4))

    def test_subset_relations_direct_and_converse(self):
        self.assertTrue(evaluate_relation("⊂", self.A, self.B))
        self.assertTrue(evaluate_relation("⊃", self.B, self.A))
        self.assertTrue(evaluate_relation("⊆", self.A, self.B))
        self.assertTrue(evaluate_relation("⊇", self.B, self.A))

    def test_negated_subset_relations(self):
        self.assertFalse(evaluate_relation("⊄", self.A, self.B))
        self.assertFalse(evaluate_relation("⊅", self.B, self.A))
        self.assertFalse(evaluate_relation("⊈", self.A, self.B))
        self.assertFalse(evaluate_relation("⊉", self.B, self.A))

    def test_strict_variant(self):
        self.assertTrue(evaluate_relation("⊊", self.A, self.B))
        self.assertTrue(evaluate_relation("⊋", self.B, self.A))


if __name__ == "__main__":
    unittest.main()
