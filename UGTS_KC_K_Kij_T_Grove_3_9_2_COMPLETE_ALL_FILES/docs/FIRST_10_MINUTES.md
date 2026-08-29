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

Choose **My First Game** on the welcome screen. The starter has a player, one crystal and a tiny
logic graph. It is deliberately small enough to understand in one sitting.

## 2. Learn the five places

- **Objects** lists the things in the current scene.
- **Scene** is where you select and move them.
- **Inspector** changes the selected object's position, rotation and size.
- **Logic** connects readable blocks instead of asking you to type code.
- **Output** explains validation and builds in ordinary language.

If a panel feels distracting, close it. You can restore the default layout from the View menu.

## 3. Press Play first

Press the green **Play** button. Move with WASD or the arrow keys and press Space to dash. In the
starter graph, every new Space press adds one to `score`.

Press **Stop** to return to editing. Play works on a temporary runtime copy; stopping does not
secretly rewrite your scene.

## 4. Change one block

Open **Logic**, select the yellow **A Value** block and change `1` to `2`. Press Play again. Each dash
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

Connections are checked before they run. A bad connection names the exact block and socket to fix.
Graphs also have a step limit, so an accidental loop stops with an explanation instead of freezing.

## 5. Save, then make an Android build

Save the project. For the 3D Grove example, generate and compile a direct-device Poco build with:

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
