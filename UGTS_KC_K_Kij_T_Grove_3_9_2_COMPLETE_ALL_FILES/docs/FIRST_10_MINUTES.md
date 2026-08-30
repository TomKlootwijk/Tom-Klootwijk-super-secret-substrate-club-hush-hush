# Your First Ten Minutes in UGTS Grove

UGTS Grove is built around one gentle loop:

```text
Choose an object -> change one thing -> press Play -> see what happened
```

You do not need to know Python or C++ to begin.

## 1. Open the editor

From this folder:

On Windows, double-click **`RUN_UGTS_STUDIO.cmd`**. It opens the editor without leaving a console
window behind and offers to install the editor dependency only if it is missing.

The equivalent commands are:

```powershell
python -m pip install -e ".[editor]"
python -m ugts_kc3 editor
# Or launch the installed desktop command:
ugts-studio
```

Choose **Start a Simple 2D Game** on the welcome screen. The starter has a player, one crystal and a tiny
logic graph. It is deliberately small enough to understand in one sitting.

## 2. Learn the six places

- **Scene Tree** lists the things in the current scene.
- **Scene** is where you select them, drag 2D objects, or use the red X, green Y and blue Z handles
  to place Mobile 3D objects.
- **Inspector** changes position, rotation and size, plus existing pictures, shapes, materials,
  simple Mobile 3D movement patterns and bounded decorative Populate Areas.
- **Logic Blocks** connects readable blocks instead of asking you to type code.
- **Animation** gives one eligible static Mobile 3D object a small library of named whole-pose clips.
  It opens when an animated object needs it and shares the bottom tray with Output.
- **Output & Builds** explains validation and builds in ordinary language. It stays closed until a
  check, build, deploy or error has useful detail.

The dark workspace starts viewport-first: Scene Tree and Resources share the left tabs, and Logic
Blocks hides the Inspector to give the graph room. The **View** menu can reopen every dock.

## 3. Press Play first

Press the green **Play** button. Move with WASD or the arrow keys and press Space to dash. In the
starter graph, every new Space press adds one to `score`.

Press **Stop** to return to editing. Play works on a temporary runtime copy; stopping does not
secretly rewrite your scene.

You may open **Logic Blocks** while Play is running. Editing is paused there, but the green step
badges and **Last Run** list update as blocks run. Select a Last Run row to find its block; the row
summarizes values, the chosen next path or an error. Stop keeps the latest trail visible while making
the graph editable again. This trail is a desktop teaching aid, not project content: it is not saved
and adds zero bytes to a web, glTF or Android build.

## 4. Change one block

Select **Player**, open **Logic Blocks**, select the yellow **A Value** block and change `1` to `2`.
Press Play again. Each dash
now adds two. That is a complete first program:

```text
When Button Pressed -> read Score -> add A Value -> change Score
```

Block colors have a stable meaning:

- Blue begins an event.
- Purple chooses a path.
- Yellow supplies data.
- Orange calculates.
- Pink changes the game.
- Green moves or pushes an object.

Connections are checked before they run. The editor explains incompatible dots immediately; **Check
Project** reports the exact saved graph/node problem before a build.
Graphs also have a step limit, so an accidental loop stops with an explanation instead of freezing.

Logic Blocks always follows the selected owner. Select a 2D or 3D object that has no logic yet and
you will see an empty workspace—not another object's graph and not a hidden starter graph. The
project is unchanged until the first real edit, such as adding a block; that edit creates and binds
the object's graph in one Undo step. Undo removes both the new graph and its binding. If an object
already owns several graphs, use the chooser in the Logic Blocks header to pick the exact one. A
Populate Area prototype is deliberately read-only here because static population prototypes cannot
own Logic Blocks; turn Populate Area off first if the authored object needs behavior.

Under **Sensing**, **Find Nearby Object** asks where to start (**Origin**), what portable tag to find
(Player, Collectible, Goal, Decorative or Hazard), and an inclusive **Radius**. It returns whether a
match was found, the nearest active/alive matching object and its distance. The origin itself is not
a result; equal-distance matches use object ID for a repeatable tie-break. Its compact native
encoding is append-only opcode 22, with the same behavior in desktop, retained HTML5 and Android.

