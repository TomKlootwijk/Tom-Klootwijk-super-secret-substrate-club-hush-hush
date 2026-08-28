# UGTS-KC 2.0 state and event extension

The baseline typed state is extended without collapsing fields:

```text
q = (position, time, phase, sheet, orientation,
     generative_address, branch, policy, uncertainty,
     linear_velocity, angular_velocity,
     curvature, torsion, mode, dynamic_state)
```

Pattern instances are immutable parameter records. Dynamic state is attached only when a pattern is animated or physically modeled. A valid event remains gated by support, compatibility, guard status and confidence.

```text
verified = in_support
           and compatible
           and guard_crossed_or_touched_under_policy
           and confidence >= floor
           and degeneracy_status in accepted_statuses
```

Equal-time events are resolved by:

1. certified time intervals,
2. explicit priority,
3. commutative patch merge when fields are disjoint or values agree,
4. conflict event when authoritative fields disagree.
