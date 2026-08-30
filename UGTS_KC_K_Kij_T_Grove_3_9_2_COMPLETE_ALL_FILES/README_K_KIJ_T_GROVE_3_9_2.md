# UGTS-KC 3.9.2 — K-Kij-T / Grove

Creation-engine release focused on a learnable desktop workflow and a compact native Mali-G720 MC7
result, with adaptive fallbacks for general Android phones.

## What is actually in this release

- Dockable PySide6 UGTS Studio with 2D/3D scene authoring, undo/redo, picture/shape/material choices,
  real preview, readable checks and direct build targets.
- A 25-block visual-logic core shared by desktop, retained 2D HTML5 and native Android, plus the
  Mobile 3D-only **Play an Animation**, **Stop an Animation**, **Read Movement**,
  **Change Movement** and **Show or Hide Extra Copies** blocks for 30 built-in block types,
  including append-only opcode 22 **Find Nearby Object** with deterministic nearest-tag sensing and
  append-only opcode 23 **When Timer Rings** with binding-local active fixed-step timing, bounded
  literal settings and no serialized suspended state. Append-only opcode 24 **Find Object Ahead**
  adds a source-aligned binary32 GSP4 cone whose Vector4 stores world-axis X/Y/Z plus minimum cosine;
  it uses no runtime trigonometry and ignores Origin rotation and scale. Append-only opcode 25
  **When Message Heard** adds exact, bounded FIFO cross-graph messages with source/target/entity
  context. The two animation actions are append-only opcodes 26 and 27. Append-only opcodes 28 and
  29 hardcode semantic `polar_movement`, exposing only object, one of seven friendly numeric fields,
  and fallback/value. A fixed four-node KCVG is 239 bytes/eight inputs versus 268 bytes/ten inputs
  for generic component access; Python/native parity is covered, while browser export rejects these
  two blocks explicitly as Mobile-3D-only. Append-only opcode 30 changes only the ephemeral
  visibility of a chosen Make Many object's generated display copies; its real ECS prototype and
  frozen KCPR recipe remain untouched, and browser export rejects it explicitly too.
- Selection-owned Logic Blocks: unbound 2D/3D objects start blank, first edit binds atomically with
  Undo, multiple bindings have a chooser, and Populate Area prototypes cannot own graphs.
- A seven-graph/27-node Mobile 3D First Steps project with seven bindings including four world bindings:
  **Find the Goal** searches from Player for Goal within 9 m and stores `nearby_goal`, while **Count
  the Timer Rings** stores a repeating one-second timer count as `timer_rings`. **Find the Goal
  Ahead** uses the saved 3D Forward world axis and Normal width and stores `goal_ahead`. In the
  **First Steps** editor tab, World Logic → **Hear the Dash Message** receives the Dash graph's
  `player.dashed` message and stores `heard_message=true`.
- ECS composition plus two-word packed polar pose/motion components and shared binary16 log-encoded
  polar LUTs. Desktop optional components use world-owned sparse pools behind a live dict-compatible
  view; cached canonical queries choose the smallest sparse pool without changing snapshots or
  hashes. Built-in record/archetype migration and tag/spatial/render-batch indexes remain future work.
- Child-facing **Make Many → Radial Burst (loops)** keeps one real ECS prototype and derives bounded
  display-only copies. Legacy-only recipes retain byte-identical KCPR v1; with Glow disabled, Burst
  opts the asset into KCPR v2, with a controlled single-recipe sidecar measuring 240 bytes. Stopped
  desktop preview uses the loop midpoint, while Play uses the real post-step fixed tick with no invented interpolation.
  Each recipe is capped at 512 instances; projects are capped at 16 Burst recipes and 2,048 Burst
  instances, with at most 64 preview copies retained in the editor. Local packed displacement
  compounds with the prototype anchor through log-encoded polar LUT semantics; Direct is the native
  baseline, LUT shares the profile, and Bayer remains the final presentation pass.
- Optional child-facing **Glow by distance** applies to Ring, Spiral, Polar Field or Burst without
  creating gameplay entities or changing their placement lineage. A zero start maps to the profile's
  explicit core; Start distance, End distance and strength compile into three binary32 fields. The
  modifier alone selects KCPR v3, while old no-Glow v1/v2 bytes remain exact and every recipe stays
  128 bytes by reusing its final 12 reserved bytes. A repeatable lineage-derived 12-bit material phase
  costs one extra 32-bit attribute per visible GPU instance. Shared LUT reuses UGLUT2 direction,
  Direct uses cosine and CPU fallback/reference uses the quantized LUT. Scene lighting adds bounded
  `base colour × field` before the unchanged final Bayer pass; Burst uses distinct prototype and copy
  draw groups. Copies evaluate local packed rho before anchor composition; the prototype evaluates
  its own packed rho, with no Cartesian-distance reconstruction.
