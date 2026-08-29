from __future__ import annotations

import json
import hashlib
import unittest

from ugts_go19.digests import (
    canonical_proof_state_json,
    canonical_proof_state_payload,
    state_digest,
)
from ugts_go19.engine import apply_move
from ugts_go19.rules import Rules
from ugts_go19.state import State


class CanonicalStateSerializationTests(unittest.TestCase):
    def test_exact_semantic_payload_is_stable_and_excludes_ply(self) -> None:
        rules = Rules(size=2, komi2=1, profile_id="state-json-2x2")
        initial = State.initial(rules)
        expected = (
            '{"board_hex":"00000000","format":"UGTS-GO-STATE-v1",'
            '"passes":0,"previous_board_hex":null,"rules":{'
            '"allow_suicide":false,"komi2":1,"passes_to_end":2,'
            '"scoring":"area","size":2,"superko":"positional_superko"},'
            '"seen_hex":["00000000"],"to_play":1}'
        )
        self.assertEqual(canonical_proof_state_json(initial, rules), expected)
        object_id = hashlib.sha256(expected.encode("utf-8")).hexdigest()
        self.assertNotEqual(object_id, state_digest(initial, rules))

        moved = apply_move(initial, 0, rules)
        same_semantics_different_ply = State(
            board=moved.board,
            to_play=moved.to_play,
            passes=moved.passes,
            seen=moved.seen,
            previous_board=moved.previous_board,
            ply=moved.ply + 99,
        )
        self.assertEqual(
            canonical_proof_state_json(moved, rules),
            canonical_proof_state_json(same_semantics_different_ply, rules),
        )
        self.assertEqual(
            json.loads(canonical_proof_state_json(moved, rules)),
            canonical_proof_state_payload(moved, rules),
        )


if __name__ == "__main__":
    unittest.main()
