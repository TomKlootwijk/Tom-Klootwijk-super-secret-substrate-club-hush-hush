from __future__ import annotations

import math
import os
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Rect, String
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
OUTPUT = ROOT / "output" / "pdf" / "KLB_SGP4_v0.5.0_Laptop_Verification_ELI5.pdf"

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
            title="KLB SGP4 v0.5.0 Laptop Verification",
            author="Codex verification run for Tom Klootwijk",
            subject="Full SGP4/SDP4 GPU verification, metrics, feasibility, and ELI5 explanation",
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
        canvas.circle(width - 8 * mm, 30 * mm, 55 * mm, fill=1, stroke=0)
        canvas.setFillColor(CYAN)
        canvas.circle(width - 8 * mm, 30 * mm, 22 * mm, fill=1, stroke=0)
    else:
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - 10 * mm, width, 10 * mm, fill=1, stroke=0)
        canvas.setFont("Body-Bold", 7.2)
        canvas.setFillColor(WHITE)
        canvas.drawString(18 * mm, height - 6.5 * mm, "KLB SEEDCHAIN GPU v0.5.0 / FULL SGP4-SDP4 VERIFICATION")
        canvas.setFont("Body", 7.2)
        canvas.drawRightString(width - 18 * mm, height - 6.5 * mm, "RTX 5070 Ti Laptop / 2026-08-16")
        canvas.setStrokeColor(LINE)
        canvas.line(18 * mm, 12 * mm, width - 18 * mm, 12 * mm)
        canvas.setFont("Body", 7.2)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 7.8 * mm, "Evidence-backed engineering assessment; not an operational navigation certification")
        canvas.drawRightString(width - 18 * mm, 7.8 * mm, f"Page {doc.page}")
    canvas.restoreState()


styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        "TitleWhite",
        fontName="Body-Bold",
        fontSize=27,
        leading=31,
        textColor=WHITE,
        spaceAfter=5 * mm,
    )
)
styles.add(
    ParagraphStyle(
        "SubtitleWhite",
        fontName="Body",
        fontSize=12.5,
        leading=17,
        textColor=HexColor("#D8E2F5"),
    )
)
styles.add(
    ParagraphStyle(
        "Kicker",
        fontName="Body-Bold",
        fontSize=8.2,
        leading=10,
        textColor=CYAN,
        spaceAfter=2.5 * mm,
    )
)
styles.add(
    ParagraphStyle(
        "H1",
        fontName="Body-Bold",
        fontSize=20,
        leading=24,
        textColor=NAVY,
        spaceAfter=4 * mm,
    )
)
styles.add(
    ParagraphStyle(
        "H2",
        fontName="Body-Bold",
        fontSize=12,
        leading=15,
        textColor=NAVY,
        spaceBefore=3 * mm,
        spaceAfter=2 * mm,
    )
)
styles.add(
    ParagraphStyle(
        "Body",
        fontName="Body",
        fontSize=9.3,
        leading=13.2,
        textColor=INK,
        spaceAfter=2.8 * mm,
    )
)
styles.add(
    ParagraphStyle(
        "Small",
        fontName="Body",
        fontSize=7.6,
        leading=10.2,
        textColor=MUTED,
    )
)
styles.add(
    ParagraphStyle(
        "Cell",
        fontName="Body",
        fontSize=7.8,
        leading=10.2,
        textColor=INK,
    )
)
styles.add(
    ParagraphStyle(
        "CellBold",
        fontName="Body-Bold",
        fontSize=7.8,
        leading=10.2,
        textColor=INK,
    )
)
styles.add(
    ParagraphStyle(
        "CellWhite",
        fontName="Body",
        fontSize=7.8,
        leading=10.2,
        textColor=WHITE,
    )
)
styles.add(
    ParagraphStyle(
        "CellWhiteBold",
        fontName="Body-Bold",
        fontSize=7.8,
        leading=10.2,
        textColor=WHITE,
    )
)
styles.add(
    ParagraphStyle(
        "CardValue",
        fontName="Body-Bold",
        fontSize=17,
        leading=19,
        alignment=TA_CENTER,
        textColor=NAVY,
    )
)
styles.add(
    ParagraphStyle(
        "CardLabel",
        fontName="Body",
        fontSize=7.5,
        leading=9.5,
        alignment=TA_CENTER,
        textColor=MUTED,
    )
)
styles.add(
    ParagraphStyle(
        "Callout",
        fontName="Body-Bold",
        fontSize=10.2,
        leading=14,
        textColor=NAVY,
    )
)
styles.add(
    ParagraphStyle(
        "VerdictWhite",
        fontName="Body-Bold",
        fontSize=14,
        leading=17,
        textColor=WHITE,
        alignment=TA_CENTER,
    )
)
styles.add(
    ParagraphStyle(
        "MonoSmall",
        fontName="Body",
        fontSize=6.8,
        leading=9.0,
        textColor=INK,
        wordWrap="CJK",
    )
)


