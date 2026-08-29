# UGTS-KC Chess 1.0 - Formal Definition

## Decision

UGTS-KC Chess 1.0 is a finite, deterministic, proof-carrying application profile over standard chess. It uses the UGTS authority chain:

`movement support -> occupancy/rule compatibility -> king-safety and special-rule guards -> verified move event -> deterministic board/rights/clock patch -> hash lineage and replay`

Heuristic evaluation, rendering and move ordering are downstream aids. They never create legal authority or a proof by themselves.

## Typed state

A position is

`q = (B, s, C, e, h, n, H, L)`

where:

- `B` is a 64-cell board carrying typed pieces;
- `s` is the side to move;
- `C` is the four-bit castling-right set;
- `e` is an optional en-passant target;
- `h` is the halfmove clock;
- `n` is the fullmove number;
- `H` is the repetition-history context when required;
- `L` is event lineage.

A one-bit side field is intentionally narrow. It is never treated as complete state.

## Verified move rule

A candidate move `m` is legal exactly when:

1. its source and destination lie in the selected piece's finite movement support;
2. source ownership, destination occupancy, capture and promotion types are compatible;
3. castling/en-passant/promotion preconditions hold when applicable;
4. after applying the full candidate patch, the moving side's king is not attacked.

The king is not captured. Checkmate is a terminal relation: check plus zero legal replies.

## Proof semantics

For a declared attacker and finite ply horizon:

- attacker nodes are OR nodes: one legal move with a proved child is sufficient;
- defender nodes are AND nodes: every legal reply must be listed and proved;
- leaves must independently verify as checkmate for the attacker;
- every node carries exact FEN and SHA-256 state identity.

A failed finite-horizon search means only `not_forced_within_horizon`.

## Exact three-piece tablebases

KQK and KRK use the dense address

`K = (((Ks * 64) + X) * 64 + Kw) * 2 + side`

with exactly `2^19 = 524,288` cells. Invalid cells remain explicit. Retrograde propagation assigns WDL and depth-to-mate (DTM). The transport file stores one outcome byte and one DTM byte per cell, then uses gzip for distribution.

## Evidence boundary

This package proves its legal kernel against perft fixtures, verifies bounded mate certificates and exactly solves the bundled KQK/KRK state spaces. It does not claim a weak or strong game-theoretic solution of the standard initial position.
