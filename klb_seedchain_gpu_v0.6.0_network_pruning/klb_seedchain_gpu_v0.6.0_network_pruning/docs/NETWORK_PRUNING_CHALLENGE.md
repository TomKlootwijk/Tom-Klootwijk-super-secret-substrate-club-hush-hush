# Mixed-orbit network pruning challenge

## Purpose

Version 0.6.0 tests the part of the UGTS query path that the one-station GPS
workload barely exercised: **support rejection and typed compatibility rejection
before the expensive relation/guard evaluation**.

The workload deliberately combines different orbital regimes and different
station policies:

```text
58 SGP4 seeds
  32 GPS operational records
  26 records from the CelesTrak TDRSS group

16 benchmark station profiles
  navigation
  relay
  Earth observation
  science
  crewed/research

7 days at 60-second event sampling
```

The station entries are benchmark policies, not operator authorizations or
claims that these exact sites provide the listed services.

## Query order

For each object-station relation, the implementation uses:

```text
1. support envelope
2. orbit/service/route compatibility
3. full SGP4 state reconstruction
4. TEME-to-PEF ground geometry
5. elevation guard
6. AOS/LOS transition
7. route and lineage output
```

The static plan is conservative. A pair excluded by the support envelope cannot
meet the declared maximum slant range under the object's orbit envelope. The
runtime guard remains authoritative; the planner is only a broad-phase filter.

## Orbit and service typing

Objects are classified into one of four benchmark orbit classes from the
initialized SGP4 record:

```text
LEO  low-period Earth orbit
MEO  medium-period orbit, including GPS
GEO  near-synchronous, low-eccentricity orbit
HEO  long-period/high-eccentricity orbit
```

Service masks are inferred from stable source labels for this benchmark:

```text
NAV        GPS records
RELAY      TDRS records
EARTH_OBS  selected low-Earth observation records
SCIENCE    science/research missions
CREWED     ISS-related profile
```

This classification is a versioned benchmark schema. It is not a general
satellite mission registry.

## Three relation sets

The CPU oracle evaluates the same physical query under three masks:

| Mode | Pair set | Role |
|---|---:|---|
| `all` | every object × every station | correctness baseline |
| `support` | statically support-possible pairs | broad-phase test |
| `active` | support plus policy-compatible pairs | full pruning test |

All three modes must produce the same retained event identities for relations
that are valid under the active policy. The support and active modes must not
lose an event that the all-pairs oracle would have retained.

## Included plan

```text
Objects                         58
Stations                        16
All object-station pairs       928
Support-possible pairs         711
Policy-compatible pairs        438
Support rejection gain         1.305204x
Compatibility gain             1.623288x
Total relation reduction       2.118721x
Orbit classes                  LEO=11, MEO=32, GEO=8, HEO=7
```

The complete audited pair table is:

```text
data/network/mixed_network_pair_plan.csv
```

It records object identity, orbit class, service mask, station policy, route,
support decision, and active decision for all 928 relations.

## CPU reference result

For 10,080 one-minute intervals over seven days:

| Mode | Logical relation intervals | Events | CPU elapsed |
|---|---:|---:|---:|
| all | 9,354,240 | 9,335 | 0.940492 s |
| support | 7,166,880 | 9,335 | 0.832536 s |
| active | 4,415,040 | 9,335 | 0.700357 s |

Acceptance results:

```text
all/support event identity      PASS
all/active event identity       PASS
support survivor equality       PASS
active compatible equality      PASS
propagation failures            0
all/active CPU time ratio        1.342875x
relation work reduction          2.118721x
```

CPU time is environment-specific. Event identity and relation counts are the
portable validation result.

## CUDA benchmark modes

`klb_network_bench` contains five principal paths:

```text
pair_all
  one thread chunk per unpruned object-station pair

pair_support
  one thread chunk per support-possible pair

pair_active
  one thread chunk per support+compatibility pair

grouped_all
  propagate each object/time state once, then evaluate all stations

grouped_active
  propagate each object/time state once, then evaluate only active stations
```

A sixth path materializes dense `double4` PEF states and queries the active
relations. This separates:

```text
seed reconstruction cost
relation-expansion cost
dense materialization cost
resident dense-query cost
```

The key comparison is not simply compressed versus dense. It is:

```text
pair-expanded direct query
vs grouped direct query
vs materialize-once + dense query
```

That reveals whether the query-first substrate benefits from relation pruning
and reuse of one reconstructed state across many relations.

## GPU acceptance criteria

The RTX run is accepted only when:

```text
pair-all GPU events equal CPU all-pairs events
pair-active GPU events equal CPU active events
pair-active and grouped-active events match
pair-active and grouped-active counters match
grouped-active and dense-active events match when dense validation is enabled
grouped-active and dense-active counters match
propagation failures are zero
event buffer is not truncated
```

Performance claims are secondary to those checks.

## Expected interpretation

A successful result would demonstrate that:

1. compact SGP4 seeds remain useful across a mixed orbit catalog;
2. typed station policies remove relations before guard solving;
3. grouped reconstruction avoids repeating SGP4 once per station;
4. event output remains identical to the unpruned oracle;
5. the direct path can be compared honestly with materialized dense state.

A failed result is also useful. If pruning overhead, divergence, register
pressure, or repeated relation logic erases the saved work, the workload meets
a declared kill criterion rather than supporting a performance claim.
