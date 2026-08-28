# Third-party data and references

## CelesTrak GPS Operational GP data

The package includes one 4,852-byte CSV snapshot and a derived KLOC1 container:

```text
data/orbit/source/gps_ops_2026-08-16_omm.csv
data/orbit/gps_ops_2026-08-16_7d_1s.kloc
```

Source query:

```text
https://celestrak.org/NORAD/elements/gp.php?GROUP=GPS-OPS&FORMAT=CSV
```

Documentation:

```text
https://celestrak.org/NORAD/documentation/gp-data-formats.php
```

Usage policy:

```text
https://celestrak.org/usage-policy.php
```

The source is included for reproducibility of the requested local test. Refresh scripts are deliberately non-polling and refuse to overwrite an existing snapshot unless explicitly forced. Users are responsible for complying with the current source terms and usage policy when refreshing or redistributing data.

The source data is not evidence that the bundled coarse Kepler+J2 predictor is SGP4-accurate. CelesTrak GP mean elements are intended for SGP4; the package preserves that accuracy boundary throughout its CLI and documentation.

## Stanford Bunny

The legacy KLSC1 examples retain optional scripts and instructions for the Stanford 3D Scanning Repository. No Stanford Bunny archive or mesh is included in this v0.3 source package.

## Third-party code

No SGP4, CelesTrak, Stanford, PyTorch, TensorRT, OptiX, Vulkan, Unity or Godot code is vendored into this package. The implementation sources are covered by the package MIT license; external data and references retain their own terms.