**Find Object Ahead** adds one child-safe **Facing** direction and **View width** to those rules. The
saved value is a Vector4 containing world-axis X/Y/Z plus minimum cosine. The runtime uses exact
binary32 GSP4 cone math without trigonometry; rotating or scaling Origin does not rotate or resize the
cone. A new 2D block starts at world Right, a new 3D block at world Forward, and advanced graphs may
link the Vector4 directly. Its compact encoding is append-only opcode 24.

Under **Events**, **When Timer Rings** starts a graph after a simple delay. Set **Seconds** directly
on the block from more than 0 through 86,400; it starts at 1 second. Leave **Repeat** on to ring again
after each period, or turn it off to ring once. Its **Count**, **Remaining** and **Entity** outputs can
feed ordinary action blocks. The timer follows this graph binding's active fixed updates: disabling
its owning object pauses the timer but not the game, and Ready or Restart begins it again from zero.
It never emits more than one ring in an update or hides a suspended program in the save file. The
same block settings and behavior are checked in the editor, desktop Play, retained HTML5 and native
Android; its compact encoding is append-only opcode 23.

**When Message Heard** starts a graph when another graph uses **Send a Game Message** with the exact
same saved name. Message names are short portable IDs such as `player.dashed`; matching is exact, not
fuzzy. The receiver exposes who sent it, an optional target and its own bound entity. Broadcasts reach
active object logic in stable scene/graph order and then World Logic; targeted messages reach the
target owner's logic plus World Logic. A message sent while another is being heard waits in the same
bounded queue, so nested conversations are breadth-first instead of re-entering a graph. Its compact
encoding is append-only opcode 25.

Mobile 3D also has **Trigger Enter** and **Trigger Exit** event blocks. They run once when the active
player crosses a sensor area's edge and provide friendly `Sensor`, `Player` and bound `Entity` values.
The same roots run in desktop Play and the native Android player without adding a collision push.
Click **+ Trigger Area** above the Scene Tree to add a ready-made one. You can also select a 3D object,
open **Trigger Area** in the Inspector and turn on **Use as Trigger**. Choose Sphere and a Radius, or
Box and Size X/Y/Z. All of those edits support Undo/Redo and save with the project.

To reuse one safe 3D object, select it and click **Save Object** above the Scene Tree. Give it a short
name, then click **+ Saved Object…** whenever you want an independent ordinary copy. Its resources
and Logic Block bytecode stay shared, but its placement, look and physics can differ.

To reuse a group, hold Ctrl and select at least two ordinary 3D objects. Click the object that should
anchor the group last, then choose **Save Together** and give the Saved Scene a clear name. Choose
**+ Saved Scene…** to place a linked copy. It appears as one group row with read-only children; select
the group and use the Inspector to move, turn or scale everything together. Choose **Unlink** only
when those children should become ordinary independent objects. Save, place and Unlink are each one
Undo step.

The definition is a snapshot: changing the original objects later does not rewrite it, and the
current editor does not yet edit a definition in place. Linked placements share the saved definition
and compact graph/resources. Animate leaf objects, not a group parent: parents with dynamic physics,
spin, Animation or transform-writing Logic Blocks are refused because the current phone runtime is
deliberately flat. Player, nested Saved Scenes and world-centred Movement Patterns are also stopped
with an explanation.

The new copy is selected in the first collider-safe free spot. For a very large object that spot can
sit beyond the playable bounds, so drag the selected copy to the final place you want.

To make a safe static 3D object move without code, select it and open **Animation**. Click **Create
Animation**. This makes a **Main** clip; the protected key at 0 seconds keeps the object's starting
pose. Move **Time** later, change **Position offset**, **Turn (degrees)** or **Size multiplier**, then
click **Add whole-pose key**. Each key deliberately keeps position, turn and size together, which
makes the path easier to understand and Undo. Choose **Once**, **Repeat** or **Back and forth**, and
choose how the selected key arrives: **Straight**, **Start gently**, **Stop gently**, **Gently at both
ends**, **Smooth**, **Extra smooth**, **Slight overshoot**, **Springy** or **Jump**. Press **Play
Animation** to preview the selected clip; **Stop** returns the view to the starting pose.

