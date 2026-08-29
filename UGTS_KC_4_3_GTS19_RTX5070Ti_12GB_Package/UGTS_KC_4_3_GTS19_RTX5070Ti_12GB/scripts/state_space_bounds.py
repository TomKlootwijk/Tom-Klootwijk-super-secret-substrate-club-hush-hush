#!/usr/bin/env python3
from __future__ import annotations

import json
import math


def main() -> int:
    colorings_log10 = 361 * math.log10(3)
    payload = {
        "board_colorings": "3^361",
        "board_colorings_log10": colorings_log10,
        "first_move_placements": 361,
        "first_move_D4_orbits": 55,
        "first_actions_including_pass_after_D4": 56,
        "score2_min": -737,
        "score2_max": 707,
        "possible_score_values": 723,
        "max_binary_threshold_questions": math.ceil(math.log2(723)),
        "warning": "finiteness and threshold counts are not practical search-size estimates",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
