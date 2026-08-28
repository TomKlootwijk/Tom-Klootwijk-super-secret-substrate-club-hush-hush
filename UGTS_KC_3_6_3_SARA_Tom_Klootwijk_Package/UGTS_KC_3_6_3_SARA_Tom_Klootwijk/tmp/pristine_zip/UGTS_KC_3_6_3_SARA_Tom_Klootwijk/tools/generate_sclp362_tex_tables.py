#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report"


def esc(value: object) -> str:
    text = str(value)
    replacements = {
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
    return "".join(replacements.get(ch, ch) for ch in text)


def operator_table() -> str:
    rows = json.loads((ROOT / "spec/sclp_3_6_2_delta_operator_catalog.json").read_text())
    out = [
        r"\begin{landscape}",
        r"\scriptsize",
        r"\setlength{\tabcolsep}{2.5pt}",
        r"\renewcommand{\arraystretch}{1.14}",
        r"\begin{longtable}{p{0.19\linewidth} p{0.08\linewidth} p{0.15\linewidth} p{0.37\linewidth} p{0.10\linewidth} p{0.07\linewidth}}",
        r"\caption{Complete 50-operator SCLP 3.6.2 delta catalog.}\label{tab:sclp-ops}\\",
        r"\toprule",
        r"\textbf{Operator ID} & \textbf{Domain} & \textbf{Mechanism} & \textbf{Normalized technical definition} & \textbf{Disposition} & \textbf{Source}\\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"\textbf{Operator ID} & \textbf{Domain} & \textbf{Mechanism} & \textbf{Normalized technical definition} & \textbf{Disposition} & \textbf{Source}\\",
        r"\midrule",
        r"\endhead",
    ]
    for row in rows:
        out.append(
            "{} & {} & {} & {} & {} & {}\\\\".format(
                r"\texttt{" + esc(row["operator_id"]) + "}",
                esc(row["domain"]),
                esc(row["mechanism"]),
                esc(row["formal_definition"]),
                esc(row["disposition"]),
                esc(row["source_scope"]),
            )
        )
    out.extend([r"\bottomrule", r"\end{longtable}", r"\end{landscape}"])
    return "\n".join(out) + "\n"


def claims_table() -> str:
    rows = json.loads((ROOT / "spec/sclp_3_6_2_claims_ledger.json").read_text())
    out = [
        r"\small",
        r"\setlength{\tabcolsep}{3.5pt}",
        r"\renewcommand{\arraystretch}{1.16}",
        r"\begin{longtable}{p{0.08\linewidth} p{0.28\linewidth} p{0.11\linewidth} p{0.47\linewidth}}",
        r"\caption{SCLP 3.6.2 claims ledger.}\label{tab:sclp-claims}\\",
        r"\toprule",
        r"\textbf{ID} & \textbf{Source claim or motif} & \textbf{Disposition} & \textbf{Technical boundary}\\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"\textbf{ID} & \textbf{Source claim or motif} & \textbf{Disposition} & \textbf{Technical boundary}\\",
        r"\midrule",
        r"\endhead",
    ]
    for row in rows:
        out.append("{} & {} & {} & {}\\\\".format(
            esc(row["claim_id"]), esc(row["source_claim_or_motif"]), esc(row["disposition"]), esc(row["technical_boundary"])
        ))
    out.extend([r"\bottomrule", r"\end{longtable}"])
    return "\n".join(out) + "\n"


def key_table() -> str:
    rows = json.loads((ROOT / "data/sclp362_key_layout.json").read_text())
    out = [
        r"\begin{table}[H]",
        r"\centering",
        r"\small",
        r"\begin{tabularx}{0.96\textwidth}{lrrlX}",
        r"\toprule",
        r"\textbf{Field} & \textbf{Bits} & \textbf{States} & \textbf{Contiguous range} & \textbf{Quantization}\\",
        r"\midrule",
    ]
    for row in rows:
        step = row["step"]
        if isinstance(step, float):
            step_s = f"{step:.12g}"
        else:
            step_s = str(step)
        out.append(f"{esc(row['field'])} & {row['bits']} & {row['states']:,} & {esc(row['contiguous_range'])} & {esc(row['range'])}; step {esc(step_s)}\\\\")
    out.extend([r"\bottomrule", r"\end{tabularx}", r"\caption{Exact field widths for the 64-bit SCLP key.}", r"\end{table}"])
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    (REPORT / "sclp362_operator_catalog_table.tex").write_text(operator_table(), encoding="utf-8")
    (REPORT / "sclp362_claims_ledger_table.tex").write_text(claims_table(), encoding="utf-8")
    (REPORT / "sclp362_key_layout_table.tex").write_text(key_table(), encoding="utf-8")
    print("generated SCLP TeX tables")
