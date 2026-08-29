# Independently replayed KXK partition heads

The retained KQK and KRK JSON files are reproducibility witnesses, not proof
authority and not WDL promotion inputs. Authority comes only from a complete
independent replay of the exact committed transport, metadata, and decoded
semantic bytes. A process-local cache is usable only after that replay succeeds.

The proved base-game domain is white-strong canonical KQK or KRK with no
castling rights, no en-passant square, no move counters, and no history. Infinite
play is classified as a draw. In particular, a KRK position carrying a castling
right is outside this lemma even if its piece placement has a canonical key.

For repository text compatibility, each retained `*-head.json` artifact is the
strict newline-free canonical head followed by exactly one LF byte. A consumer
must parse the JSON, reconstruct the strict head, and require the original raw
bytes to equal `head.canonical_bytes() + b"\n"`. `head_sha256` commits the
newline-free canonical head; `raw_file_sha256` in the full-replay witness commits
the repository artifact including its final LF.

The full-replay witness records historical CPU replay timings and current hashes
for both bundled resources. The timings came from successful full graph replays
before the later parser and source-stability hardening; they are not presented as
timings of the finalized verifier. Changing only the descriptive base-game
profile changed the deterministically reconstructed head hashes, but not the
already replayed source commitments, graph metrics, replay loop, or rule-oracle
semantics.
