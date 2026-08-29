# Architecture

```text
Camera2 YUV + IMU
        |
        v
bounded luma analysis -> FAST/BRIEF -> matching -> visual-inertial proposal
        |                                      |
        |                                      v
        |                             typed SpatialProposal
        |                                      |
        v                                      v
FrameEvidence ----------------------> eight-gate verifier
                                               |
                                  accepted only|rejected with reason
                                               v
                                    keyframe/map mutation
                                               |
                                               v
                         ordered ledger + pre/post state hashes
                                               |
                                               v
                     KSEED 4.1 chunks + CRC32 + SHA-256 chain
```

The native arm64 module is a narrow deterministic seed/CRC accelerator. It does not mutate the map. Java remains the behavioral oracle and fallback. Camera callbacks, sensor adapters and future models only propose; `ProposalVerifier` and `SlamEngine` own authoritative commits.
