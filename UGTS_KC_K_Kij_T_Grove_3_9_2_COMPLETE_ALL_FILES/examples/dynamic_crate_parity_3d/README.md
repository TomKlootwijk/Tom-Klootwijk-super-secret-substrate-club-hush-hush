# Push the Golden Crate

This small Mobile 3D project is the Python authoring golden for one missing
desktop/Android runtime slice: an ordinary dynamic object that is **not** the
Player must move after Logic Blocks applies an impulse to it.

Open `project.json` in UGTS Studio and press Play. The cyan Player remains under
your control. The untagged gold crate receives one push when the game starts and
slides toward the violet wall. The floor and wall are ordinary static scene
objects; there is no bootstrap or code-created scene.

## The child-friendly Logic Blocks setup

The crate owns one two-block graph:

```text
When Game Starts  ->  Push an Object
                         Object: This object
                         Push amount: [1.5, 0.0]
```

`crate` is dynamic, has mass `1.5`, has no gameplay tags, and is the only node
bound to `push_crate_once`. `player` has the `player` tag and no graph binding.
That distinction is the point of the example: passing by moving only Player is
not acceptable.

## Why the golden uses simple numbers

The fixed step is exactly `1/64` second. Apply Force is a one-time Ready impulse;
`1.5 / 1.5` gives the crate an exact X velocity of `1.0`. Gravity is zero for
this isolated slice. From X `-8`, 600 steps therefore end at X `1.375` after
`9.375` seconds. Those values and every intermediate checkpoint are exactly
representable as IEEE-754 binary32 values.

The wall is deliberately beyond the 600-step endpoint. This golden isolates
generic dynamic-body integration and graph ownership; collision response is a
separate behavior and cannot blur a failure here. Continue playing and the crate
eventually reaches the wall.

## Produce the native-test handoff

From the repository root:

```powershell
python examples/dynamic_crate_parity_3d/verify_example.py
```

The verifier validates the real `Mobile3DProject`, proves the graph is bound to
the untagged crate rather than Player, runs two independent worlds for 600 fixed
steps, and requires byte-identical results. It emits checkpoints at ticks 0, 1,
64, 128, 256, 512, and 600. Tick 0 is after the Ready graph has run.

For every checkpoint the report includes:

- binary32 position and velocity values;
- each value's exact `uint32` bit pattern;
- SHA-256 of the little-endian `f32[3]` position and velocity bytes;
- the complete canonical state bytes and their SHA-256.

The canonical state byte layout is:

```text
"UGTS-DYNAMIC-CRATE-F32-1\0"
u32 tick
f32 time
f32[3] crate position
f32[3] crate velocity
u8 crate alive, active, dynamic, grounded
i32 score, health
u8 finished
```

Every number is little-endian. The same report includes exact KC3D and KCVG
byte counts, SHA-256 hashes, node order, and the graph binding from scene-node
index 3 to `push_crate_once`. This is intended to be copied directly into a C++
host golden test.

## Status

The native acceptance now lives in `tests/test_android_body_physics.py`. That
test generates Android source from this exact project, passes its real KC3D and
KCVG assets into the C++ host runtime, executes the owner-bound Ready graph, and
matches all seven position/velocity bit checkpoints through the exact X `1.375`
tick-600 golden. It also compiles the
same `body_physics.cpp` source that Gradle/NDK uses in the APK.

This is source-level desktop/native acceptance evidence for the generic-body slice,
not physical-phone evidence. Player still uses its legacy Android controller,
native contacts are not yet exposed as Logic Block events, and an attached
device is still required before install, launch or performance can be claimed.