Use **New** for another motion, **Duplicate** when it should begin as a copy, and **Rename** to give
it a clear child-readable name. The stable clip ID shown to Logic Blocks does not change when its
display name changes. **Delete Clip** removes only the selected motion. Check **Play this clip when
the game starts** for at most one clip, or leave every clip unchecked so the object waits for logic.
An eligible object can keep up to 16 clips.

To control them during the game, open the object's **Logic Blocks** and add **Play an Animation**.
Choose the animated object and clip. **Restart: Yes** begins at the first pose; **No** resumes that
same clip after a hold. Add **Stop an Animation** with **Reset: No** to pause and hold the current
pose, or **Reset: Yes** to return to the object's authored pose. A World Logic graph must choose an
explicit animated object because it has no **This object** owner.

Dragging Time or the playhead is only a preview: it does not alter the saved object, dirty the
project or add an Undo step. Creating/deleting an animation or clip and changing its name, autoplay,
length, repeat mode, keys or arrival style each use normal Undo/Redo. Project Play runs autoplay and
the two animation Logic Blocks in the real desktop ECS. An Android build carries the same quantized
clips and control IDs in optional KCAN/KCVG data. Old one-clip projects remain compatible as an
implicit **Main** clip. Animation is deliberately disabled for dynamic objects, Player, Movement
Pattern, Populate Area and objects with spin velocity, because each already has—or implies—another
transform owner.

This is a compact rigid-transform clip library, not a character animator. GLB animation import,
skeletal rigs, retargeting, crossfades and animation-state-machine authoring are still absent; the
current glTF preview export is static.

## 5. Save, then make an Android build

Save the project. The simple starter above builds for 2D/HTML5. For Android, choose **Start a Mobile
3D Game**. Its first lesson uses the same event/value/action idea: Space increments Score and makes
the player grow. The Goal is also a Trigger Area with a second lesson that sets `Inside Goal` true on
entry and false on exit. Its orbit is driven by a compact two-word packed polar ECS component and a
shared sub-kilobyte log-encoded polar LUT asset. These behaviors preview in the editor and run in the
native phone player. Its supported Logic Blocks compile into bounded native graph bytecode.

Expand **World Logic** in the Scene Tree and select **Find the Goal**. Its Sensing block explicitly
starts from **Player**, looks for **Goal** within **9 m**, and feeds `Found` into **Set World State**
under the key `nearby_goal`. Keeping Player explicit is important: World Logic has no owning object
to use as an implicit origin. Change the search distance, press Play, and use Logic Trail to see the
result without building a list of every goal yourself.

Open **Find the Goal Ahead** next. It uses **Find Object Ahead** with the saved 3D Forward world axis
and Normal width, then writes `goal_ahead`. The starter player begins aligned with that world
direction; if you later turn the player, choose a new saved Direction because the cone does not follow
Origin rotation.

Still under **World Logic**, open **Count the Timer Rings**. Its repeating one-second **When Timer
Rings** block sends **Count** straight into **Set World State** as `timer_rings`. This is the readable
way to teach “once every second”; you do not need to connect Every Frame to a hand-built counter.

Open **Hear the Dash Message** next. The separate Dash graph sends `player.dashed`; this World Logic
`message_lesson` graph receives that exact name with **When Message Heard** and writes
`heard_message=true`. Press Play and dash to watch the message cross between graphs in Logic Trail.
Together, First Steps contains seven graphs, 27 nodes and seven bindings including four World Logic
bindings.

Select a non-dynamic Mobile 3D object and find **Movement Pattern** in the Inspector. Choose **Off**,
**Orbit**, **Spiral Out** or **Spiral In**, then set a radius, turn speed and start angle. The editor
keeps the packed words hidden, shows the approximate storage cost, and makes the change undoable. All
movers using the Studio profile share one binary16 log-encoded polar LUT; Android adds exactly 24 sparse bytes per
moving node. Movement Pattern stays disabled on a dynamic object because physics already controls
that object's position.