def P(text: str, style: str = "Body") -> Paragraph:
    return Paragraph(text, styles[style])


def section(kicker: str, title: str, intro: str | None = None) -> list:
    out = [P(kicker.upper(), "Kicker"), P(title, "H1")]
    if intro:
        out.append(P(intro))
    return out


def bullet(text: str, color: str = "#00A7C4") -> Paragraph:
    return Paragraph(
        f'<font color="{color}"><b>+</b></font>&nbsp;&nbsp;{text}',
        ParagraphStyle(
            "BulletInline",
            parent=styles["Body"],
            leftIndent=3 * mm,
            firstLineIndent=-3 * mm,
            spaceAfter=1.8 * mm,
        ),
    )


def callout(text: str, kind: str = "info") -> Table:
    palette = {
        "info": (CYAN_LIGHT, CYAN),
        "good": (GREEN_LIGHT, GREEN),
        "warn": (ORANGE_LIGHT, ORANGE),
        "bad": (RED_LIGHT, RED),
    }
    bg, accent = palette[kind]
    t = Table([[P(text, "Callout")]], colWidths=[174 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.7, accent),
                ("LINEBEFORE", (0, 0), (0, -1), 4, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
            ]
        )
    )
    return t


def cards(items: list[tuple[str, str]], columns: int = 4) -> Table:
    rows = []
    for start in range(0, len(items), columns):
        row_items = items[start : start + columns]
        while len(row_items) < columns:
            row_items.append(("", ""))
        cells = []
        for value, label in row_items:
            cells.append([P(value, "CardValue"), Spacer(1, 1.2 * mm), P(label, "CardLabel")])
        rows.append(cells)
    width = 174 * mm / columns
    t = Table(rows, colWidths=[width] * columns, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PAPER),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, WHITE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2 * mm),
            ]
        )
    )
    return t


def data_table(headers: list[str], rows: list[list[str]], widths: list[float] | None = None) -> Table:
    data = [[P(h, "CellWhiteBold") for h in headers]] + [[P(str(x), "Cell") for x in row] for row in rows]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Body-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.1 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.1 * mm),
    ]
    for row in range(1, len(data)):
        commands.append(("BACKGROUND", (0, row), (-1, row), PAPER if row % 2 == 0 else WHITE))
    t.setStyle(TableStyle(commands))
    return t


def performance_chart() -> Drawing:
    values = [
        ("Direct seed query", 91.974, CYAN),
        ("Materialize", 88.443, ORANGE),
        ("Resident dense query", 6.280, GREEN),
        ("Materialize + query", 94.722, NAVY),
    ]
    d = Drawing(500, 155)
    x0, y0, max_w = 150, 22, 300
    max_v = 100.0
    for idx, (label, value, color) in enumerate(values):
        y = 122 - idx * 29
        d.add(String(0, y + 3, label, fontName="Body", fontSize=8, fillColor=INK))
        d.add(Rect(x0, y, max_w, 12, fillColor=HexColor("#E8EDF5"), strokeColor=None))
        d.add(Rect(x0, y, max_w * value / max_v, 12, fillColor=color, strokeColor=None))
        d.add(String(x0 + max_w + 8, y + 2, f"{value:.3f} ms", fontName="Body-Bold", fontSize=8, fillColor=INK))
    d.add(Line(x0, y0 - 2, x0 + max_w, y0 - 2, strokeColor=LINE, strokeWidth=0.7))
    d.add(String(x0, 4, "0", fontName="Body", fontSize=7, fillColor=MUTED))
    d.add(String(x0 + max_w / 2 - 8, 4, "50 ms", fontName="Body", fontSize=7, fillColor=MUTED))
    d.add(String(x0 + max_w - 16, 4, "100 ms", fontName="Body", fontSize=7, fillColor=MUTED))
    return d


