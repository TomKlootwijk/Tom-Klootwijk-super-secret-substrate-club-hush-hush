# UGTS Chess Proof Campaign 2.0 - formal definition

Canonical identity: `ugts.application.chess-proof@2.0.0`

## Release decision

GO as an executable game-theoretic attempt and RTX 5070 Ti Laptop handoff. The orthodox initial position remains `UNKNOWN`. No weak, strong or ultra-weak solution is claimed.

## Formal object

```
UGTS-CHESS-2 = (Q, A, M, G, T, H, V, C, P, L, X)
```

- `Q`: complete typed positions and rule profile.
- `A`: attack, support, occupancy and king-safety relations.
- `M`: deterministic legal move relation.
- `G`: terminal and draw-claim guards.
- `T`: immutable state transitions.
- `H`: exact repetition-count and move-count history context.
- `V`: `WIN | LOSS | DRAW | UNKNOWN` proof values.
- `C`: content-addressed proof certificates and independent checker records.
- `P`: partition/campaign ledger and deterministic merge policy.
- `L`: event, replay and proof lineage.
- `X`: optional CPU/CUDA proposal and fixed-point execution adapters.

## Canonical authority order

```
parse -> normalize -> resolve -> type -> canonicalize -> plan
-> evaluate move/attack relations -> certify special rights
-> support -> compatibility -> terminal/king-safety guards
-> proposal -> atomic commit -> lineage -> projection
```

Pure or parallel work never mutates authority. A proposal whose pre-state hash does not match the current state is rejected.

## WDL obligations

- `WIN(q)`: at least one verified legal action reaches a certified `LOSS` child.
- `LOSS(q)`: every verified legal action is covered and reaches a certified `WIN` child.
- `DRAW(q)`: no legal action reaches `LOSS`, and a draw action, draw terminal or complete closed-complement certificate exists.
- `UNKNOWN(q)`: any required graph edge, history state, dead-position decision or proof obligation remains open.

## Draw semantics

Threefold repetition and the 50-move rule are optional actions owned by the player to move. A player may also claim by declaring an intended legal move that creates the threshold. Fivefold repetition and the 75-move rule are automatic. Checkmate takes priority. Repetition identity includes a legal en-passant right only when an en-passant capture is legal.

## Finite proof campaign

The classical initial position has twenty root obligations. The SQLite ledger may lease work and record candidate certificates, but only an independent checker can mark a candidate verified. The root aggregate consumes verified values only.

## CUDA boundary

CUDA may expand move proposals and iterate monotone fixed-point candidates. It may not certify a root by itself. Every promoted result carries the full reconstructible state/rule profile, child coverage, certificate hash and independent checker record.

## Current exact scope

Exact legality/perft, bounded mate and WDL results, replay, KQK/KRK tablebases, root-shard generation and finite demonstration fixed points are implemented and tested. The complete bundled KQK/KRK white-strong canonical no-castling/no-history partitions also reproduce independently verified source-bound heads after full rule-oracle graph replay. Those heads are not v2 WDL facts: state lifting, authenticated lemma membership and an explicit v3 migration remain promotion gates, as do full dead-position coverage, broader endgames and the initial-position proof.
