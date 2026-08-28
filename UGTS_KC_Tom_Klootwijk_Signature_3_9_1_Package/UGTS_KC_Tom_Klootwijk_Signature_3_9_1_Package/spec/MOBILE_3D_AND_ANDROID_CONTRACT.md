# Mobile 3D and Native Android Contract — 3.9.1

## Authority split

The JSON `Mobile3DProject` is the authoring/source record. Python validation and deterministic
simulation are the reference oracle. `KC3D391` is a compiled deployment record. Android rendering
and input are downstream presentation/runtime behavior and do not rewrite the source project.

## Required capabilities

- finite transforms, indexed triangle meshes and normalized quaternion rotations;
- named PBR-style materials and validated mesh/material references;
- fixed-step arcade physics with gravity, floor/bounds, sphere-proxy contacts and gameplay tags;
- camera/light/world records shared by the reference runtime and native pack;
- ordered quality tiers and Android device profiles;
- Android NDK `NativeActivity`, OpenGL ES 3.0, depth/culling, dynamic render scale,
  touch, keyboard and gamepad input;
- deterministic source/project hashes and structural scene-pack inspection.

## Compatibility

The 3.9 2D project schema remains unchanged. Mobile 3D uses
`ugts-kc-mobile-3d-project-3.9.1`, so existing 2D projects and browser builds remain valid.

## Explicit boundaries

Vulkan is an optional future backend hook, not the 3.9.1 renderer. 4D is a design-only roadmap.
No physical-device certification, Play Store approval, APK signing, continuous rigid-body
certification, skeletal animation suite, multiplayer service or editor UI is claimed.