def compression_chart() -> Drawing:
    values = [
        ("KSGP1 seed file", 5793, CYAN),
        ("Dense float4 positions", 309658112, ORANGE),
        ("Dense double4 positions", 619316224, NAVY),
        ("2 GiB stress dense buffer", 2147483648, GREEN),
    ]
    d = Drawing(500, 170)
    x0, max_w = 155, 300
    min_log, max_log = 3.0, math.log10(2147483648)
    for idx, (label, value, color) in enumerate(values):
        y = 137 - idx * 31
        d.add(String(0, y + 3, label, fontName="Body", fontSize=8, fillColor=INK))
        d.add(Rect(x0, y, max_w, 13, fillColor=HexColor("#E8EDF5"), strokeColor=None))
        span = max_w * (math.log10(value) - min_log) / (max_log - min_log)
        d.add(Rect(x0, y, max(4, span), 13, fillColor=color, strokeColor=None))
        label_value = f"{value / 1024:.2f} KiB" if value < 1024 * 1024 else f"{value / (1024**2):,.1f} MiB"
        d.add(String(x0 + max_w + 8, y + 2, label_value, fontName="Body-Bold", fontSize=8, fillColor=INK))
    d.add(String(x0, 6, "LOG SCALE: each step right is about 10x more bytes", fontName="Body", fontSize=7, fillColor=MUTED))
    return d


def accuracy_chart() -> Drawing:
    rows = [
        ("CPU vs GPU position", 0.000383791, 10.0, CYAN),
        ("CPU vs GPU velocity", 0.000000056, 0.01, GREEN),
        ("Independent position", 0.265627, 1.0, ORANGE),
        ("Independent velocity", 0.000784, 0.002, NAVY),
    ]
    d = Drawing(500, 175)
    x0, width = 165, 205
    for idx, (label, measured, limit, color) in enumerate(rows):
        y = 141 - idx * 34
        d.add(String(0, y + 3, label, fontName="Body", fontSize=8, fillColor=INK))
        d.add(Rect(x0, y, width, 12, fillColor=HexColor("#E8EDF5"), strokeColor=None))
        ratio = min(1.0, measured / limit)
        d.add(Rect(x0, y, max(2, width * ratio), 12, fillColor=color, strokeColor=None))
        d.add(Line(x0 + width, y - 2, x0 + width, y + 15, strokeColor=RED, strokeWidth=1.2))
        unit = "mm/s" if "velocity" in label.lower() else "mm"
        d.add(String(x0 + width + 7, y + 2, f"{measured:g} {unit} | limit {limit:g}", fontName="Body-Bold", fontSize=7.2, fillColor=INK))
    d.add(String(x0, 6, "Colored bar = measured maximum. Red marker = acceptance limit.", fontName="Body", fontSize=7, fillColor=MUTED))
    return d


def title_page(story: list) -> None:
    story.extend(
        [
            Spacer(1, 26 * mm),
            P("EXTREME-ACCURACY VERIFICATION / ELI5 EDITION", "Kicker"),
            P("KLB Seedchain GPU v0.5.0", "TitleWhite"),
            P("Full SGP4 / SDP4 on an RTX 5070 Ti Laptop GPU", "SubtitleWhite"),
            Spacer(1, 11 * mm),
        ]
    )
    verdict = Table([[P("VALIDATED FOR ITS STATED COMPUTE ROLE", "VerdictWhite")]], colWidths=[124 * mm])
    verdict.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), GREEN),
                ("BOX", (0, 0), (-1, -1), 0.8, HexColor("#59D3A4")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
            ]
        )
    )
    story.append(verdict)
    story.append(Spacer(1, 8 * mm))
    intro = Table(
        [
            [P("WHAT PASSED", "CellWhiteBold"), P("WHAT THIS DOES NOT CLAIM", "CellWhiteBold")],
            [
                P(
                    "Full Vallado-style near-Earth and deep-space propagation; CPU/GPU agreement; independent implementation cross-check; pass-event identity; sustained laptop feasibility; container integrity.",
                    "CellWhite",
                ),
                P(
                    "Formal proof over every possible orbit, a full ITRF/EOP navigation stack, antenna and RF modeling, stale-element prediction accuracy, or operational safety certification.",
                    "CellWhite",
                ),
            ],
        ],
        colWidths=[62 * mm, 62 * mm],
    )
    intro.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), HexColor("#15254A")),
                ("TEXTCOLOR", (0, 0), (-1, -1), WHITE),
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#3B4C70")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2 * mm),
            ]
        )
    )
    story.append(intro)
    story.append(Spacer(1, 12 * mm))
    story.append(P("Prepared 16 August 2026  |  Windows 11  |  CUDA 12.8  |  driver 591.59", "SubtitleWhite"))
    story.append(P("Package: klb_seedchain_gpu_v0.5.0_full_sgp4", "SubtitleWhite"))
    story.append(PageBreak())


