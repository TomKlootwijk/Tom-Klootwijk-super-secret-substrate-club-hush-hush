# KC Two Hands Interaction Contract

## Typed input

Each `HandPose` carries side, wrist pose, joint positions, joint radii, tracking confidence, tracking status, input source and timestamp. Left and right are separate schema values; they are not inferred from coordinates.

## Pinch guard

Pinch uses hysteresis:

```text
inactive -> active when thumb-index distance <= enter_distance
active   -> inactive when thumb-index distance >= exit_distance
exit_distance > enter_distance
```

Untracked or low-confidence data resets the reference detector and returns a reason code. A production adapter may choose hold/freeze/soften instead, but the policy must be declared.

## Bimanual transform

An anchor records both initial hand poses and the object's initial transform. The reference result uses:

```text
midpoint     = (left + right) / 2
scale        = current_separation / initial_separation
alignment    = shortest quaternion mapping initial pair axis to current pair axis
twist        = averaged wrist-orientation twist around the current pair axis
rotation     = twist * alignment
world_delta  = T(current_midpoint) * R(rotation) * S(scale) * T(-initial_midpoint)
```

Scale is clamped and degenerate separation is rejected. Confidence is the minimum confidence of the two current hands.

## Ownership and lineage

The cooperative-grab state machine distinguishes `grab_start`, `second_hand_join`, `handover` and `grab_release`. A handover keeps object identity while appending an interaction-lineage label. It does not silently create a new object.

## Input adapters

OpenXR, optical tracking, gloves, controllers, mocap and desktop emulation may all populate the same hand schema. Device-specific gesture semantics stay in adapters; authoritative object changes still pass through support, compatibility, guard and event commit.
