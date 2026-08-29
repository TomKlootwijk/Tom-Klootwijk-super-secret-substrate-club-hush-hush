# UGTS Foundation 5.0 - Unicode Set-Field and Klein-Converse Atlas

Canonical identity: `ugts.foundation.unicode-set-field-klein-converse@5.0.0`  
Legacy discovery alias: `UGTS-KC 5.0`  
Release date: 2026-08-29

This package implements the major-version conclusion that a Unicode mathematical operator can be a content-addressed executable geometric rule cell. The literal Unicode sequence resolves a typed semantic evaluator, a canonical glyph signed-distance field, a set-field action, a converse relation, a Klein reflection rule, exactness metadata and a packed execution profile.

The release keeps three layers distinguishable while co-addressing them through one literal operator record:

1. **Literal/syntax** - exact Unicode scalars and surface operand order.
2. **Geometry** - a canonical capsule-union glyph SDF, plus optional font-specific profiles.
3. **Semantics** - typed set relations and signed set-field algebra.

The packed reference profile uses a 32-bit node with a 4-bit local operator slot, signed log-radius delta, cyclic angle delta, bounded grammar path, local flags, active bit and a separate integrity parity bit. The low bit of the local operator slot is the Klein/converse selector. Integrity parity and semantic/topological parity are deliberately not the same bit.

## Quick validation

```bash
python -m unittest discover -s tests -v
python examples/operator_atlas_demo.py
python examples/set_field_demo.py
python examples/packed_stream_demo.py
python -m ugts5 verify --package-root .
```

Native scalar validation:

```bash
c++ -std=c++20 -O2 -I native native/test_packed_node.cpp -o /tmp/ugts5_native_test
/tmp/ugts5_native_test
```

## Package map

- `report/` - PDF report and editable XeLaTeX source.
- `src/ugts5/` - dependency-free Python reference runtime.
- `spec/` - JSON Schemas, Unicode atlas, hot codebook, release record, mechanism catalog and claims ledger.
- `native/` - portable C++20 packed-node oracle and optional AVX2 decoder profile.
- `examples/` - runnable demonstrations and generated sample stream.
- `tests/` - executable conformance tests.
- `validation/` - captured results, hashes, manifests and build evidence.
- `figures/` - report diagrams and glyph-field plates.

## Evidence boundary

This is a technical design and executable reference artifact. It is not independent scientific validation, legal proof of authorship or ownership, a physical-device benchmark, a claim that every set has an exact Euclidean SDF, or a claim that a finite codebook enumerates all Unicode mathematics. Global subset/equality/emptiness claims over continuous domains require an analytic, interval or otherwise certified proof; sampled LUT evidence is not a universal proof.