def build_story() -> list:
    story: list = []
    title_page(story)

    story += section(
        "Bottom line",
        "Yes, the SGP4 approach works on this laptop",
        "The package successfully stores compact orbital seeds and regenerates positions, velocities, and pass events on demand with the full SGP4/SDP4 branch set. The RTX 5070 Ti Laptop GPU is capable; the initial obstacle was automatic CUDA toolchain discovery, not insufficient hardware or a failed propagation idea.",
    )
    story.append(
        callout(
            "ELI5: instead of saving one photograph of every satellite for every second, the file saves each satellite's recipe. The GPU rapidly cooks the requested positions from those recipes. That is why the stored file stays tiny.",
            "good",
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        cards(
            [
                ("19.35 M", "full 7-day candidate intervals"),
                ("91.974 ms", "direct on-demand query, p50"),
                ("717 / 717", "pass events with exact identity"),
                ("0", "propagation and sanitizer errors"),
            ]
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(P("Decision", "H2"))
    story.append(
        data_table(
            ["Question", "Answer", "Evidence"],
            [
                ["Does full SGP4/SDP4 execute?", "YES", "Near-Earth, deep non-resonant, synchronous, and half-day resonance branches all passed."],
                ["Is the laptop powerful enough?", "YES", "About 208-212 million interval evaluations/s; 70 C maximum in a 98 s sustained run."],
                ["Is the compact representation real?", "YES, with wording caveat", "5,793-byte seed container replaces a chosen 590.6 MiB dense position buffer."],
                ["Is it an operational navigation system?", "NO", "TEME-to-PEF uses GMST+DUT1 approximation; polar motion, full EOP, RF, clock, and integrity are absent."],
            ],
            [43 * mm, 31 * mm, 100 * mm],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        callout(
            "Honest confidence statement: the bounded implementation claims are strongly validated. '100% correct for every possible input and mission' cannot be established by finite tests; that would require formal verification plus mission-specific certification.",
            "warn",
        )
    )
    story.append(PageBreak())

    story += section(
        "Root cause",
        "What was actually lacking?",
        "Three separate questions had been mixed together. The test evidence separates them cleanly.",
    )
    story.append(
        data_table(
            ["Layer", "Finding", "Verdict"],
            [
                ["SGP4/SDP4 mathematics", "All four propagation regimes execute and match reference results.", "Not lacking"],
                ["Laptop hardware", "RTX 5070 Ti Laptop, 12,227 MiB VRAM, compute capability 12.0; native GPU code runs normally.", "Not lacking"],
                ["Build integration", "The supplied Windows helper failed to discover CUDA 12.8 and then returned exit code 0 despite no executable/tests.", "Lacking"],
                ["Command-line workaround", "Explicit CUDA compiler/toolset and KLB_CUDA_ARCH=120 produced a native sm_120 + PTX build.", "Resolved for this run"],
                ["Approach scope", "Compact seeds + on-demand SGP4 is valid, but the ground-frame conversion is intentionally simplified.", "Valid, bounded"],
            ],
            [40 * mm, 101 * mm, 33 * mm],
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(P("Why the first attempt looked worse than it was", "H2"))
    story.append(bullet("CMake's automatic Windows CUDA discovery did not select the installed CUDA 12.8 toolchain for the new compute-capability 12.0 GPU."))
    story.append(bullet("The helper script did not stop or propagate the external command failure, so it printed a misleading success path."))
    story.append(bullet("After explicit configuration, the Release executable was 2,991,104 bytes and contained both <b>sgp4_bench.sm_120.cubin</b> and <b>sgp4_bench.sm_120.ptx</b>."))
    story.append(Spacer(1, 4 * mm))
    story.append(
        callout(
            "Direct answer: it was primarily the package's build automation. Your hardware and the core SGP4 seedchain approach both worked once the correct CUDA target was supplied.",
            "good",
        )
    )
    story.append(PageBreak())

    story += section(
        "Verification design",
        "How the result was challenged",
        "The test campaign deliberately used several different kinds of oracle so that one shared implementation could not simply agree with itself.",
    )
    story.append(
        data_table(
            ["Layer", "Coverage", "Result"],
            [
                ["Package integrity", "130 manifest SHA-256 entries", "130 valid; 0 missing or mismatched"],
                ["Native build/test", "MSVC + CUDA 12.8 + sm_120; CTest", "Build passed; 3/3 tests passed"],
                ["Published Vallado vectors", "Near, deep non-resonant, half-day, synchronous, GPS-like", "Maximum listed position difference 0.00682 mm"],
                ["CPU vs GPU", "256 GPS states + 40 all-branch states", "0 error/method mismatches; sub-micrometre maximum"],
                ["Independent codebase", "Python sgp4 2.25 / WGS72; 328 states, including long offsets", "0 errors; 0.265627 mm maximum position delta"],
                ["Full 7-day oracle", "19,353,600 candidate intervals", "All aggregate counters exact; 0 propagation errors"],
                ["Pass-event output", "717 expected events", "All event identities exact; timing inside tolerance"],
                ["Adversarial runtime", "memcheck, racecheck, synccheck, forced truncation", "0 sanitizer findings; truncation correctly rejected"],
            ],
            [38 * mm, 82 * mm, 54 * mm],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(P("Four regimes, not just GPS", "H2"))
    story.append(
        cards(
            [
                ("1", "near-Earth object"),
                ("2", "deep non-resonant objects"),
                ("1", "synchronous resonance object"),
                ("1", "half-day resonance object"),
            ]
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(P("The default GPS dataset contains only deep non-resonant objects. The separate Vallado branch container was therefore essential to exercise the remaining branches on the physical GPU.", "Small"))
    story.append(PageBreak())

    story += section(
        "Numerical accuracy",
        "Implementation error is far below the acceptance limits",
        "These measurements answer whether the code computes the selected SGP4 model consistently. They do not promise that an old OMM/TLE will predict the real satellite equally well.",
    )
    story.append(accuracy_chart())
    story.append(Spacer(1, 1 * mm))
    story.append(
        data_table(
            ["Comparison", "States", "RMS", "Maximum", "Limit / margin"],
            [
                ["GPS CPU vs GPU position", "256", "0.000070649 mm", "0.000383791 mm", "10 mm / 26,056x"],
                ["GPS CPU vs GPU velocity", "256", "0.000000010 mm/s", "0.000000056 mm/s", "0.01 mm/s / 178,571x"],
                ["All branches CPU vs GPU position", "40", "0.000072286 mm", "0.000378879 mm", "10 mm / 26,394x"],
                ["Independent WGS72 position", "328", "0.063645 mm", "0.265627 mm", "1 mm audit gate / 3.76x"],
                ["Independent WGS72 velocity", "328", "0.000507 mm/s", "0.000784 mm/s", "0.002 mm/s gate / 2.55x"],
            ],
            [46 * mm, 18 * mm, 37 * mm, 37 * mm, 36 * mm],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        callout(
            "The largest independent difference occurred for a reference object propagated roughly six years away from its epoch, an intentionally harsh numerical comparison. It still remained below 0.3 mm between implementations; physical orbit prediction at that age is a different question and would be much worse.",
            "info",
        )
    )
    story.append(PageBreak())

    story += section(
        "Seven-day result",
        "Pass scheduling matched end to end",
        "The main workload used 32 GPS objects, a seven-day horizon, one-second sampling, and a ground station at 52 N, 5 E.",
    )
    story.append(
        cards(
            [
                ("19,353,600", "candidate intervals"),
                ("19,207,536", "supported and compatible"),
                ("5,498,429", "visible endpoints"),
                ("0", "propagation errors"),
                ("359", "acquisition-of-signal events"),
                ("358", "loss-of-signal events"),
                ("717", "total compacted events"),
                ("717", "exact event identities matched"),
            ]
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        data_table(
            ["Comparison", "Identity", "Max guard delta", "Max crossing-time delta"],
            [
                ["GPU direct vs packaged CPU events", "717 / 717 exact", "8.372911e-9", "0.000090514 s"],
                ["GPU direct vs GPU dense", "717 / 717 exact", "2.775558e-16", "5.820766e-11 s"],
            ],
            [55 * mm, 40 * mm, 39 * mm, 40 * mm],
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(P("Determinism nuance", "H2"))
    story.append(bullet("Repacking the KSGP1 container produced a byte-identical file with the same SHA-256."))
    story.append(bullet("Regenerating the event CSV produced every field, row, identity, and value identically."))
    story.append(bullet("Its file hash differed only because Windows emitted CRLF line endings while the package used LF. Therefore semantic reproduction is exact, but the documentation's cross-platform byte-for-byte CSV claim needs canonical newlines."))
    story.append(Spacer(1, 3 * mm))
    story.append(callout("No silent data loss: forcing an event capacity of 1 for 11 produced events terminated with an explicit truncation error.", "good"))
    story.append(PageBreak())

    story += section(
        "Performance",
        "One direct query is faster; repeated cached queries are different",
        "For the stated seven-day workload, on-demand propagation avoids the cost of materializing a dense buffer and is about 3% faster end to end.",
    )
    story.append(performance_chart())
    story.append(
        data_table(
            ["Path", "p50", "p95", "p99", "Meaning"],
            [
                ["Direct seed query", "91.974 ms", "92.000 ms", "92.005 ms", "Propagate and query in one pass"],
                ["Materialize full SGP4", "88.443 ms", "-", "-", "Build 590.6 MiB double4 position buffer"],
                ["Resident dense query", "6.280 ms", "-", "-", "Query an already-built position buffer"],
                ["Dense end to end", "94.722 ms", "-", "-", "Materialization plus one query"],
            ],
            [43 * mm, 28 * mm, 26 * mm, 26 * mm, 51 * mm],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        callout(
            "Decision rule: for one pass over a horizon, direct seed propagation wins. If the exact same horizon will be queried two or more times, paying the materialization cost once and reusing the dense buffer can win on speed - if roughly 591 MiB of VRAM is acceptable.",
            "info",
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        cards(
            [
                ("210.4 M/s", "7-day direct throughput"),
                ("207.7 M/s", "1 GiB stress throughput"),
                ("212.2 M/s", "2 GiB stress throughput"),
                ("14.65x", "resident dense query vs direct"),
            ]
        )
    )
    story.append(P("The nearly constant throughput at 19.4M, 33.6M, and 67.1M candidates shows approximately linear scaling. Stress horizons extend far beyond the declared source-data horizon and are performance tests only.", "Small"))
    story.append(PageBreak())

    story += section(
        "Compression",
        "The giant ratio is real - and it is avoided materialization",
        "Calling this ordinary compression would be misleading. The package stores orbital elements and recomputes samples. The ratio therefore depends on how many time samples and which fields you choose as the hypothetical dense baseline.",
    )
    story.append(compression_chart())
    story.append(
        data_table(
            ["Baseline", "Bytes", "KSGP1 ratio", "Interpretation"],
            [
                ["KSGP1 container", "5,793", "1.0x", "32 portable seeds + timeline/metadata/container overhead"],
                ["Source OMM CSV", "4,852", "0.84x", "KSGP1 is actually 1.194x larger than the textual source"],
                ["7-day float4 positions", "309,658,112", "53,453.84x", "Avoided 16-byte position sample for each candidate"],
                ["7-day double4 positions", "619,316,224", "106,907.69x", "Measured GPU dense position-only baseline"],
                ["7-day position + velocity baseline", "928,974,336", "160,361.53x", "Higher baseline if both outputs are stored"],
                ["2 GiB stress dense buffer", "2,147,483,648", "370,703.20x", "Performance stress case, not extra information in the seed"],
            ],
            [46 * mm, 34 * mm, 31 * mm, 63 * mm],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(callout("Accurate wording: '5.8 KiB of seeds avoids materializing 590.6 MiB of seven-day double4 positions.' The ratio is horizon-dependent and compute is traded for storage.", "warn"))
    story.append(PageBreak())

    story += section(
        "GPU internals",
        "Compute-bound, register-limited, not memory-bound",
        "Nsight Compute and cuobjdump independently describe the same bottleneck: full SGP4 does substantial double-precision math per worker and uses many registers.",
    )
    story.append(
        data_table(
            ["Kernel", "Registers", "Stack", "Achieved occupancy", "SM / FP64 throughput", "DRAM"],
            [
                ["Direct seed query", "146", "48 B", "23.72%", "84.40% / 86.22%", "0.008%"],
                ["Materialize", "138", "48 B", "23.74%", "85.12% / 86.26%", "0.721%"],
                ["Dense query", "40", "0 B", "95.82%", "85.44% / 85.49%", "10.23%"],
                ["State validation", "130", "48 B", "not profiled", "not profiled", "not profiled"],
            ],
            [36 * mm, 25 * mm, 21 * mm, 32 * mm, 38 * mm, 22 * mm],
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(bullet("No register spills were reported by ptxas, even though the direct kernel uses 146 registers."))
    story.append(bullet("Theoretical direct occupancy is 25%; achieved occupancy was 23.72%. This is the clearest optimization target."))
    story.append(bullet("Short-scoreboard and wait stalls dominate; DRAM traffic is negligible for direct propagation. More memory bandwidth is unlikely to fix the main bottleneck."))
    story.append(bullet("A focused event-writing launch recorded exactly 717 global atomic requests for 717 events. L2 atomic activity was only 0.00758%, so event compaction contention is negligible here."))
    story.append(Spacer(1, 4 * mm))
    story.append(
        callout(
            "Practical optimization priority: reduce live state/register pressure or split carefully chosen phases only if profiling proves the extra traffic is worthwhile. Replacing the laptop GPU is not the first recommendation.",
            "info",
        )
    )
    story.append(PageBreak())

    story += section(
        "Reliability and thermals",
        "The laptop sustained the workload without instability",
        "A 600-repeat direct-only run held the GPU busy for about 98.4 seconds. This is enough to expose immediate thermal throttling, though it is not an hours-long endurance qualification.",
    )
    story.append(
        cards(
            [
                ("70 C", "maximum active temperature"),
                ("73.1 W", "average active GPU power"),
                ("74.8 W", "maximum sustained-run power"),
                ("2,763 MHz", "average active graphics clock"),
            ]
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        data_table(
            ["Signal", "Beginning", "End / maximum", "Interpretation"],
            [
                ["Temperature", "55 C active start", "70 C max; 69.9 C final-quarter average", "Warm but stable in this run"],
                ["Clock", "2,744 MHz first-quarter average", "2,767 MHz final-quarter average", "No sustained clock collapse"],
                ["Timing", "161.55 ms p50 short run", "162.33 ms p50 sustained", "About 0.48% slower when thermally settled"],
                ["VRAM", "seed/direct workload", "2,752 MiB maximum observed", "Well inside 12,227 MiB"],
            ],
            [35 * mm, 45 * mm, 48 * mm, 46 * mm],
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(P("CUDA runtime safety", "H2"))
    story.append(
        data_table(
            ["Tool", "Scope", "Result"],
            [
                ["Compute Sanitizer memcheck", "All-branch validation + GPU smoke workload", "0 errors"],
                ["Compute Sanitizer racecheck", "Event-writing direct smoke workload", "0 hazards, 0 warnings"],
                ["Compute Sanitizer synccheck", "Direct smoke workload", "0 errors"],
                ["Negative truncation test", "11 events into capacity 1", "Explicit failure; no silent truncation"],
            ],
            [44 * mm, 83 * mm, 47 * mm],
        )
    )
    story.append(PageBreak())

    story += section(
        "Feasibility",
        "What this can be used for now",
        "The strongest fit is high-volume analytical screening where compact distribution, deterministic regeneration, and one-pass filtering matter more than maintaining a reusable dense ephemeris cache.",
    )
    story.append(
        data_table(
            ["Use", "Fit", "Why"],
            [
                ["Constellation visibility screening", "Strong", "Millions of object-time candidates can be tested in under a tenth of a second for the demonstrated 32-object week."],
                ["Ground-station pass scheduling", "Strong with frame caveat", "717 pass boundaries reproduced with exact identities and sub-0.1 ms crossing-time delta."],
                ["Interactive scenario filtering", "Strong", "Seeds stay small; GPU recomputes only the selected horizon/criteria."],
                ["Large catalog batch analytics", "Promising, not yet measured", "Throughput scales linearly here, but thousands of objects and diverse regimes require a new benchmark."],
                ["Distribution or archival of dense trajectories", "Strong alternative", "A 5.8 KiB recipe can replace a chosen hundreds-of-MiB derived buffer."],
                ["Repeated queries over one frozen horizon", "Conditional", "Dense caching becomes faster after approximately the second query if VRAM is available."],
                ["Operational navigation / collision avoidance", "Not ready", "Requires current elements, frame/EOP rigor, covariance/uncertainty, validation, and mission certification."],
            ],
            [49 * mm, 34 * mm, 91 * mm],
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(callout("Best current product description: a GPU-native full-SGP4 analytical query substrate with a portable seed container - not a compressed truth ephemeris and not a complete navigation stack.", "good"))
    story.append(PageBreak())

    story += section(
        "Limits and fixes",
        "What must be improved before stronger claims",
        "None of these findings invalidates the core compute idea. They define the boundary between a successful technical substrate and a production-grade orbital service.",
    )
    story.append(
        data_table(
            ["Priority", "Finding", "Recommended action"],
            [
                ["P1", "Windows build helper hides failed CMake/build/test commands.", "Check and propagate every external exit code; verify expected binaries exist before reporting success."],
                ["P1", "Operational Earth-fixed accuracy is not in scope.", "Add UT1/EOP ingestion, polar motion, TEME-to-ITRF validation, station altitude/mask, and explicit time standards."],
                ["P1", "Model accuracy depends on fresh orbital elements.", "Define element-age limits and compare predictions against authoritative ephemerides over mission-relevant horizons."],
                ["P2", "Cross-platform event CSV hash is not reproducible because newline conventions differ.", "Write canonical LF or document semantic rather than byte identity."],
                ["P2", "Default GPS validation exercises only deep non-resonant objects.", "Make the all-branch Vallado container part of the standard GPU acceptance command."],
                ["P2", "Direct kernel is register-bound at about 24% occupancy.", "Profile register-lifetime reductions; preserve correctness and measure end-to-end impact."],
                ["P3", "Thermal run lasted 98 seconds, not hours.", "Add 30-60 minute endurance and repeatability runs if continuous service is intended."],
            ],
            [20 * mm, 75 * mm, 79 * mm],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        callout(
            "Go / no-go: GO for further engineering, demonstrations, and bounded analytical workloads. NO-GO for claims of operational navigation accuracy or universal correctness until the scope items above are implemented and independently certified.",
            "warn",
        )
    )
    story.append(PageBreak())

    story += section(
        "Evidence index",
        "Reproducible artifacts from this verification",
        "All paths below are relative to the package root. Console logs preserve the actual outputs; CSV and Nsight reports preserve raw metrics. The report itself is a summary, not a substitute for those artifacts.",
    )
    evidence_rows = [
        ["Integrity / build", "verification_build_windows_console.txt; verification_configure_cuda128_explicit_console.txt; verification_build_cuda128_console.txt; verification_ctest_console.txt"],
        ["Binary architecture", "verification_sgp4_cuobjdump_elf.txt; verification_sgp4_cuobjdump_ptx.txt; verification_sgp4_cuobjdump_resources.txt"],
        ["Reference accuracy", "verification_sgp4_reference_tests_console.txt; verification_gpu_gps_validation_console.txt; verification_gpu_all_branches_validation_console.txt"],
        ["Independent comparison", "verification_independent_sgp4_summary.json; verification_independent_sgp4_details.csv; verification_independent_sgp4_console.txt"],
        ["Full workload", "verification_sgp4_file_console.txt; sgp4_file_results.csv; verification_sgp4_full_cpu_oracle_console.txt"],
        ["Stress / thermals", "verification_sgp4_laptop_console.txt; verification_sgp4_2gib_console.txt; verification_sgp4_sustained_direct_console.txt; sgp4_sustained_direct_gpu_telemetry.csv"],
        ["Sanitizers / negative", "verification_compute_sanitizer_branches_console.txt; verification_compute_sanitizer_smoke_console.txt; verification_compute_sanitizer_racecheck_console.txt; verification_compute_sanitizer_synccheck_console.txt; verification_event_truncation_negative_console.txt"],
        ["Profiling", "sgp4_file_ncu.ncu-rep; sgp4_file_ncu_raw.csv; sgp4_event_ncu.ncu-rep; sgp4_event_ncu_raw.csv; verification_profile_sgp4_file_console.txt"],
        ["Determinism", "verification_repack_console.txt; verification_repacked_gps.ksgp; verification_regenerated_pass_console.txt; verification_regenerated_pass_events.csv"],
    ]
    story.append(data_table(["Evidence group", "Files"], evidence_rows, [42 * mm, 132 * mm]))
    story.append(Spacer(1, 5 * mm))
    story.append(P("System and method notes", "H2"))
    story.append(bullet("GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU, compute capability 12.0, 12,227 MiB VRAM."))
    story.append(bullet("Toolchain: NVIDIA driver 591.59, CUDA 12.8.61, CMake 4.3.2, MSVC 19.44; Release target KLB_CUDA_ARCH=120."))
    story.append(bullet("Independent library: Python sgp4 2.25 in WGS72 mode. This is an independent codebase comparison but uses the same published SGP4 model lineage."))
    story.append(bullet("Primary local model attribution: Vallado/CSSI SGP4/SDP4 implementation and the package's NOTICE_SGP4.md, validation documentation, and five-vector branch set."))
    story.append(Spacer(1, 4 * mm))
    story.append(
        callout(
            "Final verdict: the full-SGP4 seedchain mechanism is technically feasible and strongly validated on this laptop. The remaining gaps are build robustness, wording precision, and operational-system scope - not a failure of SGP4 or insufficient laptop hardware.",
            "good",
        )
    )
    return story


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = VerificationDocTemplate(str(OUTPUT))
    doc.build(build_story())
    print(f"created={OUTPUT}")
    print(f"bytes={OUTPUT.stat().st_size}")


if __name__ == "__main__":
    main()
