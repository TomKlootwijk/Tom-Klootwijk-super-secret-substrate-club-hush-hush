# UGTS-GN Source-to-Code Mapping

This table distinguishes source-derived substrate rules from GSP4 engineering additions.

| Substrate rule | GSP4 realization | Layer |
|---|---|---|
| Query-first substrate; projection is downstream | `query.execute_query`, CLI `gsp4 query` | source-derived authority preserved |
| Local radial/angular support precedes relation work | Morton/H3 candidate cells, local ENU radius/cone gate | source-derived operator + engineering index |
| Typed compatibility determines coupling | relation type contract, node type pairs, 16-bit masks, sheet/orientation checks | source-derived operator |
| Relation/SDF guard has a finite band | `QueryConfig.guard_mode`, `epsilon_m`, inside/shell gate | source-derived operator |
| Verified event follows support + compatibility + guard + confidence | ordered query gate and compact event result | source-derived event calculus |
| Transition updates route and lineage | route bits, deterministic lineage hash, `.ugnl` commit | source-derived operator + engineering record |
| Coordinates are not identity | persistent uint64 node ID, lineage seed, keys, ordered novelty | source-derived identity rule |
| Reconstructible dynamics may use seed/grammar; external novelty must be stored | deterministic graph/model state plus append-only `.ugnl` | source-derived persistence rule |
| One bit has a narrow route/validity role | sheet/orientation/relation masks never replace continuous features | source correction preserved |
| Packed data requires an error contract | G32 exporter measures error against guard epsilon | source precision rule |
| Lineage checksum is not complete identity | compact hash plus graph ID/history/novelty chain | source precision/identity rule |
| BST/pointer traversal should compile to flat GPU data | tensor edge arrays, relation tables, packed bridge buffers | source GPU translation |
| Dense diagnostics and compact novelty are separate paths | JSON/query diagnostics versus `.ugnl` verified-event retention | source memory model |
| Physical GPU claims require target rerun | `check-gpu`, RTX benchmark scripts, explicit CPU-only report boundary | source reproducibility rule |

## GSP4 engineering additions

The following are practical translations rather than claims directly established by the source:

- heterogeneous typed attention as the semantic student;
- TGN-style temporal memory for irregular observations;
- embedding and chat-teacher adapters;
- ULTRA triple interchange;
- GeoNames/OSM compilers;
- `.ugkg`, `.ugte`, and `.ugdeploy` archive formats;
- spatial-cell holdout evaluation;
- teacher provenance and abstention schema.

These additions are accepted only because they preserve the substrate ordering and keep deterministic geometry/event authority outside the language model.
