# Experimental 4D Contract Draft — Not Implemented in 3.9.1

“4D” is intentionally not overloaded in this release. A future experiment must select and name
one of two different meanings:

- **spacetime gameplay:** ordinary 3D geometry with time as an authored/queryable dimension;
- **four-spatial-dimensional geometry:** 4-vectors, 4×4 rotations in SO(4), 4D collision and a
  declared projection/slicing policy into 3D.

Before implementation, a 4D project must declare its metric, units, orientation convention,
projection/slice operator, collision semantics, temporal authority and determinism tolerance.
No 4D runtime code, renderer, physics, interchange claim or mechanism count is asserted here.