To place a 3D object directly, select it and drag one of the thick colored handles: red is X, green is
Y and blue is Z. The mesh, handles and Inspector position preview the move while the project record
stays untouched; releasing creates exactly one Undo step. Starting Play cancels an unfinished preview
and hides the handles. An object with a Movement Pattern keeps X and Z locked because the pattern owns
those coordinates, but its green Y handle remains available. Hover or click a locked handle for the
plain-language explanation, or choose **Off / Static** before placing it freely.

Select **Crystal Garden** in the Scene Tree. It is one saved static crystal with **Populate Area**
turned on; the starter recipe shows 18 display objects. Change **Objects in group** or **World
number** and watch the same repeatable garden update. Width, height and depth set its box, smallest
and largest size set variation, and **Turn copies randomly** changes only their display rotation.
The edit supports Undo/Redo and save/load, while Resources lists one item under **Populated Areas**—it
does not fill the project with copied nodes.

A Populate Area group contains 2–256 display objects including the one you authored. Projects allow
64 groups and 1,024 population objects total. The compact Android sidecar costs 36 bytes per group
plus one shared 24-byte header, and increasing a count preserves all earlier copies as a deterministic
prefix. For a responsive editor, the Scene view draws at most 64 generated copies from each group and
256 generated copies overall. A glTF preview bakes the copies into nodes; Android generates them from
the recipe and renders them with GLES instancing, subject to its visible-node quality budget.

Populate Area is only for static decoration. The Inspector refuses objects that are dynamic or
moving, have a collider or Trigger Area, carry gameplay tags, or own Logic Blocks or a Movement
Pattern. Generated copies never gain their own collision, logic, movement or gameplay behavior. The
current tool can place overlapping copies and does not provide per-copy frustum culling or LOD. There
is no Mobile 3D browser player yet, so this lesson previews on desktop and deploys through the native
Android path; HTML5 remains the 2D workflow.

The fastest compact-rendering lesson is one click: double-click `RUN_POLAR_GLOW_LAB.cmd` in the
repository root. It generates the project if absent, then opens
`build/polar-glow-lab/packed-polar-glow-burst-128-lut-subtle.json` with 128 Radial Burst displays
(one prototype plus 127 generated copies),
Shared LUT, subtle Bayer and Glow distance 0–4 at strength 1.25. You can also open
`examples/packed_polar_gpu_lab_3d/project.json` and build the same idea yourself.

For the next compounded use, double-click `RUN_POLAR_GROW_LAB.cmd`. It creates a separate
`build/polar-grow-lab/packed-polar-grow-burst-128-lut-subtle.json` project with the same 128-display
Burst, Shared LUT, subtle Bayer and Glow settings, plus **Grow glowing copies**. The two launchers
stay separate so the v3 Glow-only project remains an exact comparison instead of being silently
upgraded.

To author the effect in child-sized steps:

1. Select an orbit mover and find **Make Many** in the Inspector.
2. Choose **Ring**, **Spiral**, **Polar Field** or **Radial Burst (loops)**, then set **Objects in
   group** and **World number**.
3. Open **Glow by distance** and tick **Enable distance glow**.
4. Set **Start distance** to 0 to begin at the safe centre core, set a larger **End distance** inside
   the Movement profile, and try **Glow strength** 1.25.
5. Change **World number** to see a different repeatable bright/dim phase, or untick the checkbox to
   return to the exact old no-Glow recipe path.
6. Optionally tick **Grow glowing copies**. Only generated display copies reuse that same Glow value
   for visible size: zero Glow is 1x and maximum Glow strength 4 is at most 5x. The real object,
   collider, picking and Logic Blocks remain at their authored scale.