- Optional **Grow glowing copies** selects KCPR v4 and consumes that exact seeded Glow field again as
  `clamp(1 + glow, 1, 5)` after ordinary/Burst display scale. It changes only generated render
  copies; the real ECS prototype, collider, picking, snapshots and spatial lineage stay unchanged.
  Frozen operator `0x0053` adds no recipe parameter, LUT, texture, instance byte or ECS row, so the
  recipe remains 128 bytes and visible staging remains 36 bytes per instance.
- Native Android Studio/Gradle project with a GLES3 renderer, dynamic internal resolution,
  pointer-ID-aware two-thumb controls and adaptive Poco/general-device profiles.
- Opt-in desktop **Device Look (reference)**: exact CPU UGLUT2 composition followed by the packaged
  Bayer shader, with a visible `CPU LUT` badge, unchanged Off mode and safe raster fallback. It is a
  presentation reference, not the Android packed-instancing GPU path or a performance claim.
- Four child-facing Material Looks with safe shared-material cloning and one-step save-aware Undo,
  plus matching desktop/GLES PBR-lite shading without growing the KC3D392 material record.
- Mobile 3D **Saved Objects**: save one safe flat object, place deterministic ordinary ECS copies,
  or remove the library entry without deleting placed objects. Definitions add no runtime record;
  placed copies share resources and Logic Block bytecode, and every operation is one Undo step.
- A child-facing **Animation** timeline with up to 16 named relative transform clips per eligible
  static Mobile 3D node: New/Duplicate/Rename/Delete, one optional autoplay choice, whole-pose keys,
  nondestructive scrubbing, Once/Repeat/Back and forth and atomic Undo/Redo. **Play an Animation** and
  **Stop an Animation** Logic Blocks select, restart, pause, resume, hold or reset those clips in
  desktop Preview and native Android. All nine runtime easing modes have child-readable Arrival names.
- Exact KCAN compatibility: untouched legacy `transform_animation` projects retain byte-for-byte v1
  output with one implicit `main` autoplay clip. Clip libraries use v2's stable clip hash and autoplay
  flag; both versions keep the same 24-byte header, 24-byte whole-pose keys and deterministic
  quantization, while unused projects still emit no `KCAN392` sidecar.
- Full-screen Grove juice/post pass with glow, flash, chromatic separation, vignette,
  saturation/contrast response and pickup/goal shockwave.
- KC3D392 scene packs, glTF interchange and all retained 3.9/3.9.1 2D, browser and 3D APIs.
- GUI **Check Phone** (`Ctrl+Shift+P`) and CLI `profile-android` for a nonblocking default 30-second
  observation of a running deployed game with its screen on, covering frame cadence, memory, GPU
  temperature when exposed by Android, and crash warnings without injected input or setting edits.

## PCG

General gameplay PCG remains a future TODO. Grove ships only bounded decorative **Populate Area**:
static render-only copies with explicit caps and no independent collider, movement, gameplay or
Logic Block identity.

## Build boundary

Python/editor and native-host Burst vectors cover fixed ticks 0, 1, 4, 7 and 8, and the Android
ARM64 native target builds. The defined 18-case 32/128/384 × CPU/Direct/LUT × Bayer Off/subtle
matrix completed in build-only mode; the command is:

```powershell
python validation/benchmark_polar_render_poco.py --workload burst --include-cpu --build-only
```

The preserved run is
`build/poco-polar-render-benchmarks/20260830T000848Z-seed-5eed3920c0dec0de`: 18/18 in 272 seconds,
with 1,690-byte KCPK, 240-byte KCPR and 32-byte KCRP assets and 1,804,558–1,804,566-byte APKs.
No Burst APK from this matrix has been installed or run through GLES/Mali, so this release makes no
Burst device-performance claim.

Double-click `RUN_POLAR_GLOW_LAB.cmd` for the shortest local Glow-by-distance check. It generates the
project if absent, then opens a 128-display Burst project using Shared LUT, subtle Bayer, distance
0–4 and strength 1.25. The physical run described below adds one POCO baseline; it does not establish
the full Direct/LUT/Bayer matrix, electrical power or visual parity at every seam/orientation.

The separate fail-closed matrix command is
`python validation/benchmark_polar_render_poco.py --workload glow --include-cpu --build-only`.
The Glow handoff APK is 1,817,430 bytes with SHA-256
`17B3DAE3C4479B1BD09D335ACE551A9414BFD3BACB97BC1C976FA6E5E9C801F4`, preserved under
`build/release-handoff/20260830T012054Z-polar-glow`. It is ARM64-only, v2-signed and contains the
exact 1,690-byte KCPK, 288-byte KCPR v3 and 32-byte KCRP. Its original folder records the earlier
built-only boundary; that exact APK was later installed as the same-phone A/B control, with the
profile preserved in the Grow handoff folder.

