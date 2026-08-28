# Bayer Direct architecture

## Authority chain

```text
seed + tick + mode + palette
-> integer field query at a display sample
-> bounded luminance [0,255]
-> 8x8 Bayer threshold
-> 2-bit palette index
-> RGB565 sample
-> ANativeWindow buffer post
-> Android compositor scale
```

The substrate remains upstream of presentation. There is no mesh compiler, camera, triangle list, texture sampler, shader module, ray query, or scene graph in the APK.

## Reconstructible state

A frame is a deterministic function of:

```text
(seed:uint32, tick:uint32, mode:uint2, palette:uint2,
 width:uint16, height:uint16, profile_version:3.9.4)
```

No image history or texture asset is required. Frame identity can be checked with CRC32 for regression purposes; CRC32 is not a cryptographic identity.

## Display boundary

A physical display consumes pixels, so a final pixel buffer cannot be eliminated. “No rasterization” in this profile means no conversion of geometric primitives into fragments. The app directly evaluates a finite procedural field at the requested buffer samples, applies ordered quantization, and posts the buffer. SurfaceFlinger or the device compositor scales that buffer to the physical surface.