One real ECS object keeps the Movement Pattern; the other members are repeatable display copies
reconstructed from a tiny content-addressed recipe. The Inspector shows the exact KCPR file size and
full address, while the Scene view draws at most 64 generated previews across the whole project.
Generated members deliberately select their real prototype and never pretend to own separate physics,
collision, tags, or Logic Blocks. Glow changes their material presentation, not those boundaries.
Grow is presentation-only too: it multiplies the copies' already-authored or Burst-envelope size and
never creates or resizes a gameplay object. The Scene preview and Play preview use the same quantized
field evaluation.
For Radial Burst, the bright band follows each copy's own local Burst distance before the whole effect
is placed around its prototype; the prototype uses its own Movement radius. It is not a hidden
world-space distance check.

To control the decoration without hiding its real object, add **Show or Hide Extra Copies** in Logic
Blocks → Looks. Choose a Make Many object and Show or Hide. The object itself remains visible and
keeps running; only its derived display copies change. Starting Play again restores them, because
this tiny control is runtime state rather than an edit to the saved recipe.

In the Project dock's **Render** tab, **Shared LUT** asks Android to reconstruct packed movement through
the shared binary16 log-encoded polar LUT; **Direct math** is the matching comparison path; **CPU** is
the correctness fallback. For Glow by distance, Shared LUT reuses the same UGLUT2 direction, Direct
uses cosine and CPU uses the quantized LUT reference—the effect is not silently removed. The glow is
added to scene lighting, then **Gentle gradient smoothing** applies the canonical Bayer matrix only to
the final picture. Bayer does not smooth motion or change the ECS. Build and measure the same project
in Direct and Shared LUT modes before deciding which is faster on a phone. The one-click lab is a
manual authoring/desktop check only until its exact APK is viewed and profiled on POCO/Mali.

Use **+ Add**, **Copy** and **Delete** above the Scene Tree to construct the scene. Every structural
change supports Undo; essential referenced objects are guarded with an explanation instead of being
silently broken. Select an object and use **Appearance** in the Inspector to choose one of the
project's vector pictures, 3D shapes or materials; those choices also support Undo and Redo. Use
**File → Import 3D Shape…** to bring a Wavefront OBJ into a Mobile 3D project. Imported shapes are
checked, appear in Resources and the Shape chooser, survive Android packing, and support Undo.

For a quick polished surface, choose **Material Look** under Mobile 3D Appearance: Matte, Toy
Plastic, Metal or Crystal Glow. The object's colour stays yours. If its material is shared, Studio
safely makes a private copy for this authored object and its Populate Area copies; one Undo restores
everything. **Custom** only describes values and never rewrites them. Preset names are not saved, so
this friendly control costs no extra Android material bytes.

On a phone, hold or drag the left side to move and tap it to jump. Drag the right side to look and
tap it to dash—even while the left thumb stays down. Pinch changes camera distance. Touch roles follow
pointer IDs, so the order in which a child puts their thumbs down does not swap the controls.

In **Output & Builds**, choose **Poco X7 Pro APK (Debug)** for a directly installable file. Choose
**Poco: Build + Install + Open** only after the phone is connected, USB debugging is enabled, and its authorization
prompt has been accepted. Android Studio remains an optional advanced target, not a beginner requirement.
The blue **Deploy to Phone** toolbar button performs the complete build, install and open flow. It
stops before a long build when no authorized phone is ready and explains no-device, unauthorized,
offline or multiple-device states. Once the check succeeds, the same phone serial is used for every
phase. The generated Android project lives beside the saved project at
`.ugts-studio/deploy/<project-id>-android`. Output tells you whether building stopped, installation
stopped, or the APK installed but Android could not open it; a successful run ends with the game on
the phone.

Leave the deployed game running and its screen on, then choose **Check Phone** or press
`Ctrl+Shift+P`. The editor remains responsive while a bounded 30-second ADB check reads frame cadence,
game-process memory, GPU temperature when Android exposes it and the app's crash buffer. Output
reports those measurements and any warnings; CLI JSON also retains available RSS, battery and Android
thermal fields. The check injects no touch input, changes no game/device setting and does not edit the
project. It clears only SurfaceFlinger's diagnostic latency history between sample windows. A
disconnected phone, a game that is not running, or a screen with no active game surface produces a
plain-language stop message rather than a partial success.

