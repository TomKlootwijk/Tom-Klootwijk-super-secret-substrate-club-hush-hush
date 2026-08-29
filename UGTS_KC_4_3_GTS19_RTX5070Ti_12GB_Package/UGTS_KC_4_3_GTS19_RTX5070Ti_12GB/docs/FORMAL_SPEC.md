# UGTS-GTS19 formal specification

## 1. Canonical game

The proof target is serialized by `configs/go19_canonical.toml` and identified as
`UGTS-GO19-AREA-PSK-K7.5-v1`.

A state is

\[
S=(B,p,r,H,B_{-1}),
\]

where:

- \(B\in\{0,1,2\}^{361}\) is the board;
- \(p\in\{Black,White\}\) is the player to act;
- \(r\in\{0,1,2\}\) is the consecutive-pass count;
- \(H\) is the exact set of previously reached boards for positional superko;
- \(B_{-1}\) is the immediately previous board, retained for cross-profile audit.

The initial state is the empty board, Black to act, zero passes, and
\(H=\{B_{empty}\}\).

## 2. Transition order

For a point move \(a\), execute exactly this operator order:

1. require an empty point;
2. place the current player's stone provisionally;
3. compute adjacent opponent connected components;
4. remove every adjacent opponent component with zero liberties;
5. compute the placed stone's resulting component;
6. reject if it has zero liberties and suicide is disabled;
7. reject if the resulting board belongs to \(H\);
8. atomically commit board, player swap, pass reset, history insertion, and lineage.

For pass, preserve \(B\), swap the player, and increment \(r\). Pass is permitted
as an explicit exception to board repetition. The game terminates when \(r=2\).

This order is part of the definition. Reordering capture, own-liberty, or
repetition guards changes legal play.

## 3. Utility

At terminal state, every empty connected region is assigned to Black if its
boundary contains only Black stones, to White if its boundary contains only
White stones, and neutral otherwise.

Let \(A_B\) and \(A_W\) be the respective areas. Utility in half-points is

\[
U_2(S)=2(A_B-A_W)-15.
\]

The value is always odd, so the canonical game has no draw. Black wins iff
\(U_2>0\).

The possible area difference is an integer in \([-361,361]\), hence the exact
score lies among 723 odd half-point values from \(-737\) to \(707\).

## 4. Game-theoretic recursion

For terminal \(S\), \(V(S)=U_2(S)\). Otherwise:

\[
V(S)=
\begin{cases}
\max_{a\in L(S)}V(T(S,a)),&p=Black,\\
\min_{a\in L(S)}V(T(S,a)),&p=White.
\end{cases}
\]

Here \(L(S)\) is the legal action set including pass.

## 5. Threshold formulation

For an odd threshold \(t\), define proposition

\[
W_t(S)\equiv \text{“Black can force }U_2\ge t\text{ from }S\text{.”}
\]

Then terminal truth is \(U_2(S)\ge t\). At Black nodes, \(W_t\) is an OR over
children. At White nodes, it is an AND over children. Proof-number search uses:

- proven node: \(pn=0,dn=\infty\);
- disproven node: \(pn=\infty,dn=0\);
- unknown leaf: \(pn=dn=1\);
- OR: \(pn=\min pn_i,\;dn=\sum dn_i\);
- AND: \(pn=\sum pn_i,\;dn=\min dn_i\).

The win/loss question uses \(t=1\). An exact score can be identified with at
most ten adaptively chosen threshold decisions because there are 723 candidates.
This does not make any individual threshold search easy.

## 6. Finiteness

Positional superko requires every non-pass transition to reach a board not
already in \(H\). There are at most \(3^{361}\) board colorings. Between two
non-pass moves, at most one pass can occur without ending the game. Therefore
the mathematical game tree is finite, even though this release imposes no
move limit in the game definition. Backward induction consequently defines a
unique minimax value for the pinned rules profile.

The bound is only a finiteness proof; it is not a practical search estimate.

## 7. State equivalence

Two states may share an exact transposition entry only when they have equivalent:

- current board;
- player to act;
- pass count;
- complete repetition context;
- rules profile.

Board-only equality is insufficient under superko.

A D4 transformation is valid only when applied to the board, every history
member, and the previous-board lineage together. At the empty root, the 361
placements form exactly 55 D4 orbits; pass is a 56th action class.

## 8. Collision policy

Hashes select candidate records. They do not establish state equality. Before a
hash hit changes a proof number, the implementation must compare collision-safe
identity or retrieve and verify the content-addressed state/history record.
Cryptographic digests protect files and Merkle links; exact raw identity remains
the semantic authority.

## 9. Certificate condition

A full solved claim requires:

1. matching rules-profile digest;
2. matching empty-root state digest;
3. root `proof_number = 0` or `disproof_number = 0` for threshold 1;
4. a complete proof DAG or independently replayable equivalent;
5. validation of every terminal score and every legal-child quantifier;
6. no unresolved hash collision or missing history segment;
7. independent verification from a clean build.

The tiny certificates in this package are deterministic recomputation
certificates. They are not yet the compact standalone strategy-DAG format
required for a 19×19 solved claim.
