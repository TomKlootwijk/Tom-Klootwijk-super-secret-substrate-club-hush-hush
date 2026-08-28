# Vector Asset 2D Contract

A vector asset is identified by a stable `asset_id` and contains logical `size`, `pivot`, ordered `paths`, named `gradients` and JSON-compatible metadata.

## Path commands

Supported commands are:

```text
M x y
L x y
Q cx cy x y
C c1x c1y c2x c2y x y
Z
```

A subpath must start with `M`. `Z` closes the current subpath. Builders reject drawing commands before a move.

## Paint

Paint contains optional `fill`, optional `stroke`, non-negative `stroke_width`, opacity in `[0,1]`, `fill_rule` (`nonzero` or `evenodd`), line cap and line join. A paint string beginning with `@` references a gradient in the same asset.

## Gradients

Linear gradients define start/end vectors; radial gradients define center/radius/focus. Stops have monotonically non-decreasing offsets in `[0,1]` and CSS-compatible color strings.

## Flattening and bounds

Quadratic and cubic paths are recursively flattened to a caller-supplied positive tolerance. Bounds include all sampled path points. Flattening is a reference geometry operation, not a certified optimal tessellator.

## Serialization

All records round-trip through `to_dict`/`from_dict`. SVG export is deterministic for the same canonical asset record.
