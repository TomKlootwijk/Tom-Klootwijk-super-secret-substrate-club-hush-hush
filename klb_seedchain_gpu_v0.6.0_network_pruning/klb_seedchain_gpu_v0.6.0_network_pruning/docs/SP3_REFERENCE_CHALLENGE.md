# External SP3 reference challenge

## Why this stage exists

The Vallado vectors and the independent Python SGP4 comparison establish that
the implementation follows the SGP4 model. They do not establish that a public
mean-element snapshot follows the physical satellite with precise-orbit
accuracy.

The next accuracy layer compares the package output with an independent SP3
precise-orbit product. This comparison measures a combined difference from:

```text
SGP4 model limitations
age and quality of the GP/OMM elements
TEME-to-PEF approximation
SP3 terrestrial-frame realization
DUT1 and omitted polar motion/EOP
sampling and identifier matching
```

It is intentionally not reported as pure arithmetic error.

## Included adapter

```text
tools/compare_sp3.py
```

It accepts uncompressed `.sp3` or gzip-compressed `.sp3.gz`, keeps GPS `P`
position records, matches them to KSGP PRNs, runs `klb_sgp4 sample` at every
selected SP3 epoch, and writes per-sample XYZ and norm differences.

The output summary reports:

```text
sample count
epoch count
RMS position difference
median position difference
p95 position difference
maximum position difference
```

## Small manual data requirement

Download one IGS SP3 orbit product covering the epoch of a freshly packed GPS
OMM snapshot. A daily rapid/final product or a 48-hour ultra-rapid product is
normally only a few megabytes compressed; no large observation archive is
required.

The date ranges must overlap. Comparing an old SP3 file with a new OMM snapshot
would mostly measure element age and is not an accepted accuracy test.

## Windows use

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\compare_sp3_windows.ps1 `
  -Sp3File .\external_data\IGS0OPSULT_example.SP3.gz
```

Or call the adapter directly:

```powershell
python .\tools\compare_sp3.py `
  --sp3 .\external_data\orbit.SP3.gz `
  --ksgp .\data\network\celestrak_mixed_58obj_7d_60s.ksgp `
  --klb-sgp4 .\build\Release\klb_sgp4.exe `
  --output .\sp3_comparison.csv `
  --summary .\sp3_comparison.summary.txt
```

## Interpretation bands

No universal pass threshold is hard-coded. Record at least:

```text
SP3 product type and filename
observed or predicted ultra-rapid half
element age at each epoch
DUT1 value
matched PRNs
RMS/p95/max error
whether event order changes at the declared elevation guard
```

The decisive substrate check is event-margin preservation. A large coordinate
difference can be acceptable for a coarse visualization but unacceptable if it
changes AOS/LOS order or crosses the guard outside the application budget.

## Adapter self-test

The package includes a synthetic one-epoch SP3 fixture generated from its own
PEF samples. It tests parsing, PRN matching, command invocation, and CSV output;
it is not an independent orbit-accuracy result.
