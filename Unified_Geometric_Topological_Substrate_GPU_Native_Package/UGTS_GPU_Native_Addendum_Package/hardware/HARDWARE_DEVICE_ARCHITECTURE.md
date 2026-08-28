# UGTS-GN 1.1 Physical Device Architecture

## Target boundary

The hardware target is a headless support-compatibility-guard-commit datapath. It is not a game-engine adapter and it does not require a frame loop. A GPU, FPGA, ASIC, or optofluidic endpoint may implement the same typed semantics while using different numeric representations.

## Functional pipeline

```text
state stream / SRAM
  -> position norm and support-axis dot product
  -> radial + angular support gate
  -> sheet/orientation/mode compatibility gate
  -> relation/guard evaluator with hysteresis
  -> confidence or SNR gate
  -> route + lineage update
  -> verified-event FIFO / DMA / actuator command
```

### GPU-native profile

- Compute ABI: G64/E32 or packed G32/E16.
- Dispatch format: SPIR-V 1.4 compute, local size 256.
- Descriptor set 0: binding 0 state, binding 1 event, binding 2 counters.
- Evaluate mode is independent per invocation.
- Commit mode adds global counters and therefore incurs atomic contention.
- Production event capture should compact verified events with subgroup ballots/prefix sums instead of retaining dense non-events.

### FPGA/ASIC profile

The bundled `rtl/ugts_gate_q16_16.sv` is a reference front-end gate using Q16.16 position and normalized-axis components. It avoids square roots:

- radial support compares `x^2+y^2+z^2 <= R^2`;
- angular support requires `dot >= 0` and `dot^2 >= cos^2(alpha) * r^2`;
- compatibility compares the mode mask, sheet and orientation;
- the guard is expressed in squared-distance units using a precomputed band;
- a verified event is emitted when all gates are true.

The squared guard differs from the floating SDF guard. To approximate a radial SDF band `|r-R| <= epsilon`, program `guard_sq = 2*R*epsilon + epsilon^2` in matching fixed-point units and verify the remaining error over the target range.

### Optofluidic/waveguide profile

```text
radial-angular optical input
  -> liquid lens/overclad tuning
  -> mode-overlap coupling
  -> guided phase/interference
  -> wavelength/polarization/mode/time compatibility
  -> balanced detector guard crossing
  -> digital event latch, confidence, lineage, log
```

Maxwell, coupled-mode theory and fluid mechanics remain the physical models. The substrate contributes support, compatibility, event semantics, lineage and measurement discipline.

## Clocking and buffering

For a streaming digital device, use valid/ready handshakes between pipeline stages. The event FIFO must absorb burst yield at the maximum admitted event density. A conservative depth bound is:

```text
FIFO_depth >= peak_input_rate * maximum_backpressure_time * peak_event_yield
```

Add margin for clock-domain crossing and DMA service jitter. Overflow is a measured error condition; it must not be silently dropped.

## Precision contract

Every hardware profile declares:

- numeric format and range;
- axis-normalization tolerance;
- maximum radial and angular quantization error;
- relation/guard margin;
- confidence/SNR calibration;
- overflow/saturation behavior;
- latency in cycles and seconds;
- false accept, false reject and missed-event limits.

Use G64 float32 vectors as the golden oracle. The packed or fixed-point profile is accepted only when every discrepancy is inside the declared guard/error budget.

## Physical measurements

Report verified events per second, events per joule, support and compatibility rejection gains, median/tail event latency, false and missed-event probability, drift, calibration interval and full memory/buffer footprint. For optical devices also report insertion loss, mode overlap, detector noise, actuator settling and thermal dependence.