The current PBR-lite/opcode-25 APK is locally built and inspected at
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-debug.apk`: 1,484,357 bytes with SHA-256
`B9B1A9A1E722C5B0D0DAA6DE3634E605E16D7903BA14626B4F99B58154918497`. The explicit
`pbr-lite-op25-debug` copy is byte-identical and contains the unchanged compact sidecars plus the
linked KCAN runtime; this unanimated starter emits no KCAN asset. The Poco is
absent from ADB, so this current build has not been installed, opened or profiled on the phone yet.
The preceding local `message-op25-debug` / `message-op25-audit-fixed-debug` snapshot remains
1,451,149 bytes / `1003F061…`.

For the named-clip workflow, open `examples/multiclip_animation_3d/project.json`. Press **Play** to
watch Gentle Sway switch to Timer Hop after half a second, then inspect its three connected Logic
Blocks. The matching locally built Poco APK is
`build/UGTS-Multi-Clip-3.9.2-Poco-X7-Pro-debug.apk`: 1,504,091 bytes with SHA-256 `94FD4CB4…`.
It is ready to install, but this build has no device claim because ADB reported no attached phone.

For the linked-group workflow, open `examples/linked_saved_scenes_3d/project.json`. Expand the three
Glow Gate Trio rows, move one whole group, then Undo or Unlink it. Its verifier proves that seven
stored object records become 13 uniquely named ECS nodes plus nine render-only sparkles. The matching
local Poco APK is `build/UGTS-Saved-Scenes-3.9.2-Poco-X7-Pro-debug.apk`: 1,505,487 bytes with
SHA-256 `70FD18B2…`. It is build-tools inspected but has no phone claim while ADB has no device.

The last physically verified pre-audit opcode-25 APK is preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-message-op25-pre-audit-debug.apk`: 1,449,653 bytes with SHA-256
`FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`. Xiaomi `2412DPC0AG` /
`rodin` installed and cold-launched it; the pulled 1,449,653-byte base APK has the exact same hash.
Its bounded 30-second read-only profile measured 120.12 effective FPS, 8.372/10.183/12.641 ms
p50/p95/p99, thermal status 0 and no crashes or warnings; the capture is
`validation/device/opcode25-message-poco-profile.json`. That evidence belongs only to FBCB, not the
newer `1003…`, `B9B1…` or animation-bearing `43D1…` APKs.

The preceding opcode-24 build remains preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-cone-op24-debug.apk`, 1,460,361 bytes with SHA-256
`917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`. The opcode-23 build remains at
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
`C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`.
The preserved 1,441,929-byte opcode-22
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk`—not this timer-capable build—owns the
120.23 effective FPS, 10.118 ms p95, thermal-status-0 30-second baseline. A still earlier APK owns the
64.9-second idle baseline. These historical baselines do not replace the opcode-25 evidence above.
Interaction-heavy/touch, unplugged, long-duration, explicit fallback-rate and lower-tier testing
remain open, as does the first device install/check of the post-audit build.

Generate and compile a direct-device Poco build with:

```powershell
python -m ugts_kc3 build-android examples\grove_k_kij_t_3d\project.json build\MyAndroidGame --apk
```

To install it, enable Developer options and USB debugging on the phone, connect it, accept the phone's
authorization prompt, and run:

```powershell
python -m ugts_kc3 android-devices
python -m ugts_kc3 build-android examples\grove_k_kij_t_3d\project.json build\MyAndroidGame --install
# With that deployed game running and its screen on:
python -m ugts_kc3 profile-android org.ugts.games.k_kij_t_grove_mali_g720_mc7_arena_3d.pocox7pro --seconds 30 --json
```

Debug builds are for learning and owner-device testing. Publishing needs your own private release key.

## When something goes wrong

Read the first plain-language message in Output. Do not change five things at once. Stop Play, undo
the last change, and try a smaller change. Saving another copy before experimenting is always okay.
