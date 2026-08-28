# Included data

## `procedural_65536.klb`

A generated 65,536-point KLB37 base stream used by the original architecture benchmark.

- 37-bit continuous records in a `uint32_t` word stream.
- Log-spherical position quantization.
- Morton logical order and 16×16 XOR record swizzle.
- SHA-256 and detailed values are in `procedural_65536.manifest.json`.

## `procedural_65536_240f.klsc`

A 240-node KLSC1 deployment chain built from the KLB37 base.

- 16-frame checkpoint stride.
- Maximum novelty parent depth: 15.
- Deterministic predictor/grammar motion.
- Sparse generated novelty impulses and inverse events.
- 910,392-byte container.
- SHA-256 and detailed values are in `procedural_65536_240f.manifest.json`.

The reported 207.321330× ratio compares this reconstructible generated sequence against storing all 240 frames as dense `float3`. It is not an arbitrary animation compression claim.

Inspect without creating a large decoded file:

```bash
./build/klb_seedchain inspect data/procedural_65536_240f.klsc
```

Export a single frame only when needed:

```bash
./build/klb_seedchain export data/procedural_65536_240f.klsc 239 frame_0239.ply
```

Run the GPU deployment benchmark:

```bash
./build/klb_seedchain_bench data/procedural_65536_240f.klsc \
  --frame 239 --mode all --repeats 20
```

`*.build.txt` and `*.inspect.txt` capture the preparation-time CPU tool output for the included chain.
