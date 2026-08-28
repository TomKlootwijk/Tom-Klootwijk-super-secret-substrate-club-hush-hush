# Measurement and Acceptance Plan

## Digital targets

1. Build the exact source and record compiler/tool versions and hashes.
2. Record device name, type, driver, API version, clocks/power mode and thermal state.
3. Validate SPIR-V entry point, descriptor ABI and local size.
4. Run deterministic candidate vectors and compare all counters plus at least 4096 event records with the CPU oracle.
5. Measure cold pipeline compilation, cache-seeded pipeline hydration and native program footprint.
6. Measure device and host p50/p95/p99 latency for multiple batch sizes.
7. Report CER, SET, ESB, SRG, CRG, EY, SCR, ECR, SNC, CCF and PCP.
8. Measure actual board/package power for events per joule. Software-reported power is supplementary.
9. Stress event yield and FIFO/DMA backpressure; report overflow behavior.
10. Sweep precision and guard width; report false accept/reject against G64.

## Physical optical targets

1. Pre-register wavelength, input sector, polarization/mode set, threshold, uncertainty, energy boundary and electronic baseline.
2. Measure insertion loss and spherical-to-mode overlap.
3. Sweep liquid actuation and record tuning range, hysteresis, settling time and cycle life.
4. Drive known threshold crossings and measure B.C.E. timestamps, misses, false events and ordering.
5. Cycle temperature and duration to obtain drift and recalibration interval.
6. Include laser, actuator, detector, ADC/control and calibration energy.
7. Terminate the claim if a conventional electronic path is cheaper, faster or more accurate at equal error.

## Kill criteria

Redesign or stop when pruning is weak, event/branch density explodes, numeric error exceeds guard margin, global atomics dominate, event FIFO overflows at required yield, calibration cost erases the advantage, physical false/missed-event limits fail, or the control sidecar performs nearly all useful work.
