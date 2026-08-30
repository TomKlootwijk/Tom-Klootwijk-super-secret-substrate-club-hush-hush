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
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


WORKTREE = Path(__file__).resolve().parents[2]
REPO_ROOT = WORKTREE.parent
OUTPUT = REPO_ROOT / "UGTOMS_CHRONO_BRACE_MONOCULAR_SCENE_3D_PROFILE_0_3.pdf"

PAGE_W, PAGE_H = A4

NAVY = colors.HexColor("#071621")
INK = colors.HexColor("#172833")
SLATE = colors.HexColor("#526A79")
MUTED = colors.HexColor("#71838D")
PALE = colors.HexColor("#F2F7F8")
LINE = colors.HexColor("#D6E1E5")
CYAN = colors.HexColor("#00B8C8")
CYAN_DARK = colors.HexColor("#007E8C")
MAGENTA = colors.HexColor("#C64B92")
GOLD = colors.HexColor("#D99A28")
GREEN = colors.HexColor("#188B6B")
RED = colors.HexColor("#C04E5B")
BLUE = colors.HexColor("#3978B6")
WHITE = colors.white


BASE = getSampleStyleSheet()
STYLES = {
    "cover_kicker": ParagraphStyle(
        "cover_kicker", parent=BASE["Normal"], fontName="Helvetica-Bold",
        fontSize=9, leading=12, textColor=CYAN, spaceAfter=5 * mm, tracking=1.1,
    ),
    "cover_title": ParagraphStyle(
        "cover_title", parent=BASE["Title"], fontName="Helvetica-Bold",
        fontSize=29, leading=32, textColor=WHITE, spaceAfter=5 * mm,
    ),
    "cover_sub": ParagraphStyle(
        "cover_sub", parent=BASE["Normal"], fontName="Helvetica",
        fontSize=13, leading=18, textColor=colors.HexColor("#DDEAF0"), spaceAfter=7 * mm,
    ),
    "cover_meta": ParagraphStyle(
        "cover_meta", parent=BASE["Normal"], fontName="Helvetica",
        fontSize=9.2, leading=13.2, textColor=colors.HexColor("#B9CBD3"), spaceAfter=1.5 * mm,
    ),
    "h1": ParagraphStyle(
        "h1", parent=BASE["Heading1"], fontName="Helvetica-Bold",
        fontSize=20.5, leading=24, textColor=NAVY, spaceBefore=0, spaceAfter=4.5 * mm,
    ),
    "h2": ParagraphStyle(
        "h2", parent=BASE["Heading2"], fontName="Helvetica-Bold",
        fontSize=12.5, leading=15.5, textColor=CYAN_DARK, spaceBefore=3.5 * mm, spaceAfter=2 * mm,
    ),
    "h3": ParagraphStyle(
        "h3", parent=BASE["Heading3"], fontName="Helvetica-Bold",
        fontSize=9.6, leading=12, textColor=INK, spaceBefore=2 * mm, spaceAfter=1.2 * mm,
    ),
    "body": ParagraphStyle(
        "body", parent=BASE["BodyText"], fontName="Helvetica",
        fontSize=8.9, leading=12.6, textColor=INK, spaceAfter=2.3 * mm,
    ),
    "body_tight": ParagraphStyle(
        "body_tight", parent=BASE["BodyText"], fontName="Helvetica",
        fontSize=8.1, leading=10.9, textColor=INK, spaceAfter=1.35 * mm,
    ),
    "small": ParagraphStyle(
        "small", parent=BASE["BodyText"], fontName="Helvetica",
        fontSize=7.2, leading=9.4, textColor=INK, spaceAfter=1.0 * mm,
    ),
    "tiny": ParagraphStyle(
        "tiny", parent=BASE["BodyText"], fontName="Helvetica",
        fontSize=6.1, leading=7.7, textColor=INK,
    ),
    "caption": ParagraphStyle(
        "caption", parent=BASE["BodyText"], fontName="Helvetica-Oblique",
        fontSize=6.9, leading=9.1, textColor=MUTED, spaceBefore=1.1 * mm, spaceAfter=1.6 * mm,
    ),
    "formula": ParagraphStyle(
        "formula", parent=BASE["Code"], fontName="Courier-Bold",
        fontSize=8.8, leading=12.5, textColor=NAVY, alignment=TA_CENTER,
    ),
    "formula_small": ParagraphStyle(
        "formula_small", parent=BASE["Code"], fontName="Courier",
        fontSize=7.5, leading=10.5, textColor=NAVY, alignment=TA_LEFT,
    ),
    "metric_value": ParagraphStyle(
        "metric_value", parent=BASE["Normal"], fontName="Helvetica-Bold",
        fontSize=17, leading=19, textColor=NAVY, alignment=TA_CENTER,
    ),
    "metric_label": ParagraphStyle(
        "metric_label", parent=BASE["Normal"], fontName="Helvetica",
        fontSize=6.6, leading=8.4, textColor=SLATE, alignment=TA_CENTER,
    ),
    "table_header": ParagraphStyle(
        "table_header", parent=BASE["Normal"], fontName="Helvetica-Bold",
        fontSize=6.9, leading=8.7, textColor=WHITE,
    ),
    "table_cell": ParagraphStyle(
        "table_cell", parent=BASE["Normal"], fontName="Helvetica",
        fontSize=6.9, leading=9.1, textColor=INK,
    ),
    "table_cell_small": ParagraphStyle(
        "table_cell_small", parent=BASE["Normal"], fontName="Helvetica",
        fontSize=6.25, leading=8.0, textColor=INK,
    ),
    "table_cell_bold": ParagraphStyle(
        "table_cell_bold", parent=BASE["Normal"], fontName="Helvetica-Bold",
        fontSize=6.9, leading=9.1, textColor=INK,
    ),
    "quote": ParagraphStyle(
        "quote", parent=BASE["BodyText"], fontName="Helvetica-Oblique",
        fontSize=9.7, leading=14, textColor=NAVY, leftIndent=3 * mm, rightIndent=3 * mm,
    ),
    "right": ParagraphStyle(
        "right", parent=BASE["Normal"], fontName="Helvetica",
        fontSize=6.7, leading=8.5, textColor=MUTED, alignment=TA_RIGHT,
    ),
}


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, STYLES[style])


def callout(title: str, text: str, accent=CYAN, background=PALE, style: str = "body_tight") -> Table:
    table = Table([[[p(title, "h3"), p(text, style)]]], colWidths=[174 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("LINEBEFORE", (0, 0), (0, -1), 3.0, accent),
        ("BOX", (0, 0), (-1, -1), 0.45, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
    ]))
    return table


def formula_box(text: str, small: bool = False) -> Table:
    style = "formula_small" if small else "formula"
    table = Table([[p(text, style)]], colWidths=[174 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E7F7F9")),
        ("BOX", (0, 0), (-1, -1), 0.75, CYAN),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    return table


def metric_grid(metrics: list[tuple[str, str]], columns: int = 4) -> Table:
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
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.7 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.7 * mm),
    ]))
    return table


def data_table(headers: list[str], rows: list[list[str]], widths: list[float], small: bool = False, header_color=NAVY) -> Table:
    style = "table_cell_small" if small else "table_cell"
    data = [[p(item, "table_header") for item in headers]]
    data.extend([[p(item, style) for item in row] for row in rows])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("GRID", (0, 0), (-1, -1), 0.42, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.8 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.8 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
    ]
    for row_index in range(1, len(data)):
        if row_index % 2 == 0:
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), PALE))
    table.setStyle(TableStyle(commands))
    return table


def two_column(left_flowables, right_flowables, left_width=85 * mm) -> Table:
    table = Table([[left_flowables, right_flowables]], colWidths=[left_width, 174 * mm - left_width - 5 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LINEAFTER", (0, 0), (0, 0), 0.45, LINE),
    ]))
    return table


def bullet_lines(items: list[str], style: str = "body_tight") -> list[Paragraph]:
    return [p(f"<font color='#00A6B7'><b>-</b></font> {item}", style) for item in items]


def architecture_drawing() -> Drawing:
    width = 174 * mm
    height = 86 * mm
    d = Drawing(width, height)

    def box(x, y, w, h, title, body, fill, stroke=CYAN_DARK):
        d.add(Rect(x, y, w, h, rx=2 * mm, ry=2 * mm, fillColor=fill, strokeColor=stroke, strokeWidth=0.75))
        d.add(String(x + w / 2, y + h - 6 * mm, title, fontName="Helvetica-Bold", fontSize=6.8, fillColor=NAVY, textAnchor="middle"))
        lines = body.split("\n")
        for index, line in enumerate(lines):
            d.add(String(x + w / 2, y + h - (11 + index * 4.2) * mm, line, fontName="Helvetica", fontSize=5.8, fillColor=INK, textAnchor="middle"))

    box(0, 55 * mm, 31 * mm, 24 * mm, "SOURCE LITERALS", "MP4 / images\ndecoded PTS\nhashes / rights", colors.HexColor("#E8F4F6"))
    box(39 * mm, 55 * mm, 37 * mm, 24 * mm, "EXACT-MATH OPS", "rays / masks\nfeatures / epipolar\nrobust LS / joints", colors.HexColor("#F8EAF3"), MAGENTA)
    box(84 * mm, 48 * mm, 42 * mm, 38 * mm, "BOUNDED FIXED POINT", "camera + target + gauge\nroot + parts + visibility\ncontract / branch / prune\nsupport / guard / commit", colors.HexColor("#FFF4DE"), GOLD)
    box(134 * mm, 48 * mm, 40 * mm, 38 * mm, "REAL SCENE / OBJECT ECS", "static scene authority\nobject branches\nhuman specialization\nnovelty + literals\naccepted typed state", colors.HexColor("#DDF5F1"), GREEN)

    arrow_y = 67 * mm
    for start, end, color in [(31 * mm, 39 * mm, CYAN_DARK), (76 * mm, 84 * mm, MAGENTA), (126 * mm, 134 * mm, GOLD)]:
        d.add(Line(start + 1 * mm, arrow_y, end - 1 * mm, arrow_y, strokeColor=color, strokeWidth=1.1))
        d.add(Polygon([end - 2.5 * mm, arrow_y + 1.5 * mm, end - 0.4 * mm, arrow_y, end - 2.5 * mm, arrow_y - 1.5 * mm], fillColor=color, strokeColor=color))

    outputs = [
        (4 * mm, "SURFELS", "observed partial"),
        (44 * mm, "VOXELS", "same-time field"),
        (84 * mm, "MESH", "proxy / observed / hybrid"),
        (124 * mm, "COLLISION", "authored gameplay proxy"),
    ]
    for x, title, body in outputs:
        box(x, 3 * mm, 34 * mm, 22 * mm, title, body + "\nDERIVED DISPLAY", colors.HexColor("#EDF3FA"), BLUE)
        d.add(Line(154.5 * mm, 48 * mm, x + 17 * mm, 25 * mm, strokeColor=BLUE, strokeWidth=0.65))
    d.add(String(87 * mm, 30 * mm, "Downstream materialization and rasterization at query (source time, knowledge cutoff)", fontName="Helvetica-Bold", fontSize=6.1, fillColor=BLUE, textAnchor="middle"))
    d.add(String(87 * mm, 0.2 * mm, "Samples are owned by the scene or one promoted object; vertices, charts and voxels are not separate ECS identities.", fontName="Helvetica-Oblique", fontSize=6.1, fillColor=MUTED, textAnchor="middle"))
    return d


