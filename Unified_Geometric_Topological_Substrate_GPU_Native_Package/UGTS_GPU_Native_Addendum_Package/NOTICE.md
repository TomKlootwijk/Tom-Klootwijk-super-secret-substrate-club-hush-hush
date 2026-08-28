# Notices and provenance

- The uploaded PDFs are user-provided design records. Their raw extracted text is not redistributed in this package; only privacy-safe source notes, hashes, normalized mechanisms and claims are included.
- The package contains custom minimal Vulkan/EGL/OpenGL ES declarations solely for the functions and structures used by the self-contained benchmarks. Production builds should use the official Khronos headers.
- SPIR-V modules and driver/program cache artifacts are generated outputs of the bundled shaders and validation environment. Driver caches are implementation-specific and not portable contracts.
- SwiftShader/ANGLE and Vulkan system libraries are external runtime dependencies used during validation; they are not bundled as third-party source code.
- The hardware RTL file is a reference mapping and was not synthesized in this container.
