# Third-party data, algorithms, and references

## Vallado/CSSI SGP4/SDP4 reference family

The full propagator follows the Vallado/CSSI SGP4/SDP4 computational family,
including the near-Earth and deep-space branches and the published verification
cases. See `NOTICE_SGP4.md` for provenance and warranty boundaries.

Aholinch's practical multi-language C reference was consulted during the port:

```text
https://github.com/aholinch/sgp4
```

That repository declares an Unlicense/public-domain dedication. The KSGP1
container, OMM adapter, lineage integration, direct-query architecture, and
benchmark harness are package-specific engineering work covered by the root MIT
license.

## CelesTrak GPS Operational GP data

The package includes one 4,852-byte OMM CSV snapshot and two derived containers:

```text
data/orbit/source/gps_ops_2026-08-16_omm.csv
data/orbit/gps_ops_2026-08-16_7d_1s.kloc
data/sgp4/gps_ops_2026-08-16_7d_1s.ksgp
```

Source query:

```text
https://celestrak.org/NORAD/elements/gp.php?GROUP=GPS-OPS&FORMAT=CSV
```

Documentation and usage policy:

```text
https://celestrak.org/NORAD/documentation/gp-data-formats.php
https://celestrak.org/usage-policy.php
```

The snapshot is included for reproducibility of the requested local test.
Refresh scripts are deliberately non-polling and refuse to overwrite an
existing snapshot unless explicitly forced. Users are responsible for complying
with the current source terms and usage policy when refreshing or
redistributing data.

The legacy KLOC1 file uses the earlier coarse Kepler-plus-J2 predictor. The
KSGP1 file uses the full SGP4/SDP4 initialization and propagation path.

## Stanford Bunny

The legacy KLSC1 examples retain optional scripts and instructions for the
Stanford 3D Scanning Repository. No Stanford Bunny archive or mesh is included.

## Other frameworks

No PyTorch, TensorRT, OptiX, Vulkan, Unity, or Godot code is vendored into this
package. CUDA is used only through the locally installed NVIDIA toolkit and
runtime when the target user builds the CUDA executables.
