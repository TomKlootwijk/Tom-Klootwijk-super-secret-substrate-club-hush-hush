# Source continuity

UGTS-KC 3.9.4 is an additive Bayer Direct presentation profile over the 3.9.3 line. It appends mechanisms M610-M629 and leaves earlier mechanisms unchanged.

The profile follows boundaries already present in the supplied source line:

- UGTS-KC 3.6.2 SCLP makes typed state and relations authoritative and explicitly excludes rasterization, ray marching and display authority from the core.
- UGTS-KC 2.0 treats the core as query-first rather than a renderer and requires reconstructibility and error contracts before memory claims.
- KC Two Hands 3.0 keeps rendering downstream and recommends a compact hot/cold split.
- UGTS-GN 1.1 separates packed-memory gains from correctness and measured performance.
- KC Elizabeth 3.9 prioritizes small inspectable records, deterministic simulation and self-contained delivery.

Bayer Direct preserves the same separation:

```text
field definition + state
-> support / compatibility / guard when required
-> deterministic transition + lineage
-> optional Bayer Direct display projection
```

The display projection cannot authoritatively mutate gameplay, topology or lineage.
