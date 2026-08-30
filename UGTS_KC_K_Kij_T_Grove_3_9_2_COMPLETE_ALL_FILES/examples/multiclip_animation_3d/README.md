# Two Clips, One Motion Cube

This tiny Mobile 3D project shows how one static object can keep more than one transform Animation clip and let Logic Blocks choose what plays.

The orange `motion_cube` starts with its looping `sway` clip. After exactly half a second, its object-bound graph does this once:

```text
When Timer Rings (0.5 seconds, do not repeat)
    -> Stop Animation (reset the pose)
    -> Play Animation (clip: hop, restart: yes)
```

`hop` is not the autoplay clip. It rises two units, turns once, lands at its authored pose, and stops after one second. The cube is static (`dynamic: false`) because transform Animation owns its pose; dynamic physics must not try to move the same object.

The project targets the 12 GB POCO X7 Pro profile: arm64-v8a, Mali-G720/GLES 3, and the 120 Hz `signature_ultra` quality tier. The normal desktop preview remains available too.

## Open it

Double-click `RUN_UGTS_STUDIO.cmd` at the repository root, open this `project.json`, and press Play.
The Animation clip list and the three Logic Blocks remain editable authoring data; there is no
code-created scene or hidden runtime setup.

Useful places to inspect in `project.json`:

- `nodes[].metadata.transform_animation_library` on `motion_cube` contains `sway` and `hop`.
- Its `autoplay` field names `sway`, not `hop`.
- `nodes[].metadata.visual_graph` binds the cube to `hop_after_half_second`.
- `metadata.visual_graphs` stores Timer -> Stop -> Play.

Every key is relative to the cube's authored transform. A clip therefore starts at identity translation/rotation/scale and can safely return to that pose.

## Verify it without opening a window

From the repository root, run:

```powershell
python examples/multiclip_animation_3d/verify_example.py
```

The verifier parses the JSON with `Mobile3DProject.from_dict(json.loads(...))`, explicitly validates it, creates the desktop 3D world, and advances 180 fixed 120 Hz ticks. It checks the timer switch at tick 60, the visible middle of `hop` at tick 90, and the finished pose at tick 180. It then compiles each asset twice to prove byte determinism and strictly inspects:

- KCAN format 2 with two clip bindings on one scene node.
- KCVG with Timer plus Play Animation opcode 26 and Stop Animation opcode 27.

The command prints the current project, runtime-state, KCAN, and KCVG SHA-256 hashes. It does not build an APK.
