# Global Chess Solve Architecture

A full game-theoretic solution requires a checker-verifiable proof graph, not merely a strong engine score.

1. Freeze the legal kernel, draw policy, history representation and canonical state schema.
2. Expand exact tablebases by material signature and include DTM/DTZ policy metadata.
3. Shard unresolved state sectors by material, castling/en-passant/history class and canonical hash prefix.
4. Let workers propose WDL certificates; never let workers write authoritative outcomes directly.
5. Recompute every boundary move through the legal kernel and verify all AND-node reply coverage.
6. Merge only conflict-free, hash-addressed certificates and record source shard lineage.
7. Use heuristic engines or neural policies only for ordering and prioritization.
8. Continue until the initial-position node is certified or a proof boundary remains explicitly unresolved.

Kill criteria include omitted legal moves, hash collisions treated as identity, ambiguous repetition history, silent draw-rule changes, non-reproducible tablebase generation, or heuristic evaluation being promoted to proof.
