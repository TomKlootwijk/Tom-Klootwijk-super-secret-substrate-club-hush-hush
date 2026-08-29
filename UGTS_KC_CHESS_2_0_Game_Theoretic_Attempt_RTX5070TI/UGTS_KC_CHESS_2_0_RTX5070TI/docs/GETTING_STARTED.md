# Getting started

The Python reference requires Python 3.11 or newer. The host C++ build requires CMake 3.24+, Ninja and a C++20 compiler. CUDA is optional.

## Run all host gates

```bash
bash scripts/build_host.sh
```

This compiles both native executables, runs three CTest checks and then runs the Python suite with the packed C++ move batch enabled.

## Inspect the exact root campaign

```bash
PYTHONPATH=src python -m ugts_chess campaign-status examples/campaign/initial.sqlite3
PYTHONPATH=src python -m ugts_chess campaign-verify examples/campaign/initial.sqlite3
```

The expected status is twenty unresolved obligations and root value `unknown`.

## Validate and count legal paths

```bash
PYTHONPATH=src python -m ugts_chess validate --fen "<FEN>"
PYTHONPATH=src python -m ugts_chess perft --fen "<FEN>" --depth 4 --divide
```

## Bounded proof search

```bash
PYTHONPATH=src python -m ugts_chess bounded-wdl --fen "<FEN>" --plies 5 --out result.json
PYTHONPATH=src python -m ugts_chess verify-wdl result.json
```

A cutoff stays `unknown`. A current or intended-move draw claim is represented as an action, not an automatic terminal.

## Forced mate and exact three-piece tables

```bash
PYTHONPATH=src python -m ugts_chess prove-mate --fen "<FEN>" --plies 7 --out proof.json
PYTHONPATH=src python -m ugts_chess verify-proof proof.json
PYTHONPATH=src python -m ugts_chess probe --fen "<KQK-or-KRK-FEN>"
```

## RTX 5070 Ti Laptop handoff

Use `docs/CODEX_HANDOFF.md` and `scripts/build_rtx5070ti.ps1`. Runtime device inspection is mandatory before enabling the 9 GiB starting solver budget.
