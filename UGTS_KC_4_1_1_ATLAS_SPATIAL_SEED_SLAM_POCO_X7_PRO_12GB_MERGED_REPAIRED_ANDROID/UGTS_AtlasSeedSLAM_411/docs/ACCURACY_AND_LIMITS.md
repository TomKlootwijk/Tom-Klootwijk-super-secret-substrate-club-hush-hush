# Accuracy and limitations

The active front end is monocular Camera2 plus Android orientation/acceleration hints. It estimates relative camera motion, guarded sparse points and adjacent-keyframe semi-dense points. Metric interpretation is disabled until a known-distance anchor is accepted.

The proposal verifier prevents an observation from becoming a keyframe/map commit when identifiers, support, compatibility, guard class, confidence, numeric margin, uncertainty or required metric state fail. This is an authority boundary, not a proof that accepted geometry is globally correct.

Loop closure candidates are recorded but not committed because bundle adjustment is absent. Pure rotation, low texture, repetitive patterns, moving objects, rolling shutter, poor intrinsics, exposure changes and long trajectories may degrade or invalidate reconstruction.

KSEED retains compact evidence, accepted events, keyframes, voxel cells, calibration/profile hashes and integrity data. It intentionally does not persist raw frames by default. A seed can reconstruct deterministic schedules and fixtures; it cannot reconstruct unstored photons.

Synthetic Demo data is tagged with bit 31 and displayed as `DEMO`. It must never be interpreted as camera evidence.

No medical, structural-safety, emergency-route, legal-evidence or custody conclusion should be drawn without application-specific calibration, uncertainty policy, independent validation and human authority.
