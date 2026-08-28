from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "KLB_v0.6.0_Network_Pruning_Verification_ELI5.pdf"

NAVY = HexColor("#0B1736")
INK = HexColor("#192438")
MUTED = HexColor("#5E6B7E")
PAPER = HexColor("#F6F8FC")
LINE = HexColor("#DCE3EE")
CYAN = HexColor("#00A7C4")
CYAN_LIGHT = HexColor("#DDF6FA")
GREEN = HexColor("#14845B")
GREEN_LIGHT = HexColor("#E3F5ED")
ORANGE = HexColor("#D67419")
ORANGE_LIGHT = HexColor("#FFF0DD")
RED = HexColor("#B44747")
RED_LIGHT = HexColor("#FBE7E7")
PURPLE = HexColor("#6E57B5")
PURPLE_LIGHT = HexColor("#EEE9FB")
WHITE = colors.white


def register_fonts() -> None:
    candidates = [
        (
            Path(r"C:\Windows\Fonts\segoeui.ttf"),
            Path(r"C:\Windows\Fonts\segoeuib.ttf"),
            Path(r"C:\Windows\Fonts\segoeuii.ttf"),
        ),
        (
            Path(r"C:\Windows\Fonts\arial.ttf"),
            Path(r"C:\Windows\Fonts\arialbd.ttf"),
            Path(r"C:\Windows\Fonts\ariali.ttf"),
        ),
    ]
    for regular, bold, italic in candidates:
        if regular.exists() and bold.exists() and italic.exists():
            pdfmetrics.registerFont(TTFont("Body", str(regular)))
            pdfmetrics.registerFont(TTFont("Body-Bold", str(bold)))
            pdfmetrics.registerFont(TTFont("Body-Italic", str(italic)))
            return
    raise RuntimeError("No suitable Unicode TrueType font was found")


register_fonts()


class VerificationDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str):
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=16 * mm,
            title="KLB v0.6.0 Network Pruning Verification",
            author="Codex verification run for Tom Klootwijk",
            subject="GPU network pruning correctness, performance, feasibility, physical accuracy, and ELI5 explanation",
        )
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="body",
        )
        self.addPageTemplates(PageTemplate(id="report", frames=[frame], onPage=draw_page))


def draw_page(canvas, doc) -> None:
    width, height = A4
    canvas.saveState()
    if doc.page == 1:
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, width, height, fill=1, stroke=0)
        canvas.setFillColor(CYAN)
        canvas.rect(0, height - 10 * mm, width, 10 * mm, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#15254A"))
        canvas.circle(width - 5 * mm, 23 * mm, 61 * mm, fill=1, stroke=0)
        canvas.setFillColor(CYAN)
        canvas.circle(width - 5 * mm, 23 * mm, 23 * mm, fill=1, stroke=0)
    else:
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - 10 * mm, width, 10 * mm, fill=1, stroke=0)
        canvas.setFont("Body-Bold", 7.1)
        canvas.setFillColor(WHITE)
        canvas.drawString(18 * mm, height - 6.5 * mm, "KLB v0.6.0 / NETWORK PRUNING VERIFICATION")
        canvas.setFont("Body", 7.1)
        canvas.drawRightString(width - 18 * mm, height - 6.5 * mm, "RTX 5070 Ti Laptop / 2026-08-17")
        canvas.setStrokeColor(LINE)
        canvas.line(18 * mm, 12 * mm, width - 18 * mm, 12 * mm)
        canvas.setFont("Body", 7.0)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 7.8 * mm, "Engineering verification; not a GNSS/PNT or operational-flight certification")
        canvas.drawRightString(width - 18 * mm, 7.8 * mm, f"Page {doc.page}")
    canvas.restoreState()


styles = getSampleStyleSheet()
styles.add(ParagraphStyle("TitleWhite", fontName="Body-Bold", fontSize=26, leading=30, textColor=WHITE, spaceAfter=5 * mm))
styles.add(ParagraphStyle("SubtitleWhite", fontName="Body", fontSize=12.2, leading=16.5, textColor=HexColor("#D8E2F5")))
styles.add(ParagraphStyle("Kicker", fontName="Body-Bold", fontSize=8.0, leading=10, textColor=CYAN, spaceAfter=2.2 * mm))
styles.add(ParagraphStyle("H1", fontName="Body-Bold", fontSize=19, leading=23, textColor=NAVY, spaceAfter=3.2 * mm))
styles.add(ParagraphStyle("H2", fontName="Body-Bold", fontSize=11.5, leading=14, textColor=NAVY, spaceBefore=2.4 * mm, spaceAfter=1.8 * mm))
styles.add(ParagraphStyle("Body", fontName="Body", fontSize=9.0, leading=12.7, textColor=INK, spaceAfter=2.4 * mm))
styles.add(ParagraphStyle("BodyTight", fontName="Body", fontSize=8.4, leading=11.4, textColor=INK, spaceAfter=1.6 * mm))
styles.add(ParagraphStyle("Small", fontName="Body", fontSize=7.3, leading=9.6, textColor=MUTED))
styles.add(ParagraphStyle("Cell", fontName="Body", fontSize=7.2, leading=9.2, textColor=INK))
styles.add(ParagraphStyle("CellBold", fontName="Body-Bold", fontSize=7.2, leading=9.2, textColor=INK))
styles.add(ParagraphStyle("CellWhite", fontName="Body-Bold", fontSize=7.2, leading=9.2, textColor=WHITE))
styles.add(ParagraphStyle("Metric", fontName="Body-Bold", fontSize=16, leading=18, textColor=NAVY, alignment=TA_CENTER))
styles.add(ParagraphStyle("MetricLabel", fontName="Body", fontSize=7.0, leading=9.0, textColor=MUTED, alignment=TA_CENTER))
styles.add(ParagraphStyle("Callout", fontName="Body-Bold", fontSize=10, leading=14, textColor=NAVY))
styles.add(ParagraphStyle("CoverSmall", fontName="Body", fontSize=8, leading=10.5, textColor=HexColor("#D8E2F5")))


def P(text: str, style: str = "Body") -> Paragraph:
    return Paragraph(text, styles[style])


