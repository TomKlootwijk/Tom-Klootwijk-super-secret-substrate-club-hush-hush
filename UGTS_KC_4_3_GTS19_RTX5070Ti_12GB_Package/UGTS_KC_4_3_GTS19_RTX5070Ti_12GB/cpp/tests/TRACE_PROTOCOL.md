# Native parity trace protocol

`ugts_go_trace_eval` is a dependency-free differential-test endpoint for the
canonical area-scoring, positional-superko transition semantics. It reads one
state per line from standard input. Input fields are separated by `|`:

```text
UGTS_TRACE_V1|id|size|komi2|allow_suicide|passes_to_end|to_play|passes|ply|board_hex|previous_board_hex_or_-|sorted_seen_board_hex_csv_or_-
```

Boards use one byte per point encoded as lowercase hexadecimal (`00` empty,
`01` Black, `02` White). Points are row-major. `to_play` is `1` or `2`, pass is
move `-1`, and booleans are `0` or `1`. The protocol fixes area scoring and
positional superko; it intentionally has no field that can silently select a
different repetition or scoring rule.

For each input state the evaluator emits JSON Lines in deterministic order:

1. one `kind: "state"` record containing `terminal`, `score2`, and the complete
   ordered legal action list;
2. one `kind: "move"` record for every legal action, in that same order,
   containing the resulting board, capture counts, player, pass count, previous
   board, sorted exact seen-board set, ply, terminal flag, and area score.

Malformed input and non-move runtime failures terminate the evaluator with a
nonzero status. They are never converted into an empty or shortened legal set.
