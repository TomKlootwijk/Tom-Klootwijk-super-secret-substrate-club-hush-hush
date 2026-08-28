# Offline Knowledge Transfer Contract

## Objective

Transfer selected semantic and relational knowledge from a larger model into a
small spatial graph student while keeping geometry, identity and event commits
under explicit deterministic rules.

## Teacher outputs

### Node representation

The embedding teacher receives one concise record per entity or concept. The
stored artifact is a projected, normalized vector with model ID and source
provenance.

### Relation probability

A chat or ranking teacher receives:

```json
{
  "source": {"node_type": "sensor", "text": "..."},
  "target": {"node_type": "property", "text": "..."},
  "relation": "observes",
  "distance_m": 0.0
}
```

The accepted response is a probability plus evidence-field names. The teacher is
not asked to decide exact containment, distance, intersection or SDF crossing.

## Student objective

```text
hard binary task loss
+ soft teacher-probability loss
+ cosine embedding alignment
+ uncertainty-weighted confidence margin
```

All coefficients are configuration parameters. They are engineering starting
values, not constants derived from the substrate.

## Leakage controls

- Split complete regions rather than nearby candidate rows.
- Do not place the exact supervised edge in the message graph.
- Version teacher model, prompt/instruction and ontology.
- Keep teacher-derived facts distinguishable from measured or source facts.
- Preserve negative and uncertain examples.
- Evaluate a rule-only and non-distilled baseline.

## Production boundary

At runtime, the student proposes a relation probability. A verified event still
requires:

```text
local support
AND typed compatibility
AND deterministic guard
AND calibrated semantic threshold
```

This is the central safety boundary between semantic transfer and spatial state
authority.

## Recommended first teacher

`Qwen/Qwen3-Embedding-0.6B-GGUF`, Q8_0, is the default recommendation because it
is approximately 639 MB and supports multilingual text. It is not bundled. Use a
short instruction and 256 output dimensions initially.

Avoid embedding 32K-token documents on a 12 GB laptop GPU. Entity descriptions
should normally be tens to hundreds of tokens; batch size and context drive
runtime scratch memory even when model weights are small.
