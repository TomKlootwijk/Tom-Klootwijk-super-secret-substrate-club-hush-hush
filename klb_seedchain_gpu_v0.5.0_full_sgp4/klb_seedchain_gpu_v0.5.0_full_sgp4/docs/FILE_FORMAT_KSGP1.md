# KSGP1 compact full-SGP4 seed container

## Purpose

KSGP1 stores source mean elements, stable identity, string metadata, and a
hash-linked time-tile chain. It does **not** store the large initialized SGP4
coefficient record or dense positions. Those are deterministically compiled or
reconstructed at load/query time.

```text
256-byte KSGP1 header
N × 128-byte mean-element seed records
M × 64-byte hash-linked timeline nodes
UTF-8 NUL-terminated string table
```

All current files are little-endian.

## Header

The `Sgp4HeaderDisk` structure is exactly 256 bytes. Important fields include:

```text
magic/version
flags and record widths
seed and node counts/offsets
string-table offset and size
source byte count and source FNV-1a64
payload and terminal chain hashes
reference Unix time and Julian date
timeline start, step, duration, and sample count
source format and gravity model
default elevation mask and DUT1
source label
```

The full-model flag is mandatory for this release. The reference frame flag
records TEME output.

## Mean-element seed

Each `Sgp4SeedDisk` is 128 bytes and stores:

```text
NORAD ID and deterministic lineage seed
name and international-designator string offsets
element-set and revolution numbers
PRN, route sector, classification, and ephemeris type
epoch Julian date and Unix seconds
BSTAR
mean-motion first and second derivatives
inclination
RAAN
eccentricity
argument of perigee
mean anomaly
mean motion
```

The floating fields are binary64. This is a compact source-state record, not a
quantized position record. The initialized `Sgp4Record` is currently about 1.4
KiB per object and is generated in host memory before GPU upload.

## Timeline node

Each `Sgp4TimelineNodeDisk` is 64 bytes and contains:

```text
parent and node index
flags and chain seed
start and duration in seconds
parent, self, and source hashes
sample begin/count metadata
```

Nodes bound the declared query horizon and provide deterministic lineage and
integrity. They do not represent numerical integration checkpoints; SGP4 state
is evaluated directly from initialized coefficients and requested time.

## Hashes

The payload, node, and terminal-chain hashes use FNV-1a 64-bit. They detect
accidental corruption and enforce deterministic parent links. They are not
cryptographic signatures and do not prove authorship or authenticity.

## Reconstruction

```text
KSGP1 mean-element seed
→ full SGP4/SDP4 initialization
→ initialized coefficient record
→ query time in minutes from object epoch
→ TEME position and velocity
→ optional GMST+DUT1 TEME-to-PEF conversion
→ support/compatibility/guard/event/lineage query
```

## Compression accounting

The included 32-object file is 5,793 bytes. A declared seven-day, one-second
`float4` position timeline would occupy 309,658,112 bytes, giving a
horizon-relative ratio of about 53,453.84×. A position-plus-velocity timeline
would occupy 928,974,336 bytes, giving about 160,361.53×.

These are model-based avoided-materialization ratios, not claims that an
existing dense file was losslessly compressed. Correctness depends on the source
mean elements, the full propagator, the frame conversion, and the event margin.
