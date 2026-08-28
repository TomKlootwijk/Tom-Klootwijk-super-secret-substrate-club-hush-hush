# Dependency-free reference oracle

`ugts_reference.py` mirrors the compute shader semantics, packs/unpacks the two ABI profiles, implements the explicitly versioned glyph encoder, and provides memory and threshold-reset helpers.

Run:

```bash
python reference/ugts_reference.py
python -m unittest discover -s tests -v
```

The native target is still Vulkan/SPIR-V. This Python code is a correctness oracle and format reference, not a performance path.
