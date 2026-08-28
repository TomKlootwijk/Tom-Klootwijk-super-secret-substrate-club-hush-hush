from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report"
ROW_END = r" \\"  # LaTeX row terminator preceded by one space


def esc(text: str) -> str:
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
    }
    return "".join(repl.get(ch, ch) for ch in text)


with (ROOT / "spec" / "operator_catalog_3_6.csv").open(encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
lines = [
    r"\begin{longtable}{>{\raggedright\arraybackslash}p{1.0cm}>{\raggedright\arraybackslash}p{2.4cm}>{\raggedright\arraybackslash}p{3.2cm}>{\raggedright\arraybackslash}p{7.1cm}>{\raggedright\arraybackslash}p{2.3cm}}",
    r"\toprule",
    r"\textbf{ID} & \textbf{Domain} & \textbf{Mechanism} & \textbf{Normalized technical definition} & \textbf{Disposition / validation} \\",
    r"\midrule",
    r"\endfirsthead",
    r"\toprule",
    r"\textbf{ID} & \textbf{Domain} & \textbf{Mechanism} & \textbf{Normalized technical definition} & \textbf{Disposition / validation} \\",
    r"\midrule",
    r"\endhead",
]
for row in rows:
    lines.append(
        " & ".join(
            [
                esc(row["id"]),
                esc(row["domain"]),
                esc(row["name"]),
                esc(row["definition"]),
                f"{esc(row['disposition'])} / {esc(row['validation'])}",
            ]
        )
        + ROW_END
    )
    lines.append(r"\addlinespace[1.5pt]")
lines += [r"\bottomrule", r"\end{longtable}"]
(REPORT / "operator_catalog_table.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

with (ROOT / "spec" / "pattern_recipes_3_6.csv").open(encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
lines = [
    r"\begin{longtable}{>{\raggedright\arraybackslash}p{1.1cm}>{\raggedright\arraybackslash}p{3.5cm}>{\raggedright\arraybackslash}p{4.2cm}>{\raggedright\arraybackslash}p{7.2cm}}",
    r"\toprule",
    r"\textbf{ID} & \textbf{Pattern} & \textbf{Pipeline} & \textbf{Rule} \\",
    r"\midrule",
    r"\endfirsthead",
    r"\toprule",
    r"\textbf{ID} & \textbf{Pattern} & \textbf{Pipeline} & \textbf{Rule} \\",
    r"\midrule",
    r"\endhead",
]
for row in rows:
    lines.append(" & ".join(esc(row[key]) for key in ("id", "name", "pipeline", "rule")) + ROW_END)
    lines.append(r"\addlinespace[1.5pt]")
lines += [r"\bottomrule", r"\end{longtable}"]
(REPORT / "pattern_recipes_table.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

# Selected lexicon examples kept readable in the report; the full 0..99 table is in data/.
selected = [0, 1, 2, 7, 9, 10, 11, 12, 13, 17, 18, 19, 20, 21, 23, 27, 30, 42, 70, 99]
with (ROOT / "data" / "dutch_numbers_0_99.csv").open(encoding="utf-8") as handle:
    by_value = {int(row["value"]): row for row in csv.DictReader(handle)}
lines = [
    r"\begin{longtable}{r>{\raggedright\arraybackslash}p{3.0cm}>{\raggedright\arraybackslash}p{3.4cm}>{\raggedright\arraybackslash}p{2.7cm}>{\raggedright\arraybackslash}p{3.0cm}rr}",
    r"\toprule",
    r"\textbf{n} & \textbf{Orthography} & \textbf{Profile segments} & \textbf{Place order} & \textbf{Spoken order} & \textbf{syll.} & \textbf{pop} \\",
    r"\midrule",
    r"\endfirsthead",
    r"\toprule",
    r"\textbf{n} & \textbf{Orthography} & \textbf{Profile segments} & \textbf{Place order} & \textbf{Spoken order} & \textbf{syll.} & \textbf{pop} \\",
    r"\midrule",
    r"\endhead",
]
for value in selected:
    row = by_value[value]
    cells = [
        str(value),
        esc(row["orthography"]),
        esc(row["pronunciation_segments"]),
        esc(row["place_order"]),
        esc(row["spoken_order"]),
        row["syllable_count"],
        row["popcount"],
    ]
    lines.append(" & ".join(cells) + ROW_END)
lines += [r"\bottomrule", r"\end{longtable}"]
(REPORT / "lexicon_examples_table.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

print("generated report table inputs")