def page_head(kicker: str, title: str, intro: str | None = None) -> list:
    out = [P(kicker.upper(), "Kicker"), P(title, "H1")]
    if intro:
        out.append(P(intro, "Body"))
    return out


def callout(text: str, tone: str = "cyan") -> Table:
    palette = {
        "cyan": (CYAN_LIGHT, CYAN),
        "green": (GREEN_LIGHT, GREEN),
        "orange": (ORANGE_LIGHT, ORANGE),
        "red": (RED_LIGHT, RED),
        "purple": (PURPLE_LIGHT, PURPLE),
    }
    fill, stripe = palette[tone]
    table = Table([[P(text, "Callout")]], colWidths=[171 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("BOX", (0, 0), (-1, -1), 0.5, stripe),
        ("LINEBEFORE", (0, 0), (0, -1), 4, stripe),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return table


def metric_cards(items: list[tuple[str, str, str]], columns: int = 4) -> Table:
    cards = []
    for value, label, tone in items:
        fill = {"green": GREEN_LIGHT, "orange": ORANGE_LIGHT, "red": RED_LIGHT, "cyan": CYAN_LIGHT, "purple": PURPLE_LIGHT}.get(tone, PAPER)
        cards.append(Table([[P(value, "Metric")], [P(label, "MetricLabel")]], colWidths=[(169 / columns) * mm], style=[
            ("BACKGROUND", (0, 0), (-1, -1), fill),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
    rows = [cards[i:i + columns] for i in range(0, len(cards), columns)]
    if rows and len(rows[-1]) < columns:
        rows[-1] += [""] * (columns - len(rows[-1]))
    result = Table(rows, colWidths=[(171 / columns) * mm] * columns, hAlign="LEFT")
    result.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return result


def bullets(items: list[str], tone: str = "cyan", tight: bool = False) -> Table:
    dot = {"green": GREEN, "orange": ORANGE, "red": RED, "cyan": CYAN, "purple": PURPLE}.get(tone, CYAN)
    rows = []
    for item in items:
        marker = Drawing(8, 9)
        marker.add(Rect(2, 3, 4, 4, rx=2, ry=2, fillColor=dot, strokeColor=None))
        rows.append([marker, P(item, "BodyTight" if tight else "Body")])
    table = Table(rows, colWidths=[5 * mm, 166 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 if tight else 2.5),
    ]))
    return table


def status_table(rows: list[tuple[str, str, str]], widths: list[float] | None = None) -> Table:
    widths = widths or [42, 35, 94]
    data = [[P("AREA", "CellWhite"), P("RESULT", "CellWhite"), P("WHAT THE EVIDENCE SAYS", "CellWhite")]]
    for area, result, evidence in rows:
        data.append([P(area, "CellBold"), P(result, "CellBold"), P(evidence, "Cell")])
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for index, (_, result, _) in enumerate(rows, start=1):
        fill = GREEN_LIGHT if result.startswith("PASS") else RED_LIGHT if result.startswith("FAIL") else ORANGE_LIGHT
        ink = GREEN if result.startswith("PASS") else RED if result.startswith("FAIL") else ORANGE
        style.extend([("BACKGROUND", (1, index), (1, index), fill), ("TEXTCOLOR", (1, index), (1, index), ink)])
        if index % 2 == 0:
            style.append(("BACKGROUND", (0, index), (0, index), PAPER))
            style.append(("BACKGROUND", (2, index), (2, index), PAPER))
    table.setStyle(TableStyle(style))
    return table


def simple_table(headers: list[str], rows: list[list[str]], widths: list[float], compact: bool = False) -> Table:
    data = [[P(h, "CellWhite") for h in headers]]
    for row in rows:
        data.append([P(str(cell), "Cell") for cell in row])
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5 if compact else 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5 if compact else 5),
    ]
    for index in range(2, len(data), 2):
        style.append(("BACKGROUND", (0, index), (-1, index), PAPER))
    table.setStyle(TableStyle(style))
    return table


def horizontal_bars(labels: list[str], values: list[float], units: str, colors_list: list, width: float = 480, height: float = 165, log_scale: bool = False) -> Drawing:
    drawing = Drawing(width, height)
    left = 94
    right = 58
    top = 12
    row_h = (height - top - 10) / len(labels)
    usable = width - left - right
    transformed = [math.log10(max(v, 1e-12)) if log_scale else v for v in values]
    baseline = min(transformed) if log_scale else 0.0
    maximum = max(transformed)
    span = max(maximum - baseline, 1e-12)
    for i, (label, value, transformed_value, fill) in enumerate(zip(labels, values, transformed, colors_list)):
        y = height - top - (i + 1) * row_h + 5
        drawing.add(String(left - 8, y + 4, label, fontName="Body", fontSize=7.5, fillColor=INK, textAnchor="end"))
        drawing.add(Rect(left, y, usable, 12, fillColor=PAPER, strokeColor=LINE, strokeWidth=0.4))
        ratio = (transformed_value - baseline) / span if log_scale else value / max(values)
        bar_w = max(3, usable * ratio)
        drawing.add(Rect(left, y, bar_w, 12, fillColor=fill, strokeColor=None))
        value_text = f"{value:,.3f} {units}" if value < 1000 else f"{value:,.1f} {units}"
        drawing.add(String(left + usable + 7, y + 3.2, value_text, fontName="Body-Bold", fontSize=7.2, fillColor=NAVY))
    return drawing


def pruning_flow() -> Drawing:
    drawing = Drawing(480, 140)
    boxes = [
        (8, 55, 92, 42, "ALL PAIRS", "928"),
        (132, 55, 92, 42, "SUPPORT", "711"),
        (256, 55, 92, 42, "ACTIVE", "438"),
        (380, 55, 92, 42, "EVENTS", "9,335"),
    ]
    fills = [PAPER, CYAN_LIGHT, PURPLE_LIGHT, GREEN_LIGHT]
    strokes = [MUTED, CYAN, PURPLE, GREEN]
    for (x, y, w, h, title, value), fill, stroke in zip(boxes, fills, strokes):
        drawing.add(Rect(x, y, w, h, rx=5, ry=5, fillColor=fill, strokeColor=stroke, strokeWidth=1))
        drawing.add(String(x + w / 2, y + 26, title, fontName="Body-Bold", fontSize=7.2, fillColor=NAVY, textAnchor="middle"))
        drawing.add(String(x + w / 2, y + 10, value, fontName="Body-Bold", fontSize=14, fillColor=stroke, textAnchor="middle"))
    for x in (104, 228, 352):
        drawing.add(Line(x, 76, x + 22, 76, strokeColor=MUTED, strokeWidth=1.2))
        drawing.add(Polygon([x + 22, 76, x + 16, 80, x + 16, 72], fillColor=MUTED, strokeColor=None))
    drawing.add(String(178, 38, "remove relations that cannot meet range/policy", fontName="Body-Italic", fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
    drawing.add(String(426, 38, "events remain identical", fontName="Body-Italic", fontSize=7.5, fillColor=GREEN, textAnchor="middle"))
    return drawing


def eli5_flow() -> Drawing:
    drawing = Drawing(480, 170)
    boxes = [
        (4, 70, 104, 52, "Recipe cards", "58 compact orbit seeds"),
        (126, 70, 104, 52, "Guest list", "438 allowed links"),
        (248, 70, 104, 52, "Cook once", "propagate each satellite"),
        (370, 70, 104, 52, "Ask stations", "visibility + AOS/LOS"),
    ]
    for idx, (x, y, w, h, title, sub) in enumerate(boxes):
        fill = [CYAN_LIGHT, PURPLE_LIGHT, ORANGE_LIGHT, GREEN_LIGHT][idx]
        stroke = [CYAN, PURPLE, ORANGE, GREEN][idx]
        drawing.add(Rect(x, y, w, h, rx=6, ry=6, fillColor=fill, strokeColor=stroke, strokeWidth=1))
        drawing.add(String(x + w / 2, y + 32, title, fontName="Body-Bold", fontSize=9.0, fillColor=NAVY, textAnchor="middle"))
        drawing.add(String(x + w / 2, y + 15, sub, fontName="Body", fontSize=6.8, fillColor=INK, textAnchor="middle"))
        if idx < len(boxes) - 1:
            drawing.add(Line(x + w + 4, y + h / 2, x + w + 14, y + h / 2, strokeColor=MUTED, strokeWidth=1))
            drawing.add(Polygon([x + w + 14, y + h / 2, x + w + 9, y + h / 2 + 3, x + w + 9, y + h / 2 - 3], fillColor=MUTED, strokeColor=None))
    drawing.add(String(240, 43, "The file stores the recipe, not every future position.", fontName="Body-Bold", fontSize=10.5, fillColor=NAVY, textAnchor="middle"))
    drawing.add(String(240, 25, "Grouped mode calculates one satellite state, then checks all eligible stations.", fontName="Body", fontSize=8.2, fillColor=MUTED, textAnchor="middle"))
    return drawing


def read_json(name: str) -> dict:
    with (ROOT / name).open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def read_perf(name: str) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    with (ROOT / name).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            result[row["mode"]] = {
                "p50": float(row["p50_ms"]),
                "p95": float(row["p95_ms"]),
                "relations": float(row["relation_intervals"]),
                "propagations": float(row["propagated_intervals"]),
                "dense_bytes": float(row["dense_bytes"]),
            }
    return result


coverage = read_json("verification_v060_coverage_summary.json")
performance = read_json("verification_v060_performance_summary.json")
telemetry = read_json("verification_v060_gpu_laptop_telemetry_summary.json")
storage = read_json("verification_v060_storage_summary.json")
file_perf = read_perf("verification_v060_gpu_file_results.csv")
laptop_perf = read_perf("verification_v060_gpu_laptop_results.csv")


def build_story() -> list:
    story: list = []

    # 1 — Cover
    story.extend([
        Spacer(1, 31 * mm),
        P("INDEPENDENT EXECUTION + SOURCE AUDIT", "Kicker"),
        P("KLB v0.6.0<br/>Network Pruning Verification", "TitleWhite"),
        P("Does the compact full-SGP4 GPU approach seriously work—and what does it <i>not</i> prove?", "SubtitleWhite"),
        Spacer(1, 14 * mm),
    ])
    cover_box = Table([[P("CONDITIONALLY VALIDATED", "CellWhite")], [P("Pruning correctness and GPU feasibility: <b>yes</b>. Shipped acceptance gate and precision sat-nav accuracy: <b>no</b>.", "Body")]], colWidths=[122 * mm])
    cover_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ORANGE),
        ("BACKGROUND", (0, 1), (-1, 1), WHITE),
        ("BOX", (0, 0), (-1, -1), 1, ORANGE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([cover_box, Spacer(1, 14 * mm)])
    cover_meta = Table([
        [P("TESTED ON", "CellWhite"), P("SCOPE", "CellWhite")],
        [P("NVIDIA RTX 5070 Ti Laptop<br/>CUDA 12.8 / native sm_120", "CoverSmall"), P("58 objects × 16 stations<br/>7 days / 10,080 60-second intervals", "CoverSmall")],
        [P("REPORT DATE", "CellWhite"), P("PACKAGE", "CellWhite")],
        [P("17 August 2026<br/>Europe/Amsterdam", "CoverSmall"), P("klb_seedchain_gpu_v0.6.0_network_pruning", "CoverSmall")],
    ], colWidths=[61 * mm, 61 * mm])
    cover_meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#15254A")),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#31436B")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.extend([cover_meta, Spacer(1, 12 * mm), P("Prepared from fresh builds, full CPU/GPU runs, independent counter instrumentation, CUDA sanitizers, Nsight Compute, package-integrity checks, and a real IGS SP3 comparison.", "CoverSmall"), PageBreak()])

    # 2 — Verdict
    story.extend(page_head("01 / VERDICT", "The honest answer: it works, with two important boundaries", "The package succeeds at its central engineering idea: reject impossible network relations before doing needless work, while preserving the event set. That is different from saying every shipped acceptance gate passes or that the propagated coordinates are precise enough for GNSS navigation."))
    story.append(metric_cards([
        ("2.1187×", "STATIC RELATION REDUCTION", "green"),
        ("9,335", "EVENT IDENTITIES PRESERVED", "green"),
        ("0", "CUDA SANITIZER ERRORS", "green"),
        ("56.80 km", "REAL-SP3 POSITION RMS", "red"),
    ]))
    story.extend([Spacer(1, 3 * mm), callout("Bottom line: <b>yes</b> for compact SGP4-based network filtering, visibility scheduling and GPU feasibility. <b>No</b> for a clean as-shipped acceptance pass, and <b>no</b> for precision satellite-navigation claims.", "orange"), P("Decision matrix", "H2")])
    story.append(status_table([
        ("Pruning logic", "PASS", "All/support/active CPU runs produced the same 9,335 event identities. Independent GPU audit matched all identities and all exact counters."),
        ("GPU feasibility", "PASS", "Full native sm_120 build, laptop-scale 1,048,576-step run, 1.856 GiB dense allocation, no OOM or propagation errors."),
        ("GPU safety", "PASS", "Compute Sanitizer: 0 memory errors, 0 race hazards, 0 synchronization errors."),
        ("Release acceptance", "FAIL", "The executable returns 1 because its 1 ns / 1e-12 CPU-GPU comparator is tighter than normal floating-point CPU/GPU reproducibility."),
        ("Precision sat-nav", "FAIL", "Against a real IGS ultra-rapid SP3 product, RMS position error was 56.80 km; unsuitable for PNT/pseudorange-grade orbit truth."),
    ]))
    story.extend([Spacer(1, 3 * mm), P("This is not contradictory. The GPU and CPU can implement the <i>same SGP4 model</i> extremely closely while that model, using the supplied element set and simplified frame treatment, is still far from a precision ephemeris.", "Body"), PageBreak()])

    # 3 — ELI5
    story.extend(page_head("02 / ELI5", "Think recipe cards, a guest list, and one cook", "The compact file does not store millions of satellite coordinates. It stores the ingredients needed to calculate them when asked."))
    story.append(eli5_flow())
    story.extend([
        P("What “compression” means here", "H2"),
        bullets([
            "The <b>9,581-byte KSGP file</b> is a compact parametric description: orbit elements, names, metadata, and timeline nodes.",
            "A seven-day GPU position+velocity table at 60-second spacing occupies <b>17.84 MiB</b>. The KSGP representation is <b>1,953× smaller</b> than that table because it delays calculation until query time.",
            "It is <b>not</b> compression of the original OMM CSV: that source is 8,454 bytes, so KSGP is actually about <b>13.3% larger</b>. The win is against dense future samples, not against source text.",
        ], "cyan"),
        P("What pruning means", "H2"),
        bullets([
            "Start with every satellite-station invitation: 58 × 16 = <b>928</b> possible relations.",
            "Remove invitations that cannot meet the declared range envelope: <b>711</b> remain.",
            "Remove invitations blocked by orbit/service/route policy: <b>438</b> remain.",
            "The crucial proof is that the remaining list still produces the same <b>9,335 AOS/LOS events</b> as checking every invitation.",
        ], "purple"),
        callout("Grouped GPU mode is the sensible design: calculate one satellite position, then ask every eligible station. Pair-expanded mode recalculates the same satellite for multiple stations and is mainly a comparison baseline.", "green"),
        PageBreak(),
    ])

    # 4 — Method
    story.extend(page_head("03 / METHOD", "What was actually tested", "No verdict here is based only on a successful process launch. The audit separated package integrity, model correctness, GPU equivalence, performance, robustness, coverage, and physical accuracy."))
    story.append(simple_table(["LAYER", "TEST", "EVIDENCE"], [
        ["Package", "Filesystem + ZIP SHA-256 manifest", "251/251 entries matched in both locations"],
        ["Toolchain", "Fresh CMake/MSVC/CUDA configure and Release build", "CUDA 12.8, CC 12.0, sm_120 cubin + compute_120 PTX"],
        ["Unit/regression", "CTest Release", "4/4 executables passed"],
        ["CPU oracle", "Full 7-day all/support/active modes", "9.354M / 7.167M / 4.415M relation intervals"],
        ["GPU paths", "pair_all, pair_support, pair_active, grouped_all, grouped_active, dense", "Independent exact event/counter capture"],
        ["Robustness", "memcheck, racecheck, synccheck, truncation, malformed stations", "Expected clean/rejected outcomes"],
        ["Performance", "11-repeat file run + 7-repeat laptop run", "p50/p95/p99 CSV plus telemetry"],
        ["Kernel", "Nsight Compute full set + cuobjdump", "occupancy, registers, cache, branch and ISA data"],
        ["Physical truth", "Real IGS ultra-rapid SP3, 32 GPS, 192 epochs", "6,144 coordinate samples + 49,152 station endpoints"],
    ], [31, 58, 82], compact=True))
    story.extend([
        P("The acceptance logic I applied", "H2"),
        bullets([
            "A <b>correctness pass</b> requires identical event identities and exact intended counters after pruning—not merely similar totals.",
            "A <b>GPU feasibility pass</b> requires a native architecture build, sustained execution, safe memory behavior, and practical resource use.",
            "A <b>physical-accuracy pass</b> requires comparison to external orbit truth. CPU/GPU agreement alone cannot establish it.",
            "A <b>claim-coverage pass</b> requires the data to exercise the claimed orbit classes, station profiles, policies, routes, and event-producing cases.",
        ], "cyan", tight=True),
        callout("Temporary diagnostic instrumentation was used only to expose hidden counters and numeric deltas. It was removed, the original source SHA-256 was restored exactly, and the original executable was rebuilt.", "purple"),
        PageBreak(),
    ])

    # 5 — Integrity/build
    story.extend(page_head("04 / PACKAGE + BUILD", "The laptop hardware is adequate; automation discovery is the weak link", "The code built and ran natively on the RTX 5070 Ti Laptop GPU. The failures seen in the automatic path were Windows/CMake integration issues, not lack of GPU capability and not a flaw in the pruning concept."))
    story.append(metric_cards([
        ("251/251", "MANIFEST FILES MATCH", "green"),
        ("4/4", "CTEST PASS", "green"),
        ("sm_120", "NATIVE CUBIN", "green"),
        ("12,227 MiB", "GPU VRAM", "cyan"),
    ]))
    story.extend([Spacer(1, 3 * mm), status_table([
        ("Filesystem manifest", "PASS", "251 present, 0 missing, 0 mismatched, 0 malformed."),
        ("ZIP manifest", "PASS", "1,901,903-byte archive; all 251 declared entries hash correctly inside the archive."),
        ("Long build path", "CONDITIONAL", "MSBuild FileTracker failed at the original deep path. This is a Windows path/tooling limitation."),
        ("Short auto-configure", "FAIL", "CMake still did not auto-discover CUDA 12.8, but the script propagated the failure correctly."),
        ("Explicit CUDA configure", "PASS", "Using -T cuda=... and CMAKE_CUDA_COMPILER produced a clean Release build."),
        ("Binary architecture", "PASS", "cuobjdump found native sm_120 code plus compute_120 PTX."),
    ]), P("Compiled kernel resources", "H2")])
    story.append(simple_table(["KERNEL", "REGISTERS", "STACK", "SPILLS"], [
        ["pair_query_kernel", "152", "48 B", "0"],
        ["grouped_query_kernel", "154", "48 B", "0"],
        ["materialize_kernel", "142", "48 B", "0"],
        ["dense_query_kernel", "74", "0 B", "0"],
    ], [73, 35, 31, 32], compact=True))
    story.extend([Spacer(1, 2 * mm), callout("Answer to the earlier hardware question: <b>the laptop was not what was lacking</b>. The explicit CUDA build proves the hardware and compiler path work; automatic toolkit discovery and path length are the build-automation defects.", "green"), PageBreak()])

    # 6 — correctness
    story.extend(page_head("05 / PRUNING CORRECTNESS", "The core pruning proof passed exactly", "Every relation mode was evaluated over the complete seven-day, 60-second challenge. Static pruning removed work without removing any valid AOS/LOS event."))
    story.append(pruning_flow())
    story.append(metric_cards([
        ("9,354,240", "ALL RELATION INTERVALS", "cyan"),
        ("7,166,880", "SUPPORT INTERVALS", "purple"),
        ("4,415,040", "ACTIVE INTERVALS", "green"),
        ("2.1187×", "TOTAL PRUNING GAIN", "green"),
    ]))
    story.extend([Spacer(1, 3 * mm), simple_table(["EXACT COUNTER", "ALL", "SUPPORT", "ACTIVE / GROUPED"], [
        ["relation intervals", "9,354,240", "7,166,880", "4,415,040"],
        ["propagated intervals", "9,354,240", "7,166,880", "4,415,040 pair / 584,640 grouped"],
        ["supported", "5,932,861", "5,932,861", "3,970,997 active"],
        ["compatible + boundary", "3,970,997", "3,970,997", "3,970,997"],
        ["visible", "1,101,511", "1,101,511", "1,101,511"],
        ["AOS / LOS / total events", "4,653 / 4,682 / 9,335", "same", "same"],
        ["propagation errors", "0", "0", "0"],
    ], [52, 38, 38, 43], compact=True), P("Independent audit discoveries", "H2"), bullets([
        "The release's displayed “counter match” helper omits <b>relation intervals, propagated intervals, and supported intervals</b>. My instrumentation checked them explicitly; they match the intended values.",
        "The default benchmark times pair_support but does not compare its event vector. My independent capture showed pair_support and pair_active events match exactly.",
        "Grouped active reduces orbit propagations by <b>7.5517×</b> relative to pair-active, because each object/time state is reused across stations.",
    ], "orange", tight=True), PageBreak()])

    # 7 — numerical gate
    story.extend(page_head("06 / CPU–GPU NUMERICS", "Why the executable says FAIL even though the results verify", "The release comparator requires crossing times within 1 nanosecond and guards within 1e-12. CPU and GPU execute floating-point transcendental operations differently, so these tolerances are not realistic for cross-architecture reproducibility."))
    story.append(metric_cards([
        ("9,335/9,335", "EVENT IDENTITIES MATCH", "green"),
        ("29.23 µs", "CROSSING-TIME RMS DELTA", "orange"),
        ("343.26 µs", "WORST TIME DELTA", "orange"),
        ("9.56e−8", "WORST GUARD DELTA", "orange"),
    ]))
    story.extend([Spacer(1, 3 * mm), callout("The GPU run is <b>not a false pass</b>; it is a <b>false failure at the comparator boundary</b>. Counts and identities agree, while every event exceeds an unnecessarily strict tolerance by a very small numerical amount.", "orange"), P("Observed delta distribution", "H2"), simple_table(["METRIC", "P50", "P95", "P99", "MAX"], [
        ["crossing time", "16.98 µs", "54.79 µs", "78.67 µs", "343.26 µs"],
        ["visibility guard", "3.01e−9", "4.24e−8", "6.11e−8", "9.56e−8"],
    ], [42, 32, 32, 32, 33]), P("What must change", "H2"), bullets([
        "Define a documented engineering tolerance based on the scheduling requirement—likely milliseconds for crossing interpolation, not nanoseconds.",
        "Keep exact identity/count checks, exact integer counter checks, no-truncation checks, and zero-propagation-error checks.",
        "Report maximum and percentile numeric deltas instead of collapsing all agreement into one boolean.",
        "Add pair_support events and the omitted counters to the normal release acceptance output so the independent diagnostic patch is unnecessary.",
    ], "cyan"), P("Until that is done, the honest release status is: <b>algorithmically validated, acceptance gate failing as shipped</b>.", "Body"), PageBreak()])

    # 8 — file performance
    story.extend(page_head("07 / SEVEN-DAY PERFORMANCE", "Grouped reuse beats repeated pair work", "These are medians from the full 10,080-interval, seven-day file preset. Lower is better."))
    story.append(horizontal_bars(
        ["pair_all", "pair_support", "pair_active", "grouped_all", "grouped_active", "dense materialize", "dense query"],
        [file_perf[k]["p50"] for k in ["pair_all", "pair_support", "pair_active", "grouped_all", "grouped_active", "materialize_dense", "query_dense_active"]],
        "ms", [MUTED, CYAN, PURPLE, ORANGE, GREEN, HexColor("#547B9C"), HexColor("#2C6C8B")], height=190,
    ))
    story.append(metric_cards([
        ("1.57×", "PAIR ACTIVE VS ALL", "green"),
        ("1.54×", "GROUPED VS ACTIVE PAIR", "green"),
        ("37.52×", "RESIDENT DENSE QUERY", "cyan"),
        ("52.57 ms", "DENSE END-TO-END", "cyan"),
    ]))
    story.extend([Spacer(1, 3 * mm), bullets([
        "pair_active: <b>86.66 ms</b>, down from pair_all at 136.01 ms. Static active pruning produces a real 1.57× speedup in the pair-expanded design.",
        "pair_support: <b>136.93 ms</b>, slightly slower than pair_all. Removing only 23% of pairs does not offset launch/divergence/occupancy effects at this small horizon.",
        "grouped_active: <b>56.40 ms</b>. It is 1.54× faster than pair_active because it propagates each object/time once, then reuses the state.",
        "grouped_all and grouped_active are almost identical at this scale. Orbit propagation and the small eight-block grid dominate, so pruning station checks alone is not the primary win.",
        "materialize + dense query is <b>52.57 ms</b>, about 6.8% faster than grouped_active even for one query. Dense is the latency winner when the fixed horizon comfortably fits memory.",
    ], "green", tight=True), callout("The compact method's strongest case is low storage, flexible horizons, and avoiding persistent dense state—not absolute single-query latency when a dense table already fits.", "orange"), PageBreak()])

    # 9 — laptop stress
    story.extend(page_head("08 / LAPTOP-SCALE STRESS", "A million time steps ran stably at sustained load", "The prescribed laptop preset used 1,048,576 one-second intervals. The dense table alone was 1.856 GiB. Seven timed repetitions were completed for every strategy."))
    story.append(horizontal_bars(
        ["pair_all", "pair_support", "pair_active", "grouped_all", "grouped_active", "dense materialize", "dense query"],
        [laptop_perf[k]["p50"] for k in ["pair_all", "pair_support", "pair_active", "grouped_all", "grouped_active", "materialize_dense", "query_dense_active"]],
        "ms", [MUTED, CYAN, PURPLE, ORANGE, GREEN, HexColor("#547B9C"), HexColor("#2C6C8B")], height=190, log_scale=True,
    ))
    story.append(metric_cards([
        ("99.61%", "AVG GPU UTILIZATION", "green"),
        ("74 °C", "PEAK TEMPERATURE", "green"),
        ("85.06 W", "PEAK POWER", "cyan"),
        ("2,472 MiB", "PEAK USED VRAM", "cyan"),
    ]))
    story.extend([Spacer(1, 3 * mm), simple_table(["MODE", "P50", "P95", "KEY INTERPRETATION"], [
        ["pair_all", "10,781.62 ms", "10,783.31 ms", "baseline repeated propagation"],
        ["pair_active", "4,312.30 ms", "4,312.87 ms", "2.50× faster than pair_all"],
        ["grouped_active", "810.40 ms", "811.64 ms", "5.32× faster than pair_active"],
        ["dense end-to-end", "804.52 ms", "≈805.54 ms", "0.7% faster than grouped_active"],
        ["resident dense query", "145.61 ms", "145.62 ms", "5.57× faster after materialization"],
    ], [40, 35, 35, 61], compact=True), P("Stress verdict", "H2"), bullets([
        "No out-of-memory event, GPU reset, propagation error, or sanitizer fault occurred.",
        "777 telemetry samples covered the run. Average power was 73.70 W; average temperature was 70.34 °C; SM clock averaged 2,757 MHz.",
        "Dense event equivalence was intentionally skipped by the release on this preset because validation was capped at 10,080 intervals. Full dense equivalence was already proven on the seven-day file preset.",
    ], "green", tight=True), PageBreak()])

    # 10 — storage/feasibility
    story.extend(page_head("09 / STORAGE + FEASIBILITY", "The representation is extremely compact versus sampled trajectories", "The package's compression story is real only when stated against the correct baseline: future sampled states."))
    story.append(metric_cards([
        ("9,581 B", "KSGP CONTAINER", "green"),
        ("17.84 MiB", "7-DAY DENSE GPU TABLE", "cyan"),
        ("1,953×", "7-DAY DENSE / KSGP", "green"),
        ("203,127×", "LAPTOP DENSE / KSGP", "green"),
    ]))
    story.extend([Spacer(1, 4 * mm), simple_table(["REPRESENTATION", "SIZE", "WHAT IT CONTAINS", "TRADE-OFF"], [
        ["source OMM CSV", "8,454 B", "human-readable mean elements", "smallest source; parsing/initialization required"],
        ["KSGP1", "9,581 B", "58 fixed seeds + names + compiled/timeline metadata", "GPU-ready; 13.3% larger than source CSV"],
        ["dense float4", "8.92 MiB", "position-only 16-byte states", "very fast reuse; no velocity"],
        ["dense position+velocity", "17.84 MiB", "32-byte state per object/time", "fastest query; fixed horizon and memory"],
        ["laptop dense position+velocity", "1.856 GiB", "1,048,576 samples", "still feasible here, but scales linearly"],
    ], [43, 31, 57, 40], compact=True), P("Feasibility boundaries", "H2"), bullets([
        "The compact approach wins decisively when you need many possible horizons, distribute small orbit datasets, cannot reserve dense memory, or queries are sparse/streaming.",
        "Dense materialization wins latency when the same fixed horizon is queried repeatedly and memory is available. In both tested horizons it already broke even within the first query.",
        "Memory grows as <b>objects × samples × bytes-per-state</b>. KSGP size is nearly independent of sample count; computation grows with the samples actually evaluated.",
        "KSGP is a model-backed representation, not lossless compression of an exact future trajectory. Its physical fidelity is bounded by the SGP4 inputs and frame/time treatment.",
    ], "cyan"), callout("Serious answer on compression: <b>yes</b>, the deferred-state representation is real and useful. But advertising “1,953× compression” must name the dense sampled-state baseline and must not imply higher physical accuracy.", "orange"), PageBreak()])

    # 11 — coverage
    network = coverage["network"]
    event_cov = network["event_coverage"]
    story.extend(page_head("10 / EXACT COVERAGE", "The test is broad, but not literally universal", "The pair plan covers the full 58 × 16 Cartesian product and all declared orbit classes and route sectors. Event-producing coverage is narrower, especially for GEO relay cases."))
    story.append(metric_cards([
        ("928/928", "UNIQUE PAIRS PRESENT", "green"),
        ("54/58", "OBJECTS WITH EVENTS", "orange"),
        ("14/16", "STATIONS WITH EVENTS", "orange"),
        ("369/438", "ACTIVE PAIRS WITH EVENTS", "orange"),
    ]))
    orbit_rows = []
    for orbit in ["LEO", "MEO", "GEO", "HEO"]:
        row = network["coverage_by_orbit"][orbit]
        orbit_rows.append([orbit, str(row["objects"]), str(row["active_pairs"]), str(row["active_pairs_with_events"]), f'{row["events"]:,}', str(row["objects_with_events"])])
    story.extend([Spacer(1, 3 * mm), simple_table(["ORBIT", "OBJECTS", "ACTIVE", "ACTIVE + EVENTS", "EVENTS", "OBJECTS + EVENTS"], orbit_rows, [24, 25, 29, 36, 27, 30], compact=True), P("What is covered", "H2"), bullets([
        "LEO 11, MEO 32, GEO 8, HEO 7; service classes include NAV, RELAY, SCIENCE, EARTH_OBS, and CREWED combinations.",
        "All route sectors 0–5 appear in the event set; event interval indices span 3 through 10,077.",
        "All 9,335 events map only to active pairs. No pruned pair reappears in the oracle output.",
    ], "green", tight=True), P("Gaps that matter", "H2"), bullets([
        "Four TDRS GEO objects generated no events, and only 4 of 48 active GEO pairs generated events. This is not deep GEO event diversity.",
        "Singapore Relay and Equatorial Relay profiles generated no events. Sixty-nine active pairs generated none during the seven-day window.",
        "The network fixture contains no half-day resonant objects. Separate core SGP4/Vallado tests cover the half-day branch, but not through this network-pruning workload.",
        "The data is a deterministic challenge fixture, not a probabilistic survey of all real station networks, masks, ranges, outages, or policy combinations.",
    ], "orange", tight=True), PageBreak()])

    # 12 — SP3
    sp3 = coverage["sp3_analysis"]["overall"] if "sp3_analysis" in coverage else coverage.get("sp3", {}).get("overall", {})
    visibility = coverage["sp3_visibility"]
    story.extend(page_head("11 / PHYSICAL ACCURACY", "Full SGP4 runs—but it is not precision sat-nav truth", "A real external IGS ultra-rapid SP3 file was compared against the package's GPS predictions: 32 satellites, 192 fifteen-minute epochs, 6,144 position samples over 48 hours."))
    story.append(metric_cards([
        ("56.80 km", "POSITION RMS ERROR", "red"),
        ("54.77 km", "MEDIAN ERROR", "red"),
        ("60.83 km", "P95 ERROR", "red"),
        ("126.67 km", "MAX ERROR", "red"),
    ]))
    story.extend([Spacer(1, 3 * mm), callout("This result rules out precision GNSS/PNT use. Receiver navigation and pseudorange work require precise time/frames and metre-to-centimetre-class orbit products—not tens of kilometres.", "red"), P("Visibility impact over the same SP3 window", "H2"), simple_table(["CHECK", "SGP4", "SP3", "AGREEMENT / DELTA"], [
        ["station endpoints", "14,556 visible", "14,550 visible", "49,124/49,152 agree (99.943%)"],
        ["support predicate", "—", "—", "2 endpoint disagreements"],
        ["coarse 15-min crossings", "645", "650", "588 common identities"],
        ["common crossing time", "—", "—", "18.80 s RMS; 49.65 s max"],
        ["unmatched crossing identities", "57 only SGP4", "62 only SP3", "boundary/interval sensitivity"],
    ], [42, 35, 35, 59], compact=True), P("How both facts can be true", "H2"), bullets([
        "A 50–60 km difference is small compared with a roughly 26,600 km GPS orbital radius, so most above/below-mask endpoints remain unchanged; near a boundary, the same error shifts crossing time or interval identity.",
        "The official IGS ultra-rapid product contains 24 hours observed plus 24 hours predicted. RMS was 56.25 km in the observed half and 57.34 km in the predicted half, so prediction alone does not explain the result.",
        "TLE/OMM SGP4 is useful for coarse scheduling and catalog tracking. It is not the orbit/time/frame stack used for precision satellite navigation.",
    ], "orange", tight=True), P('Reference: <link href="https://igs.org/products" color="#00A7C4">IGS Products</link>; orbit file IGS0OPSULT_20262271800_02D_15M_ORB.SP3 (retrieved from the UCSD IGS archive mirror).', "Small"), PageBreak()])

    # 13 — kernel and engineering
    story.extend(page_head("12 / GPU ENGINEERING", "The kernel is compute-heavy, register-heavy, and under-filled on the smoke grid", "Nsight Compute profiled grouped_active after skipping the grouped_all launches. The smoke case uses only eight blocks, so these numbers diagnose shape and resource pressure rather than laptop-scale throughput."))
    story.append(metric_cards([
        ("154", "REGISTERS / THREAD", "orange"),
        ("25%", "THEORETICAL OCCUPANCY", "orange"),
        ("4.58%", "ACHIEVED OCCUPANCY", "orange"),
        ("97.72%", "BRANCH EFFICIENCY", "green"),
    ]))
    story.extend([Spacer(1, 3 * mm), simple_table(["METRIC", "VALUE", "INTERPRETATION"], [
        ["grid / block", "8 × 128", "only 0.06 waves/SM; too small to fill GPU"],
        ["register limit", "3 blocks/SM", "154 registers constrain theoretical occupancy"],
        ["SM busy", "44.89% active cycles", "FP64 is the most-used pipeline"],
        ["memory throughput", "0.12% peak", "not DRAM-bandwidth-bound in this profile"],
        ["L1/TEX hit rate", "99.86%", "hot working set; memory locality is good"],
        ["eligible warps/scheduler", "0.08", "latency hiding is weak in tiny grid"],
        ["stack / spills", "48 B / 0", "stack exists, but no register spills reported"],
    ], [44, 39, 88], compact=True), P("Engineering implications", "H2"), bullets([
        "Grouped reuse is the right algorithmic direction. It removes repeated propagation before micro-optimizing station predicates.",
        "For small object counts, launch shape and available parallelism dominate. Consider batching independent networks, windows, or epochs to expose more blocks.",
        "Reducing register pressure may raise occupancy, but SGP4's double-precision state is intrinsically register-intensive. Validate accuracy before trading doubles for floats.",
        "Pruning yields larger timing benefits on the million-step workload because there is enough work to amortize overhead and expose its reduced relation count.",
    ], "cyan"), callout("Do not interpret the 4.58% smoke occupancy as a failure of the laptop. The sustained run reached 99.6% GPU utilization; the profile shows that this tiny grid under-fills the device, while the long grid does not.", "green"), PageBreak()])

    # 14 — intended aspects
    story.extend(page_head("13 / INTENDED-ASPECT CHECKLIST", "What passed, what is conditional, and what remains unproven", "This matrix maps the package's intended challenge areas to fresh evidence rather than treating a single console summary as the entire test."))
    story.append(status_table([
        ("All four orbit classes", "PASS", "LEO/MEO/GEO/HEO all present; core half-day resonance is separate, not exercised by network data."),
        ("Station policy pruning", "PASS", "16 typed profiles; exact active-mask invariant; all events belong only to active pairs."),
        ("Support pruning safety", "PASS", "All/support event identities and survivor counts match; no lost valid event."),
        ("CPU active pruning", "PASS", "All/active produce identical 9,335-event identity set and exact expected counters."),
        ("GPU pair equivalence", "PASS", "All, support and active identities/counters independently captured and exact."),
        ("Grouped equivalence", "PASS", "Pair/grouped event identities and all audited counters match."),
        ("Dense equivalence", "PASS", "Full seven-day grouped/dense validation passes; long preset deliberately validates only prefix."),
        ("No errors/truncation", "PASS", "Zero propagation errors; capacity=1 rejects explicitly as truncated."),
        ("Input rejection", "PASS", "Duplicate station IDs and invalid latitude are rejected with specific errors."),
        ("CUDA safety", "PASS", "memcheck/racecheck/synccheck all report zero findings."),
        ("Windows build automation", "CONDITIONAL", "Correct failure propagation, but CUDA auto-discovery and deep path remain unreliable."),
        ("CPU/GPU release gate", "FAIL", "All identities match; release tolerance is nevertheless too strict and returns failure."),
        ("Physical orbit accuracy", "FAIL", "Real-SP3 trajectory error is tens of kilometres; not precision navigation."),
        ("Universal workload claim", "CONDITIONAL", "Broad deterministic fixture, but eventless GEO/station cases and no network half-day resonance."),
    ], [43, 34, 94]))
    story.extend([Spacer(1, 3 * mm), callout("Overall engineering classification: <b>prototype validated for its pruning and compact-compute purpose; release acceptance and precision-navigation positioning require corrective work.</b>", "orange"), PageBreak()])

    # 15 — actions and evidence
    story.extend(page_head("14 / NEXT ACTIONS + EVIDENCE", "How to turn this into a clean release pass", "The central algorithm does not need to be discarded. The next work is to make acceptance honest, expand coverage, and separate coarse scheduling claims from precision navigation claims."))
    story.append(simple_table(["PRIORITY", "ACTION", "ACCEPTANCE TARGET"], [
        ["P0", "Replace 1 ns / 1e-12 cross-device gate with documented engineering tolerances; retain exact identity and integer checks.", "Executable exits 0 on current RTX while reporting p50/p95/p99/max deltas."],
        ["P0", "Add relation, propagation, supported counters and pair_support event comparison to normal validation.", "No diagnostic patch required to prove all intended counters."],
        ["P1", "Fix CUDA 12.8 auto-discovery and shorten/normalize Windows build paths.", "Official script configures and builds from the distributed path."],
        ["P1", "Keep real SP3 regression separate from implementation equivalence; add EOP/time/frame documentation.", "Claims explicitly say coarse SGP4 scheduling, not precision PNT."],
        ["P1", "Add event-producing GEO/relay and half-day resonant network cases.", "Every intended branch produces observable network events."],
        ["P2", "Batch small workloads or tune register pressure after correctness is locked.", "Higher achieved occupancy without changing event/crossing accuracy."],
    ], [18, 91, 62], compact=True))
    story.extend([P("Key evidence produced by this run", "H2"), simple_table(["ARTIFACT", "PURPOSE"], [
        ["verification_v060_cpu_verify_console.txt", "full seven-day CPU oracle and pruning equivalence"],
        ["verification_v060_exact_counter_coverage_console.txt", "independent all/support/active/grouped/dense counters"],
        ["verification_v060_gpu_cpu_mismatch_diagnostic_console.txt", "identity and numeric-delta diagnosis"],
        ["verification_v060_gpu_file_results.csv", "11-repeat full-horizon GPU metrics"],
        ["verification_v060_gpu_laptop_results.csv", "7-repeat million-step GPU metrics"],
        ["verification_v060_gpu_laptop_telemetry.csv", "777 temperature/power/clock/utilization samples"],
        ["verification_v060_ncu_grouped_active.ncu-rep", "Nsight Compute full kernel profile"],
        ["verification_v060_coverage_summary.json", "pair/event/orbit/station/SP3 coverage audit"],
        ["verification_v060_sp3_comparison.csv", "6,144 real-SP3 coordinate deltas"],
        ["verification_v060_manifest_console.txt", "251-entry filesystem integrity result"],
    ], [93, 78], compact=True), P("Final answer", "H2"), callout("<b>Yes, it seriously works for its actual purpose:</b> compact, on-demand full-SGP4 propagation plus static network pruning and grouped GPU visibility evaluation. <b>It is not yet a clean release pass</b> because the comparator rejects harmless CPU/GPU drift, and <b>it is not a precision satellite-navigation solution</b> because external orbit error is far too large.", "green"), P("All metrics in this report were generated locally from the named package and hardware on 17 August 2026. The original declared package files and ZIP passed SHA-256 verification; newly created verification artifacts are intentionally outside the supplied manifest.", "Small")])

    return story


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = VerificationDocTemplate(str(OUTPUT))
    doc.build(build_story())
    print(OUTPUT)


if __name__ == "__main__":
    main()
