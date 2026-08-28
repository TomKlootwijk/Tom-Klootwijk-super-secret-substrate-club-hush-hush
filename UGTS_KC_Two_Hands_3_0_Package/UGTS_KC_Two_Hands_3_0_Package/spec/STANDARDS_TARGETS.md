# External Standards Targets (checked 16 August 2026)

These standards are integration targets, not bundled implementations.

- **glTF 2.0.1** - Khronos runtime 3D asset delivery specification. The reference exporter emits a self-contained glTF 2.0 JSON document with embedded buffer data.
- **OpenUSD 26.08 documentation** - scene-description and composition target. The package emits readable USDA but does not bundle the OpenUSD runtime or claim full composition conformance.
- **Vulkan 1.4** - native graphics/compute target. The current reference package does not execute the 3.0 renderer on a physical Vulkan GPU.
- **WebGPU and WGSL** - portable graphics/compute target. A WGSL record/evaluation prototype is included.
- **OpenXR 1.1 / XR_EXT_hand_tracking** - XR hand-input adapter target. The reference hand state is synthetic/desktop-testable and does not call an OpenXR runtime.
- **MaterialX 1.39** - material graph interchange target. The bundled graph is a deliberately small independent reference graph.
- **OpenColorIO / ACES 2.0 workflows** - production color-management target. The package stores color-pipeline metadata and implements only compact preview transforms.

Official reference locations are listed in `docs/REFERENCES.md`.
