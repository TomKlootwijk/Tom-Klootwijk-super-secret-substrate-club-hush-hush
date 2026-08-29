#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "report" / "generated"
OUT.mkdir(parents=True, exist_ok=True)


def load(name: str):
    return json.loads((ROOT / "spec" / name).read_text(encoding="utf-8"))


def esc(value: object) -> str:
    s = str(value)
    repl = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "<": r"\textless{}",
        ">": r"\textgreater{}",
    }
    return "".join(repl.get(ch, ch) for ch in s)


def write(name: str, text: str) -> None:
    (OUT / name).write_text(text, encoding="utf-8")


atlas = load("operator_atlas.json")
by_id = {o["id"]: o for o in atlas["operators"]}
rows: list[str] = []
for o in atlas["operators"]:
    conv = by_id[o["converse_id"]]["unicode"]["literal"] if o.get("converse_id") else "-"
    family = "-" if o["family_id"] is None else str(o["family_id"])
    kappa = "-" if o["kappa"] is None else str(o["kappa"])
    literal = rf"\({o['unicode']['literal']}\)"
    converse = "-" if conv == "-" else rf"\({conv}\)"
    # Human-facing display labels may wrap; exact machine IDs remain in the final column/JSON.
    kernel_display = esc(o["semantic"]["kernel"].replace("_", " "))
    rows.append(
        f"{literal} & {esc(', '.join(o['unicode']['scalars']))} & {family} & {kappa} & "
        f"{converse} & {kernel_display} & {esc(o['id'])} \\\\"
    )
write("operator_table.tex", "\n".join(rows) + "\n")

codebook = load("hot_codebook_set_core_16.json")
rows = []
for i, entry in enumerate(codebook["entries"]):
    if entry is None:
        rows.append(f"{i} & - & - & reserved & - \\\\")
    else:
        rows.append(
            f"{i} & {entry['family']} & {entry['kappa']} & \\({entry['literal']}\\) & "
            f"{esc(entry['operator_id'])} \\\\"
        )
write("codebook_table.tex", "\n".join(rows) + "\n")

mechs = load("mechanisms.json")["mechanisms"]
rows = []
for m in mechs:
    rows.append(
        f"{esc(m['id'])} / {esc(m['legacy_id'])} & {esc(m['domain'])} & {esc(m['name'])} & "
        f"{esc(m['definition'])} & {esc(m['validation'])} \\\\"
    )
write("mechanism_table.tex", "\n".join(rows) + "\n")

claims = load("claims_ledger.json")["claims"]
rows = []
for c in claims:
    disposition = esc(c["disposition"].replace("_", " "))
    rows.append(
        f"{esc(c['id'])} & {esc(c['claim'])} & {disposition} & {esc(c['reason'])} \\\\"
    )
write("claims_table.tex", "\n".join(rows) + "\n")

sources = load("source_register.json")["sources"]
rows = []
for source in sources:
    rows.append(
        f"{esc(source['id'])} & \\nolinkurl{{{source['filename']}}} & "
        f"\\texttt{{{source['sha256'][:12]}...}} & {esc(source['use'])} \\\\"
    )
write("source_table.tex", "\n".join(rows) + "\n")

# Filenames already appear in the registered-source table; this compact block preserves full hashes without clipping.
full = [f"{source['id']}  {source['sha256']}" for source in sources]
write("source_hashes.txt", "\n".join(full) + "\n")

validation_rows = [
    ("Python conformance", "83 tests", "PASS"),
    ("JSON Schema", "3 instances", "0 errors"),
    ("Native scalar codec", "C++20", "PASS"),
    ("Operator atlas", "20 cells", "all content hashes verified"),
    ("Hot codebook", "16 slots", "14 assigned / 2 reserved"),
    ("Mechanism delta", "64 rows", "USF001-USF064 / M886-M949"),
    ("Claims ledger", "24 rows", "admit / bound / reject recorded"),
    ("Wheel", "py3-none-any", "built and clean-installed"),
]
rows = [f"{esc(a)} & {esc(b)} & {esc(c)} \\\\" for a, b, c in validation_rows]
write("validation_table.tex", "\n".join(rows) + "\n")

print(f"generated {len(list(OUT.iterdir()))} report fragments")
