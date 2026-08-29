# Your First Ten Minutes in UGTS Grove

UGTS Grove is built around one gentle loop:

```text
Choose an object -> change one thing -> press Play -> see what happened
```

You do not need to know Python or C++ to begin.

## 1. Open the editor

From this folder:

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
- **Inspector** changes position, rotation and size, plus existing pictures, shapes and materials.
- **Logic Blocks** connects readable blocks instead of asking you to type code.
- **Output & Builds** explains validation and builds in ordinary language.

If a panel feels distracting, close it. The **View** menu can reopen each panel.

## 3. Press Play first

Press the green **Play** button. Move with WASD or the arrow keys and press Space to dash. In the
starter graph, every new Space press adds one to `score`.

Press **Stop** to return to editing. Play works on a temporary runtime copy; stopping does not
secretly rewrite your scene.

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

## 5. Save, then make an Android build

Save the project. The simple starter above builds for 2D/HTML5. For Android, choose **Start a Mobile
3D Game**. That phone-ready lesson uses the same event/value/action idea: Space increments Score and
makes the player grow. The orbiting goal is driven by a compact two-word log-polar ECS component and
a shared sub-kilobyte lookup asset. Both behaviors preview in the editor and run in the native phone
player. Its supported Logic Blocks compile into bounded native graph bytecode.

Use **+ Add**, **Copy** and **Delete** above the Scene Tree to construct the scene. Every structural
change supports Undo; essential referenced objects are guarded with an explanation instead of being
silently broken. Select an object and use **Appearance** in the Inspector to choose one of the
project's vector pictures, 3D shapes or materials; those choices also support Undo and Redo.

On a phone, hold or drag the left side to move and tap it to jump. Drag the right side to look and
tap it to dash—even while the left thumb stays down. Pinch changes camera distance. Touch roles follow
pointer IDs, so the order in which a child puts their thumbs down does not swap the controls.

In **Output & Builds**, choose **Poco X7 Pro APK (Debug)** for a directly installable file. Choose
**Poco APK + Install** only after the phone is connected, USB debugging is enabled, and its authorization
prompt has been accepted. Android Studio remains an optional advanced target, not a beginner requirement.

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
