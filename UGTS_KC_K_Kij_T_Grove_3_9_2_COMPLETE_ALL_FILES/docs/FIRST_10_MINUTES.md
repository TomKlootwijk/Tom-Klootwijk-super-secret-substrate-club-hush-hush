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

## 2. Learn the five places

- **Scene Tree** lists the things in the current scene.
- **Scene** is where you select and move them.
- **Inspector** changes position, rotation and size, plus existing pictures, shapes, materials,
  simple Mobile 3D movement patterns and bounded decorative Populate Areas.
- **Logic Blocks** connects readable blocks instead of asking you to type code.
- **Output & Builds** explains validation and builds in ordinary language.

If a panel feels distracting, close it. The **View** menu can reopen each panel.

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

Open **Logic Blocks**, select the yellow **A Value** block and change `1` to `2`. Press Play again. Each dash
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

Mobile 3D also has **Trigger Enter** and **Trigger Exit** event blocks. They run once when the active
player crosses a sensor area's edge and provide friendly `Sensor`, `Player` and bound `Entity` values.
The same roots run in desktop Play and the native Android player without adding a collision push.
Click **+ Trigger Area** above the Scene Tree to add a ready-made one. You can also select a 3D object,
open **Trigger Area** in the Inspector and turn on **Use as Trigger**. Choose Sphere and a Radius, or
Box and Size X/Y/Z. All of those edits support Undo/Redo and save with the project.

## 5. Save, then make an Android build

Save the project. The simple starter above builds for 2D/HTML5. For Android, choose **Start a Mobile
3D Game**. Its first lesson uses the same event/value/action idea: Space increments Score and makes
the player grow. The Goal is also a Trigger Area with a second lesson that sets `Inside Goal` true on
entry and false on exit. Its orbit is driven by a compact two-word log-polar ECS component and a
shared sub-kilobyte lookup asset. These behaviors preview in the editor and run in the native phone
player. Its supported Logic Blocks compile into bounded native graph bytecode.

Select a non-dynamic Mobile 3D object and find **Movement Pattern** in the Inspector. Choose **Off**,
**Orbit**, **Spiral Out** or **Spiral In**, then set a radius, turn speed and start angle. The editor
keeps the packed words hidden, shows the approximate storage cost, and makes the change undoable. All
movers using the Studio profile share one lookup table; Android adds exactly 24 sparse bytes per
moving node. Movement Pattern stays disabled on a dynamic object because physics already controls
that object's position.

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

Use **+ Add**, **Copy** and **Delete** above the Scene Tree to construct the scene. Every structural
change supports Undo; essential referenced objects are guarded with an explanation instead of being
silently broken. Select an object and use **Appearance** in the Inspector to choose one of the
project's vector pictures, 3D shapes or materials; those choices also support Undo and Redo. Use
**File → Import 3D Shape…** to bring a Wavefront OBJ into a Mobile 3D project. Imported shapes are
checked, appear in Resources and the Shape chooser, survive Android packing, and support Undo.

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

Generate and compile a direct-device Poco build with:

```powershell
python -m ugts_kc3 build-android examples\grove_k_kij_t_3d\project.json build\MyAndroidGame --apk
```

To install it, enable Developer options and USB debugging on the phone, connect it, accept the phone's
authorization prompt, and run:

```powershell
python -m ugts_kc3 android-devices
python -m ugts_kc3 build-android examples\grove_k_kij_t_3d\project.json build\MyAndroidGame --install
```

Debug builds are for learning and owner-device testing. Publishing needs your own private release key.

## When something goes wrong

Read the first plain-language message in Output. Do not change five things at once. Stop Play, undo
the last change, and try a smaller change. Saving another copy before experimenting is always okay.
