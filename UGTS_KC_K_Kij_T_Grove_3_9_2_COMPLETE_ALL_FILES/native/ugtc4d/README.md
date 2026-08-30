# Portable UGTC4D decoder baseline

`ugtc4d_decoder.hpp/.cpp` is the independent C++17 oracle for the current
custom substrate file. It has no H.264, AV1, MediaCodec, ZIP, or other standard
media payload dependency.

Implemented and verified:

- strict UGTC4D 1.0 header, canonical directory/alignment, whole-file and
  section SHA-256, run-coded metadata, and semantic section addresses;
- literal UGLUT2 binary16 parsing plus UGTRV1 SplitMix64 seed lineage and exact
  Q16/Q30 traversal regeneration (the pixel permutation is not stored);
- UGRICE1 RAW, signed modulo-256 Rice, and normalized static byte-rANS decode;
- predictor 13 Cartesian MED plus reversible green-luma lift;
- predictor 14 Cartesian MED plus exact q709 `[Y,Cb,Cr]` codeword inverse;
- predictor 11 temporal/substrate MED plus exact Cartesian scatter;
- per-frame polar/Cartesian hashes and the final decoded RGB8/PTS stream hash.

The generated host fixture covers predictors 13, 11, and 14. The Release binary
also independently verified the authored full-raster artifacts; measured sizes,
hashes, and timing belong in their external validation receipts rather than as
hard-coded format claims here.

Current boundaries:

- this is a decoder/oracle, not yet an Android camera encoder or Grove scene
  player integration;
- predictors 10 and 12 are not implemented because the verified authored files
  use 11, 13, and 14;
- UGRICE structural/hash/table canonicality is checked, but the C++ reader does
  not yet re-run the encoder's byte-smallest RAW/Rice/rANS choice as a second
  canonicality oracle;
- the host oracle currently owns the complete file in RAM. A phone production
  reader should replace that storage adapter with bounded file/asset mapping;
- it reconstructs the exact accepted RGB8 observations and timestamps. It does
  not infer unobserved geometry or turn the seed alone into video evidence.

Regenerate and run the fixture from the repository root:

```powershell
$env:PYTHONPATH='src'
python native/host_tests/fixtures/generate_ugtc4d_native_fixture.py
cmake -S native/host_tests -B build/native-ugtc4d-decoder
cmake --build build/native-ugtc4d-decoder --config Release --target ugtc4d_decoder_tests
build/native-ugtc4d-decoder/Release/ugtc4d_decoder_tests.exe
```
