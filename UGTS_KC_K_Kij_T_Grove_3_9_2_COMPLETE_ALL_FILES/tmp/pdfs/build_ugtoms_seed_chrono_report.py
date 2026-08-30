from __future__ import annotations

from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


WORKSPACE = Path(__file__).resolve().parents[2]
PARENT = WORKSPACE.parent
OUTPUT = PARENT / "UGTOMS_CHRONO_BRACE_MONOCULAR_SCENE_3D_PROFILE_0_3.pdf"

NAVY = HexColor("#12263A")
INK = HexColor("#1E2B36")
SLATE = HexColor("#5D6B76")
PALE = HexColor("#EFF4F6")
TEAL = HexColor("#008B8B")
CYAN = HexColor("#DCF4F1")
ORANGE = HexColor("#E2782B")
GOLD = HexColor("#F1C453")
GREEN = HexColor("#147A55")
RED = HexColor("#B5423C")
WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN_X = 17 * mm
MARGIN_TOP = 17 * mm
MARGIN_BOTTOM = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X

BASE = getSampleStyleSheet()
STYLES = {
    "title": ParagraphStyle(
        "title",
        parent=BASE["Title"],
        fontName="Helvetica-Bold",
        fontSize=26,
        leading=30,
        textColor=WHITE,
        alignment=TA_LEFT,
        spaceAfter=8,
    ),
    "subtitle": ParagraphStyle(
        "subtitle",
        parent=BASE["Normal"],
        fontName="Helvetica",
        fontSize=12.2,
        leading=16.5,
        textColor=HexColor("#DCEAF0"),
    ),
    "h1": ParagraphStyle(
        "h1",
        parent=BASE["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=NAVY,
        spaceBefore=2,
        spaceAfter=9,
        keepWithNext=True,
    ),
    "h2": ParagraphStyle(
        "h2",
        parent=BASE["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12.3,
        leading=15.5,
        textColor=TEAL,
        spaceBefore=7,
        spaceAfter=5,
        keepWithNext=True,
    ),
    "body": ParagraphStyle(
        "body",
        parent=BASE["BodyText"],
        fontName="Helvetica",
        fontSize=9.15,
        leading=13.1,
        textColor=INK,
        spaceAfter=6,
    ),
    "small": ParagraphStyle(
        "small",
        parent=BASE["BodyText"],
        fontName="Helvetica",
        fontSize=7.55,
        leading=10.1,
        textColor=SLATE,
        spaceAfter=3,
    ),
    "table_header": ParagraphStyle(
        "table_header",
        parent=BASE["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=7.65,
        leading=10.1,
        textColor=WHITE,
    ),
    "caption": ParagraphStyle(
        "caption",
        parent=BASE["BodyText"],
        fontName="Helvetica-Oblique",
        fontSize=7.35,
        leading=9.4,
        textColor=SLATE,
        spaceBefore=3,
        spaceAfter=6,
    ),
    "bullet": ParagraphStyle(
        "bullet",
        parent=BASE["BodyText"],
        fontName="Helvetica",
        fontSize=8.8,
        leading=12.3,
        leftIndent=12,
        firstLineIndent=-7,
        bulletIndent=2,
        textColor=INK,
        spaceAfter=3,
    ),
    "callout": ParagraphStyle(
        "callout",
        parent=BASE["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=9.7,
        leading=13.6,
        textColor=NAVY,
        backColor=CYAN,
        borderColor=TEAL,
        borderWidth=0.7,
        borderPadding=8,
        spaceBefore=5,
        spaceAfter=8,
    ),
    "warning": ParagraphStyle(
        "warning",
        parent=BASE["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12.8,
        textColor=HexColor("#6C2D15"),
        backColor=HexColor("#FFF0E4"),
        borderColor=ORANGE,
        borderWidth=0.7,
        borderPadding=7,
        spaceBefore=4,
        spaceAfter=7,
    ),
    "code": ParagraphStyle(
        "code",
        fontName="Courier",
        fontSize=7.45,
        leading=9.8,
        textColor=INK,
        backColor=PALE,
        borderColor=HexColor("#C5D3DA"),
        borderWidth=0.5,
        borderPadding=7,
        spaceAfter=7,
    ),
}


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, STYLES[style])


def bullet(text: str) -> Paragraph:
    return Paragraph(f"- {text}", STYLES["bullet"])


def table(rows: list[list[str]], widths: list[float], *, compact: bool = False) -> Table:
    data = []
    for row_index, row in enumerate(rows):
        style = (
            STYLES["table_header"]
            if row_index == 0
            else STYLES["small"] if compact else STYLES["body"]
        )
        data.append([Paragraph(str(cell), style) for cell in row])
    result = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, HexColor("#B7C5CD")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return result


def arrow(d: Drawing, x1: float, y: float, x2: float, color=ORANGE) -> None:
    d.add(Line(x1, y, x2 - 5, y, strokeColor=color, strokeWidth=1.4))
    d.add(Polygon([x2 - 5, y + 3, x2, y, x2 - 5, y - 3], fillColor=color, strokeColor=color))


def status_table() -> Table:
    return table(
        [
            ["STATUS", "CURRENT EVIDENCE", "BOUNDARY"],
            ["VERIFIED", "Portable C++ writer/reader plus independent Python replay", "Synthetic exact fixtures"],
            ["PARTIAL", "Seed-regenerated 2D UGLUT2 traversal and owner-only YUV420 codewords", "No Klein/KLB37/tree/kinematic/SDF family"],
            ["PHYSICAL", "297 Camera2 frames/results/spooled at 1280 x 720 / 30 fps", "10-second POCO run"],
            ["PHYSICAL", "297 Mali integer dispatches; full CPU byte parity", "No CPU fallback"],
            ["VERIFIED", "Native on-device replay and independent pulled-file Python replay", "All Y/U/V/PTS/metadata"],
            ["UNKNOWN", "Metric 3D, hidden surfaces, complete human body", "No promotion from pixels alone"],
        ],
        [26 * mm, 87 * mm, 46 * mm],
        compact=True,
    )


def async_pipeline_drawing() -> Drawing:
    d = Drawing(CONTENT_W, 174)
    stages = [
        (0, 113, 76, "CAMERA2", "AImage / PTS", TEAL),
        (92, 113, 82, "COPY QUEUE", "preallocated", NAVY),
        (190, 113, 82, "UGRAWS1", "exact spool", ORANGE),
        (288, 113, 82, "VULKAN", "u8 residual", GREEN),
        (386, 113, 90, "UGYUVS1", "ordered commit", TEAL),
    ]
    for x, y, w, title, body, color in stages:
        d.add(Rect(x, y, w, 39, 4, 4, fillColor=PALE, strokeColor=color, strokeWidth=1.1))
        d.add(String(x + w / 2, y + 24, title, textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.4, fillColor=NAVY))
        d.add(String(x + w / 2, y + 10, body, textAnchor="middle", fontName="Helvetica", fontSize=6.5, fillColor=SLATE))
    for x1, x2 in [(76, 92), (174, 190), (272, 288), (370, 386)]:
        arrow(d, x1 + 2, 132, x2 - 2)
    d.add(String(38, 96, "camera callback", textAnchor="middle", fontName="Helvetica-Bold", fontSize=6.8, fillColor=TEAL))
    d.add(String(133, 96, "bounded handoff", textAnchor="middle", fontName="Helvetica-Bold", fontSize=6.8, fillColor=NAVY))
    d.add(String(231, 96, "spool worker", textAnchor="middle", fontName="Helvetica-Bold", fontSize=6.8, fillColor=ORANGE))
    d.add(String(329, 96, "post-capture worker", textAnchor="middle", fontName="Helvetica-Bold", fontSize=6.8, fillColor=GREEN))
    d.add(String(431, 96, "block workers", textAnchor="middle", fontName="Helvetica-Bold", fontSize=6.8, fillColor=TEAL))
    d.add(Line(431, 111, 431, 72, strokeColor=ORANGE, strokeWidth=1.2))
    d.add(Rect(248, 34, 82, 34, 4, 4, fillColor=CYAN, strokeColor=TEAL, strokeWidth=1))
    d.add(Rect(346, 34, 82, 34, 4, 4, fillColor=CYAN, strokeColor=TEAL, strokeWidth=1))
    d.add(Rect(438, 34, 38, 34, 4, 4, fillColor=PALE, strokeColor=NAVY, strokeWidth=1))
    d.add(String(289, 54, "NATIVE", textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.2, fillColor=NAVY))
    d.add(String(289, 42, "strict replay", textAnchor="middle", fontName="Helvetica", fontSize=6.3, fillColor=SLATE))
    d.add(String(387, 54, "PYTHON", textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.2, fillColor=NAVY))
    d.add(String(387, 42, "independent", textAnchor="middle", fontName="Helvetica", fontSize=6.3, fillColor=SLATE))
    d.add(String(457, 54, "PLAYER", textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.0, fillColor=NAVY))
    d.add(String(457, 42, "pending", textAnchor="middle", fontName="Helvetica", fontSize=6.1, fillColor=SLATE))
    arrow(d, 431, 51, 438)
    arrow(d, 330, 51, 346)
    d.add(Line(431, 72, 289, 72, strokeColor=ORANGE, strokeWidth=1.2))
    d.add(Line(289, 72, 289, 68, strokeColor=ORANGE, strokeWidth=1.2))
    d.add(String(0, 10, "UI/main thread: scene lifecycle and controls only - never camera copy, hashing, residual generation, entropy, or file I/O", fontName="Helvetica-Bold", fontSize=7.2, fillColor=RED))
    return d


def file_layers_drawing() -> Drawing:
    d = Drawing(CONTENT_W, 136)
    blocks = [
        (0, 76, 76, 42, "SEED", "8 B root", TEAL),
        (82, 76, 85, 42, "UGLUT2", "144 B once", GOLD),
        (173, 76, 90, 42, "HEADER", "512 B", NAVY),
        (269, 76, 90, 42, "FRAMES", "384 B + blocks", ORANGE),
        (365, 76, 72, 42, "END", "192 B", GREEN),
        (443, 76, 33, 42, "SHA", "chain", TEAL),
    ]
    for x, y, w, h, title, body, color in blocks:
        text_color = INK if color == GOLD else WHITE
        d.add(Rect(x, y, w, h, 3, 3, fillColor=color, strokeColor=None))
        d.add(String(x + w / 2, y + 25, title, textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.3, fillColor=text_color))
        d.add(String(x + w / 2, y + 11, body, textAnchor="middle", fontName="Helvetica", fontSize=6.3, fillColor=text_color))
    d.add(String(0, 55, "Final .ugsp4c: seed/program state + exact novelty evidence + integrity/commit state", fontName="Helvetica-Bold", fontSize=8, fillColor=NAVY))
    d.add(Rect(0, 13, 225, 26, 3, 3, fillColor=HexColor("#FFF0E4"), strokeColor=ORANGE, strokeWidth=0.8))
    d.add(String(8, 28, "Transient .camera-exact.spool.partial", fontName="Helvetica-Bold", fontSize=7.2, fillColor=HexColor("#6C2D15")))
    d.add(String(8, 18, "dense Y/U/V + metadata; removed only after verified replay", fontName="Helvetica", fontSize=6.3, fillColor=SLATE))
    d.add(Rect(242, 13, 234, 26, 3, 3, fillColor=PALE, strokeColor=TEAL, strokeWidth=0.8))
    d.add(String(250, 28, "Not stored: W x H permutation, MP4 payload, generated pixels", fontName="Helvetica-Bold", fontSize=7, fillColor=NAVY))
    d.add(String(250, 18, "the traversal is regenerated; camera novelty remains explicit", fontName="Helvetica", fontSize=6.3, fillColor=SLATE))
    return d


def compute_drawing() -> Drawing:
    d = Drawing(CONTENT_W, 146)
    d.add(Rect(0, 80, 116, 45, 4, 4, fillColor=PALE, strokeColor=TEAL, strokeWidth=1))
    d.add(Rect(180, 80, 116, 45, 4, 4, fillColor=PALE, strokeColor=GREEN, strokeWidth=1))
    d.add(Rect(360, 80, 116, 45, 4, 4, fillColor=PALE, strokeColor=ORANGE, strokeWidth=1))
    d.add(String(58, 106, "HOST-VISIBLE INPUT", textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.1, fillColor=NAVY))
    d.add(String(58, 91, "current / previous / map", textAnchor="middle", fontName="Helvetica", fontSize=6.4, fillColor=SLATE))
    d.add(String(238, 106, "MALI COMPUTE", textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.1, fillColor=NAVY))
    d.add(String(238, 91, "256 lanes; modulo u8", textAnchor="middle", fontName="Helvetica", fontSize=6.4, fillColor=SLATE))
    d.add(String(418, 106, "VERIFIED OUTPUT", textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.1, fillColor=NAVY))
    d.add(String(418, 91, "GPU bytes == CPU bytes", textAnchor="middle", fontName="Helvetica", fontSize=6.4, fillColor=SLATE))
    arrow(d, 118, 102, 178, GREEN)
    arrow(d, 298, 102, 358, GREEN)
    d.add(Line(418, 78, 418, 55, strokeColor=ORANGE, strokeWidth=1.2))
    d.add(Line(418, 55, 58, 55, strokeColor=ORANGE, strokeWidth=1.2))
    d.add(Line(58, 55, 58, 78, strokeColor=ORANGE, strokeWidth=1.2))
    d.add(String(238, 39, "full byte parity is the acceptance gate; a mismatch stops the GPU path", textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.2, fillColor=RED))
    d.add(String(238, 20, "Entropy selection, ordered commits, disk I/O and geometry stay outside this shader.", textAnchor="middle", fontName="Helvetica", fontSize=7, fillColor=SLATE))
    return d


def cover_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(TEAL)
    canvas.rect(0, PAGE_H - 22 * mm, PAGE_W, 22 * mm, fill=1, stroke=0)
    canvas.setFillColor(GOLD)
    canvas.circle(PAGE_W - 27 * mm, PAGE_H - 56 * mm, 16 * mm, fill=1, stroke=0)
    canvas.setFillColor(ORANGE)
    canvas.circle(PAGE_W - 27 * mm, PAGE_H - 56 * mm, 7 * mm, fill=1, stroke=0)
    canvas.restoreState()


def later_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(HexColor("#C5D2D9"))
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_X, PAGE_H - 11 * mm, PAGE_W - MARGIN_X, PAGE_H - 11 * mm)
    canvas.setFillColor(SLATE)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(MARGIN_X, PAGE_H - 8.5 * mm, "UGTOMS GSP4 camera seed-storage profile 0.3 - PARTIAL-SUBSTRATE DRAFT")
    canvas.drawRightString(PAGE_W - MARGIN_X, 8 * mm, f"{doc.page}")
    canvas.restoreState()


def page_decor(canvas, doc) -> None:
    if doc.page == 1:
        cover_page(canvas, doc)


class OverlayDocTemplate(SimpleDocTemplate):
    """Draw repeated navigation after flowables so no table can cover it."""

    def afterPage(self) -> None:
        if self.page > 1:
            later_page(self.canv, self)


def page_title(title: str, kicker: str) -> list:
    return [p(kicker.upper(), "small"), p(title, "h1")]


def build_story() -> list:
    story = []
    story.extend(
        [
            Spacer(1, 45 * mm),
            p("UGTOMS GSP4 Camera Seed Storage", "title"),
            p("Camera2 exact evidence, Mali Vulkan compute, UGYUVS1 replay, and bounded non-generative 3D+time", "subtitle"),
            Spacer(1, 12 * mm),
            p("PROFILE 0.3 - PARTIAL-SUBSTRATE CAMERA DRAFT", "subtitle"),
            Spacer(1, 6 * mm),
            p("Target: POCO X7 Pro | 1280 x 720 YUV420 at 30 fps | Mali-G720 MC7", "subtitle"),
            p("Evidence snapshot: 2026-08-30 | 297-frame POCO capture and Mali dispatch verified", "subtitle"),
            Spacer(1, 25 * mm),
            p("Engineering verdict", "subtitle"),
            p(
                "The physically implemented path is an asynchronous partial-substrate exact-camera baseline: Camera2 samples are copied into a bounded queue, durably spooled without loss, transformed after capture by an integer Vulkan-compute residual stage, committed as a UGYUVS1 seed/address program plus explicit novelty, and accepted only after native and independent Python replay. It does not yet execute the full Klein/KLB37/tree/kinematic/SDF substrate. The root seed cannot replace arbitrary camera novelty, and metric 3D and hidden surfaces remain UNKNOWN.",
                "subtitle",
            ),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Executive verdict", "What exists and what does not"))
    story.append(status_table())
    story.append(Spacer(1, 6))
    story.append(
        p(
            "<b>Delivered partial-substrate baseline:</b> Camera2 dense YUV420 is the authority. The seed-regenerated 2D UGLUT2 traversal, GSP4-derived lineage, exact modular residuals, negative-memory omission, durable commits, and two independent replay implementations are concrete. The Mali shader and Vulkan host path execute with byte-for-byte CPU comparison on every dispatch.<br/><br/><b>Size truth:</b> root seed payload 8 B; standalone capture 177,487,908 B (169.266 MiB); APK 1,582,206 B; file + APK 179,070,114 B. Accepted dense YUV was 410,572,800 B, so this run is 2.31324:1, or 56.7707% smaller.",
            "callout",
        )
    )
    story.append(
        p(
            "SCOPE CORRECTION: this physical UGYUVS1/Vulkan artifact is not a full-substrate encoding. It does not execute or serialize/hash-bind the discrete Klein quotient, KLB37-style packed log-spherical nodes, parity/radix-tree bifurcation, kinematic phase/velocity/acceleration, periodic lower-case phi cone field, or the pyramid/triangle, sphere, cone and apex SDF operator family.",
            "warning",
        )
    )
    story.extend(
        [
            bullet("No user-supplied MP4 is an input, payload, or acceptance fixture for this camera profile."),
            bullet("The installed ARM64 APK is 1,582,206 bytes, SHA-256 D421BCD4...2C4841C; its ZIP entries include no .mp4."),
            bullet("The inspected ARM64 library exposes AImageReader and Vulkan compute symbols but no AMediaCodec or AMediaExtractor symbols."),
            bullet("The editable KCCH392 pack owns one PLAYER node and one RECORDER node; its current pack is 436 bytes and its UGLUT2 dependency is 144 bytes."),
            bullet("The POCO accepted 297 Camera2 images with 297 capture results and spooled all 297; the exact spool was 410,672,720 bytes."),
            bullet("Mali-G720 MC7 executed 297 residual dispatches with full CPU byte parity and no fallback; native replay verified all planes, metadata and sensor PTS."),
            bullet("The pulled 177,487,908-byte file passed independent Python verification; visible player presentation, host C++ rerun, endurance, and crash-prefix recovery remain open."),
            bullet("Same-frame exact comparison: UGYUVS1 is 1.7085484454x the FFV1 file and 2.7289156226x the x264 lossless file; it is not codec-competitive yet."),
        ]
    )
    story.append(
        p(
            "This PDF remains a DRAFT because the exact partial-substrate recorder/transcoder/replay chain is physical, but the full-substrate camera operator, visible PLAYER-node presentation, one- and ten-minute endurance, kill recovery and calibrated 3D promotion are not yet complete.",
            "warning",
        )
    )
    story.append(PageBreak())

    story.extend(page_title("Asynchronous execution contract", "No main-thread encoding"))
    story.append(async_pipeline_drawing())
    story.extend(
        [
            p("<b>Camera callback:</b> acquire one AImage, validate dimensions/strides/timestamp, copy dense Y/U/V and the 128-byte canonical metadata record into a reserved slot, release the AImage, and return. It does not hash, encode, submit Vulkan, or write files."),
            p("<b>Spool worker:</b> consumes slots in ordinal order, writes the exact UGRAWS1 record, hashes planes and metadata, releases each slot, and fails explicitly on any I/O or sequence error."),
            p("<b>Post-capture worker:</b> starts only after the spool is closed and consistent. It rechecks every spool digest, dispatches Vulkan residual work, feeds bounded native block workers, commits results in canonical order, finalizes UGYUVS1, replays the file, then deletes the spool only after exact verification."),
            p("<b>Main/UI thread:</b> only owns activity/scene lifecycle and editable controls. Stop/focus-loss can trigger finalization, but transcode and replay continue on a dedicated worker."),
            p("Queue pressure never licenses a drop. The legal outcomes are continued exact spooling or an explicit failure receipt and stop.", "warning"),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("What is stored", "Seed, recipe, novelty, and transient spool are different"))
    story.append(file_layers_drawing())
    story.append(
        table(
            [
                ["Artifact", "Role", "Persistence / size"],
                ["root_seed_u64", "Selects deterministic traversal lineage", "8 bytes; addressing only"],
                ["UGLUT2", "Literal binary16 log-radius and direction support", "144 bytes once; SHA-bound"],
                ["KCCH392", "Editable PLAYER/RECORDER scene-node ownership", "436-byte current pack"],
                ["UGRAWS1 spool", "Crash-survivable exact dense Camera2 handoff", "Transient; 1,382,736 bytes/frame with fixed metadata/header"],
                ["UGYUVS1 .ugsp4c", "Final seed program plus exact novelty and integrity chain", "Content-dependent; never seed-only for arbitrary camera data"],
                ["JSON receipt", "Independent audit and machine-readable replay result", "Derivative; not sample authority"],
            ],
            [38 * mm, 72 * mm, 49 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("At 1280 x 720 YUV420, one authoritative dense frame is exactly <b>1,382,400 bytes</b>. The spool adds one 208-byte frame header and one 128-byte metadata record: 1,382,736 bytes/frame, about 41.48 MB/s at 30 fps."),
            p("That is approximately 414.8 MB for 10 seconds, 2.49 GB for one minute, and 24.89 GB for ten minutes before final transcode. These are deterministic capacity estimates, not measured sustained phone throughput."),
            p("<b>Measured physical run:</b> 410,572,800 accepted YUV bytes became a 177,487,908-byte standalone .ugsp4c (169.266 MiB). With the 1,582,206-byte APK, the combined stored footprint is 179,070,114 bytes. The 8-byte seed is included in program state; it is not the standalone recording size."),
            p("A tiny seed is not a tiny lossless camera recording. If the observations are absent from the file, APK, network, or declared external store, they cannot be reconstructed exactly.", "callout"),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Literal codeword and 2D log-polar traversal", "The partial baseline executes the address program"))
    story.append(
        Preformatted(
            "UGCODE24-420(x,y) = [Y(y,x), U(floor(y/2),floor(x/2)),\n"
            "                      V(floor(y/2),floor(x/2))]\n\n"
            "store Y at every generated (x,y)\n"
            "store U,V only when x and y are both even\n\n"
            "a_i = UGTRV1(UGLUT2, combine(root_seed, recipe_seed), i)",
            STYLES["code"],
        )
    )
    story.extend(
        [
            p("Every 2 x 2 luma group contains four Y bytes plus one U and one V byte. Canonical owner packing therefore preserves the exact six YUV420 bytes without copying chroma four times."),
            p("UGTRV1 regenerates every luma address exactly once from doubled pixel centers, binary16 radius/direction lanes, integer Q16/Q30 conversion, radial and angular classification, packed rho/theta keys, SplitMix64 lineage, and a Cartesian final tie-break."),
            p("The file stores the root seed, recipe/profile identifiers and dependency hashes. It never stores a 1280 x 720 permutation. The current 720p synthetic oracle generated the traversal and inverted all Y/U/V bytes exactly."),
            p("Seed and recipe are executable structure. Novelty bytes are irreducible observed evidence. The distinction is the core information boundary.", "callout"),
            p("Current fixed-profile evidence", "h2"),
        ]
    )
    story.append(
        table(
            [
                ["Item", "Verified value"],
                ["Dense YUV420 bytes/frame", "1,382,400"],
                ["Owner-packed codeword bytes/frame", "1,382,400"],
                ["UGLUT2", "144 bytes; SHA-256 dde65daf...243b49"],
                ["Python oracle traversal digest", "a3be1412...05fa22"],
                ["Pack/inverse", "Every synthetic Y, U and V byte reproduced"],
            ],
            [62 * mm, 97 * mm],
            compact=True,
        )
    )
    story.append(PageBreak())

    story.extend(page_title("Full-substrate gap and next acceptance gate", "Correction - the physical artifact is a partial baseline"))
    story.append(
        p(
            "The 297-frame POCO result verifies a useful exact camera/storage path, but it does not satisfy the user's full-substrate requirement. Every missing operator below must become operative in the encoded program, hash-bound, and independently replayable. A decorative LUT, unused receipt field, or CPU-only side calculation does not close this gate.",
            "warning",
        )
    )
    story.append(
        table(
            [
                ["Required substrate element", "Physical UGYUVS1 baseline", "Full-substrate acceptance"],
                ["Discrete Klein quotient", "ABSENT", "Versioned seam/gluing rule plus finite seam fixtures"],
                ["Packed log-spherical nodes", "Only 2D UGLUT2 address traversal", "KLB37-style fixed record; seed-regenerated rho/theta/phi; generated-node hash"],
                ["Parity/radix-tree bifurcation", "ABSENT", "Flat breadth-first radix/BST records; deterministic branch/route hash"],
                ["Kinematic calculus", "ABSENT", "Bounded fixed-point phase += velocity; velocity += acceleration"],
                ["Lower-case phi cone field", "ABSENT", "Periodic phi, frozen units/range/wrap and guarded field classification"],
                ["Elementary SDF family", "ABSENT", "T side-view pyramid/delta triangle, sphere, cone and apex operators"],
                ["Exact camera residual", "PRESENT and physically verified", "Must remain byte authority after every generated prediction"],
            ],
            [48 * mm, 48 * mm, 63 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("<b>Implementation gate:</b> freeze one versioned integer/fixed-point operator, including quantization, overflow, seam, branch, wrap and guard behavior. Hash-bind the generated node program and every selected predictor/route to each frame or block."),
            p("Port that same operator to Mali Vulkan, native CPU and the independent Python oracle. Require identical generated nodes, branch hashes, SDF/guard classifications, residual bytes, Y/U/V, metadata and PTS across all three implementations."),
            p("Re-encode the same 297-frame fixture and count every stored node, tree, SDF, kinematic and guard byte. Compare the final exact file against the 177,487,908-byte partial baseline, FFV1 and x264 lossless. Until that passes, full-substrate size and compression benefit are UNKNOWN.", "callout"),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Applied GSP4 baseline and negative memory", "Novelty is exact difference, not invention"))
    story.append(
        Preformatted(
            "finite generated state\n"
            "  -> radial/angular address support\n"
            "  -> lane/profile compatibility\n"
            "  -> finite buffer/timestamp/predictor guards\n"
            "  -> verified exact modulo-256 difference\n"
            "  -> seed-derived route and lineage\n"
            "  -> append-only novelty chain\n\n"
            "delta = (observed - predicted) mod 256\n"
            "observed = (predicted + delta) mod 256",
            STYLES["code"],
        )
    )
    story.extend(
        [
            p("A zero residual is negative memory: the generated prior state already yields the accepted byte, so no novelty value is emitted. A nonzero residual remains in the file. Omission never means empty space, disappearance, occlusion, or a hidden surface."),
            p("Each default block covers 65,536 luma addresses and chooses the byte-smallest exact representation under a canonical tie order."),
        ]
    )
    story.append(
        table(
            [
                ["ID", "Block representation", "Exact payload rule"],
                ["0", "ZERO", "No residual values; generated state is already exact"],
                ["1", "DENSE", "Every owner-ordered residual byte"],
                ["2", "SPARSE_BITMASK", "Occupancy bits followed by nonzero bytes"],
                ["3", "SPARSE_GAPS", "Canonical ULEB zero-gaps plus nonzero bytes"],
            ],
            [14 * mm, 49 * mm, 96 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("The current predictor baseline is RAW_EXACT_LANE for checkpoints and PREVIOUS_SAME_ADDRESS afterward. Spatial MED and temporal-plus-spatial-difference searches remain future exact candidates; adding them must not change sample authority."),
            p("Every frame binds ordinal, sensor timestamp, metadata, dependency ordinal, dense-plane hashes, pre-substrate digest, novelty digest, prior-record hash and self hash. Two alternating commit slots expose only a fully committed prefix after interruption."),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Why Mali Vulkan compute is used", "Exact integer residual, not AI"))
    story.append(compute_drawing())
    story.extend(
        [
            p("The shader computes the canonical owner-ordered residual from current dense bytes, prior dense bytes, and a seed-derived lane-source map. It uses 8-bit storage and 256 invocations per workgroup. The host records dispatch count, workgroups, GPU timestamp, wall time and residual SHA-256."),
            p("The CPU independently computes the full residual and compares every byte before the writer consumes GPU output. Vulkan failure or mismatch disables the GPU route; it does not silently authorize approximate data."),
            p("<b>Physical execution:</b> the POCO selected Mali-G720 MC7 with Vulkan API 1.3.278, 256-lane workgroups and 5,400 groups for 1,382,400 owner-ordered lanes. All 297 frames dispatched on the GPU with no CPU fallback. The first dispatch measured 2.446846 ms GPU and 4.227 ms wall, with full CPU byte parity. Its frame-0 residual SHA-256 is b690a0143df7870c4407c2e9fb33e91526fc4b3cc4978e0e88d17a38610475c6; this is not an aggregate residual hash."),
            p("<b>Capability boundary:</b> ADB also reports storageBuffer8BitAccess, shaderInt8, up to 1,024 compute invocations, 32,768 bytes shared memory and 64-byte noncoherent atoms. One run proves this bounded path on this device/software state, not every driver, workload or thermal condition."),
            p("<b>Bandwidth:</b> authoritative capture is about 41.47 MB/s. A naive current+previous upload plus residual readback is about 124.4 MB/s, excluding a one-time/static lane map and synchronization. That traffic is modest for an integrated GPU, but host-visible mapping, cache flush/invalidate, readback fences, spool I/O and CPU block packaging can dominate. Physical measurements decide the bottleneck."),
            p("<b>NPU:</b> not used. The task is a simple exact integer bijection, while NPU paths add vendor/runtime uncertainty and usually target approximate tensor inference. An NPU may propose non-authoritative features later, never camera-content truth."),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Verified partial-baseline device evidence", "Evidence snapshot - bounded claims only"))
    story.append(
        table(
            [
                ["Check", "Result"],
                ["Python codeword oracle", "9 tests pass; strided normalization, owner packing, inverse, residual and lineage"],
                ["Independent Python UGYUVS1 verifier", "7 tests pass; all four block modes, commit recovery, FINAL gates, corruption rejection"],
                ["Native/Python 320 x 180 cross-fixture", "4 exact frames; file SHA-256 22ac87ed...216d1"],
                ["Native/Python 1280 x 720 cross-fixture", "3 exact frames; 4,147,200 authoritative bytes; file SHA-256 63b51ae1...7cdab"],
                ["720p file size", "1,393,123 bytes for checkpoint + unchanged + five-byte sparse change"],
                ["720p novelty", "1,380,600 checkpoint events, 0 unchanged events, 5 sparse events"],
                ["720p block modes", "15 DENSE, 27 ZERO, 3 SPARSE_GAPS"],
                ["Native worker settings", "4 persistent block workers, max 8 in flight, deterministic ordered commit"],
                ["Installed APK", "1,582,206 bytes; SHA-256 D421BCD4...2C4841C; ARM64"],
                ["Static payload audit", "No .mp4 ZIP entry; 144-byte UGLUT2; 436-byte KCCH392"],
                ["Static native symbol audit", "AImageReader + Vulkan compute symbols; no AMediaCodec/AMediaExtractor symbols"],
                ["Physical Camera2 capture", "297 accepted images = 297 results = 297 spooled; 410,672,720-byte exact spool"],
                ["Physical Mali transcode", "297 dispatches; 6 block workers; 12 in flight; no fallback; CPU full parity"],
                ["Physical native replay", "297 frames; Y/U/V + metadata + sensor PTS verified; spool removed afterward"],
                ["Pulled-file Python replay", "PASS; 177,487,908 bytes; SHA-256 9df3c9c6...514669"],
            ],
            [59 * mm, 100 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("The synthetic 720p fixture is intentionally favorable: the second frame is identical and the third changes only five owner-lane bytes. Its ratio does not predict natural-camera file size."),
            p("The host benchmark measured about 23.4 MiB/s for a checkpoint and about 32.2-32.7 MiB/s for unchanged/sparse append, with 0.418 seconds to replay three frames. These one-run host numbers are diagnostic, not POCO performance."),
            p("The physical final file is 43.2293% of 410,572,800 authoritative plane bytes, a 56.7707% reduction for this run. It contains 126,884,266 novelty events, 150 DENSE blocks and 4,305 SPARSE_BITMASK blocks. This is one capture, not a general compression ratio."),
            p("A separate host C++ replay, visible PLAYER-node presentation, endurance and kill-recovery evidence remain open; the existing on-device native replay and independent Python replay do not waive those gates.", "warning"),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Same-frame storage comparison", "Exact baselines - current UGYUVS1 is not codec-competitive"))
    story.append(
        p(
            "All exact candidates below were decoded to the same 410,572,800-byte planar yuv420p stream. The authoritative replay SHA-256 is <b>10ac4aaa25d68465921419a74dfc2f4f15c3269ed11fe26e04465cd93a36f84b</b>. The lossy proxy is included only as a size reference and does not pass that hash.",
            "callout",
        )
    )
    story.append(
        table(
            [
                ["Format / setting", "Bytes", "Decoded identity", "Measured finding"],
                ["Raw yuv420p replay", "410,572,800", "Authority", "Uncompressed exact baseline"],
                ["UGYUVS1 .ugsp4c", "177,487,908", "Exact SHA match", "2.31324:1 versus raw"],
                ["FFV1 level 3 MKV", "103,882,280", "Exact SHA match", "UGYUVS1 is 1.7085484454x larger"],
                ["libx264 -qp 0 MKV", "65,039,720", "Exact SHA match", "UGYUVS1 is 2.7289156226x larger"],
                ["H.264 High 8 Mb/s proxy MP4", "9,515,400", "SHA differs - lossy", "7,686,088 bps actual; not an exact peer"],
            ],
            [46 * mm, 27 * mm, 37 * mm, 49 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("The UGYUVS1 file is also 18.6527006747x the lossy proxy, but that ratio is not a lossless comparison. A small proxy cannot satisfy the profile's byte-identical replay contract."),
            p("<b>Storage verdict:</b> both verified conventional lossless baselines win decisively on this capture. UGYUVS1 currently earns its engineering value through seed execution, deterministic lineage, canonical novelty records, crash-safe commits, and auditability - not through a file-size win."),
            p("The next compression work is bounded: test additional exact predictor and block programs against the same frame ledger, retain only byte-identical decodes, and report the smallest tested result. Do not claim an absolute minimum.", "warning"),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("From exact camera time to bounded 3D+time", "Classical geometry only after replay truth"))
    story.append(p("IMPLEMENTATION STATE: visible GLES player presentation and 3D reconstruction are NOT IMPLEMENTED in the delivered camera artifact. This page defines a bounded, non-generative promotion path; it does not report reconstructed geometry.", "warning"))
    story.append(
        table(
            [
                ["Stage", "Allowed operation", "Authority / failure state"],
                ["0 - evidence", "Exact Y/U/V, sensor time, crop, exposure and camera metadata", "OBSERVED; replayable"],
                ["1 - camera", "Measured intrinsics/distortion/shutter; row-aware ray tubes", "BOUNDED_SUPPORT or UNKNOWN"],
                ["2 - proposals", "GFTT/KLT, masks, descriptors, flow, motion partitions", "PROPOSAL_ONLY"],
                ["3 - contraction", "H/F/E, Sampson, cheirality, parallax, triangulation, reprojection", "Surviving bounded branches"],
                ["4 - scene/object", "Static candidate, independent motion, occluder, unresolved, unknown", "Every observed footprint classified"],
                ["5 - materialize", "Same-time sparse points, surfels, sparse voxels or open mesh", "Derived from promoted support"],
                ["6 - rasterize", "Display or proposal residual", "Downstream; cannot certify itself"],
            ],
            [24 * mm, 79 * mm, 56 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("The contractor is circular in the useful sense: camera, object association, scale gauge, visibility, pose and geometry branches repeatedly narrow one another while preserving every surviving alternative. It must be outward-rounded and finite; convergence to a pretty answer is not evidence."),
            p("Static regions matter as much as people or moving objects. A mask complement, low motion, repeated texture or prediction success is not proof of static geometry or free space."),
            p("No face, voxel, surfel or sheet spans two source times. Chrono continuity is lineage between same-time states. A mesh at one instant may exist only where that instant has promoted visible support; topology behind the camera remains UNKNOWN."),
            p("MoGe2, DA3, DINOv3, SAM3, ViT, SLAM and similar systems may inspire exact equations or supply hash-bound proposals. Learned depth, features, masks, pose or completion never replace the exact residual and never write authoritative geometry."),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Human specialization without a generated body", "Body4D as bounded visible structure"))
    story.append(
        table(
            [
                ["May be represented", "Must stay UNKNOWN or PROXY_ONLY"],
                ["Visible 2D joints and part masks at one time", "Hidden anatomy and unobserved backs"],
                ["Bounded joint-angle alternatives and cyclic constraints", "A single learned pose treated as truth"],
                ["Same-time articulated transforms with evidence intervals", "Cross-time skin sheet or closed topology"],
                ["Visibility, association and owner-handoff branches", "Occlusion inferred from missing pixels alone"],
                ["Visible open surface or explicitly authored proxy", "Cloth, hair, skin continuity without support"],
            ],
            [79.5 * mm, 79.5 * mm],
        )
    )
    story.extend(
        [
            p("A human target needs more state than a generic rigid object: joint graph, part association, self-occlusion, articulation limits, cloth/hair discontinuity, contact and identity continuity. Those fields are specialized constraints, not permission to synthesize a complete person."),
            p("Body4D-style outputs can enter as bounded candidate joints, visible parts or a removable proposal seed. They must carry model/code/checkpoint/configuration hashes and cannot promote hidden shape."),
            p("Negative-memory events for a person include support birth/tightening/retraction, joint-branch split, chart discontinuity, visibility change, owner handoff and checkpoint seal. Equal accepted state emits no event."),
            p("Practical outputs are an editable matchmove proxy, visible-joint motion track, partial surface reference or downstream authored animation aid. They are not a recovered complete physical body, biometric identity, medical model or garment-fit truth.", "callout"),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("File-format and application ROI", "Use custom state where it earns verification"))
    story.append(
        table(
            [
                ["Format / application", "Evidence-adjusted ROI", "Rule"],
                [".ugsp4c / UGYUVS1", "HIGH for partial seed-replay research; LOW current storage efficiency", "Partial-substrate camera evidence; 1.7085484454x FFV1 and 2.7289156226x x264 lossless on this run"],
                [".ugsp4c.partial", "HIGH for crash recovery", "Expose committed prefix only; label incomplete"],
                ["UGRAWS1 spool", "HIGH for capture safety", "Transient and large; delete only after verified final replay"],
                ["Grove JSON + KCCH392", "HIGH for editability", "Ordinary scene-node ownership; no bootstrap/global camera"],
                ["JSON/JSONL receipts", "HIGHEST for audit/interchange", "Hashes, units, time, status, limits; not sample authority"],
                ["PLY", "HIGH once sparse support exists", "Promoted points/surfels only; include units/status"],
                ["glTF 2.0.1 JSON / USDA", "MEDIUM for downstream presentation", "Derived visible geometry and animation; not evidence authority"],
                ["Alembic / OpenUSD", "DEFER", "Use only after real time-slice geometry exists"],
                ["OpenVDB", "DEFER", "Use only for bounded supported sparse voxels; UNKNOWN is not empty"],
                ["APK", "HIGH for the device proof", "Distribution shell; audit code/assets separately"],
                ["PDF", "HIGH for human review", "Never the only machine authority"],
            ],
            [49 * mm, 43 * mm, 67 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("Highest practical application order", "h2"),
            bullet("Exact POCO camera recorder plus pending editable PLAYER-node presentation and deterministic pull-back verification."),
            bullet("Editable time scrubber and evidence inspector for YUV, metadata, novelty and lineage."),
            bullet("Calibrated classical matchmove and partial scene/object reconstruction workstation."),
            bullet("Human visible-joint and open-surface reference tooling with bounded alternatives."),
            bullet("After-the-fact RTX search for the smallest exact file among explicitly tested seed/predictor/block programs."),
            p("ROI here means engineering leverage supported by repository evidence, not demonstrated revenue. General closed 3D reconstruction, biometric/medical use and universal-format ambitions have low current ROI because their authority and validation are missing."),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Physical acceptance ledger", "Bounded POCO evidence and remaining gates"))
    story.append(
        table(
            [
                ["Required receipt field", "Current state"],
                ["Installed APK bytes / SHA-256", "PASS - 1,582,206 B / D421BCD4...2C4841C; device hash matches host"],
                ["Camera ID and YUV_420_888 size/rate", "PASS - camera 0; 1280 x 720; 30/30 fps; min 33,333,333 ns"],
                ["Accepted AImages = results = spooled = dispatched = replayed", "PASS - 297 = 297 = 297 = 297 = 297"],
                ["Unique monotonic sensor timestamps and zero silent drops", "PASS - strict reader accepted; 9.857788-second PTS span; 30.027 fps"],
                ["Exact transient spool", "PASS - 410,672,720 bytes; removed only after native replay"],
                ["Mali dispatch", "PASS - Mali-G720 MC7; API 1.3.278; 297 dispatches; no CPU fallback"],
                ["Frame-0 GPU timing / residual SHA", "PASS - 2,446,846 gpu ns; 4,227,000 wall ns; b690a014...10475c6"],
                ["GPU residual equals independent CPU residual for every frame", "PASS - full parity; prepared residual consumed"],
                ["Final .ugsp4c bytes and SHA-256", "PASS - 177,487,908 B / 9df3c9c6...514669"],
                ["On-device native replay Y/U/V/PTS/metadata", "PASS - all 297 frames"],
                ["Pulled-file independent Python receipt", "PASS - finalized; no tail; every hash/record/frame accepted"],
                ["Separate host C++ rerun", "PENDING"],
                ["Visible GLES player presentation", "NOT IMPLEMENTED"],
                ["One-minute and ten-minute PSS/thermal/battery", "PENDING ENDURANCE RUNS"],
                ["Kill-during-capture committed-prefix recovery", "PENDING CRASH TEST"],
            ],
            [78 * mm, 81 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("This 297-frame run closes one bounded physical camera/transcode/replay test. The full scene matrix still requires separate static/color/checkerboard and textured-motion recordings, plus any optional person test. None relax privacy, geometry or UNKNOWN rules."),
            p("Acceptance requires the same authoritative bytes and timestamps on the phone, native host reader and independent Python reader. A visible image alone is not proof; neither is a successful Vulkan dispatch without replay parity."),
            p("If Vulkan is slower, unavailable or mismatched, preserve the exact spool and run the CPU path with an explicit receipt. If storage cannot sustain capture, stop explicitly. Never trade exactness for a silent drop.", "warning"),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Hard nonclaims and local evidence register", "No hallucinated completion"))
    story.append(
        table(
            [
                ["Claim", "Required wording"],
                ["Lossless", "Byte-identical declared dense Camera2 YUV420 + sensor time/metadata; not photons"],
                ["Seed", "Regenerates traversal/program state; arbitrary camera novelty stays explicit"],
                ["Substrate", "Physical file is PARTIAL: 2D traversal/lineage/residual only; full Klein/KLB37/tree/kinematic/SDF operator is open"],
                ["GPU", "Exact residual accelerator with CPU parity; not geometry or AI authority"],
                ["Phone", "One 297-frame end-to-end run is proven; visible playback/endurance/crash gates remain open"],
                ["3D", "Exact pixels do not imply depth; unsupported physical space remains UNKNOWN"],
                ["Time", "No primitive spans source times; continuity is lineage"],
                ["Static", "Low motion or mask complement is not certified static support/free space"],
                ["Human", "Visible bounded support/proxy only; no invented full body"],
                ["Optimality", "Smallest among tested exact programs; never absolute/global minimum"],
            ],
            [41 * mm, 118 * mm],
            compact=True,
        )
    )
    story.append(p("Primary local evidence", "h2"))
    sources = [
        "spec/UGTOMS_GSP4_SEED_CAMERA_0_1.md",
        "native/ugtc4d/YUV_SEED_CAPTURE_FORMAT.md",
        "native/ugtc4d/yuv_seed_capture.hpp and .cpp",
        "src/ugts_kc3/gsp4_camera_codeword.py and tests/test_gsp4_camera_codeword.py",
        "src/ugts_kc3/ugyuvs1.py and tests/test_ugyuvs1.py",
        "src/ugts_kc3/android_template/project/app/src/main/cpp/chrono_seed_capture_session.cpp",
        "src/ugts_kc3/android_template/project/app/src/main/cpp/chrono_vulkan_residual.cpp",
        "tmp/ugyuvs1_native_720p_cross_receipt.json and tmp/ugyuvs1_720p_stdout.txt",
        "tmp/gsp4_seed_camera_android_device_20260830/build-report.json",
        "tmp/poco_gsp4_physical_20260830/poco_capture.ugsp4c and poco_capture.verify.json",
        "../klb_cuda_arch_test_v0.1.0/klb_cuda_arch_test/README.md and packed-format sources",
        "../Unified_Geometric_Topological_Substrate_GPU_Native_Package/UGTS_GPU_Native_Addendum_Package/spec/UGTS_GN_1.1.md",
        "Parent TODO.md - user-authored directions and live acceptance status",
    ]
    story.extend(bullet(source) for source in sources)
    story.append(
        p(
            "Final position: retain the verified partial baseline, implement and cross-verify the missing full-substrate operator before claiming substrate completion, keep capture/spooling asynchronous, and let classical bounded evidence - never generated completion - decide what can become 3D or 4D.",
            "callout",
        )
    )
    return story


def build_pdf() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = OverlayDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title="UGTOMS GSP4 Camera Seed Storage Profile 0.3 - Partial-Substrate Camera Draft",
        author="OpenAI Codex with repository evidence",
        subject="Partial-substrate Camera2 exact spool, Mali Vulkan residual, UGYUVS1 replay, full-substrate gap, bounded non-generative 3D+time",
    )
    doc.build(build_story(), onFirstPage=page_decor, onLaterPages=page_decor)
    print(OUTPUT)


if __name__ == "__main__":
    build_pdf()
