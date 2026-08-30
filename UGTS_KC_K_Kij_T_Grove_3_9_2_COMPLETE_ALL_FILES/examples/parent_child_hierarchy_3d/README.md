# The Moving Carrier Family

This is the smallest visual test for editable parent/child transforms. The cyan
`Carrier` is a normal moving ECS object. Its amber `Arm` and violet `Mast` are
children, and the lime `Beacon` is a child of `Mast`.

## Try it in the editor

1. Double-click `RUN_UGTS_STUDIO.cmd` at the repository root.
2. Choose **Open Project…** and open this folder's `project.json`.
3. Expand `Carrier` in the dark Scene Tree. You should see this exact shape:

   ```text
   Carrier
   ├─ Arm
   └─ Mast
      └─ Beacon
   ```

4. Press **Play**. The carrier moves to the right while turning. Arm, Mast, and
   Beacon must stay rigidly attached; Beacon follows through both parent levels.
5. Stop, right-click `Arm`, and choose **Detach**. It must stay in the same world
   position. Undo must attach it again.
6. Right-click an unattached display object and use **Attach to…**. Attaching also
   preserves its world position, so there should be no visual jump.

The Inspector says **Transform inside …** for a child. Those values are local to
its parent; the viewport and move gizmo stay in world space.

## Manual phone procedure

Connect the POCO X7 Pro with Developer options and USB debugging enabled, accept
the computer's RSA prompt, then click **Deploy to Phone**. The editor builds the
ARM64/OpenGL ES 3 APK, installs it through ADB, and launches it. A missing or
unauthorized device is reported in the Output panel instead of being treated as
a successful deployment.

## Intentional first-slice limits

Attached children are display objects: Collision is None, Dynamic is off, tags
are empty, Spin is zero, and they do not own Logic Blocks, Movement Patterns,
Populate Area, or Transform Animation. A parent may move or spin, and every
parent that owns children must use a positive uniform scale. The hierarchy is
bounded to eight parent edges. These rules keep desktop, packed Android, glTF,
and the editor deterministic without pretending that child physics already
exists.

Run the source-level verifier from the repository root with:

```powershell
python examples/parent_child_hierarchy_3d/verify_example.py
```

That verifier checks the authored/local and composed/world poses, fixed-step
movement, strict compact KCHI links, retained glTF children, and deterministic
repeated execution. The exact checked APK has also installed and cold-launched on
the authorized `2412DPC0AG` / `rodin_eea` Poco. Its 15-second five-sample profile
observed 120.15 effective FPS and 9.959 ms p95 with thermal status 0 and no
crashes/warnings. This five-node/~60-triangle scene is not a sustained, large-game/
AAA or recorded interaction-heavy child-following result.
