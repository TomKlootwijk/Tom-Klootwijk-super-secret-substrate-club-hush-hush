from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report"


def esc(value: object) -> str:
    s = str(value)
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        s = s.replace(old, new)
    return s


def operator_table() -> None:
    rows = json.loads((ROOT / "spec" / "sara_3_6_3_delta_operator_catalog.json").read_text(encoding="utf-8"))
    out = [
        r"\setlength{\tabcolsep}{3pt}\begin{longtable}{@{}p{0.17\linewidth} p{0.09\linewidth} p{0.15\linewidth} p{0.32\linewidth} p{0.10\linewidth} p{0.08\linewidth}@{}}",
        r"\toprule",
        r"\textbf{ID} & \textbf{Domain} & \textbf{Name} & \textbf{Formal definition} & \textbf{Disposition} & \textbf{Validation}\\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"\textbf{ID} & \textbf{Domain} & \textbf{Name} & \textbf{Formal definition} & \textbf{Disposition} & \textbf{Validation}\\",
        r"\midrule",
        r"\endhead",
    ]
    for row in rows:
        out.append(
            "{} & {} & {} & {} & {} & {}\\\\\n\\addlinespace[1.5pt]".format(
                esc(row["id"]), esc(row["domain"]), esc(row["name"]),
                esc(row["formal_definition"]), esc(row["disposition"]), esc(row["validation"])
            )
        )
    out.extend([r"\bottomrule", r"\end{longtable}"])
    (REPORT / "sara363_operator_catalog_table.tex").write_text("\n".join(out), encoding="utf-8")


def claims_table() -> None:
    rows = json.loads((ROOT / "spec" / "sara_3_6_3_claims_ledger.json").read_text(encoding="utf-8"))
    out = [
        r"\setlength{\tabcolsep}{3pt}\begin{longtable}{@{}p{0.09\linewidth} p{0.33\linewidth} p{0.09\linewidth} p{0.40\linewidth}@{}}",
        r"\toprule",
        r"\textbf{ID} & \textbf{Claim} & \textbf{Disposition} & \textbf{Technical note}\\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"\textbf{ID} & \textbf{Claim} & \textbf{Disposition} & \textbf{Technical note}\\",
        r"\midrule",
        r"\endhead",
    ]
    for row in rows:
        out.append(
            "{} & {} & {} & {}\\\\\n\\addlinespace[1.5pt]".format(
                esc(row["id"]), esc(row["claim"]), esc(row["disposition"]), esc(row["technical_note"])
            )
        )
    out.extend([r"\bottomrule", r"\end{longtable}"])
    (REPORT / "sara363_claims_ledger_table.tex").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    operator_table()
    claims_table()
    print("generated SARA 3.6.3 TeX tables")
