# Chrono Video Observation Inspector

This directory is a deterministic UGTOMS observation/proposal fixture. Open `project.json` in UGTS Studio. The original MP4 remains authoritative by external path and SHA-256. `polar_preview.mp4` is an already-log-polar downstream diagnostic and must not be passed through `UGCVLUT1` again. Playback is finite and holds the last frame; it does not infer a chronology loop.

```powershell
python -m ugts_kc3 validate-3d project.json
python -m ugts_kc3 build-android project.json android --profile poco_x7_pro_12gb --debug-assets
```

No accepted physical 3D is present because the source has no verified camera calibration, timing bounds, pose, or metric scale.
