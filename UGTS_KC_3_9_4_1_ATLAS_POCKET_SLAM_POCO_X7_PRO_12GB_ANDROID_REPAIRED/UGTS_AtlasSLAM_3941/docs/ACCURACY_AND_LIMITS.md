# Accuracy, calibration, and limits

## What the app estimates

The compact core estimates orientation from the phone rotation sensor, a translation **direction** from monocular epipolar geometry, a bounded nominal translation step, guarded sparse 3D points, and keyframe-only semi-dense points. It fuses accepted points into quantized voxel centres.

## Metric scale

Monocular reconstruction has an inherent scale ambiguity. Before an anchor, the exported state is `relative_units`. The scale-anchor workflow records two estimated camera positions and a user-supplied measured displacement. It scales poses, trajectory, voxel size, and geometry uniformly.

An anchor does not remove drift, rolling-shutter effects, lens distortion, bad correspondence, or weak geometry. Verify the result against a second independent control length.

## Intrinsics

The preference order is:

1. Camera2 `LENS_INTRINSIC_CALIBRATION`, mapped through the active-array crop and output rotation;
2. a focal-length/physical-sensor metadata estimate;
3. a declared generic focal model.

Only the first is labelled `camera2_factory_intrinsic_calibration`. The second is explicitly an estimate. The compact app does not run a checkerboard calibration or distortion-calibration session, and it does not undistort the Y plane.

## Acceptance guards

Sparse geometry requires, among other things:

- enough descriptor matches and epipolar inliers;
- non-degenerate translation direction;
- positive ray parameters in both views;
- parallax within a bounded range;
- limited closest-ray gap;
- bounded two-view reprojection error.

Semi-dense proposals additionally require texture, a distinct photometric minimum, a reverse-neighbourhood consistency check, and a bounded cost.

These guards reduce obvious bad points. They do not certify survey accuracy.

## Likely failure modes

- Pure rotation or very small translation.
- Repetitive or textureless surfaces.
- Moving people, vehicles, screens, water, foliage, or flexible objects.
- Low light, motion blur, autofocus hunting, or severe exposure changes.
- Strong lens distortion near frame edges.
- Long feature-poor corridors and large accumulated loops.
- Rolling-shutter motion during fast turns.
- IMU magnetic/pose disturbances depending on the sensor selected by Android.
- Thermal throttling during sustained capture.

## Capture guidance

Move slowly, include lateral translation rather than only panning, keep 60–80% visual overlap, revisit textured static structure, avoid very close edge-only views, and pause when people or moving objects dominate the frame. For scale, use a rigid measured control distance large enough to dominate position noise.

## Evidence boundary

This package has host-side deterministic tests and source-policy checks. It was not built or physically measured on a POCO X7 Pro in the packaging environment. It therefore makes no measured claim for absolute error, drift per metre, frame rate under load, thermals, battery life, or APK size.
