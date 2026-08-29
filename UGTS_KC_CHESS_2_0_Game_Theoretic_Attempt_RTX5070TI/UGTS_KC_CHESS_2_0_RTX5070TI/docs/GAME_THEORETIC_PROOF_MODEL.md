# Classical chess as a finite proof problem

The authoritative game state is

```
Q = (board, side, castling rights, legal en-passant right,
     halfmove clock, fullmove number, repetition-count context,
     rule profile, lineage)
```

A legal action is either a verified move or an available draw claim. Automatic terminals include checkmate, stalemate, fivefold repetition and the 75-move rule. Dead position requires a certificate under the full classical profile; the bundled recognizer covers a conservative exact subset.

For a completed finite graph, the least WIN/LOSS fixed point is seeded by terminal nodes:

- checkmated side-to-move: LOSS;
- automatic/claimed draw: DRAW;
- WIN when at least one action reaches LOSS;
- LOSS when every legal action reaches WIN;
- the closed unresolved complement is DRAW only after the graph is complete.

For bounded search, unresolved children keep the parent UNKNOWN unless an exact winning child already closes the existential obligation. No-mate-at-depth is never promoted to DRAW.

The twenty initial legal moves form stable root obligations. Their child values are from the child side-to-move perspective. One verified child LOSS proves a White root WIN; all twenty verified child WIN values prove a White root LOSS; otherwise a DRAW requires complete resolved coverage and at least one draw continuation. Until then, the root is UNKNOWN.
