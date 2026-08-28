# Game Project and HTML5 Export Contract

## Project schema

The schema identifier is `ugts-kc-game-project-3.9`. A project contains metadata, display settings, input, vector assets, audio, tilemaps, scenes, a valid start-scene ID and build settings.

## Validation

Validation aggregates independent issues and reports errors/warnings plus counts. It checks project/display/input/audio records, vector assets, scene/entity validity, duplicate IDs, unknown tilemaps, unknown vector asset references and unknown sound references.

## Instantiation

A scene instantiates into a fresh `GameWorld`. Initial state is deep-copied, the scene ID and score are defaulted, and every entity/component record is reconstructed through the component codec.

## Content identity

`content_hash` is SHA-256 over canonical sorted JSON with integral-number normalization. It is a reproducibility/integrity identifier, not an ownership claim.

## HTML5 build

The exporter validates the project before writing output. Single-file mode embeds the project and runtime in `index.html`; bundle mode writes `kc-runtime.js`. Each build writes a report containing project hash, file hashes and byte counts. Project JSON is escaped before insertion into script context.

The browser runtime is a separate implementation sharing project semantics with Python. Cross-language bit-identical floating-point state is not claimed.
