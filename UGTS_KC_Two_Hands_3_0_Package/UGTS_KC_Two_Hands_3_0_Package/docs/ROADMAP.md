# Post-3.0 Production Roadmap

1. Replace reference triangle subsampling with a topology-aware simplifier and certified error propagation.
2. Add a native C++ or Rust core with a stable C ABI while retaining the Python oracle.
3. Compile the 3.0 shader contracts to SPIR-V and execute on named physical Vulkan devices.
4. Implement an actual WebGPU browser demo using the same records and event proposal layout.
5. Bind OpenXR hand joints to the typed `HandPose` schema and exercise confidence/fallback policies.
6. Add engine adapters that consume the same scene/event schema without becoming state authority.
7. Add skeletal animation, maintained constraints, character sweeps and conventional physics fallback.
8. Add server-authoritative replication, interest management, checkpoints and rollback transport.
9. Integrate OpenUSD composition, glTF runtime packaging, MaterialX look interchange and OCIO color transforms.
10. Compare against conventional mesh/BVH/physics implementations on equal-error workloads and apply kill criteria.