Double-click `RUN_POLAR_GROW_LAB.cmd` for the compounded v4 check. The final handoff at
`build/release-handoff/20260830T023441Z-polar-grow` contains a 1,819,202-byte ARM64 APK
(`E5348442…`) plus its 304-byte KCPR v4. That exact APK was installed and profiled on Poco
`2412DPC0AG`: 120.33 FPS at 120 Hz, 8.380/10.113/11.295-ms p50/p95/p99, zero CPU fallbacks,
127 GPU-generated/grown copies, thermal status 0 and no crash. The same-phone Glow-v3 control also
held 120.33 FPS; one sequential A/B is not a power or statistically isolated overhead claim.

Targeted Ruff passes; the final Grow-integrated full suite is green: 763 tests and 305 subtests in
238.71 seconds. First Steps emits a 1,265-byte KCVG with SHA-256
`363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`, a 914-byte KCPK with
SHA-256 `8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313`, and a 60-byte KCSP with
SHA-256 `E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`, totaling 2,239 bytes.
Fresh idle execution produces state SHA-256
`a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`; dash execution sets
`heard_message=true` and `score=1`.

The current PBR-lite/opcode-25/animation-runtime APK is locally built and inspected at 1,484,357
bytes with SHA-256 `B9B1A9A1E722C5B0D0DAA6DE3634E605E16D7903BA14626B4F99B58154918497`. The canonical and
`pbr-lite-op25` paths are byte-identical, v2-signed, ARM64-only and contain the unchanged current
sidecars; the native library includes KCAN while the unanimated starter emits no KCAN asset. The Poco
is absent from ADB, so this `B9B1…` build has no install, launch or physical
profile claim. The preceding local `message-op25` / `message-op25-audit-fixed` snapshot remains
1,451,149 bytes / `1003F061…`.

The animation demo APK is 1,483,820 bytes / `43D197EC…`; its 88-byte KCAN contains one binding and
two ping-pong keys. It is also locally built and inspected only.

The current graph-controlled multi-clip demo is
`build/UGTS-Multi-Clip-3.9.2-Poco-X7-Pro-debug.apk`: 1,504,091 bytes / `94FD4CB4…`. It is v2-signed,
ARM64-only, GLES 3, min-SDK 26/target-SDK 36, and contains a 240-byte KCAN v2 with two clips/seven
keys plus a 191-byte KCVG with Play/Stop opcodes 26/27. It is locally built and inspected only
because no ADB device was attached.

The last physically verified pre-audit opcode-25 APK is preserved at the explicit
`message-op25-pre-audit-debug` path (1,449,653 bytes; SHA-256
`FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`). `aapt`/`apksigner`
inspection verifies package `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 /
`3.9.2-poco-x7-pro`, minimum SDK 26, target/compile SDK 36, GLES3, ARM64-only native code, the debug
certificate and v2 signature.
Embedded KCVG/KCPK/KCSP hashes match that build's source sidecars.
Xiaomi `2412DPC0AG` / `rodin` installed and cold-launched it; the pulled 1,449,653-byte base APK has
the same SHA-256. Its 30-second profile measured 120.12 effective FPS, 8.372/10.183/12.641 ms
p50/p95/p99, thermal status 0 and no crashes or warnings; see
`validation/device/opcode25-message-poco-profile.json`. This physical evidence belongs only to FBCB.

The preceding opcode-24 build is preserved at
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-cone-op24-debug.apk` (1,460,361 bytes; SHA-256
`917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`). The opcode-23 build remains
preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk` (1,443,529 bytes; SHA-256
`C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`). The preserved 1,441,929-byte opcode-22
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk` owns the
30-second Poco result: 120.23 effective FPS, 10.118 ms p95, 132,590–138,573 KiB PSS,
44.634–45.511 °C reported GPU temperature, thermal status 0 and no crash lines or warnings. A still
earlier 3.9.2 APK owns the retained 64.9-second idle baseline. Interaction-heavy/touch, unplugged,
long-duration thermal and 60/90 Hz/lower-tier fallback evidence remain open. UGTS is not yet a
complete Godot-like engine: linked multi-object scenes/prefabs, GLB import/animation authoring,
skeletal animation and retargeting, crossfades/layered blending, animation-state-machine authoring,
richer physics/content pipelines, production distribution, Vulkan and a full AAA asset/content
pipeline remain future work.