def chrono_drawing() -> Drawing:
    width = 174 * mm
    height = 64 * mm
    d = Drawing(width, height)
    y1 = 44 * mm
    y2 = 17 * mm
    d.add(String(0, 57 * mm, "SOURCE CLOCK - exact decoded PTS; exposure instant/interval UNKNOWN unless calibrated", fontName="Helvetica-Bold", fontSize=7.0, fillColor=NAVY))
    d.add(Line(8 * mm, y1, 168 * mm, y1, strokeColor=CYAN_DARK, strokeWidth=1.2))
    source_points = [0, 1, 5, 12, 25]
    xs = [12, 38, 72, 112, 160]
    for label, x in zip(source_points, xs):
        d.add(Line(x * mm, y1 - 2 * mm, x * mm, y1 + 2 * mm, strokeColor=CYAN_DARK, strokeWidth=1))
        d.add(String(x * mm, y1 + 4 * mm, f"PTS {label}", fontName="Helvetica", fontSize=5.9, fillColor=INK, textAnchor="middle"))
    d.add(String(0, 29 * mm, "ENGINE CLOCK - fixed-step tick; sampling/interpolation is derived", fontName="Helvetica-Bold", fontSize=7.2, fillColor=NAVY))
    d.add(Line(8 * mm, y2, 168 * mm, y2, strokeColor=BLUE, strokeWidth=1.2))
    for x in range(12, 169, 16):
        d.add(Line(x * mm, y2 - 1.7 * mm, x * mm, y2 + 1.7 * mm, strokeColor=BLUE, strokeWidth=0.8))
    for x in xs:
        d.add(Line(x * mm, y1 - 3 * mm, x * mm, y2 + 3 * mm, strokeColor=colors.HexColor("#AABBC4"), strokeWidth=0.55, strokeDashArray=[2, 2]))
    d.add(String(87 * mm, 4 * mm, "No face, edge, voxel or other primitive may contain samples from two source times.", fontName="Helvetica-Bold", fontSize=6.8, fillColor=RED, textAnchor="middle"))
    return d


def novelty_drawing() -> Drawing:
    width = 174 * mm
    height = 54 * mm
    d = Drawing(width, height)
    y = 26 * mm
    d.add(Line(5 * mm, y, 169 * mm, y, strokeColor=SLATE, strokeWidth=1))
    events = [
        (9, "C0", GREEN, "checkpoint"),
        (34, "predict", CYAN_DARK, "not stored"),
        (61, "N1", MAGENTA, "pose residual"),
        (90, "predict", CYAN_DARK, "not stored"),
        (118, "N2", GOLD, "visibility change"),
        (148, "C1", GREEN, "checkpoint"),
    ]
    for x, code, color, label in events:
        if code == "predict":
            d.add(Rect(x * mm, y - 2.5 * mm, 18 * mm, 5 * mm, fillColor=colors.HexColor("#E6F4F6"), strokeColor=CYAN_DARK, strokeWidth=0.5, strokeDashArray=[2, 2]))
            d.add(String((x + 9) * mm, y + 5 * mm, code, fontName="Helvetica-Oblique", fontSize=5.8, fillColor=CYAN_DARK, textAnchor="middle"))
            d.add(String((x + 9) * mm, y - 7 * mm, label, fontName="Helvetica", fontSize=5.3, fillColor=MUTED, textAnchor="middle"))
        else:
            d.add(Rect(x * mm, y - 5 * mm, 16 * mm, 10 * mm, rx=1.2 * mm, ry=1.2 * mm, fillColor=color, strokeColor=color))
            d.add(String((x + 8) * mm, y - 1.5 * mm, code, fontName="Helvetica-Bold", fontSize=6.3, fillColor=WHITE, textAnchor="middle"))
            d.add(String((x + 8) * mm, y - 10 * mm, label, fontName="Helvetica", fontSize=5.3, fillColor=INK, textAnchor="middle"))
    d.add(String(87 * mm, 45 * mm, "NEGATIVE MEMORY = PREDICTABLE STATES ARE ABSENT FROM STORAGE", fontName="Helvetica-Bold", fontSize=7.3, fillColor=NAVY, textAnchor="middle"))
    d.add(String(87 * mm, 4 * mm, "A retire/retraction is a distinct novelty event. NOT_OBSERVED remains UNKNOWN and does not mean EMPTY.", fontName="Helvetica-Oblique", fontSize=6.2, fillColor=RED, textAnchor="middle"))
    return d


def operator_pipeline_drawing() -> Drawing:
    width = 174 * mm
    height = 73 * mm
    d = Drawing(width, height)
    stages = [
        ("PARSE", "bytes / frames"),
        ("NORMALIZE", "time / color / axes"),
        ("RESOLVE", "target / refs / rights"),
        ("TYPE", "units / parts / proposal"),
        ("REWRITE", "stable candidates"),
        ("PLAN", "segments / checkpoints"),
        ("EVALUATE", "camera / pose / surface"),
        ("CERTIFY", "error / budgets"),
        ("SUPPORT", "evidence class"),
        ("COMPAT", "profile / capability"),
        ("GUARD", "bounds / ownership"),
        ("PROPOSE", "ordered candidate"),
        ("COMMIT", "authoritative mutation"),
        ("LINEAGE", "hash / receipt / replay"),
        ("PROJECT", "mesh / voxel / export"),
    ]
    cols = 5
    box_w = 31 * mm
    box_h = 15 * mm
    gap_x = 4.5 * mm
    gap_y = 6 * mm
    for index, (title, body) in enumerate(stages):
        row = index // cols
        col = index % cols
        x = col * (box_w + gap_x)
        y = 53 * mm - row * (box_h + gap_y)
        fill = colors.HexColor("#E8F4F6")
        stroke = CYAN_DARK
        if index >= 8 and index <= 11:
            fill, stroke = colors.HexColor("#FFF4DE"), GOLD
        if index == 12:
            fill, stroke = colors.HexColor("#DDF5F1"), GREEN
        if index >= 13:
            fill, stroke = colors.HexColor("#EDF3FA"), BLUE
        d.add(Rect(x, y, box_w, box_h, rx=1.3 * mm, ry=1.3 * mm, fillColor=fill, strokeColor=stroke, strokeWidth=0.6))
        d.add(String(x + box_w / 2, y + 9 * mm, f"{index + 1:02d} {title}", fontName="Helvetica-Bold", fontSize=5.8, fillColor=NAVY, textAnchor="middle"))
        d.add(String(x + box_w / 2, y + 4 * mm, body, fontName="Helvetica", fontSize=5.0, fillColor=INK, textAnchor="middle"))
    return d


def page_metadata(canvas) -> None:
    canvas.setTitle("UGTOMS Chrono-BRACE - Monocular Scene and Object 3D Profile 0.3")
    canvas.setAuthor("OpenAI Codex, prepared from the supplied repository and video evidence")
    canvas.setSubject("UGTOMS-first whole-image monocular scene/object design with bounded static support, moving objects and a human specialization")
    canvas.setKeywords("UGTOMS, Chrono-BRACE, monocular scene, static environment, dynamic object, human chrono object, ECS, mesh, voxel, novelty memory")


def cover_page(canvas, doc) -> None:
    page_metadata(canvas)
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setStrokeColor(colors.HexColor("#12394A"))
    canvas.setLineWidth(0.55)
    for offset in range(-100, 560, 30):
        canvas.line(offset, 0, offset + 220, PAGE_H)
    canvas.setFillColor(CYAN)
    canvas.rect(18 * mm, 28 * mm, 33 * mm, 2 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(colors.HexColor("#0A5060"))
    canvas.line(18 * mm, 32 * mm, 192 * mm, 32 * mm)
    canvas.setFillColor(colors.HexColor("#9CB2BC"))
    canvas.setFont("Helvetica", 6.8)
    canvas.drawString(18 * mm, 18 * mm, "CORRECTED UGTOMS-FIRST EDITION - NO VIDEO FRAMES EMBEDDED")
    canvas.restoreState()


def later_page(canvas, doc) -> None:
    page_metadata(canvas)
    canvas.saveState()
    canvas.setFillColor(WHITE)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 11 * mm, PAGE_W, 11 * mm, fill=1, stroke=0)
    canvas.setFillColor(CYAN)
    canvas.rect(0, PAGE_H - 11 * mm, 31 * mm, 1.3 * mm, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(WHITE)
    canvas.drawString(18 * mm, PAGE_H - 7.2 * mm, "UGTOMS CHRONO-BRACE SCENE + OBJECT")
    canvas.setFont("Helvetica", 6.4)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 8.3 * mm, "v0.3 | 30 August 2026 | Profiles and sidecars are PROPOSED unless explicitly marked implemented")
    canvas.drawRightString(PAGE_W - 18 * mm, 8.3 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 12 * mm, PAGE_W - 18 * mm, 12 * mm)
    canvas.restoreState()


