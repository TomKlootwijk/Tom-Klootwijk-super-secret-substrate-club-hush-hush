# Input, Animation, Tilemap and Audio Contract

## Input

An action has an ID, bindings, deadzone, threshold and optional clamping. A binding identifies a device kind, code, scale and optional device index. Raw input is resolved into an `InputFrame` containing current and previous values. Edge queries use the action threshold.

## Animation

Keyframe times are strictly increasing within a track. A track targets a property path and interpolates scalar or equal-length vector values. Clips define duration and playback mode. Crossfades blend complete sampled property maps. State-machine transitions are evaluated in declared order.

## Tilemaps

Tile layers share map dimensions and tile size. A tile definition may mark solidity and movement cost. A* paths operate on in-bounds non-solid cells and return an empty path when the goal is unreachable or an endpoint is blocked. Collision rectangles merge only contiguous compatible solid cells.

## Audio

A sound cue defines oscillator type, frequency/sweep, duration, volume, noise and ADSR envelope. Notes use equal temperament relative to configurable A4. A sequence schedules cue IDs at non-negative beats within a declared length. The Python layer is data/validation only; the HTML5 exporter realizes cues through Web Audio.
