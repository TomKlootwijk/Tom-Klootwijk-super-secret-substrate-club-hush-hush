from __future__ import annotations

import json

from ugts_chess import MateProver, Position, Searcher, verify_mate_certificate

fen = "8/8/8/8/8/k7/8/1QK5 w - - 0 1"
position = Position.from_fen(fen)
search = Searcher().search(position, max_depth=4)
proof = MateProver().prove(position, max_plies=3)
verified = verify_mate_certificate(proof.certificate)
print(json.dumps({"search": search.to_dict(position), "proof": proof.certificate, "verified": verified}, indent=2))
