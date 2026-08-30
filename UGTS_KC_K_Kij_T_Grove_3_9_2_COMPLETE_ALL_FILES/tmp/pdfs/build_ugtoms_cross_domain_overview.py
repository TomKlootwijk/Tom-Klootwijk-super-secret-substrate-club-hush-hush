from __future__ import annotations

from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfbase.pdfmetrics import stringWidth


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output" / "pdf" / "UGTOMS_cross_domain_pilot_overview_review_draft.pdf"
SCREENSHOT = (
    ROOT
    / "build"
    / "release-handoff"
    / "20260830T023441Z-polar-grow"
    / "device-screenshot.png"
)

PAGE_W, PAGE_H = A4

NAVY = colors.HexColor("#07131D")
INK = colors.HexColor("#17242E")
SLATE = colors.HexColor("#506575")
MUTED = colors.HexColor("#6C7E8A")
PALE = colors.HexColor("#F2F7F9")
LINE = colors.HexColor("#D8E2E7")
CYAN = colors.HexColor("#00BFD1")
CYAN_DARK = colors.HexColor("#007F8E")
MAGENTA = colors.HexColor("#D04B9C")
GOLD = colors.HexColor("#E3A638")
GREEN = colors.HexColor("#1B9B75")
RED = colors.HexColor("#C54F5C")
WHITE = colors.white


BASE = getSampleStyleSheet()
STYLES = {
    "cover_kicker": ParagraphStyle(
        "cover_kicker",
        parent=BASE["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=CYAN,
        spaceAfter=5 * mm,
        tracking=1.2,
    ),
    "cover_title": ParagraphStyle(
        "cover_title",
        parent=BASE["Title"],
        fontName="Helvetica-Bold",
        fontSize=31,
        leading=34,
        textColor=WHITE,
        spaceAfter=5 * mm,
    ),
    "cover_sub": ParagraphStyle(
        "cover_sub",
        parent=BASE["Normal"],
        fontName="Helvetica",
        fontSize=14,
        leading=19,
        textColor=colors.HexColor("#DDEAF0"),
        spaceAfter=8 * mm,
    ),
    "cover_meta": ParagraphStyle(
        "cover_meta",
        parent=BASE["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#B9CBD3"),
    ),
    "h1": ParagraphStyle(
        "h1",
        parent=BASE["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=21,
        leading=25,
        textColor=NAVY,
        spaceBefore=0,
        spaceAfter=5 * mm,
    ),
    "h2": ParagraphStyle(
        "h2",
        parent=BASE["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=CYAN_DARK,
        spaceBefore=4 * mm,
        spaceAfter=2.5 * mm,
    ),
    "h3": ParagraphStyle(
        "h3",
        parent=BASE["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=INK,
        spaceBefore=2.5 * mm,
        spaceAfter=1.5 * mm,
    ),
    "body": ParagraphStyle(
        "body",
        parent=BASE["BodyText"],
        fontName="Helvetica",
        fontSize=9.1,
        leading=13.1,
        textColor=INK,
        spaceAfter=2.5 * mm,
    ),
    "body_tight": ParagraphStyle(
        "body_tight",
        parent=BASE["BodyText"],
        fontName="Helvetica",
        fontSize=8.4,
        leading=11.5,
        textColor=INK,
        spaceAfter=1.5 * mm,
    ),
    "small": ParagraphStyle(
        "small",
        parent=BASE["BodyText"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10.2,
        textColor=INK,
        spaceAfter=1.3 * mm,
    ),
    "tiny": ParagraphStyle(
        "tiny",
        parent=BASE["BodyText"],
        fontName="Helvetica",
        fontSize=6.3,
        leading=8.2,
        textColor=INK,
    ),
    "caption": ParagraphStyle(
        "caption",
        parent=BASE["BodyText"],
        fontName="Helvetica-Oblique",
        fontSize=7.1,
        leading=9.4,
        textColor=MUTED,
        alignment=TA_LEFT,
        spaceBefore=1.5 * mm,
        spaceAfter=2 * mm,
    ),
    "formula": ParagraphStyle(
        "formula",
        parent=BASE["Code"],
        fontName="Courier-Bold",
        fontSize=9.2,
        leading=13,
        textColor=NAVY,
        alignment=TA_CENTER,
    ),
    "metric_value": ParagraphStyle(
        "metric_value",
        parent=BASE["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=20,
        textColor=NAVY,
        alignment=TA_CENTER,
    ),
    "metric_label": ParagraphStyle(
        "metric_label",
        parent=BASE["Normal"],
        fontName="Helvetica",
        fontSize=6.8,
        leading=8.8,
        textColor=SLATE,
        alignment=TA_CENTER,
    ),
    "table_header": ParagraphStyle(
        "table_header",
        parent=BASE["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.1,
        leading=9.1,
        textColor=WHITE,
    ),
    "table_cell": ParagraphStyle(
        "table_cell",
        parent=BASE["Normal"],
        fontName="Helvetica",
        fontSize=7.1,
        leading=9.4,
        textColor=INK,
    ),
    "table_cell_small": ParagraphStyle(
        "table_cell_small",
        parent=BASE["Normal"],
        fontName="Helvetica",
        fontSize=6.4,
        leading=8.3,
        textColor=INK,
    ),
    "table_cell_bold": ParagraphStyle(
        "table_cell_bold",
        parent=BASE["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.1,
        leading=9.4,
        textColor=INK,
    ),
    "quote": ParagraphStyle(
        "quote",
        parent=BASE["BodyText"],
        fontName="Helvetica-Oblique",
        fontSize=10,
        leading=14.5,
        textColor=NAVY,
        leftIndent=3 * mm,
        rightIndent=3 * mm,
        alignment=TA_LEFT,
    ),
    "right": ParagraphStyle(
        "right",
        parent=BASE["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=MUTED,
        alignment=TA_RIGHT,
    ),
}


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, STYLES[style])


def label(text: str, color: colors.Color) -> Table:
    cell = Paragraph(text, ParagraphStyle(
        f"label-{text}",
        parent=STYLES["tiny"],
        fontName="Helvetica-Bold",
        textColor=WHITE,
        alignment=TA_CENTER,
    ))
    table = Table([[cell]], colWidths=[12 * mm], rowHeights=[5.2 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("BOX", (0, 0), (-1, -1), 0.5, color),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 0.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5 * mm),
    ]))
    return table


def callout(
    title: str,
    text: str,
    accent: colors.Color = CYAN,
    background: colors.Color = PALE,
    style: str = "body_tight",
) -> Table:
    content = [
        p(title, "h3"),
        p(text, style),
    ]
    table = Table([[content]], colWidths=[174 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("LINEBEFORE", (0, 0), (0, -1), 3.2, accent),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]))
    return table


def formula_box(text: str) -> Table:
    table = Table([[p(text, "formula")]], colWidths=[174 * mm], rowHeights=[16 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E9F8FA")),
        ("BOX", (0, 0), (-1, -1), 0.8, CYAN),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    return table


def metric_grid(metrics: list[tuple[str, str]], columns: int = 3) -> Table:
    rows = []
    for start in range(0, len(metrics), columns):
        row = []
        for value, desc in metrics[start:start + columns]:
            row.append([p(value, "metric_value"), p(desc, "metric_label")])
        while len(row) < columns:
            row.append([p("", "metric_value"), p("", "metric_label")])
        rows.append(row)
    table = Table(rows, colWidths=[174 * mm / columns] * columns)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    return table


def data_table(
    headers: list[str],
    rows: list[list[str]],
    widths: list[float],
    small: bool = False,
    header_color: colors.Color = NAVY,
) -> Table:
    cell_style = "table_cell_small" if small else "table_cell"
    data = [[p(h, "table_header") for h in headers]]
    for row in rows:
        data.append([p(value, cell_style) for value in row])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.7 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.7 * mm),
    ]
    for row_index in range(1, len(data)):
        if row_index % 2 == 0:
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), PALE))
    table.setStyle(TableStyle(commands))
    return table


def two_column(left_flowables, right_flowables, left_width=85 * mm) -> Table:
    table = Table(
        [[left_flowables, right_flowables]],
        colWidths=[left_width, 174 * mm - left_width - 5 * mm],
        hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LINEAFTER", (0, 0), (0, 0), 0.5, LINE),
    ]))
    return table


def bullet_lines(items: list[str], style: str = "body_tight") -> list[Paragraph]:
    return [p(f"<font color='#00A6B7'><b>-</b></font> {item}", style) for item in items]