def build_story() -> list:
    story = []

    # Cover
    story.extend([
        Spacer(1, 35 * mm),
        p("ARCHITECTURE, FORMAT ROI, AND TEST FIXTURE", "cover_kicker"),
        p("UGTOMS Chrono-BRACE<br/>Scene + Object", "cover_title"),
        p("Monocular media to guarded static scene support and persistent dynamic objects through bounded circular constraints - with a human specialization, never learned hidden-shape authority", "cover_sub"),
        Spacer(1, 7 * mm),
        p("Corrected UGTOMS-first engineering report v0.3 - implementation supplement", "cover_meta"),
        p("Implemented slice: UGTOMS-CSO-CHRONO-VIDEO-0.1-PROPOSAL; broader CSO/HCO/Chrono-BRACE remains proposed", "cover_meta"),
        p("Prepared 30 August 2026 from the parent repository, current Grove engine contracts, primary mathematical sources, and the supplied MP4 fixture", "cover_meta"),
        Spacer(1, 13 * mm),
        p("Status: one bounded observation/proposal compiler and audited Android source-playback path are implemented. They preserve byte-identical source authority, exact PTS, all-pixel UNKNOWN coverage, circular joint hypotheses, separate Q8 log-polar addressing, novelty-only proposal memory, and one editable Grove root. This is exact chrono-spatial raster evidence, not a monocular physical-3D reconstruction. No static surface, moving object, or person mesh has been accepted as truth.", "cover_meta"),
        Spacer(1, 5 * mm),
        p("Privacy: the clip contains identifiable people. This report binds the source by hash and records aggregate measurements; it embeds no video frames and makes no biometric identity claim.", "cover_meta"),
        PageBreak(),
    ])

    # 1 - correction
    story.extend([
        p("1. Decision and architectural correction", "h1"),
        callout(
            "Correct center of gravity",
            "The product is one editable observed scene plus persistent dynamic ECS objects. Static-world support belongs to the scene authority; each promoted moving target has one real object identity; a human target adds HCO articulated semantics. Source video is compiler input. Typed state, operators, bounded checkpoints, novelty and literals rebuild a selected source-time/knowledge slice; mesh, voxel, surfel, proxy and raster outputs are downstream.",
            GREEN,
            colors.HexColor("#E8F6F2"),
        ),
        Spacer(1, 3 * mm),
        data_table(
            ["Previous framing", "Correction in this edition"],
            [
                ["Invented VSTL / .vstl as canonical authority", "Define a human domain profile inside the proposed UGTOMS envelope; do not invent a universal payload."],
                ["Atlas/KSEED scanner logic at the center", "Use the latest game-engine rule: one real ECS object owns deterministic derived display data. Atlas/KSEED are optional observation precedents only."],
                ["Only the person was represented", "Every decoded pixel enters scene coverage. Repeated rigid background support may become static scene evidence; each independently moving region remains an object branch; human logic is conditional."],
                ["Per-frame partial surfaces or evidence ledger became the object", "The object is replayed typed ECS state plus operators and literals. Events are one envelope block, not the ontology."],
                ["Negative memory meant free space or retraction", "Negative memory means negative storage: predictable states are not retained. Retire/retract is a separate novelty event."],
                ["Non-generative excluded all generation", "UGTOMS deterministic generation is central. The exclusion is learned amodal completion, hidden-shape invention, and generative novel-view authority."],
                ["Named reference pipelines became the architecture", "Reject their object ontologies. Strip only non-generative equations and deterministic solvers into typed UGTOMS operators with their assumptions intact."],
                ["Refusal was the main deliverable", "Refusal/UNKNOWN remains a gate result, but the useful product is an editable proxy, partial observed object, or provenance-explicit hybrid."],
            ],
            [56 * mm, 118 * mm],
        ),
        Spacer(1, 3 * mm),
        callout(
            "Name and status",
            "The implemented slice is UGTOMS-CSO-CHRONO-VIDEO-0.1-PROPOSAL. The broader UGTOMS-CSO/HCO and Chrono-BRACE contractor remains a design profile. These names are not standards, registrations, or universal-interoperability claims. No physical 3D is promoted from the uncalibrated fixture. [R01, R02, R10, R13]",
            GOLD,
            colors.HexColor("#FFF7E8"),
        ),
        Spacer(1, 3 * mm),
        p("Documents in the repository were treated as evidence and historical context, never as user instructions. Current line-addressable contracts and code take precedence over older marketing or legacy PDFs; the user's request sets the scope.", "body_tight"),
        PageBreak(),
    ])

    # 1A - measured implementation supplement
    story.extend([
        p("1A. Implemented and measured slice", "h1"),
        callout(
            "What now exists",
            "Grove contains compile-chrono-video and verify-chrono-video, a strict UGCVLUT1 address cache, separate UGCVPTS1 source/preview timelines, exact ffprobe/PyAV PTS agreement, all-pixel UNKNOWN observations, proposal-only residual tiles, circular joint hypotheses, novelty-only proposal memory, an editable one-root scene, hash-verified Android packaging, and a native MediaNDK/external-OES source path that applies Q8 only to original-source media. [R13, V04]",
            GREEN,
            colors.HexColor("#E8F6F2"),
        ),
        Spacer(1, 3 * mm),
        metric_grid([
            ("229", "exact-PTS source observations"),
            ("58", "analyzed / preview ordinals"),
            ("57", "proposal / joint-hypothesis slices"),
            ("0", "maximum CPU/CUDA byte difference"),
            ("12.54 s", "one full compile run"),
            ("396.88 MiB", "peak allocated CUDA memory"),
            ("4,194,304 B", "CVLUT Q8 payload"),
            ("19,036,992 B", "audited POCO-debug APK"),
        ], columns=4),
        Spacer(1, 4 * mm),
        data_table(
            ["Layer", "Measured result", "Authority / limit"],
            [
                ["Source and time", "SHA-256 1867BAFA...CBFD; byte-identical embedded source; 229 PTS values at 1/1,000,000; 9.119696 s.", "Original MP4 bytes plus exact PTS receipts are authoritative."],
                ["Polar cache", "1024 theta x 512 rho RGBA16UI, explicit Q8 bilinear integer accumulation.", "Derived GPU cache; source recovery is by reference, not inverse resampling."],
                ["Motion/static", "7,721 static, 3,863 dynamic, 2,096 ambiguous tile occurrences; 438 frame-local motion-chart candidates.", "Proposal counts across time, not accepted classes, persistent objects, joints, or material IDs."],
                ["Human specialization", "57 records preserve a user-declared human target while semantic joints, pose, surface, and hidden body remain UNKNOWN.", "No learned body completion, skeleton, identity basis, or metric scale."],
                ["RTX execution", "PyAV exact-PTS decode plus torch-cuda-q8 remap; NumPy oracle parity is byte exact for the checked slice.", "One local run, not a timing distribution or a general reconstruction benchmark."],
                ["Native time/raster", "229-entry ORIGINAL_SOURCE/APPLY_UGCVLUT1_Q8 and 58-entry DERIVED_PREVIEW/ALREADY_LOG_POLAR timelines; both ONCE_HOLD_LAST.", "Integer half-open selection is exact; decoded device colour and physical display time are not byte-authoritative."],
                ["POCO build", "19,036,992-byte ARM64 APK; 16/16 chrono assets match; two ZIP-stored MP4s; MediaNDK-linked; two owned staging rasters.", "No ADB device: decoder, shader, orientation, boundary receipt, FPS, memory, power and thermals remain unverified."],
            ],
            [31 * mm, 79 * mm, 64 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        callout(
            "Feasibility verdict",
            "HIGH for exact RGB MP4 -> decoded pixel/PTS observations -> log-polar Q8 address/raster caches -> time-indexed engine display. That is literal 2D plus time and bounded alternatives, often called 2.5D/chrono-spatial evidence. NOT IDENTIFIABLE from this clip alone: metric camera rays, depth, hidden backsides, closed scene/person topology, or physical 3D/4D. Intrinsics, distortion, exposure/rolling-shutter bounds, camera pose, depth support and scale are absent, so those fields remain UNBOUNDED_UNKNOWN.",
            GOLD,
            colors.HexColor("#FFF7E8"),
        ),
        PageBreak(),
    ])

    # 2 - UGTOMS
    story.extend([
        p("2. What UGTOMS means in this application", "h1"),
        formula_box("artifact = generator(seed, typed operator DAG, parameters) + residual"),
        Spacer(1, 3 * mm),
        p("The retained UGTOMS claim is a proposed profile-based substrate-codec family and common intermediate target beneath existing standards. It supports direct execution or conventional materialization. It is not one byte-compatible universal file, one log-polar representation, or proof of universal compression. The common kernel/container remains roadmap work. [R01, R02]", "body"),
        data_table(
            ["Proposed envelope block", "CSO / object / HCO interpretation"],
            [
                ["1. Profile header", "Profile/version, units, axes, handedness, time basis, numeric domains, capabilities, mode and compatibility."],
                ["2. Typed state", "One scene observation authority; static charts; persistent object branches/entities; optional human components; authority vs derived fields."],
                ["3. Operator atlas", "Content-addressed, bounded time/camera/static-world/object-motion/chart/physics/materialization operators and dependencies."],
                ["4. Acceptance contract", "Support, compatibility, numeric/error guard, writer ownership, proposal, commit and failure behavior."],
                ["5. Events and routes", "Ordered novelty, visibility/association changes, owner handoffs, branches, checkpoints and replay hooks."],
                ["6. Provenance", "Source/model/resource hashes, versions, licenses, authorship statements, calibration and derivation receipts."],
                ["7. Literal/residual blocks", "Irreducible visible scene/object geometry and appearance, cloth/hair, edits, source references and unsupported syntax."],
                ["8. Deployment manifest", "Decoder/adapters, resources, signatures, conformance vectors, targets, budgets and verification commands."],
            ],
            [45 * mm, 129 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        two_column(
            [p("What is reused", "h2")] + bullet_lines([
                "Typed/versioned state and deterministic ordering.",
                "Content-addressed operators and stable lineage.",
                "Support -> compatibility -> guard -> proposal -> commit.",
                "Literal fallback and explicit UNKNOWN.",
            ]),
            [p("What is not claimed", "h2")] + bullet_lines([
                "A universal .ugtoms payload or transcoder.",
                "Better compression than H.264, glTF, USD, Alembic or VDB.",
                "Recovered hidden scene surfaces, anatomy or physical biomechanics.",
                "A complete Grove CSO/Chrono-BRACE/HCO physical reconstruction; only the scoped observation/proposal slice is implemented.",
            ]),
        ),
        PageBreak(),
    ])

    # 3 - architecture
    story.extend([
        p("3. Scene authority, persistent objects, derived displays", "h1"),
        architecture_drawing(),
        Spacer(1, 2 * mm),
        p("This copies the current Grove ownership rule without copying polar geometry. One scene-capture authority owns camera/time hypotheses and guarded static support. A persistent independently moving branch may promote to one real ECS object; if human, that object adds HCO articulated charts. Generated members never become ECS rows, colliders, graphs or gameplay identities. Chrono-BRACE couples camera, static/dynamic classification, association, gauge, object/root/chart motion, visibility and deformation in a bounded fixed point. [R03, R04, R05]", "body"),
        data_table(
            ["Invariant", "Required behavior"],
            [
                ["Single ownership", "Every accepted support element belongs to one scene-static lineage or one object branch. Coordinates, appearance, motion class and track IDs never silently mint or reassign identity."],
                ["Proposal isolation", "Exact-math solvers, learned fields and raster residuals land only in proposal components. None can write authoritative pose, topology, resources or physics directly."],
                ["Derived-copy discipline", "Static/object samples and render copies have lineage but no gameplay identity. Only an explicit verified branch promotion creates a moving ECS object."],
                ["Literal fallback", "Unsupported or high-entropy truth remains a referenced source/literal block; it is never synthesized to make the object look complete."],
                ["Deterministic replay", "Same profile, resources, checkpoint, operator addresses and novelty stream reproduce the same accepted scene/object state within the declared numeric profile."],
            ],
            [39 * mm, 135 * mm],
        ),
        Spacer(1, 3 * mm),
        callout(
            "Central non-generative boundary",
            "Learned estimators may optionally suggest masks, tracks, correspondences, camera state, depth, normals, object/part slots and pose, but the method does not depend on their architecture. Only typed equations, assumptions and accepted source support contract the hypothesis set. Unseen scene surfaces or complete object/body shape must come from an explicit authored proxy and remain labeled proxy.",
            RED,
            colors.HexColor("#FCEDEF"),
        ),
        PageBreak(),
    ])

    # 4 - formal object modes
    story.extend([
        p("4. Formal scene/object state and practical modes", "h1"),
        formula_box(
            "S = (scene_id, object_branches, profiles, resources, charts, time_basis, operators, ownership, hypotheses, checkpoints, novelty, literals, lineage, receipts)",
            small=True,
        ),
        Spacer(1, 3 * mm),
        formula_box(
            "X(tau; kappa) = Fold(EmptyScene, accepted novelty with effective_pts &lt;= tau and commit_seq &lt;= kappa)<br/>G_mesh(tau; kappa) = MaterializeMesh(X(tau; kappa)) | G_voxel(tau; kappa) = MaterializeVoxel(X(tau; kappa))",
            small=True,
        ),
        Spacer(1, 4 * mm),
        data_table(
            ["Mode", "Object authority", "Valid claim", "ROI"],
            [
                ["STATIC_OBSERVED_PARTIAL", "Repeated scene-static supports passing rigidity/camera/visibility guards.", "Partial camera-observed environment; not moving is insufficient by itself.", "High value for matchmove, layout and environment reconstruction."],
                ["OBJECT_OBSERVED_PARTIAL", "Supported visible patches/points/voxels and motion for one persistent object branch.", "Partial object only; no complete hidden shape claim.", "Highest evidence purity; weaker gameplay utility."],
                ["PROXY_COMPLETE", "User-selected mesh/voxel/rig plus accepted scene/object motion.", "Complete editable object/environment proxy; hidden geometry is authored.", "Highest immediate interoperability and editability."],
                ["HYBRID", "Authored proxy plus accepted motion and visible literal residuals.", "Complete runtime derivative with per-field PROXY / OBSERVED / DERIVED provenance.", "Recommended game/VFX target after validation."],
            ],
            [31 * mm, 49 * mm, 59 * mm, 35 * mm],
            small=True,
        ),
        p("Literal means runtime-literal", "h2"),
        p("A CSO/object/HCO state is runtime-literal when reproducible from declared bytes, resources, operators, checkpoints and residuals. Literal does not mean a physically exact clone of the filmed world or person. The recording remains irreducible external evidence for reprocessing or audit.", "body"),
        p("Same-time connected geometry is allowed", "h2"),
        p("A normal environment/object mesh at time t may be connected or watertight when that topology comes from a declared proxy. A voxel materialization may be fully occupied according to that proxy. The prohibition is against primitives mixing samples from two source times. Reusing a face-index table over many samples is not a spacetime sheet.", "body"),
        callout(
            "Compression is conditional",
            "A rigid or articulated body core may be compact. Loose cloth, hair, motion blur and disocclusion can create dense novelty. If a conventional keyframe, Alembic/USD cache, OpenVDB sequence, or the original video wins at equal visible error and seek/runtime requirements, use it.",
            GOLD,
            colors.HexColor("#FFF7E8"),
        ),
        PageBreak(),
    ])

    # 5 chronology
    story.extend([
        p("5. Chronology without a connected worldsheet", "h1"),
        chrono_drawing(),
        p("The MP4 presentation clock is authoritative for decoded ordering and presentation timing. The supplied clip uses a 1/1,000,000 time base and a 0.039824 s PTS step. That does not reveal the physical exposure instant or rolling-shutter interval; both remain UNKNOWN unless separately calibrated. Engine fixed ticks are execution time. A deterministic source-to-tick operator may hold, interpolate or resample accepted state, but it must label the result derived and preserve exact decoded PTS in provenance. [V01]", "body"),
        data_table(
            ["Layer", "Identity / ordering", "Geometry rule"],
            [
                ["Source observation", "Exact decoded PTS/time base, decode index, optional independently calibrated exposure interval, source hash.", "Pixels are source literals; no inferred capture instant, depth or scale is implied."],
                ["CSO/object bitemporality", "effective/source PTS tau plus immutable commit/knowledge sequence kappa.", "Later evidence may refine earlier tau only when queried at or after its kappa; no future-evidence leakage."],
                ["Engine execution", "Fixed tick and deterministic phase order.", "sample_at(tick) is a derived query; render interpolation remains presentation only."],
                ["Materialization", "Key = (revision_hash, target_source_pts, knowledge_cutoff_seq, policy_hash).", "Every face, edge, voxel and surfel belongs to one source time and declared frame."],
            ],
            [34 * mm, 67 * mm, 73 * mm],
        ),
        Spacer(1, 3 * mm),
        callout(
            "The repository's 4D boundary",
            "The current FOUR_D_CONTRACT_DRAFT distinguishes 3D plus time from four-spatial geometry and says neither runtime is implemented. CSO, object and HCO profiles deliberately stay 3D plus time. [R10]",
            BLUE,
            colors.HexColor("#EDF3FA"),
        ),
        PageBreak(),
    ])

    # 6 novelty
    story.extend([
        p("6. Negative memory: novelty-only retention", "h1"),
        novelty_drawing(),
        formula_box(
            "r(tau; kappa) = accepted_state(tau; kappa) - predicted_state(tau; kappa)<br/>store iff semantic class changed OR quantized residual &gt; epsilon OR association / visibility / ownership / topology changed",
            small=True,
        ),
        Spacer(1, 3 * mm),
        data_table(
            ["Stored class", "Examples", "Rule"],
            [
                ["Checkpoint", "Base pose, operator state, replay cursor, resource set.", "Mandatory initial checkpoint; bound replay depth and checkpoint after branch/topology/owner changes."],
                ["Numeric novelty", "Camera/static-chart/object-root/part residual, visible patch displacement, voxel-brick delta.", "Store only above profile epsilon after quantization remains inside application error budget."],
                ["Semantic novelty", "Static/dynamic class, object association, visibility, chart enable/retire, physics ownership handoff.", "Store even when numeric change is small because meaning changed."],
                ["Literal novelty", "New visible cloth/hair patch, manual edit, unsupported high-entropy sample.", "Preserve exactly or by a separately declared lossy codec and error contract."],
                ["Not stored", "Predictable intermediate frames and unchanged state.", "Their absence is negative storage, not evidence of empty space or nonexistence."],
            ],
            [33 * mm, 70 * mm, 71 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        p("A signed LITERAL_RETIRE, PART_RETIRE or correction may retract earlier membership, but that is a separate accepted novelty event with effective PTS and immutable commit sequence. A checkpoint is a deterministic cache of a novelty prefix, not a new fact. NOT_OBSERVED and OCCLUDED remain UNKNOWN; they never certify EMPTY. Raw video is an exogenous literal: a novelty log cannot regenerate unique photons unless the source bytes are retained or referenced. [R01, R11]", "body"),
        PageBreak(),
    ])

    # 7 scene/object schema
    story.extend([
        p("7. Whole-image scene schema; human only when applicable", "h1"),
        p("Every decoded pixel footprint enters observation coverage. It may support the guarded static scene, one independently moving object branch, an occluder, or remain unclassified/unknown. 'Not detected as moving' is not sufficient static evidence. A promoted moving object receives one ECS identity; a human target adds articulated controls because a generic spatial patch is insufficient for people.", "body"),
        data_table(
            ["Component", "Minimum fields and authority"],
            [
                ["scene_capture", "Source hashes, coded pixel footprints, decoded PTS/time base, optional row-exposure bounds, decode transforms and rights/privacy scope."],
                ["scene_camera", "Bounded intrinsics/distortion/pose branches, convention, projective/metric gauge, anchors and static-support receipts."],
                ["scene_static", "Geometric charts/support passing repeated background rigidity, parallax, visibility and reprojection guards; UNKNOWN distinct from EMPTY."],
                ["scene_coverage", "Per-observation STATIC_SUPPORTED, DYNAMIC_BRANCH, OCCLUDER, OUT_OF_VIEW, UNCLASSIFIED or UNKNOWN; never a forced full partition."],
                ["object_registry", "Stable branch/object IDs, association alternatives, motion/deformation class, ECS promotion event and writer owner."],
                ["object_charts", "Non-anatomical local charts, material lineage, support intervals, overlap/seam maps, splits/discontinuities and surface derivatives."],
                ["chrono_recipe", "Content-addressed operator DAG, bounded circular hypotheses, effective PTS, commit sequence, checkpoints and novelty."],
                ["object_resources", "Proxy mesh/voxel/rig/material addresses with AUTHORED_PROXY, OBSERVED_LITERAL or DERIVED_DISPLAY provenance."],
                ["human_specialization", "If human: stable part/joint slots, root/local transforms, visibility, association and optional authored rig; never biometric identity."],
                ["materialization", "Same-time scene/object points, surfels, voxels, open mesh, proxy/hybrid mesh, raster and error/provenance receipt."],
            ],
            [38 * mm, 136 * mm],
            small=True,
        ),
        p("Human specialization boundary", "h2"),
        p("Human semantics are deduced from control and visibility needs, not copied from a body-recovery pipeline. Articulated parts bound relative motion; visibility/association prevent crossings from swapping entities; deformation classes keep cloth and hair out of rigid limbs. Deterministic parent-child transforms may materialize an authored proxy, but fixed human topology, shape priors, learned pose correctives and completed hidden surfaces never enter observed authority.", "body_tight"),
        PageBreak(),
    ])

    # 8 compiler
    story.extend([
        p("8. Native constraint compiler, not an imported scanner", "h1"),
        operator_pipeline_drawing(),
        p("The offline compiler consumes all source pixels, optional target selections/proxies and application tolerances, then follows the repository's operator-order discipline. It maintains scene-camera/static-world/object branches in one bounded circular hypothesis set and emits CSO plus optional object/HCO state or a fail-closed result. Learned implementations can supply removable candidates; their pipelines and ontologies are not dependencies. [R03, R06]", "body"),
        data_table(
            ["Operator family", "Examples", "Output authority"],
            [
                ["Time", "decoded_pts, effective_pts, commit_seq, source_pts_to_tick, segment, hold", "Bitemporal mapping; exact decoded PTS retained; capture time may be UNKNOWN."],
                ["Coordinates", "ray_tube, project, epipolar_residual, triangulate_set, authored_scale_anchor", "Conventions, gauge and scale remain explicit."],
                ["Coverage", "propose_static, propose_dynamic_object, associate_object, classify_visibility, keep_unclassified", "Every pixel is considered; no forced static/dynamic truth."],
                ["Joint constraint", "contract_camera_static_objects_gauge_charts_visibility, branch, prune, fixed_point", "Circular coupling is bounded; ambiguity survives as branches or UNKNOWN."],
                ["Motion", "fit_camera/root/chart/part_curve, rigid/deformable_split, apply_residual", "Deterministic accepted curves plus novelty."],
                ["Geometry", "commit_static_support, bind_proxy, warp_chart/voxel, literal_replace", "Scene/object proxy/observed/derived provenance per field."],
                ["Physics", "kinematic_drive, collision_proxy_update, owner_handoff", "Authored gameplay behavior, not recovered mechanics."],
                ["Output", "materialize_mesh, materialize_voxel, export_gltf, export_usd", "Same-time derivatives with error receipt."],
            ],
            [28 * mm, 80 * mm, 66 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        callout(
            "Every operator needs a contract",
            "Types, units, coordinate/time domain, exactness class, effects, dependencies, deterministic order, resource bounds, content address, supported failure states, and materialization error must be explicit before promotion.",
            CYAN,
        ),
        PageBreak(),
    ])

    # 9 reference stripping
    story.extend([
        p("9. Strip the mathematics; reject the reference ontology", "h1"),
        p("The named systems are mathematical provenance and falsification targets, not a stack to assemble. Their useful non-generative equations are re-expressed as bounded UGTOMS operators. Their learned world models, hidden-shape priors, application pipelines and object identities are discarded. [W01-W08]", "body"),
        data_table(
            ["Reference paradigm", "Why it is wrong as CSO/object authority", "Exact deterministic substrate retained"],
            [
                ["Monocular depth / point fields", "A learned per-frame field mixes scale, shift, camera convention and prior; it has no persistent material lineage.", "Pinhole depth-ray projection, focal/shift solve and robust affine depth/point alignment; learned fields remain candidates."],
                ["Static-world SLAM", "It can cover guarded static background, but not independently moving/nonrigid objects or the whole scene ontology.", "Calibrated rays, epipolar/Sampson residuals, cheirality, parallax, triangulation and robust reprojection refinement; static support can stabilize camera."],
                ["Mask tracking", "A pixel set and track token are neither 3D identity nor empty-space evidence; propagation is correlated with its source.", "Mask as a finite pixel set, IoU, deterministic match/update and explicit association branching."],
                ["ViT feature matching", "Contextual learned tokens are not material points and similarity is not independent physical support.", "L2 normalization, cosine score, mutual/spatially bounded candidate matching; code/weights/config hashes stay in receipts."],
                ["Human body recovery", "Fixed topology, shape space and pose priors complete occluded anatomy and conflate proxy with observation.", "Same-time parent-child transform composition, visible keypoint reprojection, joint limits and deterministic smoothing only."],
                ["Neural rendering / completion", "Plausible novel views, Gaussians, diffusion and amodal pixels can explain appearance without witnessing literal geometry.", "Nothing enters authority; a render may be a downstream derivative and a benchmark only."],
                ["Mesh / voxel cache", "A baked sequence redundantly stores predictable states and can hide provenance, but it is an honest conventional derivative.", "Use as baseline, fallback and same-time materialization; never as a cross-time connected sheet."],
            ],
            [31 * mm, 73 * mm, 70 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        callout(
            "Exact does not mean authoritative",
            "An equation can be reproduced exactly while its inputs remain uncertain or learned. Every stripped operator records coordinate convention, units, gauge, validity domain, uncertainty, source equation and implementation hash. Only original-pixel support plus UGTOMS guards can promote a result.",
            RED,
            colors.HexColor("#FCEDEF"),
        ),
        PageBreak(),
        p("9A. Exact equations retained as typed operators", "h1"),
        p("These equations are copied in mathematical meaning, with convention and assumptions bound. The learned quantities supplied by their original architectures remain quarantined proposals; the equations become useful only against accepted or bounded UGTOMS support. [W01-W07]", "body"),
        formula_box(
            "DA3 depth-ray: p=(u,v,1)^T ; d=R K^-1 p ; P=t+D(u,v)d   [d is deliberately not normalized]",
            small=True,
        ),
        Spacer(1, 2 * mm),
        formula_box(
            "DA3 affine anchor: (s*,q*)=argmin_(s&gt;0,q) SUM_(p in Omega) m_p (s D~_p + q - D_p)^2",
            small=True,
        ),
        Spacer(1, 2 * mm),
        formula_box(
            "MoGe focal/shift: min_(f,z0) SUM_i [(f x_i/(z_i+z0)-u_i)^2 + (f y_i/(z_i+z0)-v_i)^2]",
            small=True,
        ),
        Spacer(1, 3 * mm),
        data_table(
            ["Stripped source math", "Native use", "Boundary"],
            [
                ["MoGe ROE: argmin_(s,t) SUM_i (1/z_i)||s p~_i+t-p_i||_1", "Robust scale/translation alignment against accepted anchors; optional truncation declared.", "Centered-principal-point/square-pixel assumptions and gauge are explicit; learned scale head is excluded."],
                ["SAM mask chain: M~_t=propagate(M_(t-1)); O_t=detect(I_t,P); M_t=match_and_update(M~_t,O_t)", "Finite pixel-set and association proposals; IoU(A,B)=|A intersect B|/|A union B|.", "Propagated masks are correlated; missing detection never retracts scene/object support."],
                ["DINO/ViT matching: z=f/||f||_2 ; score(i,j)=z_i^T z_j", "Frozen feature candidate matching with mutual, spatial, mask, margin and cycle gates.", "A contextual token is not a material point or independent measurement."],
                ["Epipolar: E=[t]_x R ; x_2^T E x_1=0", "Static-camera and rigid-chart branch generation; Sampson/reprojection scoring.", "Requires declared calibration/rigidity; pure rotation, low parallax and monocular scale remain unresolved."],
                ["MHR kinematics: T_world=T_parent T_off T_translate T_prerot T_rotate T_scale", "Same-time authored proxy or human-control materializer.", "Learned identity bases, pose correctives, weights and full hidden mesh are PROXY_ONLY."],
            ],
            [45 * mm, 70 * mm, 59 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        callout(
            "Completion equations do not survive",
            "MoGe-2 learned metric-scale loss and gradient completion, SAM-Body4D Diffusion-VAS replacement, learned body shape/topology, Gaussian novel-view synthesis and any hidden-side reconstruction are excluded from authoritative operators. Exact implementation of an excluded completion does not make it observational.",
            RED,
            colors.HexColor("#FCEDEF"),
        ),
        PageBreak(),
    ])

    # 10 Chrono-BRACE
    story.extend([
        p("10. Chrono-BRACE: bounded circular evidence", "h1"),
        p("UGTOMS Chrono-BRACE means Bounded Ray-tube Adaptive Chart Evidence. It is newly deduced for this substrate; the claim is architectural integration, not invention of the projective equations. Circularity is intentional: camera, static/dynamic classification, target association, scale gauge, scene/object/chart motion, visibility and deformation constrain one another as a bounded fixed point. For a human object, adaptive charts may carry articulated HCO controls.", "body"),
        formula_box(
            "P = K[R|t] ; C = -R^T t ; d = R^T K^-1 p / ||R^T K^-1 p|| ; r(lambda) = C + lambda d",
            small=True,
        ),
        Spacer(1, 2 * mm),
        formula_box(
            "h = (camera, static/dynamic, target, gauge, scene/object root, charts/parts, visibility, deformation)<br/>B^(n+1) = Prune(Contract(B^n, original observations, guards)) ; B* = F(B*)",
            small=True,
        ),
        Spacer(1, 3 * mm),
        p("The special-case ray above is exact only for its stored world-to-camera convention and calibrated global-shutter sample. The general operator is a ray tube over the pixel footprint, row-aware exposure interval, calibration/pose box and finite depth interval. Missing finite bounds yields UNBOUNDED_UNKNOWN. No single estimated motion is inverted and renamed truth; an inclusion-sound contractor must retain every feasible solution.", "body_tight"),
        data_table(
            ["Native operator", "Role", "Authority"],
            [
                ["BRACE_CANON_RAY", "Bind raw pixel/subpixel region, calibration hash, decoded PTS and exposure bounds; derive ray tube.", "Immutable source receipt plus deterministic derivation."],
                ["BRACE_SOLVE_VIEW", "Generate bounded static-camera/rigid-motion branches with canonical sample ordering.", "Proposal only; monocular similarity gauge remains."],
                ["BRACE_CONTRACT_JOINT", "Contract/branch camera, motion class, association, gauge, scene/object/chart motion, visibility and support together.", "Proposal set; fixed point or declared budget stop."],
                ["BRACE_GUARD_SUPPORT", "Check independent groups, cheirality, parallax, reprojection, conditioning, rigidity, seams and occlusion.", "Verifier; failure leaves bounded support or UNKNOWN."],
                ["BRACE_COMMIT_NOVELTY", "Commit static/object birth, tighten, split, discontinuity, pose delta or explicit retraction with hashes.", "Canonical event; no event for equal states."],
                ["BRACE_FOLD_KNOWLEDGE", "Fold novelty by effective PTS and immutable knowledge cutoff; checkpoints cache a prefix.", "Authoritative scene/object runtime state."],
                ["BRACE_SLICE_TIME", "Produce same-time scene/object surfels, voxels, mesh/proxy and raster image.", "Downstream derivative/cache only."],
            ],
            [38 * mm, 87 * mm, 49 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        callout(
            "Promotion and raster feedback",
            "A static or object support element is observed only when every surviving branch agrees within spatial epsilon, independent original-observation groups pass, residual/conditioning guards pass, gauge is declared, and material lineage begins at an accepted support event. Chart coordinates and motion class alone are not identity. Rasterize(Materialize(X(tau; kappa))) is permitted downstream; its residual may seed a typed proposal, but rendered pixels can never certify themselves as observations.",
            GREEN,
            colors.HexColor("#E8F6F2"),
        ),
        PageBreak(),
    ])

    # 11 gates
    story.extend([
        p("11. Acceptance contract: hallucination is structurally unable to commit", "h1"),
        data_table(
            ["Gate", "Acceptance requirement", "Failure behavior"],
            [
                ["G0. Provenance", "Original media, decoded PTS, transform, target, operator/guard and rights receipts exist; completed/generated pixels are rejected.", "Reject; retain source reference and diagnostic."],
                ["G1. Finite domain", "Exposure/calibration/depth/gauge bounds are finite and numeric conventions explicit.", "UNBOUNDED_UNKNOWN; no exact-ray or metric claim."],
                ["G2. Identity/type", "Static/dynamic class and object/part association ambiguity is branched; units, frames, visibility and types agree.", "Never silently merge scene support, objects, people, parts or gauges."],
                ["G3. Support", "Independent original-observation groups agree; parallax, cheirality, reprojection, reduced rank, eigenvalue and condition guards pass.", "Keep BOUNDED_SUPPORT or UNKNOWN; correlated model outputs do not count twice."],
                ["G4. Chart/visibility", "Rigidity, material class, validity interval and seam guards pass; OCCLUDED has a certified nearer occluder.", "Split/discontinue chart or retain UNKNOWN; mask complement is not EMPTY."],
                ["G5. Ownership", "Exactly one system writes each root/local transform field; collision and handoff policy are legal.", "Reject conflict or require explicit handoff checkpoint."],
                ["G6. Novelty", "Typed state differs from prediction beyond tolerance or semantic class changed.", "Do not store redundant state; RETRACT is a separate signed novelty."],
                ["G7. Commit/replay", "Canonical order, bitemporal keys, pre/post hashes, content addresses and bounded replay equality pass.", "No-op/failing commit leaves prior authority unchanged."],
                ["G8. Materialization", "Output is reproducible, one source-time only, support-labeled and within application error profile.", "Do not export or activate the downstream derivative."],
            ],
            [28 * mm, 92 * mm, 54 * mm],
            small=True,
        ),
        Spacer(1, 4 * mm),
        two_column(
            [p("Required coverage states", "h2")] + bullet_lines([
                "OBSERVED_SUPPORTED",
                "STATIC_SUPPORTED",
                "DYNAMIC_OBJECT_BRANCH",
                "PROXY_AUTHORED",
                "DERIVED_WITHIN_ERROR",
                "OCCLUDED",
                "UNCLASSIFIED",
                "UNKNOWN",
            ]),
            [p("Prohibited promotions", "h2")] + bullet_lines([
                "confidence -> truth",
                "model agreement -> measurement",
                "track/motion label -> object identity",
                "occlusion -> empty space",
                "attractive mesh -> accepted geometry",
                "content hash -> authorship or consent",
            ]),
        ),
        Spacer(1, 3 * mm),
        callout(
            "Acceptance is application-specific",
            "Animation blocking may accept larger screen-space joint error than collision. Medical, forensic, biometric, body-measurement and safety uses are outside this profile until separate domain standards, calibration and independent validation exist.",
            GOLD,
            colors.HexColor("#FFF7E8"),
        ),
        PageBreak(),
    ])

    # 12 representation
    story.extend([
        p("12. Same-time materializations and error accounting", "h1"),
        data_table(
            ["Representation", "Use", "Authority and topology", "Main cost / failure"],
            [
                ["Static scene support", "Camera stabilization, layout, matchmove and environment reconstruction.", "Repeated guarded static charts only; unclassified/moving/hidden areas remain UNKNOWN.", "Dynamic leakage, weak parallax, scale gauge and large environment extent."],
                ["Observed surfels / points", "Debugging, evidence-aware partial replay, coverage.", "Only supported visible samples; open and incomplete is valid.", "Weak collision and appearance continuity; large sample count."],
                ["Sparse voxel bricks", "Volumetric effects, coarse occupancy and collision research.", "Same-time cells; UNKNOWN distinct from EMPTY; provenance per brick/range.", "Quantization, aliasing and temporal churn."],
                ["Observed open mesh", "Visible patches and residual overlays.", "Faces only where same-time support and topology checks pass.", "Cracks/disocclusion; remeshing can create dense novelty."],
                ["Authored proxy mesh", "Complete game object, rigging, collision, editability.", "Hidden shape is explicit authored resource; not observation-derived.", "Visual mismatch to performer; license/rights and rig conventions."],
                ["Hybrid mesh", "Recommended game/VFX object.", "Proxy topology plus accepted motion and visible literal residuals with per-field provenance.", "Needs robust binding, residual budgets and tool UI."],
                ["Baked cache", "DCC interchange and baseline comparison.", "Every sample is a conventional derivative with source/receipt references.", "Storage-heavy; weaker live editability and causal structure."],
            ],
            [30 * mm, 42 * mm, 64 * mm, 38 * mm],
            small=True,
        ),
        p("Required materialization receipt", "h2"),
        formula_box(
            "(revision_hash, target_source_pts, knowledge_cutoff_seq, policy_hash, coordinate_frame, units, resource_hashes, operator_hash, checkpoint_hash, novelty_range, provenance_class, world_error, collision_error, screen_error_px, topology_class)",
            small=True,
        ),
        Spacer(1, 3 * mm),
        p("The current scene contract already requires units/frames and a derived-geometry error contract; it also says presentation quality does not certify simulation or collision quality. CSO/HCO extends that separation across static scene, moving object, human, proxy and hybrid layers. [R07]", "body"),
        callout(
            "No connected sheet",
            "A materializer may reuse proxy topology between time samples, but each output primitive is evaluated at one time. Observed connectivity is created only by locally certified same-chart support; closure, stitching and hole filling remain PROXY or DERIVED. Temporal identity lives in entity/part IDs, support lineage, checkpoints and events. No face, voxel cell or edge connects different source times.",
            MAGENTA,
            colors.HexColor("#FAEFF6"),
        ),
        PageBreak(),
    ])

    # 13 physics
    story.extend([
        p("13. Physics integration is writer ownership, not inverse biomechanics", "h1"),
        data_table(
            ["Mode", "Transform authority", "Required handoff"],
            [
                ["OBSERVATION_PLAYBACK", "CSO/object system owns camera/object/chart transforms; physics may read collision proxies but cannot move them.", "None while active; collision response is sensing or explicitly mapped gameplay."],
                ["PHYSICS_ROOT", "Physics owns object root position/velocity; HCO may own local human joints and pose-relative display.", "Checkpoint root state and disable observation root writer before activation."],
                ["RAGDOLL", "Physics owns declared articulated bodies/joints after an explicit profile-specific transfer.", "Checkpoint pose/velocity, retire prior writers, activate physics ownership; reverse transfer is another event."],
                ["PRESENTATION_BLEND", "Renderer blends previous/current accepted states only for display.", "Never writes interpolated values back into authoritative ECS/component pools."],
            ],
            [36 * mm, 86 * mm, 52 * mm],
        ),
        p("Current engine evidence and limits", "h2"),
        two_column(
            bullet_lines([
                "Fixed-step deterministic runtime and ordered phases exist.",
                "Verified proposal -> support/guard -> commit, hashes, checkpoints and replay exist in the general runtime.",
                "GameWorld3D has stable entities and world-owned sparse component pools.",
                "Derived Make Many displays never become ECS rows and never overwrite authoritative state.",
            ]),
            bullet_lines([
                "Current Mobile 3D physics is bounded arcade physics with simple proxies, not human/deformable physics.",
                "KCAN is rigid transform animation only; no skeleton, retargeting, crossfade or animated glTF path.",
                "KCHI children are display-only; it cannot be relabeled a skeleton.",
                "Mass, inertia, friction, muscle force and contact force are authored gameplay values, not recovered from video.",
            ]),
        ),
        Spacer(1, 4 * mm),
        callout(
            "Hard guard, soft presentation",
            "The profile may enforce finite time steps, valid rotations, declared positive authored mass, bounded joint/collision policies and no competing writers. These checks prevent engine corruption; they do not turn monocular footage into measured biomechanics. [R03, R04, R08]",
            RED,
            colors.HexColor("#FCEDEF"),
        ),
        PageBreak(),
    ])

    # 14 engine mapping
    story.extend([
        p("14. Engine integration: reuse semantics, do not bend packs", "h1"),
        data_table(
            ["Existing mechanism", "Valid reuse", "Do not claim / missing work"],
            [
                ["project.json + scene/editor", "Editable CSO capture root, object branches, optional HCO components, resources, policies and materializers.", "Do not hide the feature in code-only setup; authoring must remain editable."],
                ["GameWorld3D / EntityState3D", "One capture/scene authority plus one entity per promoted moving object; composite sidecars and sparse manager-owned data.", "Do not mint a row/node for every static chart, object candidate, vertex, joint, surfel or voxel."],
                ["KCVG / event runtime", "Typed proposal/commit actions, ownership handoff and deterministic replay hooks.", "Current opcodes do not implement CSO/Chrono-BRACE/HCO operators or arbitrary model code."],
                ["KC3D / native NodeData", "One ordinary non-physics root binding and static resource carriers; bind a strict sibling sidecar by node/project hashes.", "Keep KC3D byte-for-byte unchanged; it is not a human geometry-cache codec."],
                ["KCAN392", "Root or ordinary rigid TRS clips where meaning fits.", "Not skeleton, skinning, retargeting, character animation or cloth."],
                ["KCHI392", "Bounded visual parent transform for ordinary objects.", "Not a body joint hierarchy; children cannot own physics/graphs/animation in current slice."],
                ["KCPK392", "Compatible packed root movement only under its existing numeric profile.", "Do not encode arbitrary human surface or skeletal motion as polar movement."],
                ["KCPR392 / KCRP392", "Ownership precedent and procedural display/presentation only.", "Not person geometry, chronology, occupancy or evidence."],
                ["Future strict sibling sidecar", "Only after JSON proof: scene/object profiles, bitemporal cursor, checkpoint/novelty/literal addresses.", "Name/layout remain TBD; no compression or runtime-conformance claim."],
                ["Canonical JSON / JSONL receipts", "Offline source, proposal, support, outlier, guard, manual edit and materialization records.", "Omit heavy receipts from lean runtime; source media remains by hash/reference."],
            ],
            [34 * mm, 73 * mm, 67 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        p("The CSO camera/object fold system must be sole writer for its declared fields and run before current packed movement and rigid animation; priority is not ownership. Static scene support never writes moving transforms. Canonical time selection uses integer/rational PTS arithmetic, never world.time floating seconds. UGTOMS wraps profiles without renaming existing packs; binary sidecars wait for editable JSON, two readers, golden vectors, malformed-input rejection and comparison data. [R01-R05, R09]", "body_tight"),
        PageBreak(),
    ])

    # 15 format ROI
    story.extend([
        p("15. File-format ROI", "h1"),
        callout(
            "ROI definition",
            "This is evidence-adjusted engineering priority, not proven financial return. The repository contains no customer pricing, acquisition-cost or support-cost evidence for CSO/HCO. Highest ROI means least semantic invention, strongest editability/interchange, and shortest route to a falsifiable benchmark.",
            GOLD,
            colors.HexColor("#FFF7E8"),
        ),
        Spacer(1, 3 * mm),
        data_table(
            ["Boundary", "Recommended form", "Priority and rule"],
            [
                ["Source", "Original MP4/images by SHA-256 plus exact stream metadata", "HIGHEST. Preserve all scene pixels as reprocessing truth; never replace H.264 with CSO novelty."],
                ["Editable authority", "Existing project.json extended by versioned CSO/object/HCO JSON Schemas", "HIGHEST. Inspectable, undoable, diffable and aligned with current editor/runtime authority."],
                ["Receipts", "Canonical JSON/JSONL with source/model/resource hashes and gate results", "HIGH. Auditable and easy to verify; keep optional in release builds."],
                ["Exact runtime time", "UGCVPTS1 sibling cache", "HIGH and implemented for this fixture. Compact canonical media-ordinal to source-PTS intervals; internal profile ABI, not interchange or geometry."],
                ["Exact raster address", "UGCVLUT1 RGBA16UI/Q8 sibling cache", "HIGH and implemented when repeated GPU log-polar resampling is useful. Derived/non-invertible; never a depth or surface file."],
                ["Broad runtime/DCC", "glTF 2.0 / GLB static scene, object, rig and animation derivatives", "HIGH interoperability. Current Grove lacks skeletal-animation import/export; adapter work required."],
                ["Baked DCC cache", "OpenUSD or Alembic", "HIGH as baseline/fallback for time-sampled scene/object meshes; storage-heavy and not canonical CSO/HCO authority."],
                ["Sparse volume", "OpenVDB derivative", "MEDIUM for VFX/voxel materialization; not universal runtime authority."],
                ["Partial geometry", "PLY or glTF points/open mesh", "MEDIUM diagnostic export; weak chronology and semantics unless paired with manifest/receipts."],
                ["Future geometry runtime", "Strict sibling CSO/object sidecar only after promotion gates", "CONDITIONAL. Potential seek/runtime gains; name/layout remain TBD and unfrozen."],
                ["Distribution", "Small by-reference UGTOMS conformance manifest", "CONDITIONAL. Profile ID, source/resource hashes, units, tolerances, verifier; no universal transcoding."],
                ["Human report", "PDF", "Use for review only. PDF is never the machine authority."],
            ],
            [33 * mm, 65 * mm, 76 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        p("A carrier that contains the same UGTOMS operator payload and decoder approaches the same content size. The practical difference becomes direct execution, intermediate duplication, runtime overhead, tooling and conformance - not a magical extension. [R01]", "body_tight"),
        PageBreak(),
    ])

    # 16 application ROI
    story.extend([
        p("16. Practical application ROI", "h1"),
        data_table(
            ["Rank", "Application", "Why it is practical", "Acceptance / kill gate"],
            [
                ["1 - HIGH NOW", "Chrono observation/raster inspector", "Exact source hash/PTS, all-pixel UNKNOWN coverage, deterministic log-polar playback and proposal receipts work without claiming depth.", "Physical POCO run must show correct decoder/shader/orientation and zero unreported late boundaries; ordinary video remains the source baseline."],
                ["2 - HIGH NEXT", "Calibrated camera matchmove plus partial static environment", "Guarded repeated background support can yield open points/surfels without hidden completion.", "Add measured intrinsics/timing and beat conventional SfM/SLAM on inspectability, replay or editability at equal reprojection error."],
                ["3 - HIGH", "Scene/object compiler onto authored proxies", "Separates camera, static set and moving objects; proxy closure gives editable runtime assets without hidden-shape claims.", "Beat or match conventional glTF scene/animation workflow on error, correction time, seek and bytes."],
                ["4 - MEDIUM", "Human performance/HCO specialization", "Articulated root/part chronology can support animation blocking and VFX while body topology stays authored.", "Needs bounded associations/camera evidence; correction time and replay must improve, and no completed anatomy may commit."],
                ["5 - MEDIUM", "Observed surfel/voxel capture QA", "Coverage, occlusion, scene change and evidence-aware effects tolerate open partial geometry.", "Preserve UNKNOWN and outperform a conventional point/voxel cache on inspectability or selective replay."],
                ["CONDITIONAL", "Telepresence / volumetric scene replay", "Direct materialization and novelty streaming may reduce repeated state.", "Needs consent, latency/loss, branch recovery and cross-device validation; ordinary video may remain better."],
                ["STOP", "Metric measurement, medical, forensic, biometric identity, garment fit or safety", "Monocular gauge, hidden surfaces and model bias make current evidence insufficient.", "Requires separate calibrated/regulated validation; do not market CSO/HCO for these uses."],
            ],
            [23 * mm, 40 * mm, 67 * mm, 44 * mm],
            small=True,
        ),
        Spacer(1, 4 * mm),
        two_column(
            [p("Expected compact layers", "h2")] + bullet_lines([
                "Repeated rigid static scene charts",
                "Stable object and optional human part slots",
                "Camera, object-root and articulated pose curves",
                "Visibility state and sparse manual corrections",
                "Shared environment/object proxies and deterministic materializers",
            ]),
            [p("Expected residual-heavy layers", "h2")] + bullet_lines([
                "Vegetation, water, reflections, cloth and hair",
                "Motion blur and rolling-shutter effects",
                "Disocclusion and repeated crops",
                "Small objects, expression, fingers and accessories",
                "Lighting-dependent appearance and topology changes",
            ]),
        ),
        Spacer(1, 3 * mm),
        callout(
            "Highest-ROI substrate order",
            "Implement the exact-math operator registry, manual/geometry baseline, bounded joint contractor, editable object and downstream rasterizer first. Optional learned masks, features, depth or pose fields may later seed removable proposals with frozen hashes; they never determine the object ontology or complete hidden shape.",
            GREEN,
            colors.HexColor("#E8F6F2"),
        ),
        PageBreak(),
    ])

    # 17 video facts
    story.extend([
        p("17. Supplied MP4: immutable facts and diagnostic probe", "h1"),
        metric_grid([
            ("12,132,305", "source bytes"),
            ("229", "decoded video frames"),
            ("9.119696 s", "container/stream duration"),
            ("25.110486", "frames per second (62500/2489)"),
        ]),
        Spacer(1, 3 * mm),
        data_table(
            ["Field", "Observed value"],
            [
                ["Source", "C:/Users/Tom/Videos/KasiaDansGedicht/sam_2353410928515192.mp4"],
                ["SHA-256", "1867BAFA7C80C31F18856525CBF580EDAA36D524270B1FA59CC643B51964CBFD"],
                ["Video stream", "H.264 Main; 1280 x 720; exact frame rate 62500/2489; time base 1/1,000,000; 0.039824 s PTS step."],
                ["Container metadata boundary", "No camera intrinsics, metric scale, IMU, depth or shutter/exposure calibration was exposed by ffprobe."],
                ["Manual six-frame inspection", "Multiple independently moving dancers, moving/reframing camera, person-person occlusion, crops, loose clothing and hair. No faces are reproduced here."],
            ],
            [43 * mm, 131 * mm],
            small=True,
        ),
        p("Deterministic OpenCV diagnostic at 640 x 360", "h2"),
        data_table(
            ["Gap", "FB retained", "Median flow", "H inliers", "H residual >3 px", "F inliers"],
            [
                ["1 frame", "93.3%", "3.01 px", "89.3%", "10.7%", "89.9%"],
                ["5 frames", "65.4%", "11.20 px", "79.2%", "20.8%", "83.4%"],
                ["12 frames", "40.3%", "16.83 px", "67.1%", "32.9%", "79.1%"],
                ["25 frames", "24.8%", "21.51 px", "55.8%", "44.2%", "70.8%"],
            ],
            [23 * mm, 28 * mm, 30 * mm, 27 * mm, 39 * mm, 27 * mm],
        ),
        p("Method: up to 24 uniformly spaced frame pairs per gap; 800 Shi-Tomasi corners; pyramidal Lucas-Kanade with forward/backward error <=1.5 px; homography RANSAC at 3 px; fundamental-matrix RANSAC at 1.5 px. Tracks are unsegmented and mix people with background. The numbers diagnose track loss and projective inconsistency only - not calibration, camera pose, metric depth or a person mesh. [V01, V02]", "caption"),
        PageBreak(),
    ])

    # 18 fixture result
    story.extend([
        p("18. Correct first experiment on the supplied clip", "h1"),
        data_table(
            ["Step", "Action", "Honest expected result"],
            [
                ["1", "Bind MP4 hash, exact decoded PTS/time base, decode transform, rights/consent and target-selection record; mark capture/exposure timing UNKNOWN.", "Source literal accepted; no ray or geometry claim."],
                ["2", "Create native/manual coverage candidates for all pixels: possible static background, each moving object/person, occluders and unclassified regions.", "2D proposal sets only; not-moving does not yet mean static."],
                ["3", "Declare bounds for intrinsics, distortion, row exposure, camera motion, depth and scale gauge.", "This clip currently lacks them; unconstrained terms yield UNBOUNDED_UNKNOWN."],
                ["4", "Jointly contract camera and repeated background-rigidity branches; accept static scene support only after parallax, visibility, reprojection and conditioning gates.", "Partial static map if bounded; dynamic leakage or weak evidence stays branched/UNKNOWN."],
                ["5", "Open one branch per independently moving region; split generic charts by motion/material. Add articulated HCO controls only for a selected human.", "Bounded partial object support; cloth/hair and hidden backsides remain time-local/UNKNOWN."],
                ["6", "Bind an explicit authored proxy for PROXY_COMPLETE/HYBRID, or stay OBSERVED_PARTIAL; compose same-time part transforms deterministically.", "Complete topology is PROXY_ONLY, never observation-derived."],
                ["7", "Commit only novelty, semantic changes, retractions and checkpoints with effective PTS plus knowledge sequence.", "Predictable states are absent from storage; future evidence cannot leak into causal replay."],
                ["8", "Materialize and rasterize one bitemporal slice; compare with glTF animation, USD/Alembic caches, OpenVDB and original video.", "Replay, seek, edit time, bytes, runtime cost and declared error decide promotion."],
            ],
            [15 * mm, 93 * mm, 66 * mm],
            small=True,
        ),
        Spacer(1, 4 * mm),
        callout(
            "Current result for this fixture",
            "PASS: byte-exact source binding and embedded copy; 229 exact-PTS observations; all 921,600 pixels covered once per observation as UNKNOWN; 58 analyzed/preview ordinals; 57 deterministic proposal and joint-hypothesis slices; novelty-only proposal events; byte-exact NumPy/PyTorch-CUDA Q8 remapping; strict source/preview UGCVPTS1 caches; a hash-verified editable bundle; and an audited MediaNDK-linked POCO ARM64 APK. FAIL-CLOSED FOR LITERAL 3D: the clip exposes no intrinsics, distortion, exposure/shutter model, depth bound or metric anchor. DEVICE-OPEN: no attached-phone decoder, shader, orientation, boundary, performance or thermal evidence. This is an exact chrono-spatial raster observation/proposal slice, not a reconstructed scene or person.",
            RED,
            colors.HexColor("#FCEDEF"),
        ),
        Spacer(1, 3 * mm),
        p("A successful first prototype need not recover a complete scene or unique body. It must preserve all-pixel coverage, keep guarded static support separate from moving branches, create one editable entity per promoted object, specialize a human only when selected, and prove that novelty-only retention beats a conventional baseline for at least one bounded layer.", "body"),
        PageBreak(),
    ])

    # 19 milestones
    story.extend([
        p("19. Implementation sequence and promotion gates", "h1"),
        data_table(
            ["Phase", "Concrete artifact", "Exit gate"],
            [
                ["P0 - contract/schema", "CSO/Chrono-BRACE plus HCO specialization contracts, JSON Schemas, authority classes, coverage and bitemporal events.", "Review agrees on static/dynamic ambiguity, gauge, UNKNOWN, capture bounds, circular contraction, novelty and time rules."],
                ["P1 - exact operator registry", "Versioned source-equation registry plus all-pixel coverage, manual/native rays/masks/matches, epipolar and reprojection baseline.", "Every operator fixes convention, domain, uncertainty, bounds, deterministic order and failure state."],
                ["P2 - bounded BRACE core", "Joint camera/static/object branch boxes, inclusion-sound contractor, support/conditioning guards, lineage and bitemporal fold.", "Ambiguity fixtures contract correctly; unresolved clip inputs remain bounded/UNKNOWN rather than completed."],
                ["P3 - editable engine scene", "Editable capture root, static atlas, promoted object entities, optional HCO component, inspector corrections and writer validation.", "No sample/chart ECS rows; undo/save/load/causal and sealed replay are deterministic."],
                ["P4 - materializers", "Same-time static/object surfel, voxel, open mesh, proxy and raster outputs plus conventional baselines.", "Bitemporal cache key, random seek equality, error receipts and no cross-time primitive."],
                ["P5 - optional proposal seeds", "Only now add frozen-hash learned mask/feature/depth/pose candidate adapters.", "Removing every adapter changes convenience, never schema/authority; generated/amodal pixels are rejected."],
                ["P6 - binary decision", "Only after measured need, evaluate a strict CSO/object sibling sidecar and by-reference UGTOMS manifest.", "Two readers, golden vectors, malformed-input rejection, benchmarks and migration/fallback policy."],
                ["P7 - physical proof", "Exact compiled workload, device/build hashes, timing, memory, thermals and visual capture.", "Claims remain limited to tested asset/device/profile; no transfer from current polar Grow evidence."],
            ],
            [31 * mm, 88 * mm, 55 * mm],
            small=True,
        ),
        Spacer(1, 4 * mm),
        p("The root TODO.md now distinguishes the measured compiler slice from the remaining contractor, geometry, inspector, streaming, and device gates. Checked items name artifacts; open items are not implied by the passing compiler bundle.", "body"),
        callout(
            "Do not freeze the binary first",
            "The highest-ROI first artifact is editable JSON plus a deterministic materializer and comparison harness. A compact sidecar is justified only if measured runtime, seek, memory or distribution gains survive equal-quality conventional baselines.",
            GOLD,
            colors.HexColor("#FFF7E8"),
        ),
        PageBreak(),
    ])

    # 20 verification
    story.extend([
        p("20. Verification matrix and kill conditions", "h1"),
        data_table(
            ["Dimension", "Measure", "Promotion condition"],
            [
                ["Semantic", "Scene-static/object/part lineage, coverage class, provenance, owner state and event order.", "Round-trip equality; ambiguous motion/association branches; UNKNOWN never becomes STATIC or EMPTY."],
                ["Chronology", "Exact decoded PTS, capture bounds, effective PTS, knowledge sequence, segments, causal/sealed seek and replay.", "No future leakage; random seeks equal sequential replay at the same knowledge cutoff."],
                ["Geometry", "Branch diameter, independent supports, reprojection, parallax, cheirality, reduced rank/conditioning and visible support.", "All promotion guards pass; proxy/observed/bounded/unknown classes remain distinct."],
                ["Novelty ROI", "Bytes per accepted layer, residual density, checkpoint depth and decode cost.", "Beat conventional curve/cache baseline on a declared objective; otherwise retain conventional format."],
                ["Runtime", "CPU/GPU time, memory, startup, seek latency, energy/thermals and fallback.", "No hidden materialization cost; measurements include decoder/resources."],
                ["Robustness", "Static/dynamic leakage, occlusion, crop, object crossing, camera loss, long gap, chart/owner change.", "Fail closed, branch or literal fallback; never complete through failure."],
                ["Editability", "Static/dynamic correction, object association, human joint edit, proxy swap, checkpoint, undo/save/reload.", "User can inspect and change authoritative state in the editable scene/project."],
                ["Rights/privacy", "Consent scope, model/resource licenses, retention, export and deletion workflow.", "No release until named owner approves source, proxy, model and person-data use."],
            ],
            [31 * mm, 75 * mm, 68 * mm],
            small=True,
        ),
        p("Immediate kill conditions", "h2"),
        two_column(
            bullet_lines([
                 "A learned or raster-derived output can write authority without original-observation guards.",
                "The profile cannot distinguish proxy, observed, derived and unknown geometry.",
                "A background/object/person crossing silently changes static or entity identity.",
                 "Decoded PTS, capture uncertainty, or knowledge sequence is discarded/rounded away.",
                "Two systems write the same transform field.",
            ]),
            bullet_lines([
                "Residual density makes CSO/HCO larger/slower with no editability or seek benefit.",
                "A binary is frozen before JSON/schema and two-reader proof.",
                 "A render residual is counted as independent evidence for the state that rendered it.",
                "Video-derived gameplay physics is presented as measured biomechanics.",
                "Consent or model/resource license cannot be established.",
            ]),
        ),
        Spacer(1, 3 * mm),
        callout(
            "Definition of done for v0.1 implementation",
            "One editable CSO fixture on the supplied clip; all-pixel coverage; byte-exact source binding and capture-time uncertainty; guarded static support plus object branches; optional HCO target; bounded circular contraction; bitemporal novelty replay; same-time scene/object mesh/voxel/raster derivatives; conventional baselines; malformed-input rejection; and every UNKNOWN named.",
            GREEN,
            colors.HexColor("#E8F6F2"),
        ),
        PageBreak(),
    ])

    # 21 nonclaims
    story.extend([
        p("21. Hard nonclaims", "h1"),
        data_table(
            ["Not claimed", "Reason"],
            [
                ["Complete monocular scene scanner or unique hidden-object/body recovery", "Many static/dynamic assignments, 3D scenes, objects and camera/scale states explain the same pixels; hidden regions are unobserved."],
                ["A four-spatial-dimensional scene/person mesh", "CSO/HCO is 3D plus time; continuity is ECS/chart/event lineage, not a connected spacetime sheet."],
                ["Measured anatomy, dimensions, garment fit or biomechanics", "No calibrated multi-sensor metrology, medical standard, mass/force instrumentation or domain validation."],
                ["Biometric or legal identity", "Target branches and track IDs are authoring lineage only; face/gait identity is out of scope."],
                ["Reference/model output as physical truth", "Only stripped deterministic math is native. Learned masks, features, depth, pose and shape are removable proposals; agreement is not independent measurement."],
                ["Amodal, diffusion or hidden-texture completion", "Diffusion-VAS and full-shape/novel-view generation are excluded from authoritative state."],
                ["Implemented complete CSO/Chrono-BRACE/HCO reconstruction", "Only a scoped observation/proposal compiler is implemented. There is no bounded physical contractor, promoted dynamic surface, semantic skeleton, hidden body, or general scene/object residual codec."],
                ["Universal .ugtoms file", "UGTOMS remains a proposed profile family/common target; envelope and interoperability are future work."],
                ["Compression win", "Only an equal-quality benchmark against source video, glTF curves, USD/Alembic caches and VDB can establish it."],
                ["Physical-device proof for the chrono workload", "The audited POCO-debug APK compiles and its bytes/source contracts verify, but no device is attached. Existing polar Grow evidence cannot transfer to this MediaCodec/LUT workload."],
                ["Byte-exact phone RGB or photon-time display", "MediaCodec device YUV-to-RGB and EGL/vsync/display timing are derived. Exactness is limited to source bytes, PTS selection, LUT addresses and Q8 weighting until a physical receipt says otherwise."],
                ["Exact LOOP wrap", "The audited delivered caches are ONCE_HOLD_LAST. Explicit LOOP can detect the cycle but cannot pre-stage ordinal zero before wrap and is therefore best-effort/late."],
            ],
            [63 * mm, 111 * mm],
        ),
        Spacer(1, 4 * mm),
        p("Bottom line", "h2"),
        callout(
            "The observed scene and persistent objects are the authority",
            "A mesh, voxel or raster at source time tau and knowledge cutoff kappa is a downstream materialization of guarded static support plus persistent object states. Chrono-BRACE circularly contracts bounded camera/static/object/visibility hypotheses before commit. Negative memory means predictable canonical states are not stored. Hidden geometry is explicit proxy or UNKNOWN.",
            CYAN,
            colors.HexColor("#E7F7F9"),
            "quote",
        ),
        Spacer(1, 4 * mm),
        p("This converts 'chrono-temporally spatially' into an implementable rule: all camera-observed pixels enter typed coverage; static scene and moving objects remain distinct branches; humans add an articulated specialization; decoded chronology and capture uncertainty stay explicit; circular evidence is bounded; novelty replay is bitemporal; no primitive crosses time; and conventional 3D/raster outputs remain downstream and editable.", "body"),
        PageBreak(),
    ])

    # 22 repo references
    story.extend([
        p("22. Repository evidence map", "h1"),
        p("Local paths are relative to UGTS_KC_K_Kij_T_Grove_3_9_2_COMPLETE_ALL_FILES unless noted. Line references identify the audited 30 August 2026 worktree.", "body_tight"),
        data_table(
            ["ID", "Primary local source and use"],
            [
                ["R01", "tmp/pdfs/build_ugtoms_cross_domain_overview.py:524-532, 580-648, 729-795, 892-900, 959-1019 - UGTOMS definition, equation, claim status, envelope, adapters, tests and roadmap."],
                ["R02", "docs/UGTS_ENGINE_WORKLOG.md:761-809 - retained UGTOMS and deterministic knowledge-conduit status; proposed rather than implemented common kernel."],
                ["R03", "docs/ENGINE_ARCHITECTURE.md:29-60, 84-145, 270-363, 427-522 - ECS authority, ordering, derived populations, animation/hierarchy limits and presentation separation."],
                ["R04", "README.md:147-171, 225-250, 570-626 - sparse pools, one real ECS prototype, current packs and explicit skeletal/AAA gaps."],
                ["R05", "docs/UGTS_SUBSTRATE_MECHANISM_MAP.md:21-55, 77-91, 118-146 - bounded polar chain, derived display ownership and measured Grow evidence boundary."],
                ["R06", "src/ugts_kc3/runtime.py and src/ugts_kc3/replay.py - proposal validation, support/guard/commit, hashes, checkpoint, replay and divergence mechanisms."],
                ["R07", "spec/SCENE_AND_ASSET_CONTRACT.md:1-39 - scene authority, stable IDs, units/frames, materialization and derived-geometry error contract."],
                ["R08", "spec/GAME_RUNTIME_CONTRACT.md:1-36 and spec/MOBILE_3D_AND_ANDROID_CONTRACT.md:1-29 - fixed-step order, snapshot/hash rules and bounded physics/mobile claims."],
                ["R09", "spec/POLAR_GLOW_GROW_V4_CONTRACT.md:1-91 - generated-display-only growth and prohibition on writing derived scale to authoritative ECS/NodeData."],
                ["R10", "spec/FOUR_D_CONTRACT_DRAFT.md:1-12 - 3D plus time versus four-spatial geometry; neither runtime implemented."],
                ["R11", "UGTS-GN package source UGTS_GN_1.1.md:233-248, as cited by the repository audit - novelty-only logs require retained/reconstructible authority and bounded replay."],
                ["R12", "Parent repo SUBSTRATE_ROI_STRATEGY.pdf and TODO.md - repo-wide evidence-adjusted ROI, format policy, universal-format stop rule and CSO/Chrono-BRACE implementation backlog."],
                ["R13", "src/ugts_kc3/chrono_video.py; spec/CHRONO_VIDEO_OBSERVATION_CONTRACT.md; android_template chrono_video_lut/timeline/player.cpp, UgtsNativeActivity.java and chrono shaders - exact-PTS compiler/verifier, Q8 LUT, strict source/preview time caches, MediaNDK/external-OES decode and owned-raster staging."],
            ],
            [15 * mm, 159 * mm],
            small=True,
        ),
        Spacer(1, 4 * mm),
        callout(
            "Evidence hierarchy",
            "Current code and contracts govern implemented behavior. The scoped chrono-video compiler is implemented; physical contraction and complete CSO/HCO remain architecture. Preserved build/device records support only their exact artifact and workload. Legacy PDFs and attached documents inform chronology but do not override the user's request or current source state.",
            BLUE,
            colors.HexColor("#EDF3FA"),
        ),
        PageBreak(),
    ])

    # 23 external sources and video methodology
    story.extend([
        p("23. External mathematical provenance and fixture method", "h1"),
        data_table(
            ["ID", "Primary source", "Exact retained / stripped boundary"],
            [
                ["W01", "MoGe, CVPR 2025, https://openaccess.thecvf.com/content/CVPR2025/papers/Wang_MoGe_Unlocking_Accurate_Monocular_Geometry_Estimation_for_Open-Domain_Images_with_CVPR_2025_paper.pdf ; MoGe-2, https://arxiv.org/pdf/2507.02546", "Retain focal/z-shift objective, weighted affine alignment and local support sets. Learned point/metric scale and gradient completion remain proposals/preview; centered principal point and square-pixel assumptions are explicit."],
                ["W02", "Depth Anything 3 technical report, https://depth-anything-3.github.io/assets/da3_tech_report_2025.pdf", "Retain p.6 depth-ray projection, Eq.1-2 DLT/RQ factor math and Eq.8 anchored affine alignment. Predicted rays/depth/camera and focal/300 metric convention are proposals; Gaussian/novel-view path excluded."],
                ["W03", "DINOv3, https://arxiv.org/html/2508.10104", "Retain frozen-feature cosine/top-k spatial candidate math. Contextual features are learned/correlated and never material support or identity."],
                ["W04", "SAM 3, https://arxiv.org/html/2511.16719", "Retain finite mask sets, propagate/detect/match/update and IoU association math as proposals. Negative matching score never means scene/object retraction."],
                ["W05", "SAM 3D Body, https://arxiv.org/html/2602.15989", "Visible 2D keypoint/part proposals and joint-limit/reprojection math only. Learned camera, pose, shape, skeleton and mesh remain hypotheses/proxy; single-view depth ambiguity is preserved."],
                ["W06", "SAM-Body4D, https://arxiv.org/html/2512.08406v1", "Mask/association and deterministic smoothing may seed proposals. Strip Diffusion-VAS occlusion/replacement equations, amodal pixels, completed shape and first-frame shape authority."],
                ["W07", "Momentum Human Rig, https://arxiv.org/html/2511.15586", "Retain Eq.3 same-time parent/offset/translation/prerotation/rotation/scale transform composition for authored human proxy materialization. Identity bases, pose correctives, weights and hidden full mesh are PROXY_ONLY."],
                ["W08", "Vision Transformer, https://arxiv.org/html/2010.11929", "Its patch embedding/global-attention equations establish that tokens are contextual learned states, not material point IDs; only deterministic feature candidate math survives."],
            ],
            [14 * mm, 88 * mm, 72 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        p("DA3 code boundary was checked at commit 3d835ec1a5802d64a8b8b15f817a1ab54809bfe4 and MoGe at 74fbce054ebed49800de42d0ad0e83495065719a. A repository implementation can change; the operator registry must pin the exact paper equation and code revision actually used.", "caption"),
        PageBreak(),
        p("23. Classical projective provenance and fixture", "h1"),
        data_table(
            ["ID", "Primary source", "Use and boundary"],
            [
                ["W09", "Longuet-Higgins, 1981, https://doi.org/10.1038/293133a0", "Essential-matrix two-view geometry; requires calibrated rigid views and does not resolve monocular metric scale."],
                ["W10", "Nister, 2004, https://doi.org/10.1109/TPAMI.2004.17", "Five-point relative-pose candidate generation; Chrono-BRACE uses a canonical bounded sample order and verifier guards."],
                ["W11", "Hartley and Sturm, 1997, https://doi.org/10.1006/cviu.1997.0547", "Reprojection-based triangulation; low parallax/conditioning remains ray support or UNKNOWN."],
                ["W12", "Triggs et al., 2000, https://doi.org/10.1007/3-540-44480-7_21", "Robust joint reprojection refinement; gauge and covariance/conditioning must stay explicit."],
                ["W13", "Vidal et al., 2006, https://doi.org/10.1007/s11263-005-4839-7", "Multibody motion constraints propose static/dynamic/rigid chart branches; human/nonrigid validity is guarded and time-bounded."],
                ["W14", "Fischler and Bolles, 1981, https://doi.org/10.1145/358669.358692", "Hypothesize/verify logic and robust subsets; randomness is replaced or fully ledgered by deterministic seed/order/outlier receipts."],
                ["W15", "ORB-SLAM3, https://doi.org/10.1109/TRO.2021.3075644", "Static-background camera/gauge falsification reference. Its application/library is not the CSO/object representation."],
            ],
            [14 * mm, 90 * mm, 70 * mm],
            small=True,
        ),
        p("Fixture records", "h2"),
        data_table(
            ["ID", "Local evidence"],
            [
                ["V01", "ffprobe and SHA-256 run on 30 August 2026 against the supplied MP4: source path/hash, 12,132,305 bytes, H.264 Main, 1280 x 720, 229 frames, 9.119696 s, 62500/2489 fps, 1/1,000,000 time base."],
                ["V02", "tmp/pdfs/ugtoms_person_chrono_work/video_probe.py and video_probe.json - deterministic OpenCV track/homography/fundamental diagnostics; method and interpretation limit printed in the JSON."],
                ["V03", "Six-frame local contact inspection used only to characterize scene difficulty; no frame is embedded in this report."],
                ["V04", "Parent UGTOMS_CHRONO_VIDEO_SAMPLE_0_2_SOURCE_LUT_FINAL: manifest SHA-256 191D5F5A...AD0F9C; verifier PASS; embedded source; 229 source and 58 preview timeline entries; 57 proposals/joint hypotheses; CPU/CUDA max difference 0; 396.88 MiB CUDA peak. Audited 19,036,992-byte APK SHA-256 C9CF4D75...A89DD4; 16 matching chrono assets; no ADB device."],
            ],
            [15 * mm, 159 * mm],
            small=True,
        ),
        Spacer(1, 3 * mm),
        p("Primary papers/official code were checked as available on 30 August 2026. Licenses, checkpoints and code can change and must be pinned. Citation is mathematical provenance, exclusion evidence or a benchmark reference - never adoption of the source architecture, installation evidence or clip-level validation.", "body_tight"),
        HRFlowable(width="100%", thickness=0.7, color=LINE, spaceBefore=3 * mm, spaceAfter=3 * mm),
        p("Prepared for root-repository handoff. Companion execution backlog: parent TODO.md. Supersedes the architecture of UGTS_VSTL_MONOCULAR_CHRONO_LITERAL_HUMAN_0_1.pdf; that earlier artifact should be treated as historical, not current guidance.", "caption"),
    ])

    return story


def build_pdf() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=17 * mm,
        title="UGTOMS Chrono-BRACE - Monocular Scene and Object 3D Profile 0.3",
        author="OpenAI Codex",
        subject="UGTOMS-first architecture for whole-image monocular static scene, dynamic objects and human specialization",
    )
    doc.build(build_story(), onFirstPage=cover_page, onLaterPages=later_page)
    print(OUTPUT)


if __name__ == "__main__":
    build_pdf()
