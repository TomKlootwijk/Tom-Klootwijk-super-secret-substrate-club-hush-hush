from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

entries = [
("C001","Profile","UGTS chess solver profile","A versioned application profile mapping standard chess into typed state, verified moves, deterministic transitions, proof search and exact bounded tablebases.","ENGINEERING","Implemented"),
("C002","Governance","Evidence boundary","Separate exact rule/proof results, heuristic search results, external standards and unproved full-game claims.","RETAIN","Enforced"),
("C003","State","Position tuple","q=(board, side, castling, en-passant, halfmove, fullmove, repetition history, lineage).","ENGINEERING","Implemented"),
("C004","Coordinates","Square address","Map a1..h8 bijectively to integer cells 0..63 with explicit file/rank transforms.","RETAIN","Exact"),
("C005","Identity","Piece identity","Piece type, color and square are distinct fields; captured pieces leave the board through a verified event.","ENGINEERING","Implemented"),
("C006","State","Side-to-move bit","One bit selects the mover only; it never replaces board, rights, clocks or lineage.","RETAIN","Implemented"),
("C007","State","Castling-right mask","Four explicit rights are carried and patched by king/rook moves or home-rook capture.","ENGINEERING","Implemented"),
("C008","State","En-passant target","A transient target square is typed separately and admitted only under pawn and king-safety guards.","ENGINEERING","Implemented"),
("C009","State","Move counters","Halfmove and fullmove counters remain explicit for draw semantics and FEN round trips.","RETAIN","Implemented"),
("C010","Encoding","Strict FEN codec","Parse and serialize six-field Forsyth-Edwards positions with structure validation.","ENGINEERING","Implemented"),
("C011","Persistence","Canonical state record","Serialize deterministic sorted records for state identity and evidence artifacts.","ENGINEERING","Implemented"),
("C012","Persistence","SHA-256 state identity","Use SHA-256 over canonical state as the proof/replay identity; hashes are integrity metadata, not legal identity.","RETAIN","Implemented"),
("C013","Indexing","Compact 64-bit cache key","Use deterministic BLAKE2b-64 as a transposition/index key while keeping SHA-256 authoritative.","ENGINEERING","Implemented"),
("C014","Identity","Repetition identity","Board, side, castling and effective en-passant rights form the repetition key; clocks are excluded.","ENGINEERING","Implemented"),
("C015","Support","Piece movement support","Leaper offsets, pawn direction and finite slider rays provide coarse move support.","RETAIN","Implemented"),
("C016","Compatibility","Occupancy and color gate","A supported destination must agree with side, own occupancy, capture and promotion semantics.","ENGINEERING","Implemented"),
("C017","Relation","Attack relation","Typed pawn, knight, king and slider attacks define check and castling-transit relations.","RETAIN","Implemented"),
("C018","Guard","King-safety guard","A move commits only when the mover's king is not attacked in the resulting state.","RETAIN","Implemented"),
("C019","Guard","Castling transit guard","Castling requires rights, home rook, empty corridor and unattacked origin/transit/destination.","ENGINEERING","Implemented"),
("C020","Guard","En-passant exposure guard","The captured pawn is removed before testing whether the moving side's king is exposed.","ENGINEERING","Implemented"),
("C021","Branch","Promotion branch","A last-rank pawn event branches into exactly Q/R/B/N outcomes.","RETAIN","Implemented"),
("C022","Event","Move proposal","A proposed move records source hash, support, compatibility, guard status and reason codes.","ENGINEERING","Implemented"),
("C023","Transition","Deterministic board patch","Verified moves atomically patch source, destination, capture, rook motion and promotion.","ENGINEERING","Implemented"),
("C024","Transition","Rights patch","Castling rights are deterministically removed by king/rook motion and home-rook capture.","ENGINEERING","Implemented"),
("C025","Transition","Clock and turn patch","Every move updates en-passant, halfmove, fullmove and side-to-move fields in a fixed order.","ENGINEERING","Implemented"),
("C026","Event","Move event record","Committed events carry UCI, SAN, pre/post hashes, capture, promotion, check and lineage label.","ENGINEERING","Implemented"),
("C027","Replay","Hash-checked replay","Replay requires contiguous sequence and matching pre/post state hashes.","RETAIN","Implemented"),
("C028","Terminal","Checkmate relation","No legal moves plus check is a terminal loss for the side to move.","RETAIN","Implemented"),
("C029","Terminal","Stalemate relation","No legal moves without check is a draw.","RETAIN","Implemented"),
("C030","Terminal","Dead-position subset","Kings-only, single-minor and same-color-bishop-only exact dead positions are recognized.","BOUNDED","Implemented subset"),
("C031","Terminal","Draw counters","Claimable 50-move/threefold and automatic 75-move/fivefold policies remain explicit.","RETAIN","Implemented"),
("C032","Query","Legal move enumeration","Generate all and only moves passing support, compatibility and king-safety guards.","ENGINEERING","Validated"),
("C033","Validation","Perft oracle","Count legal move paths and compare with established regression fixtures.","RETAIN","Validated"),
("C034","Encoding","SAN projection","Generate deterministic human-readable algebraic notation downstream of legal authority.","OPTIONAL","Implemented"),
("C035","Heuristic","Transparent evaluation","Material and small piece-square terms order non-terminal search without becoming proof authority.","ENGINEERING","Implemented"),
("C036","Search","Alpha-beta negamax","Bounded adversarial search evaluates alternating legal transitions with fail-soft mate scores.","RETAIN","Implemented"),
("C037","Search","Iterative deepening","Search depth increases monotonically and preserves the last completed result under a time budget.","ENGINEERING","Implemented"),
("C038","Search","Quiescence","At the horizon, captures, promotions and all check evasions extend tactical stability.","ENGINEERING","Implemented"),
("C039","Search","Transposition record","Cache depth, score bound and best move under a compact key; collisions cannot certify proofs.","ENGINEERING","Implemented"),
("C040","Search","Deterministic move ordering","Use TT move, promotion, capture score and UCI ordering for reproducible runs.","ENGINEERING","Implemented"),
("C041","Search","Mate-distance score","Encode checkmate with ply distance so faster wins and slower losses are preferred.","ENGINEERING","Implemented"),
("C042","Proof","OR attacker node","A forced-mate proof selects one legal attacker move with a proved child.","RETAIN","Implemented"),
("C043","Proof","AND defender node","A proof enumerates every legal defender reply and proves every child.","RETAIN","Implemented"),
("C044","Proof","Checkmate leaf","A proof leaf independently verifies check, zero legal replies and declared winner.","RETAIN","Implemented"),
("C045","Proof","Mate certificate","Serialize FEN, SHA-256, node roles, chosen moves, complete replies and horizon.","ENGINEERING","Implemented"),
("C046","Proof","Independent verifier","A small checker regenerates legal moves, checks reply completeness and replays every edge.","ENGINEERING","Implemented"),
("C047","Proof","Finite-horizon status","Failure is reported as not forced within the declared horizon, never as a global game result.","BOUNDARY","Enforced"),
("C048","Tablebase","KXK exact profile","Retrograde solve KQK and KRK over all legal three-piece cells.","ENGINEERING","Implemented"),
("C049","Packing","Dense 19-bit KXK key","Pack strong king, major piece, weak king and side into 19 exact address bits.","ENGINEERING","Implemented"),
("C050","Tablebase","Validity cell","Invalid overlaps, adjacent kings and side-not-to-move-in-check cells are marked explicitly.","ENGINEERING","Implemented"),
("C051","Tablebase","Terminal initialization","Seed checkmates as losses and stalemates as draws before retrograde propagation.","RETAIN","Implemented"),
("C052","Tablebase","Predecessor relation","Generate exact reverse king/slider moves without storing a full edge graph.","ENGINEERING","Implemented"),
("C053","Tablebase","WDL propagation","A predecessor is win if any child is loss and loss if every child is win; unresolved cells are draw.","RETAIN","Implemented"),
("C054","Tablebase","DTM propagation","Wins minimize and losses maximize plies to checkmate under optimal play.","ENGINEERING","Implemented"),
("C055","Tablebase","Major-piece capture draw","Weak-king capture of the queen/rook exits to exact K-v-K draw.","ENGINEERING","Implemented"),
("C056","Compression","Gzip table transport","Store two bytes per dense address and gzip the payload; compression is transport, not correctness.","ENGINEERING","Implemented"),
("C057","Symmetry","Black-strong normalization","Color-swap plus 180-degree rotation maps black-strong KXK into the canonical white-strong table.","ENGINEERING","Implemented"),
("C058","Tablebase","Exact best move query","Select DTM-minimizing wins, DTM-maximizing losses or draw-preserving moves.","ENGINEERING","Implemented"),
("C059","Evidence","Tablebase metadata","Record outcome counts, maximum DTM, byte sizes and SHA-256 transport hash.","ENGINEERING","Implemented"),
("C060","Tooling","Command-line workflow","Expose info, validate, perft, solve, prove, verify, probe, generate and demo commands.","ENGINEERING","Implemented"),
("C061","Schema","JSON contracts","Version proof, project and evidence records with machine-readable schemas.","ENGINEERING","Supplied"),
("C062","Presentation","Offline proof viewer","A self-contained HTML page displays boards and navigates OR/AND proof branches.","OPTIONAL","Implemented"),
("C063","Validation","Automated release gates","Compile, run tests, check perft, proof, tablebase hashes, package schema and manifest.","ENGINEERING","Passed"),
("C064","Roadmap","Distributed global proof sharding","Shard by typed material/history state and admit only checker-verified boundary certificates.","FUTURE","Specified"),
]

spec = ROOT / "spec"
spec.mkdir(exist_ok=True)
fields = ["id","domain","mechanism","definition","disposition","validation"]
with (spec / "chess_mechanisms.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(fields)
    writer.writerows(entries)
records = [dict(zip(fields, row)) for row in entries]
(spec / "chess_mechanisms.json").write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {len(entries)} mechanisms")