def funnel_drawing() -> Drawing:
    width = 174 * mm
    height = 151 * mm
    d = Drawing(width, height)

    stages = [
        (6 * mm, 129 * mm, 162 * mm, 18 * mm, colors.HexColor("#DDF7FA"), "A. DOMAIN INFLOW", "Games, CAD, manufacturing, robotics, cities, science, health, media, data"),
        (14 * mm, 106 * mm, 146 * mm, 18 * mm, colors.HexColor("#D6EEF5"), "B. PRESERVE SEMANTICS", "Standards, units, coordinates, topology, tolerances, rules and provenance"),
        (24 * mm, 83 * mm, 126 * mm, 18 * mm, colors.HexColor("#CBE7EF"), "C. FIND SHARED STRUCTURE", "Repetition, symmetry, hierarchy, fields, constraints, cycles and dictionaries"),
        (38 * mm, 60 * mm, 98 * mm, 18 * mm, colors.HexColor("#B8DEE7"), "D. UGTOMS CORE", "Seed + typed operator DAG + bounded parameters + ECS + content address"),
        (49 * mm, 37 * mm, 76 * mm, 18 * mm, colors.HexColor("#F7E3F0"), "E. IRREDUCIBLE TRUTH", "Residual or literal fallback for unique and high-entropy information"),
    ]
    for x, y, w, h, fill, title, subtitle in stages:
        inset = 5 * mm
        points = [x, y + h, x + w, y + h, x + w - inset, y, x + inset, y]
        d.add(Polygon(points, fillColor=fill, strokeColor=CYAN_DARK, strokeWidth=0.7))
        d.add(String(x + w / 2, y + 10.4 * mm, title, fontName="Helvetica-Bold", fontSize=8.2, fillColor=NAVY, textAnchor="middle"))
        d.add(String(x + w / 2, y + 5.1 * mm, subtitle, fontName="Helvetica", fontSize=6.4, fillColor=INK, textAnchor="middle"))

    core_y = 17 * mm
    d.add(Rect(51 * mm, core_y, 72 * mm, 13 * mm, rx=2 * mm, ry=2 * mm, fillColor=NAVY, strokeColor=NAVY))
    d.add(String(87 * mm, core_y + 8.2 * mm, "F. VERIFY", fontName="Helvetica-Bold", fontSize=8.3, fillColor=WHITE, textAnchor="middle"))
    d.add(String(87 * mm, core_y + 3.4 * mm, "Hashes, tolerances, conformance, safety and security gates", fontName="Helvetica", fontSize=6.1, fillColor=colors.HexColor("#DDEAF0"), textAnchor="middle"))

    d.add(Line(87 * mm, 37 * mm, 87 * mm, 30 * mm, strokeColor=MAGENTA, strokeWidth=1.5))
    d.add(Line(87 * mm, core_y, 87 * mm, 10 * mm, strokeColor=CYAN, strokeWidth=1.5))

    output_y = 0.5 * mm
    outputs = [
        (1 * mm, 36 * mm, "DIRECT EXECUTION", "GPU / runtime / controller"),
        (69 * mm, 36 * mm, "STANDARD MATERIALIZATION", "glTF / STEP / 3MF / DICOM"),
        (137 * mm, 36 * mm, "MEASURED FEEDBACK", "bytes / fidelity / energy / safety"),
    ]
    for x, w, title, subtitle in outputs:
        d.add(Rect(x, output_y, w, 9 * mm, rx=1.2 * mm, ry=1.2 * mm, fillColor=colors.HexColor("#E7F5F7"), strokeColor=CYAN_DARK, strokeWidth=0.6))
        d.add(String(x + w / 2, output_y + 5.4 * mm, title, fontName="Helvetica-Bold", fontSize=5.8, fillColor=NAVY, textAnchor="middle"))
        d.add(String(x + w / 2, output_y + 2.1 * mm, subtitle, fontName="Helvetica", fontSize=4.9, fillColor=SLATE, textAnchor="middle"))
        d.add(Line(87 * mm, 10 * mm, x + w / 2, output_y + 9 * mm, strokeColor=CYAN_DARK, strokeWidth=0.6))
    return d


def architecture_drawing() -> Drawing:
    width = 174 * mm
    height = 47 * mm
    d = Drawing(width, height)
    boxes = [
        (0 * mm, "AUTHORING", "Dark editor\nLogic Blocks"),
        (31 * mm, "STATE", "ECS pools\nreal prototype"),
        (62 * mm, "PACKS", "KCPK / KCPR\nKCRP"),
        (93 * mm, "RENDER", "LUT / Direct\nPolar fields"),
        (124 * mm, "OUTPUT", "PBR -> Glow\nfinal Bayer"),
        (155 * mm, "TARGET", "ARM64 GLES3\nPoco / Mali"),
    ]
    box_w = 24 * mm
    for index, (x, title, subtitle) in enumerate(boxes):
        fill = colors.HexColor("#E7F5F7") if index < 5 else colors.HexColor("#F6E4F0")
        stroke = CYAN_DARK if index < 5 else MAGENTA
        d.add(Rect(x, 15 * mm, box_w, 24 * mm, rx=2 * mm, ry=2 * mm, fillColor=fill, strokeColor=stroke, strokeWidth=0.8))
        d.add(String(x + box_w / 2, 31.5 * mm, title, fontName="Helvetica-Bold", fontSize=6.7, fillColor=NAVY, textAnchor="middle"))
        lines = subtitle.split("\n")
        d.add(String(x + box_w / 2, 24.2 * mm, lines[0], fontName="Helvetica", fontSize=6.1, fillColor=INK, textAnchor="middle"))
        d.add(String(x + box_w / 2, 19.5 * mm, lines[1], fontName="Helvetica", fontSize=6.1, fillColor=INK, textAnchor="middle"))
        if index < len(boxes) - 1:
            start = x + box_w
            end = boxes[index + 1][0]
            d.add(Line(start + 1 * mm, 27 * mm, end - 1 * mm, 27 * mm, strokeColor=SLATE, strokeWidth=1))
            d.add(Polygon([end - 2.4 * mm, 28.5 * mm, end - 0.4 * mm, 27 * mm, end - 2.4 * mm, 25.5 * mm], fillColor=SLATE, strokeColor=SLATE))
    d.add(String(87 * mm, 7 * mm, "Authoritative ECS state remains separate from derived display copies; direct consumption avoids unnecessary baked intermediates.", fontName="Helvetica-Oblique", fontSize=6.5, fillColor=MUTED, textAnchor="middle"))
    return d


def page_metadata(canvas) -> None:
    canvas.setTitle("UGTOMS Cross-Domain Pilot Overview - Review Draft")
    canvas.setAuthor("Tom Klootwijk")
    canvas.setSubject("UGTOMS cross-domain architecture, pilot metrics, projections, and open-use intent")
    canvas.setKeywords("UGTOMS, UGTS, ECS, procedural compression, manufacturing, rendering, open use")


def cover_page(canvas, doc) -> None:
    page_metadata(canvas)
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setStrokeColor(colors.HexColor("#123647"))
    canvas.setLineWidth(0.55)
    for offset in range(-80, 520, 28):
        canvas.line(offset, 0, offset + 210, PAGE_H)
    canvas.setStrokeColor(colors.HexColor("#0A5060"))
    canvas.setLineWidth(1.1)
    canvas.line(18 * mm, 32 * mm, 192 * mm, 32 * mm)
    canvas.setFillColor(CYAN)
    canvas.rect(18 * mm, 28 * mm, 25 * mm, 2 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#91AAB4"))
    canvas.setFont("Helvetica", 6.8)
    canvas.drawString(18 * mm, 18 * mm, "PRIVATE REVIEW COPY - CONTAINS PERSONAL DATA SUPPLIED BY DECLARANT")
    canvas.restoreState()


def later_page(canvas, doc) -> None:
    page_metadata(canvas)
    canvas.saveState()
    canvas.setFillColor(WHITE)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 11 * mm, PAGE_W, 11 * mm, fill=1, stroke=0)
    canvas.setFillColor(CYAN)
    canvas.rect(0, PAGE_H - 11 * mm, 28 * mm, 1.3 * mm, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(WHITE)
    canvas.drawString(18 * mm, PAGE_H - 7.2 * mm, "UGTOMS CROSS-DOMAIN PILOT OVERVIEW")
    canvas.setFont("Helvetica", 6.6)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 8.5 * mm, "Review draft v0.1 | 30 August 2026 | Evidence labels: M measured, I implemented, C calculated, P projected, H hypothesis")
    canvas.drawRightString(PAGE_W - 18 * mm, 8.5 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 12 * mm, PAGE_W - 18 * mm, 12 * mm)
    canvas.restoreState()


