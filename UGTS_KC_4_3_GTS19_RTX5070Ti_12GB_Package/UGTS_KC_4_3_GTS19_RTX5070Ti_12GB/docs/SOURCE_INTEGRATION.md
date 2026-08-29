# UGTS source integration register

Version 4.3 is an additive game-theoretic specialization. The following
project artifacts are treated as its conceptual lineage:

| Project artifact | Role in this package |
|---|---|
| UGTS-KC 2.0 Expanded Substrate | query/state/event discipline and explicit lineage |
| UGTS-KC Two Hands 3.0 | deterministic proposal, guard, and atomic commit ordering |
| UGTS-KC 3.6 | content-addressed definitions and replay identity |
| UGTS-KC 3.6.2 SCLP | finite packing, guard discipline, and failure boundaries |
| UGTS-KC Elizabeth Vector Game Runtime 3.9 | deterministic game runtime and self-contained interaction model |
| GPU-Native Addendum | compact-state GPU execution and evidence boundaries |
| UGTS-KC 4.2 General Operator Order Addendum | explicit operator/order serialization |
| UGTS-KC 4.2 Go Solver | prior rules engine, exact mini-board solver, certificates, and test baseline |
| UGTS Versioning Charter Phase 1 | chronology and additive-version intent |

The 4.3 game transition is expressed in the UGTS sequence:

```text
state support
-> legal-action query
-> candidate proposal
-> occupancy/topology guards
-> capture closure
-> own-liberty guard
-> repetition guard
-> atomic commit
-> content witness
-> proof update
```

Wallet-specific SARA behavior and unrelated spatial-scanning profiles are not
part of the Go semantics.
