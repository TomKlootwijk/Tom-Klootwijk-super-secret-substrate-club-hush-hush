# UGTS-KC 3.9.4 Bayer Direct formal definition

UGTS-KC 3.9.4 Bayer Direct is a bounded presentation profile in which deterministic integer fields are queried directly at a finite low-resolution display lattice, quantized by an exact 8x8 Bayer threshold permutation, mapped to a four-entry RGB565 palette, and posted through `ANativeWindow`. The profile carries no mesh, texture, shader, ray, camera, lighting, depth, or scene representation in its installable hot path.

Let the display state be

```text
q_BD = (seed, tick, mode, palette, width, height, flags).
```

For pixel coordinate `(x,y)`, a selected bounded field program returns

```text
L = clamp(F_mode(x,y,q_BD), 0, 255).
```

Let `B8(x mod 8, y mod 8)` be the standard permutation of integers 0 through 63. The four-level output index is

```text
k = min(3, floor((4 L + 4 B8) / 256)).
```

The display sample is

```text
C(x,y) = Palette_palette[k] in RGB565.
```

The authoritative UGTS handoff remains:

```text
field definition + state
-> support / compatibility / guard where application events require them
-> deterministic transition + lineage
-> optional Bayer Direct display projection
```

The display projection never writes authoritative gameplay or topology state.