def build_story() -> list:
    story = []

    # Cover
    story.extend([
        Spacer(1, 38 * mm),
        p("ENGINEERING OVERVIEW AND OPEN-USE INTENT", "cover_kicker"),
        p("UGTOMS", "cover_title"),
        p("Universal Geometric Topological<br/>Open Modular Substrate", "cover_sub"),
        p("Cross-domain pilot overview: from a measured UGTS game-engine slice to a reusable digital and physical substrate program.", "cover_sub"),
        Spacer(1, 10 * mm),
        p("Private review draft v0.1", "cover_meta"),
        p("Tom Klootwijk | BSN (user-supplied): NL200678942 | 10-07-1990 | Netherlands (NL)", "cover_meta"),
        p("Prepared 30 August 2026", "cover_meta"),
        Spacer(1, 16 * mm),
        p("This document records engineering evidence, explicit hypotheses, and a proposed perpetual free-use intent. It is not a standard, safety certification, proof of ownership, patent opinion, or legal advice.", "cover_meta"),
        Spacer(1, 5 * mm),
        p("Privacy note: this private review copy contains a BSN and date of birth supplied by Tom Klootwijk. The identity and identifier have not been independently verified. A public edition should normally redact those fields.", "cover_meta"),
        PageBreak(),
    ])

    # Executive overview
    story.extend([
        p("Executive overview", "h1"),
        callout(
            "Thesis",
            "UGTOMS is best treated as a typed generative substrate, codec family, and execution model. It can sit beneath existing domain standards, preserve their semantics, encode repeated or causal structure compactly, and either execute directly or materialize conventional outputs. It is not one universal log-polar codec and it does not replace domain expertise.",
            CYAN,
        ),
        Spacer(1, 3 * mm),
        p("The current UGTS pilot establishes one real, bounded proof point: compact polar population and material-field state was encoded, executed through ECS-aware Android GLES3 rendering, and measured on a Poco/Mali phone. The evidence is narrow but concrete. The cross-domain UGTOMS program extends the same architectural strategy to other data classes through domain-specific operator vocabularies, residual fallbacks, standards adapters, and conformance gates.", "body"),
        p("The strongest strategic correction from the recent discussion is also the fairest one: if glTF, KTX2, Unity bundles, Unreal packages, STEP, 3MF, or another container carries the identical UGTOMS recipe and decoder, its content payload approaches the same size. It has effectively become a UGTOMS carrier. The remaining difference is runtime size, duplicated intermediates, direct execution, and implementation quality.", "body"),
        p("Evidence legend", "h2"),
        data_table(
            ["Label", "Meaning", "Use in this report"],
            [
                ["[M]", "Measured and preserved", "Artifact, phone, timing, memory, thermal, or test evidence retained locally."],
                ["[I]", "Implemented and host verified", "Current worktree behavior covered by source/native/shader tests, but not necessarily re-profiled on the phone."],
                ["[C]", "Calculated", "Transparent arithmetic derived from measured byte counts."],
                ["[P]", "Projection", "Sensitivity calculation under stated assumptions; not a forecast or benchmark."],
                ["[H]", "Hypothesis", "Cross-domain research or engineering opportunity requiring a domain adapter and independent validation."],
            ],
            [18 * mm, 45 * mm, 111 * mm],
        ),
        Spacer(1, 4 * mm),
        two_column(
            [p("What is demonstrated", "h2")] + bullet_lines([
                "A compact, content-addressed operator recipe can replace explicit repeated placement data for one polar workload.",
                "One real ECS prototype can own derived display copies without minting generated gameplay entities.",
                "The shared LUT, Direct fallback, Glow, Grow, PBR-lite, and final Bayer stages can compose in a bounded mobile renderer.",
                "The preserved build held the 120 Hz display cadence during a 30-second Poco capture.",
            ]),
            [p("What remains unproven", "h2")] + bullet_lines([
                "Universal compression, a universal domain ontology, or one codec that efficiently compresses arbitrary data.",
                "General mesh, texture, broad animation, audio, and residual codecs.",
                "Manufactured-part accuracy, machine safety, clinical use, or regulatory conformance.",
                "GPU-only milliseconds, electrical power, long-duration thermals, and production-store deployment.",
            ]),
        ),
        PageBreak(),
    ])

    # Funnel
    story.extend([
        p("The UGTOMS funnel", "h1"),
        p("Many domains narrow into a small shared substrate only after their authoritative semantics are preserved. The substrate then fans out into direct execution, standard materialization, and an evidence feedback loop.", "body"),
        funnel_drawing(),
        Spacer(1, 2 * mm),
        callout(
            "The non-negotiable center",
            "Representable does not mean compressible. A short seed selects an output already implicit in the decoder, operator vocabulary, or shared dictionary. Unique, random, encrypted, or high-entropy information may require a residual nearly as large as the original. Residual fallback is therefore part of the substrate, not a failure case.",
            MAGENTA,
            colors.HexColor("#FAEFF6"),
        ),
        Spacer(1, 3 * mm),
        p("The funnel gives domain experts an explicit place to retain control. Units, tolerances, coordinate frames, safety constraints, privacy, provenance, and regulatory rules remain at the domain boundary. UGTOMS may compact and execute structure, but it cannot silently reinterpret those obligations.", "body_tight"),
        PageBreak(),
    ])

    # Core model
    story.extend([
        p("Core model and compounding", "h1"),
        formula_box("artifact = generator(seed, typed operator DAG, parameters) + residual"),
        Spacer(1, 4 * mm),
        data_table(
            ["Substrate element", "Role", "Failure boundary"],
            [
                ["Seed and lineage", "Random-access identity, reproducibility, variation, and stable derivation.", "A seed is an address into possible outputs, not missing information by magic."],
                ["Typed operator DAG", "Carries semantic operations, dependencies, units, and bounded composition.", "A universal VM still needs domain-specific operators and versioned meanings."],
                ["Parameters and LUTs", "Compact values and reusable approximations for bounded calculations.", "Quantization error, seams, interpolation, and hardware behavior require explicit budgets."],
                ["ECS/component state", "Separates authoritative identities and state from derived display or manufacturing views.", "Derived outputs must not silently become authoritative objects."],
                ["Content addresses", "Name exact meaning and dependencies, support caches, provenance, and reproducible builds.", "A hash proves byte identity, not safety, quality, or ownership."],
                ["Residual/literal fallback", "Preserves irreducible measurements, edits, scans, recordings, and exceptions.", "Compression may approach 1x or become negative for high-entropy content."],
            ],
            [31 * mm, 68 * mm, 75 * mm],
        ),
        p("How compounding can be real", "h2"),
        p("One shared graph may derive geometry, collision, levels of detail, material coordinates, placement, animation, manufacturing features, and provenance from one causal description. This removes repeated descriptions across formats. That is genuine compound leverage.", "body"),
        p("How compounding can be overstated", "h2"),
        p("Independent compression ratios do not multiply naively. A 100x mesh reduction and 100x texture reduction do not automatically make a game 10,000x smaller. Whole-package reduction is weighted by how many baseline bytes each codec actually captures, plus decoder and runtime overhead.", "body"),
        callout(
            "Direct execution is a separate advantage",
            "Disk compression does not guarantee RAM or GPU compression. Generated geometry and textures may expand into normal buffers. Direct procedural evaluation can avoid some materialization, but it exchanges storage for compute, latency, energy, and implementation complexity. Every domain needs both byte and execution metrics.",
            GOLD,
            colors.HexColor("#FFF7E7"),
        ),
        PageBreak(),
    ])

    # Formal UGTOMS claim
    story.extend([
        p("The UGTOMS Claim", "h1"),
        data_table(
            ["Field", "Private review record"],
            [
                ["Claim identifier", "UGTOMS-CLAIM-001"],
                ["Status", "Proposed architecture claim - review draft, not a registration or legal finding"],
                ["Proposer / declarant", "Tom Klootwijk"],
                ["Dutch identity anchor", "BSN (user-supplied): NL200678942 | Date of birth: 10-07-1990 | Netherlands (NL)"],
                ["Recorded", "30 August 2026"],
                ["Scope", "The UGTOMS proposal, reviewed corpus pattern, demonstrated adapters, domain pilots, and stated open-use intent"],
            ],
            [43 * mm, 131 * mm],
        ),
        Spacer(1, 4 * mm),
        Table(
            [[p(
                "<b>Claim.</b> UGTOMS is proposed as a profile-based substrate-codec architecture and common intermediate target. The reviewed corpus demonstrates a recurring representational pattern across rendering and game logic, sparse geospatial event queries, orbital seed reconstruction, spatial evidence streams, symbolic operator cells, and exact state or proof ledgers. Direct GSP4-to-UGTS bridge evidence and a GSP4-derived cone gate in the game engine show that mechanisms can cross domain and runtime boundaries.<br/><br/>This supports a credible common adapter target and codec family. It does not establish one byte-compatible universal codec, universal compression, historical provenance of unrelated technology, or ownership of third-party applications and standards.",
                "quote",
            )]],
            colWidths=[174 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF7F8")),
                ("BOX", (0, 0), (-1, -1), 1, CYAN_DARK),
                ("LEFTPADDING", (0, 0), (-1, -1), 6 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
            ]),
        ),
        p("Why this wording is supportable", "h2"),
        data_table(
            ["Evidence", "What it supports"],
            [
                ["[I/C] GSP4 bridge", "126 geospatial candidates compile into both UGTS-GN G64 and G32 profiles with a declared precision guard and preserved hashes."],
                ["[I] Direct mechanism lineage", "The game engine documents GSP4's componentwise normalized cone gate as visual-graph opcode 24 across desktop, browser, and Android semantics."],
                ["[M/I] Domain pilots", "The corpus contains separate retained profiles for game rendering/ECS, geospatial graphs, packed GPU state, symbolic operators, SLAM evidence, orbital reconstruction, and exact proof ledgers."],
                ["[H] Common target", "A versioned UGTOMS envelope can unify profile declaration, typed state, operators, guards, lineage, residuals, and evidence without erasing domain-specific formats."],
            ],
            [45 * mm, 129 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        callout(
            "Identity and evidence boundary",
            "The BSN, birth date, nationality context, and declaration are supplied by Tom Klootwijk for this private review. This document records the requested attribution anchor but does not independently verify identity, authorship, inventorship, ownership, priority, patentability, or government registration.",
            RED,
            colors.HexColor("#FCEEEF"),
        ),
        PageBreak(),
    ])

    # Pilot architecture
    story.extend([
        p("UGTS pilot architecture and status", "h1"),
        architecture_drawing(),
        Spacer(1, 2 * mm),
        data_table(
            ["Layer", "Status", "Current evidence"],
            [
                ["Desktop editor", "[I] Retained", "Dark desktop editor, one-click run flow, child-facing controls, Logic Blocks graph authoring, and Android build/deploy/profile tooling."],
                ["ECS core", "[I] Worktree verified", "World-owned built-in component pools preserve the EntityState3D compatibility surface. Focused 17 tests + 17 subtests, broad 139 + 62, Android parity 17; independent ordinary-path review closed."],
                ["Packed kinematics", "[M] Retained", "KCPK stores packed polar state and a shared UGLUT2 profile. Current measured artifact carries a 1,690-byte KCPK."],
                ["Polar populations", "[M] Retained", "KCPR v4 stores one 304-byte recipe with nine operator meanings for Burst, Glow, and generated-copy Grow. One real prototype owns 127 derived displays."],
                ["Render substrate", "[M] Retained", "KCRP v1 is 32 bytes and selects shared LUT plus subtle 8x8 Bayer output. Final measured artifact used 64 levels at strength 0.3."],
                ["Polar Material Bands", "[I] Host verified", "Independent polar material coordinate; KCRP v1 remains exact 32 bytes, opt-in v2 is 40 bytes; no KCPR change, no new LUT fetch, 36-byte stride retained. No refreshed Poco profile yet."],
                ["General asset codecs", "[H] Not implemented", "No general procedural/residual mesh, texture, audio, broad animation, or arbitrary-data codec is currently claimed."],
                ["Physical adapters", "[H] Research program", "No STEP, 3MF, CNC, robotics, medical, or metrology conformance implementation is currently claimed."],
            ],
            [37 * mm, 32 * mm, 105 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        callout(
            "Presentation boundary",
            "Polar Bands is a presentation consumer of the packed log-polar chart. Glow remains a scalar field; Grow changes generated display scale only; Bayer remains the final presentation pass. None of these creates gameplay entities, collision, connected geometry, or manufacturing truth.",
            MAGENTA,
            colors.HexColor("#FAEFF6"),
        ),
        PageBreak(),
    ])

    # GSP4 adapter evidence
    story.extend([
        p("GSP4 adapter: a concrete cross-domain bridge", "h1"),
        p("GSP4 Spatial Knowledge Distillation v0.5.0 is the strongest reviewed adapter evidence outside the game pilot. It ingests GeoNames, OpenStreetMap, and irregular CSV inputs into a sparse typed UGKG2 graph, applies deterministic support, compatibility, finite-guard, route, lineage, and novelty rules, and emits an actual UGTS-GN candidate ABI. The learned model proposes and ranks; the deterministic gate remains authoritative.", "body"),
        metric_grid([
            ("126", "[I] candidates exported"),
            ("8,064 B", "[C] G64 state at 64 B each"),
            ("4,032 B", "[C] G32 state at 32 B each"),
            ("4.364554 m", "[M] maximum sampled G32 position error"),
            ("25 m", "[I] declared position guard"),
            ("2.000x", "[C] G64-to-G32 candidate-state reduction"),
        ], 3),
        Spacer(1, 4 * mm),
        data_table(
            ["GSP4 artifact", "Preserved evidence", "Boundary"],
            [
                ["Sparse graph", "228 nodes, 1,305 edges, 8 unequal observation windows; 57,545 B", "No fixed-frame padding. This is a domain graph, not a universal scene format."],
                ["Novelty ledger", "118 hash-linked UGNL3 records; 8,560 B including header", "The chain records accepted novelty; it does not recover discarded source information."],
                ["UGTS bridge", "G64: 12 f32 + 4 u32; packed G32: 8 u32; payload hashes preserved", "Local ENU and query-local time are profile rules. Precision finding is sample- and guard-specific."],
                ["Deployment", "Valid 16-member bundle; 1,351,748 B; wheel 99,169 B; 21 tests pass", "The 2x result applies only to the 8,064 B candidate buffer, not the full deployment or model."],
                ["Learned proposer", "341,459 parameters; 1,408,503 B smoke model", "About 0.55 test link accuracy: pipeline evidence only, not production semantic quality."],
                ["GPU closure", "Candidate buffers are emitted for the shared ABI", "The exact GSP4 buffers were not yet executed through the upstream SPIR-V evaluator and returned into the novelty ledger."],
            ],
            [32 * mm, 68 * mm, 74 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        callout(
            "Direct lineage into the game engine",
            "The current engine's visual-graph opcode 24, query.nearest_in_cone, explicitly adapts GSP4's componentwise normalized binary32 cone gate for desktop, browser, and Android semantics. This is real mechanism transfer, not a visual analogy. The engine also adapts bounded FIFO and canonical-order concepts from the GPU Native corpus into game messages.",
            GREEN,
            colors.HexColor("#EAF7F2"),
        ),
        PageBreak(),
    ])

    # Cross-corpus evidence
    story.extend([
        p("Cross-corpus evidence atlas", "h1"),
        p("The parent corpus contains separate, bounded profile families. Their common spine supports the UGTOMS architecture claim, while their different byte formats show why a shared canonical envelope is still future work.", "body"),
        data_table(
            ["Pilot / profile", "Concrete retained result", "Honest limit"],
            [
                ["UGTS game / KCPK, KCPR, KCRP", "304 B population recipe; 1 prototype + 127 derived displays; 36 B visible stride; 120.33 FPS on Poco/Mali.", "One bounded rendering workload; no general mesh, texture, audio, or arbitrary-data codec."],
                ["GSP4 / UGKG2, UGNL3, G64/G32", "126 candidates: 8,064 -> 4,032 B; 4.364554 m sampled error inside 25 m guard; 21 tests.", "Separate geospatial profiles; exact exported stream still needs end-to-end SPIR-V event closure."],
                ["UGTS-GN GPU Native", "At 1,048,576 candidates: 96 MiB dense G64/E32; 32.761 MiB packed G32 plus compact novelty = 2.9303x smaller.", "RTX results show locality and packed-state gains, not automatic physical cache enlargement or universal hardware compression."],
                ["KLB SGP4/SDP4 / KSGP1", "5,793 B for 32 orbital objects; direct GPU avoids 1.0-2.0 GiB dense trajectory materialization at tested horizons; about 1.03x end-to-end speedup.", "Model-based expansion from orbital elements, not lossless compression of a pre-existing trajectory file. Status documents need reconciliation."],
                ["KSEED Android sensor ledger", "361.58 s Poco run; 8,328 frames; 348 keyframes; 8,702 events; 805,002 B CRC/hash-chained ledger; p50 processing 1.355 ms.", "Selected evidence and novelty, not reconstructible camera photons or a metric SLAM scan; the 9,534x observed-luma ratio is not an image-codec claim."],
                ["Foundation Unicode / UG5N", "64 catalogued mechanisms, 24 claims, 83 tests; content-addressed semantic evaluator, glyph SDF, rule cells, and PackedNode32 PASS.", "Bounded symbolic/operator evidence, not all Unicode, all mathematics, or a general text-compression result."],
                ["Geometry and kinematics", "UGTS-KC 2.0 records 60 additions and 47 tests; Two Hands 3.0 adds compiler, BVH, material, replay, glTF/USDA export, and 117 tests.", "Useful primitives only. No STEP, 3MF, STEP-NC, G-code, metrology, printed part, or CNC conformance proof exists."],
                ["Proof-oriented Chess / Go profiles", "Exact canonical states, checkpoints, certificates, content-addressed lineage, and bounded proposal/verifier patterns.", "Separate formats; unsolved roots remain UNKNOWN and do not support solved-game or universal-codec claims."],
            ],
            [39 * mm, 77 * mm, 58 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        callout(
            "Cross-corpus inference [I/H]",
            "The repeated spine is typed and versioned state; bounded operators; seeds for reconstructible structure; residual or novelty records for irreducible external facts; support, compatibility, guard, commit, and lineage authority; hot state separated from cold provenance; content addressing; and either direct execution or standard materialization. The recurrence is real. Interoperability between the separate formats is not yet demonstrated.",
            CYAN,
        ),
        PageBreak(),
    ])

    # Proposed common kernel and falsifiability
    story.extend([
        p("Proposed UGTOMS kernel and claim tests", "h1"),
        p("A common UGTOMS intermediate target should wrap existing domain profiles rather than rename them. One canonical envelope can declare how a profile is interpreted, guarded, reconstructed, audited, and materialized while leaving KCPR, G32, KSEED, KSGP1, UG5N, and future standards adapters free to retain domain-specific layouts.", "body"),
        data_table(
            ["Canonical envelope block", "Minimum purpose"],
            [
                ["1. Profile header", "Version, profile identifier, units, coordinate frame, numeric domains, capabilities, and compatibility policy."],
                ["2. Typed state", "Stable identities, components, topology, hot packed fields, and authoritative versus derived ownership."],
                ["3. Operator atlas", "Content-addressed operator DAG, bounded parameters, dependencies, seed lineage, and deterministic scope."],
                ["4. Acceptance contract", "Support, compatibility, precision or tolerance guard, commit rules, failure behavior, and safety boundary."],
                ["5. Events and routes", "Transitions, canonical ordering, bounded queues, novelty, replay, and proof or certificate hooks."],
                ["6. Provenance", "Source references, authorship assertions, versions, content hashes, derivation, rights, and evidence lineage."],
                ["7. Literal and residual blocks", "Lossless escape for unsupported syntax and irreducible measurements, edits, exceptions, or high-entropy data."],
                ["8. Deployment manifest", "Required decoder and dictionaries, targets, dependencies, signatures, test vectors, and measured evidence."],
            ],
            [53 * mm, 121 * mm],
            small=True,
        ),
        p("A claim survives only if it can fail", "h2"),
        data_table(
            ["Test", "Pass condition"],
            [
                ["Independent decode", "Two independent implementations produce the same canonical result and declared hash or the same bounded result inside tolerance."],
                ["Semantic preservation", "Identity, topology, units, coordinate frames, operator meanings, and authoritative state survive round-trip or declared materialization."],
                ["Fail closed", "Malformed, unsupported, unsafe, or out-of-budget inputs are rejected or preserved literally; they are not silently reinterpreted."],
                ["Full accounting", "Reported size includes decoder, dictionaries, residuals, container, and fallbacks; runtime reports RAM, materialization, compute, latency, and energy."],
                ["External boundary", "Standards adapters pass their own conformance and tolerance checks; physical output adds simulation, test article, metrology, hazard review, and approval."],
            ],
            [43 * mm, 131 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        callout(
            "Next claim-qualifying proof",
            "Freeze the canonical envelope and operator registry; execute the exact GSP4 G32 stream through UGTS-GN SPIR-V and compare CPU/GPU event order; round-trip one KSGP1, KSEED, and KCPR recipe through that envelope; then add one real STEP or 3MF adapter with a tolerance report and manufactured coupon. That would convert architectural recurrence into measured cross-domain interoperability.",
            GOLD,
            colors.HexColor("#FFF7E7"),
        ),
        PageBreak(),
    ])

    # Measured evidence
    story.extend([
        p("Measured Poco/Mali evidence", "h1"),
        metric_grid([
            ("1,819,202 B", "[M] ARM64 debug APK"),
            ("2,026 B", "[C] KCPK + KCPR + KCRP"),
            ("19,330 B", "[C] all packaged scene, graph, shader and pack assets"),
            ("120.33 FPS", "[M] effective 120 Hz cadence"),
            ("128", "[M] rendered instances from one ECS prototype"),
            ("36 B", "[M] visible instance stride"),
        ], 3),
        Spacer(1, 4 * mm),
        data_table(
            ["Metric", "Preserved value", "Interpretation / boundary"],
            [
                ["Build", "61.204 s total; Gradle successful in 55 s", "Source export 3.447 s; Gradle portion 57.757 s."],
                ["APK composition", "Native library 1,786,936 B = 98.226%", "Small APK primarily demonstrates a lean ARM64 runtime; it is not a full production content comparison."],
                ["Workload", "1 ECS prototype + 127 derived copies", "Generated members are not ECS entities; visible payload is 4,608 B."],
                ["Frame capture", "30 s; 756 intervals; p50/p95/p99 8.380/10.113/11.295 ms", "One interval exceeded 1.5 display periods. SurfaceFlinger cadence, not GPU timer data."],
                ["Memory", "PSS 143,165-148,551 KiB; RSS 262,770-270,174 KiB", "Process ranges for this exact debug workload."],
                ["CPU", "8.313% mean total phone capacity; 66.508% mean of one core", "Eight logical cores. Peak values 8.853% and 70.822%."],
                ["Thermal", "GPU 41.897-46.710 C; battery 33.0-33.1 C; status 0", "Battery remained 98%; no electrical power was measured."],
                ["Stability", "No crash lines and no warnings", "A bounded 30-second run, not endurance certification."],
                ["Launch", "652 ms cold; 337 ms restored", "Private app data after install: 18 KiB."],
                ["Verification", "763 tests + 305 subtests in 238.71 s", "Focused integration 48 + 62; Ruff and independent review passed for the preserved slice."],
            ],
            [33 * mm, 65 * mm, 76 * mm],
            small=True,
        ),
        PageBreak(),
    ])

    # Screenshot
    story.extend([
        p("Physical render proof", "h1"),
        p("The image below is the preserved device screenshot from the exact Grow v4 handoff artifact. It verifies that the bounded lab rendered on model 2412DPC0AG / rodin_eea through the target Android path. It is not evidence of finished art direction or universal visual quality.", "body"),
    ])
    if SCREENSHOT.exists():
        shot = Image(
            str(SCREENSHOT),
            width=160 * mm,
            height=(160 * mm) * (1220.0 / 2712.0),
        )
        shot.hAlign = "CENTER"
        story.extend([
            Spacer(1, 2 * mm),
            shot,
            p("[M] Preserved device-screenshot.png: 128-display radial Burst with shared LUT, Glow, generated-copy Grow, PBR-lite, and subtle final Bayer. Android navigation controls remain visible at right.", "caption"),
        ])
    story.extend([
        Spacer(1, 3 * mm),
        two_column(
            [p("Runtime telemetry", "h2")] + bullet_lines([
                "Requested and effective mode: shared LUT.",
                "128 GPU instances, one LUT profile, two GPU batches.",
                "127 generated GPU copies, zero CPU fallbacks.",
                "Glow samples: 128; grown generated copies: 127.",
                "KCPR v4, 36-byte stride, ecs_generated=false.",
            ], "small"),
            [p("Explicit non-claims", "h2")] + bullet_lines([
                "No usable GPU timer-query extension: no GPU-only milliseconds.",
                "No electrical power measurement.",
                "One sequential Glow/Grow A/B pair is not causal performance isolation.",
                "USB/ADB disconnected only after the preserved install, launch, profile, and final reinstall completed.",
            ], "small"),
        ),
        PageBreak(),
    ])

    # Compression
    story.extend([
        p("Compression arithmetic and fair comparison", "h1"),
        p("Current placement comparison", "h2"),
        metric_grid([
            ("26.947x", "[C] 8,192 B of 128 raw f32 matrices / 304 B recipe"),
            ("96.289%", "[C] fewer placement bytes than those matrices"),
            ("43.75%", "[C] less visible staging: 36 B vs 64 B per instance"),
        ], 3),
        Spacer(1, 3 * mm),
        p("This is a placement-representation comparison, not a complete scene, asset, or game compression ratio. The current Burst contract caps 512 instances per recipe and 2,048 per project. A constant 304-byte recipe compared with 512 raw matrices would be 107.789x smaller [P/C]. The broader format ceiling of 4,096 would be 862.316x [P/C], but that is outside the current Burst per-recipe contract and has not been profiled on the Poco.", "body_tight"),
        formula_box("R_total = 1 / ((1 - f) + f / r + d)"),
        p("Here f is the baseline package share captured generatively, r is the reduction on that share, and d is decoder/runtime overhead as a fraction of the baseline. The following 1 GB sensitivity cases are illustrative, not forecasts.", "body_tight"),
        data_table(
            ["Generatable share f", "Reduction r", "Overhead d", "Result from 1 GB", "Whole reduction"],
            [
                ["50%", "20x", "2%", "545 MB", "1.83x"],
                ["70%", "50x", "2%", "334 MB", "2.99x"],
                ["90%", "100x", "2%", "129 MB", "7.75x"],
                ["95%", "100x", "1%", "69.5 MB", "14.39x"],
                ["99%", "200x", "0.5%", "19.95 MB", "50.13x"],
            ],
            [35 * mm, 30 * mm, 27 * mm, 42 * mm, 40 * mm],
        ),
        p("Applying the same strategy to traditional containers", "h2"),
        data_table(
            ["Comparison", "Expected outcome"],
            [
                ["Baked conventional payload vs UGTOMS recipe", "Potentially large savings where semantic structure is reusable."],
                ["UGTOMS-native vs glTF/KTX/Unity/Unreal/3MF carrying identical operators", "Content payloads converge. The container has become a UGTOMS carrier."],
                ["Recipe plus full baked fallback for legacy readers", "Compatibility improves, but the duplicate payload can erase the storage advantage."],
                ["Specialized UGTOMS runtime vs general engine using the same codec", "Difference shifts to runtime floor, subsystem overhead, direct execution, caches, and materialized intermediates."],
            ],
            [69 * mm, 105 * mm],
        ),
        PageBreak(),
    ])

    # Cross-domain matrix digital
    story.extend([
        p("Cross-domain matrix: digital and information systems", "h1"),
        p("These are [H] adapter programs unless explicitly marked otherwise. Existing standards remain authoritative interchange boundaries; UGTOMS would encode internal structure and preserve residual truth.", "body"),
        data_table(
            ["Domain and boundary", "Candidate UGTOMS operators", "Opportunity", "Required gate"],
            [
                ["Games / VFX / XR<br/>glTF, KTX2, OpenUSD", "ECS populations, scene composition, material fields, procedural geometry, animation and shared dictionaries.", "High for repeated or deliberately procedural content. Low for unique scans and recordings.", "Runtime parity, visual error, memory, GPU cost, interoperability, asset rights. Current pilot is the only device-measured slice."],
                ["CAD / product engineering<br/>STEP AP242", "Features, constraints, assemblies, parameter families, exact topology plus B-rep residual.", "Medium to high for product families and repeated assemblies; lower for one-off scans.", "Units, dimensional tolerance, topology identity, configuration management, exact round-trip."],
                ["BIM / cities / infrastructure<br/>IFC, CityGML", "Repeated families, alignments, topology, levels of detail, staged deltas, construction lineage.", "High for standardized repeated assets; lower for as-built capture.", "Coordinate reference systems, legal/as-built provenance, quantity accuracy, authoring round-trip."],
                ["Geospatial / environment<br/>OGC encodings", "Terrain, vegetation and road generators plus authoritative measured residual layers.", "Depends on regularity and scale. Generated context may be tiny; observations remain data-heavy.", "Do not replace measurements. Preserve uncertainty, time, coordinate system, source and resolution."],
                ["Science / engineering data<br/>HDF5", "Equations, initial conditions, solver graphs, structured fields and residual chunks.", "Medium when data is model-compressible; minimal for high entropy or already compressed data.", "Exactness or declared error, uncertainty, reproducibility, versioned solver semantics, provenance."],
                ["Healthcare / imaging<br/>DICOM", "Adjunctive simulation, derived models, anatomy parameterization, never silent replacement of source images.", "Usually low to medium for patient-specific captures; possibly higher for reusable derived models.", "Clinical validation, privacy, consent, source retention, regulatory and safety review."],
                ["Audio / media", "Synthesis graphs, events, reusable instruments, procedural ambience plus waveform residual.", "High for synthesized/repetitive content; low for speech, acting, or unique recordings.", "Perceptual quality, timing, rights, accessibility, residual fidelity."],
                ["General software / data / workflows", "Typed operator VM, content-addressed modules, literal fallback, provenance graph.", "Only where stable semantics and reuse exist. Random, encrypted, or precompressed data may expand.", "Schema/version compatibility, security, privacy, deterministic failure, migration."],
            ],
            [37 * mm, 49 * mm, 43 * mm, 45 * mm],
            small=True,
        ),
        PageBreak(),
    ])

    # Physical domains
    story.extend([
        p("Cross-domain matrix: physical manufacturing and operations", "h1"),
        callout(
            "Physical-domain priority",
            "For manufacturing, the strongest UGTOMS value may be parametric reuse, deterministic regeneration, traceability, and late binding to a machine - not merely smaller files. A game-device benchmark cannot establish manufactured-part accuracy, process capability, safety, or certification.",
            GOLD,
            colors.HexColor("#FFF7E7"),
        ),
        Spacer(1, 3 * mm),
        data_table(
            ["Domain and boundary", "Candidate operator model", "Potential value", "Mandatory validation"],
            [
                ["Additive manufacturing<br/>3MF, AMF", "Lattice, beam graph, boolean, SDF, infill, graded-material and slice operators plus mesh/voxel residual.", "Compact families of regular lattices, infill, microstructures, and parameter sweeps.", "Units, watertightness, materials, min feature, slice fidelity, printer constraints, coupon tests, metrology."],
                ["CNC / subtractive<br/>STEP-NC, ISO 6983 / RS274", "Workplans, workingsteps, tools, strategies and canonical machining functions compiled to machine-specific motion.", "Reuse and late binding may matter more than byte count; one plan can target validated postprocessors.", "Stock, fixtures, collisions, kinematics, limits, feeds/speeds, simulation, dry run, operator approval."],
                ["Robotics / factory / digital twin<br/>OPC UA", "ECS objects and components, graph methods, events, state machines, cells, recipes and lineage.", "High for repeated cells, variants, commissioning state, and traceable configuration.", "Real-time deadlines, fail-safe state, safety integrity, cybersecurity, hardware-in-loop, controlled rollout."],
                ["Electronics / EDA / semiconductor", "Hierarchical netlists, repeated structures, constraints, placement/routing patterns, process parameter sets.", "Potentially high for regular arrays and reusable design families; exact layouts may dominate.", "Electrical rules, timing, signal/power integrity, foundry PDK rights, DRC/LVS, manufacturing signoff."],
                ["Architecture / fabrication", "Parametric families, panelization, joinery, nesting, tolerances, assembly sequence and provenance.", "High for repeated systems and mass customization.", "Codes, structural analysis, tolerances, site conditions, procurement, inspection, signed responsibility."],
                ["Materials / chemistry / process recipes", "Molecular or process graphs, parameter schedules, measured residuals and uncertainty.", "Potential reuse across families, simulation and controlled recipes.", "Do not infer physical behavior from topology alone. Laboratory validation, hazards, regulations and traceability."],
                ["Logistics / supply chain", "Typed process graph, identities, constraints, route families, events and content-addressed documents.", "Compact reusable plans and deterministic change lineage.", "Real-world state remains authoritative; security, privacy, legal records, exceptions and auditability."],
            ],
            [39 * mm, 49 * mm, 42 * mm, 44 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        p("A safe physical workflow defaults to materialization and verification: UGTOMS recipe -> canonical domain model -> standards-conformant output -> simulation -> machine-specific postprocess -> dry run or test article -> metrology -> approved production. Direct controller execution is a later privilege earned by evidence, not the default.", "body_tight"),
        PageBreak(),
    ])

    # Standards crosswalk
    story.extend([
        p("Standards crosswalk and adapter posture", "h1"),
        p("UGTOMS should not ask industries to discard mature standards. It should use them as controlled ingress and egress contracts. Every adapter needs versioned semantics, conformance vectors, failure behavior, and round-trip or tolerance evidence.", "body"),
        data_table(
            ["Boundary", "What it already provides", "UGTOMS relationship"],
            [
                ["glTF 2.0", "Compact, runtime-neutral, extensible scene and asset transport.", "Potential carrier or bake target for operator-produced nodes, meshes, materials, animation, and transforms."],
                ["KTX2", "GPU texture container with registered supercompression mechanisms.", "Texture/material recipe carrier only through a recognized scheme or extension; otherwise materialize a standard texture."],
                ["OpenUSD", "Extensible scene composition and layered opinions.", "Map operator graphs, variants and provenance into a composition workflow without claiming drop-in compatibility."],
                ["STEP AP242", "Managed model-based 3D engineering/product data.", "Preserve product semantics and exact geometry at boundary; compact feature families internally."],
                ["3MF / AMF", "Additive model, materials, components, lattices, booleans, slices and related extensions.", "Materialize validated manufacturing packages or define an independently reviewed extension."],
                ["STEP-NC / ISO 6983", "Process-oriented or program-oriented numerical control.", "Compile typed workplans into verified controller programs; never bypass machine validation."],
                ["OPC UA", "Industrial information model for structure, behavior, semantics, communications and conformance.", "Bridge ECS/operator concepts to controlled information models and certified profiles."],
                ["IFC / CityGML", "Built-environment and city semantics, topology, coordinate context and levels of detail.", "Generate repeated structures while preserving authoritative property and coordinate semantics."],
                ["HDF5", "Hierarchical scientific data model with groups, datasets, chunks and compression.", "Store recipe, parameters, residual chunks, provenance and reconstruction metadata alongside measurements."],
                ["DICOM", "Medical information objects, encoding, storage, messaging and conformance.", "Adjunct only unless independently validated; preserve originals, identifiers, privacy, and conformance."],
                ["W3C PROV", "Portable provenance concepts for entities, activities, agents and derivation.", "Map content addresses, operator execution, authorship assertions and materialization lineage."],
            ],
            [31 * mm, 63 * mm, 80 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        callout(
            "Compatibility tradeoff",
            "A standard file containing only an unknown UGTOMS extension is not readable by legacy consumers. Shipping both recipe and full baked fallback preserves compatibility but can erase storage savings. The project must choose per target: require the decoder, materialize the standard payload, or deliberately carry both.",
            CYAN,
        ),
        PageBreak(),
    ])

    # Roadmap
    story.extend([
        p("Roadmap and conformance funnel", "h1"),
        data_table(
            ["Stage", "Deliverable", "Exit evidence"],
            [
                ["0. Preserve pilot", "Freeze current KCPK/KCPR/KCRP meanings, test vectors, device artifact, and evidence boundaries.", "Existing Grow v4 artifact remains reproducible; Polar Bands gets a refreshed Poco run before device claims."],
                ["1. Define UGTOMS kernel", "Canonical binary container, typed operator registry, units, parameter domains, content addresses, residual/literal blocks, provenance, versioning.", "Independent reader/writer, malformed-input rejection, golden vectors, migration rules."],
                ["2. Build digital codecs", "Procedural/residual mesh, texture/material, animation, audio, scene and general-data families.", "Per-domain storage, RAM, compute, energy, fidelity, determinism, and fallback benchmarks."],
                ["3. Standards adapters", "glTF/KTX/OpenUSD, STEP/3MF, OPC UA, HDF5 and selected other mappings.", "Round-trip or declared tolerance, conformance tools, loss reports, versioned capability profiles."],
                ["4. Physical sandbox", "Lattice coupon, parametric assembly, CNC workplan, robotic-cell recipe and metrology pipeline.", "Simulation, hardware-in-loop, test article, measurements, hazard analysis, human approval."],
                ["5. Production governance", "Security model, signing, provenance, reproducible releases, independent audits, domain certification where applicable.", "External conformance evidence; no universal production claim from one domain."],
            ],
            [28 * mm, 78 * mm, 68 * mm],
        ),
        p("Metrics required for every domain", "h2"),
        metric_grid([
            ("Bytes", "disk, network, cache and residual share"),
            ("Memory", "CPU RAM, GPU RAM and peak materialization"),
            ("Compute", "latency, throughput, CPU/GPU/controller cost"),
            ("Energy", "measured power or energy, not battery-percentage inference"),
            ("Fidelity", "exactness or declared error/tolerance budget"),
            ("Interchange", "standard conformance and round-trip behavior"),
            ("Determinism", "same inputs/version -> named reproducibility scope"),
            ("Provenance", "source, operator, version, rights and derivation trace"),
            ("Safety", "domain hazard, security and regulatory gates"),
        ], 3),
        Spacer(1, 4 * mm),
        callout(
            "Acceptance rule",
            "A mechanism becomes retained only when its serialized meaning, direct behavior, fallback, limits, malformed-input handling, domain tolerance, and named evidence are all recorded. A smaller file alone does not prove useful substrate application; a visually or physically plausible output alone does not prove deterministic or safe parity.",
            GREEN,
            colors.HexColor("#EAF7F2"),
        ),
        PageBreak(),
    ])

    # Recent decision record
    story.extend([
        p("Recent decision record", "h1"),
        p("This section summarizes the latest discussion and implementation direction. It is a decision record, not a verbatim transcript.", "body"),
        data_table(
            ["Turn / decision", "Resulting clarification"],
            [
                ["Use the log-encoded polar LUT for rendering", "The LUT must participate in placement and material calculation, not merely exist as a CPU lookup or renamed table."],
                ["Apply Bayer after the render", "The canonical 8x8 Bayer operation remains the final presentation stage. It is not authoritative geometry, motion, gameplay, or a universal smoothing claim."],
                ["Compound the substrate", "Reuse the same bounded polar state across placement, Glow, generated-copy Grow, material coordinates, phase, lineage, and output without adding redundant instance lanes or LUT fetches."],
                ["Use UGTS to its fullest", "Adopt compact operator recipes, seeds, content addresses, ECS ownership, direct execution, fallback, evidence boundaries, TODO/worklog discipline, and independent review."],
                ["Report current metrics", "Preserve exact APK, pack, instance, performance, memory, CPU, thermal, test, and caveat data for the named Poco workload."],
                ["Compare against traditional engines", "Mainstream systems already contain pieces such as instancing, ECS, procedural generation, and compressed assets. The fair advantage must be measured end to end."],
                ["Apply the same strategy inside traditional formats", "Their content payloads converge toward UGTOMS. The comparison becomes specialized native execution versus a general container/runtime carrying the same codec."],
                ["Extend across digital and physical domains", "Frame UGTOMS as a typed generative substrate with domain-specific operators, residual truth, standards adapters, conformance, provenance, safety, and free-use intent."],
                ["Use the GSP4 adapter and full parent corpus", "Make an architectural claim supported by direct GSP4-to-UGTS packing, game-engine mechanism lineage, and recurring bounded profiles, while keeping each existing format distinct."],
                ["Call the proposal UGTOMS", "Use UGTOMS for the proposed Universal Geometric Topological Open Modular Substrate. Preserve KCPR, G32, KSEED, KSGP1, UG5N, and other real profile names where technically required."],
                ["Tie the declaration to Dutch identity", "Record Tom Klootwijk, BSN (user-supplied) NL200678942, date of birth 10-07-1990, and Netherlands (NL) in this private review copy, without asserting independent verification."],
            ],
            [54 * mm, 120 * mm],
        ),
        Spacer(1, 4 * mm),
        p("The implementation work running alongside this document also closed ordinary-path ECS pool compatibility issues and corrected the editor's polar meter wording: it now reports deterministic samples for the selected recipe rather than claiming those copies received the viewport's shared preview allocation. These corrections reinforce the same principle: name exactly what is represented and measured.", "body"),
        PageBreak(),
    ])

    # Open use
    story.extend([
        p("Perpetual free-use intent - private review draft", "h1"),
        callout(
            "Repository fact",
            "The current workspace has no top-level LICENSE covering the complete project. An existing attribution notice includes MIT terms for two inherited mechanisms only. Therefore this PDF records Tom's intent and a publication path; it does not claim that every current file is already globally licensed.",
            RED,
            colors.HexColor("#FCEEEF"),
        ),
        Spacer(1, 4 * mm),
        p("Proposed statement for Tom to review, approve, and have checked before publication", "h2"),
        Table(
            [[p(
                "<b>Tom Klootwijk | BSN (user-supplied): NL200678942 | Date of birth: 10-07-1990 | Netherlands (NL)</b> states the intent that original UGTOMS specifications, reference implementations, test vectors, schemas, software, and hardware designs that he owns or is authorized to license remain available worldwide, to every person and organization, in every field of use, including commercial use, free of royalties and access fees, in perpetuity.<br/><br/>The intended permissions include use, study, reproduction, modification, execution, compilation, implementation, manufacture, having made, distribution, sale, import, sublicensing, and creation of derivative works. No field of industry or application is excluded. This identity line and declaration are supplied for review and are not independently verified by this report.",
                "quote",
            )]],
            colWidths=[174 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF7F8")),
                ("BOX", (0, 0), (-1, -1), 1, CYAN_DARK),
                ("LEFTPADDING", (0, 0), (-1, -1), 6 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
            ]),
        ),
        p("Essential boundaries", "h2"),
        data_table(
            ["Boundary", "Required meaning"],
            [
                ["Controlled rights only", "The grant can cover only rights Tom actually owns or is authorized to license. Third-party material and inherited licenses remain separate."],
                ["Patent scope", "If method or hardware patent rights are intended, use an explicit patent grant or non-assert reviewed for applicable law. Copyright licenses alone may not be enough."],
                ["Trademark and identity", "Free technical use does not authorize impersonation, false endorsement, or unrestricted use of personal identity and trademarks."],
                ["Safety and compliance", "No warranty, fitness, certification, regulatory approval, or transfer of implementer responsibility is implied."],
                ["Privacy", "This review copy includes personal data supplied by Tom. Produce a redacted public edition unless deliberate publication of those fields is confirmed."],
                ["Legal status", "This is an engineering review draft, not a signed license instrument or legal opinion. Obtain qualified Netherlands/international counsel for the final covenant."],
            ],
            [40 * mm, 134 * mm],
            small=True,
        ),
        PageBreak(),
    ])

    # License actions and close
    story.extend([
        p("Making the intent durable", "h1"),
        p("A perpetual free-use promise becomes practically reusable when the covered materials, rights, licenses, versions, and third-party boundaries are machine-readable and independently auditable.", "body"),
        data_table(
            ["Action", "Recommended implementation"],
            [
                ["1. Rights inventory", "List original files, contributors, employers/contractors, inherited mechanisms, third-party dependencies, datasets, trademarks, and any patent claims."],
                ["2. Choose code license", "Apache-2.0 if an express standardized patent grant is desired, or MIT if simplicity and existing sibling-project precedent are preferred. Counsel should decide."],
                ["3. Choose specification/data license", "CC BY 4.0 if attribution is desired, or CC0 for original material intended for dedication where legally possible. These do not solve patent/trademark scope."],
                ["4. Cover hardware designs", "Adopt an appropriate open hardware license and identify source, design files, preferred form for modification, and patent treatment."],
                ["5. Publish boundaries", "Add top-level LICENSE, NOTICE, THIRD_PARTY, contributor terms, trademark policy, patent covenant if applicable, and SPDX identifiers."],
                ["6. Freeze the grant", "Sign and date the approved covenant, archive an immutable release and hashes, and preserve the exact license text with every distribution."],
                ["7. Separate compatibility from endorsement", "Allow descriptive UGTOMS compatibility claims only after conformance testing; do not imply certification or Tom's endorsement without permission."],
            ],
            [38 * mm, 136 * mm],
        ),
        Spacer(1, 5 * mm),
        callout(
            "Suggested public intent line",
            "UGTOMS original materials that Tom Klootwijk is authorized to license are intended to remain available worldwide, for any field of use including commercial use, without royalties, in perpetuity, subject to the published license terms, applicable law, and third-party rights.",
            GREEN,
            colors.HexColor("#EAF7F2"),
        ),
        Spacer(1, 5 * mm),
        p("Engineering conclusion", "h2"),
        p("The pilot demonstrates that one bounded class of repeated, polar, seed-derived rendering state can be encoded, executed, and measured compactly on a real Mali phone. The cross-domain UGTOMS program is a credible research and engineering agenda. It is not yet empirical proof of universal compression, manufacturing conformance, safety, or legal ownership.", "body"),
        p("The next defensible milestone is not a universal claim. It is a small cross-domain conformance pack: one digital scene recipe, one procedural/residual mesh or texture, one 3MF lattice coupon, one STEP parameter family, and one provenance record, all with exact bytes, independent readers, materialized outputs, tolerances, and measured cost.", "body"),
        PageBreak(),
    ])

    # References
    references = [
        ("[E1]", "Preserved Grow v4 evidence", "build/release-handoff/20260830T023441Z-polar-grow/evidence.json"),
        ("[E2]", "Preserved facts and device screenshot", "build/release-handoff/20260830T023441Z-polar-grow/facts.json and device-screenshot.png"),
        ("[E3]", "Grow contract", "spec/POLAR_GLOW_GROW_V4_CONTRACT.md"),
        ("[E4]", "Polar Material Bands contract", "spec/POLAR_MATERIAL_BANDS_V1_CONTRACT.md"),
        ("[E5]", "Substrate mechanism map and worklog", "docs/UGTS_SUBSTRATE_MECHANISM_MAP.md and docs/UGTS_ENGINE_WORKLOG.md"),
        ("[E6]", "GSP4-derived game-engine cone gate and provenance", "README.md and docs/ATTRIBUTION_NOTICE.md"),
        ("[P1]", "GSP4 package summary and architecture", "[PARENT]/gsp4_spatial_kd_v0.5.0/gsp4_spatial_kd_v0.5.0/PACKAGE_SUMMARY.json and docs/GSP4_ARCHITECTURE.md"),
        ("[P2]", "GSP4 source mapping, bridge, and validation", "[PARENT]/gsp4_spatial_kd_v0.5.0/gsp4_spatial_kd_v0.5.0/docs/SOURCE_TO_CODE_MAPPING.md, src/ugts_spatial/ugts_bridge.py, and results/validation/final_validation.json"),
        ("[P3]", "UGTS-GN 1.1 contract and derived metrics", "[PARENT]/Unified_Geometric_Topological_Substrate_GPU_Native_Package/UGTS_GPU_Native_Addendum_Package/spec/UGTS_GN_1.1.md and benchmarks/derived_metrics.json"),
        ("[P4]", "UGTS-GN physical RTX report and claim ledger", "[PARENT]/Unified_Geometric_Topological_Substrate_GPU_Native_Package/UGTS_GPU_Native_Addendum_Package/benchmarks/PHYSICAL_GPU_REPORT_RTX_5070_TI_LAPTOP.md and spec/claims_ledger.csv"),
        ("[P5]", "KLB full SGP4/SDP4 source and physical logs", "[PARENT]/klb_seedchain_gpu_v0.5.0_full_sgp4/klb_seedchain_gpu_v0.5.0_full_sgp4/src/sgp4.cpp and verification_sgp4_2gib_console.txt"),
        ("[P6]", "Poco KSEED device metrics and explanation", "[PARENT]/UGTS_KC_4_1_Poco_X7_Pro_Seed_Native_Package/UGTS_KC_4_1_Poco_X7_Pro_Seed_Native/validation/device_poco_x7_pro_2026-08-28/performance_metrics.json and PERFORMANCE_ELI5.md"),
        ("[P7]", "Foundation Unicode v5 overview and validation", "[PARENT]/UGTS__FOUNDATION__UNICODE_v5/UGTS__FOUNDATION__UNICODE_SET_FIELD_KLEIN_CONVERSE__v5.0.0__2026-08-29/README.md and validation/cli_verify.json"),
        ("[P8]", "UGTS-KC 2.0 mechanism catalog and validation", "[PARENT]/UGTS_KC_2_0_Tom_Klootwijk_Package/UGTS_KC_2_0_Tom_Klootwijk_Package/spec/extended_mechanism_catalog.csv and validation/test_summary.json"),
        ("[P9]", "Two Hands 3.0 release validation", "[PARENT]/UGTS_KC_Two_Hands_3_0_Package/UGTS_KC_Two_Hands_3_0_Package/validation/release_summary.json"),
        ("[S1]", "Shannon - communication and statistical structure", "https://doi.org/10.1002/j.1538-7305.1948.tb01338.x"),
        ("[S2]", "farbrausch - operator DAG and executable compression practice", "https://www.farbrausch.de/~fg/seminars/workcompression_download.pdf"),
        ("[S3]", "Khronos glTF 2.0 specification", "https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html"),
        ("[S4]", "Khronos KTX 2.0 specification", "https://registry.khronos.org/KTX/specs/2.0/ktxspec.v2.html"),
        ("[S5]", "OpenUSD documentation", "https://openusd.org/release/"),
        ("[S6]", "ISO STEP AP242", "https://www.iso.org/standard/84300.html"),
        ("[S7]", "3MF specification suite", "https://3mf.io/spec/"),
        ("[S8]", "ISO/ASTM AMF", "https://committee.iso.org/standard/74640.html"),
        ("[S9]", "NIST RS274NGC interpreter", "https://www.nist.gov/publications/nist-rs274ngc-interpreter-version-3"),
        ("[S10]", "ISO 14649-10 STEP-NC", "https://www.iso.org/standard/40895.html"),
        ("[S11]", "OPC UA overview and concepts", "https://reference.opcfoundation.org/specs/OPC-10000-1/4"),
        ("[S12]", "buildingSMART IFC standards", "https://www.buildingsmart.org/standards/bsi-standards/industry-foundation-classes/"),
        ("[S13]", "OGC CityGML 3.0", "https://docs.ogc.org/is/20-010/20-010.html"),
        ("[S14]", "HDF5 data model", "https://portal.hdfgroup.org/documentation/hdf5/latest/_h5_d_m__u_g.html"),
        ("[S15]", "DICOM current standard", "https://www.dicomstandard.org/current/"),
        ("[S16]", "W3C PROV overview", "https://www.w3.org/TR/prov-overview/"),
        ("[L1]", "Apache License 2.0", "https://www.apache.org/licenses/LICENSE-2.0.html"),
        ("[L2]", "Creative Commons Attribution 4.0", "https://creativecommons.org/licenses/by/4.0/legalcode.en"),
        ("[L3]", "Creative Commons CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/legalcode.en"),
    ]
    story.extend([
        p("Local and parent-corpus evidence register", "h1"),
        p("Local evidence paths are relative to the UGTS_KC_K_Kij_T_Grove_3_9_2_COMPLETE_ALL_FILES workspace. [PARENT] means C:/Tom Klootwijk super secret substrate club hush hush. These sources support the measured, implemented, and cross-corpus statements in this review; a path entry is not an independent provenance or ownership determination.", "body"),
        data_table(
            ["ID", "Source", "Path"],
            [[ref, title, url] for ref, title, url in references[:15]],
            [14 * mm, 63 * mm, 97 * mm],
            small=True,
        ),
        Spacer(1, 4 * mm),
        callout(
            "Corpus audit rule",
            "Direct implementation, physical-device evidence, calculation, inference, projection, and hypothesis are kept separate. Conflicts between stale summaries and later evidence are reported as reconciliation work, not silently resolved in favor of the stronger claim.",
            CYAN,
        ),
        PageBreak(),
        p("External standards and licensing references", "h1"),
        p("External sources are primary specifications, standards bodies, or original technical sources where practical. Listing a standard does not claim current UGTOMS compliance, endorsement, adoption, or ownership.", "body"),
        data_table(
            ["ID", "Source", "URL"],
            [[ref, title, f"<link href='{url}' color='#007F8E'>{url}</link>"] for ref, title, url in references[15:]],
            [14 * mm, 63 * mm, 97 * mm],
            small=True,
        ),
        Spacer(1, 4 * mm),
        p("Method note", "h2"),
        p("Measured values were taken from preserved evidence artifacts and audit records in the named current and parent workspaces. Calculated percentages and ratios use those bytes directly. Worktree status is separated from physical-device evidence. Cross-corpus recurrence is an architectural inference; separate profile formats are not presented as interoperable. Scenario reductions use the displayed formula and assumptions. Cross-domain opportunities are hypotheses, not validated codecs or compliance claims.", "body_tight"),
        p("Document status: private review draft v0.1. Generated 30 August 2026.", "right"),
    ])

    return story


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title="UGTOMS Cross-Domain Pilot Overview - Review Draft",
        author="Tom Klootwijk",
        subject="UGTOMS cross-domain architecture, pilot metrics, projections, and open-use intent",
    )
    doc.build(build_story(), onFirstPage=cover_page, onLaterPages=later_page)
    print(OUTPUT)


if __name__ == "__main__":
    main()
