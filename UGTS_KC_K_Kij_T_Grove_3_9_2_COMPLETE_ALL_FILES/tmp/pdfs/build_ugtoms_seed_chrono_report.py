from __future__ import annotations

from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
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

NAVY = HexColor("#13283F")
INK = HexColor("#1D2B3A")
SLATE = HexColor("#5C6B78")
PALE = HexColor("#EDF3F6")
TEAL = HexColor("#078C8C")
CYAN = HexColor("#DDF4F2")
ORANGE = HexColor("#E4802C")
GOLD = HexColor("#F5C85B")
GREEN = HexColor("#17835C")
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
        fontSize=27,
        leading=31,
        textColor=WHITE,
        alignment=TA_LEFT,
        spaceAfter=8,
    ),
    "subtitle": ParagraphStyle(
        "subtitle",
        parent=BASE["Normal"],
        fontName="Helvetica",
        fontSize=12.5,
        leading=17,
        textColor=HexColor("#D9E9F1"),
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
        fontSize=12.5,
        leading=16,
        textColor=TEAL,
        spaceBefore=8,
        spaceAfter=5,
        keepWithNext=True,
    ),
    "body": ParagraphStyle(
        "body",
        parent=BASE["BodyText"],
        fontName="Helvetica",
        fontSize=9.25,
        leading=13.2,
        textColor=INK,
        spaceAfter=6,
    ),
    "small": ParagraphStyle(
        "small",
        parent=BASE["BodyText"],
        fontName="Helvetica",
        fontSize=7.7,
        leading=10.4,
        textColor=SLATE,
        spaceAfter=3,
    ),
    "table_header": ParagraphStyle(
        "table_header",
        parent=BASE["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=7.8,
        leading=10.4,
        textColor=WHITE,
    ),
    "caption": ParagraphStyle(
        "caption",
        parent=BASE["BodyText"],
        fontName="Helvetica-Oblique",
        fontSize=7.4,
        leading=9.5,
        textColor=SLATE,
        spaceBefore=3,
        spaceAfter=6,
    ),
    "bullet": ParagraphStyle(
        "bullet",
        parent=BASE["BodyText"],
        fontName="Helvetica",
        fontSize=8.9,
        leading=12.5,
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
        fontSize=10,
        leading=14,
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
        fontSize=9.2,
        leading=13,
        textColor=HexColor("#6E2E14"),
        backColor=HexColor("#FFF1E5"),
        borderColor=ORANGE,
        borderWidth=0.7,
        borderPadding=7,
        spaceBefore=4,
        spaceAfter=7,
    ),
    "code": ParagraphStyle(
        "code",
        fontName="Courier",
        fontSize=7.6,
        leading=10.1,
        textColor=INK,
        backColor=PALE,
        borderColor=HexColor("#C6D5DD"),
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
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, HexColor("#B9C7CF")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return result


def status_table() -> Table:
    rows = [
        ["STATUS", "RESULT", "BOUNDARY"],
        ["VERIFIED", "Custom seed-driven exact RGB24+PTS replay", "229/229 source frames"],
        ["VERIFIED", "8-byte fixed-profile traversal seed", "Addressing only"],
        ["IMPLEMENTED", "UGCODE24 q709 reversible codeword", "227 selected frames"],
        ["ACTIVE", "Portable C++ and Grove/POCO runtime", "Not yet device-proven"],
        ["UNKNOWN", "Metric 3D, hidden surfaces, complete human", "No promotion from this clip"],
    ]
    return table(rows, [28 * mm, 83 * mm, 48 * mm], compact=True)


def pipeline_drawing() -> Drawing:
    width = CONTENT_W
    height = 104
    d = Drawing(width, height)
    boxes = [
        (0, 57, 80, 34, "OBSERVED", "RGB24 + PTS"),
        (97, 57, 82, 34, "ADDRESS", "seed + UGLUT2"),
        (196, 57, 82, 34, "UGCODE24", "reversible lanes"),
        (295, 57, 82, 34, "NOVELTY", "exact residual"),
        (394, 57, 82, 34, "PROGRAM", "UGFRM2/UGRICE1"),
    ]
    for x, y, w, h, title, body in boxes:
        d.add(Rect(x, y, w, h, 4, 4, fillColor=PALE, strokeColor=TEAL, strokeWidth=1))
        d.add(String(x + w / 2, y + 22, title, textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.5, fillColor=NAVY))
        d.add(String(x + w / 2, y + 9, body, textAnchor="middle", fontName="Helvetica", fontSize=6.7, fillColor=SLATE))
    for x in (80, 179, 278, 377):
        d.add(Line(x + 3, 74, x + 14, 74, strokeColor=ORANGE, strokeWidth=1.4))
    d.add(Line(435, 54, 435, 31, strokeColor=ORANGE, strokeWidth=1.2))
    d.add(Line(435, 31, 40, 31, strokeColor=ORANGE, strokeWidth=1.2))
    d.add(Line(40, 31, 40, 52, strokeColor=ORANGE, strokeWidth=1.2))
    d.add(String(235, 17, "inverse execution restores identical RGB24 + half-open PTS intervals", textAnchor="middle", fontName="Helvetica-Oblique", fontSize=7.2, fillColor=SLATE))
    return d


def size_drawing() -> Drawing:
    values = [
        ("Lossy MP4 source", 12_132_305, ORANGE),
        ("Exact seed-program", 122_540_032, TEAL),
        ("Decoded RGB24", 633_139_200, NAVY),
    ]
    max_value = max(item[1] for item in values)
    d = Drawing(CONTENT_W, 125)
    d.add(String(0, 112, "Byte scale (linear)", fontName="Helvetica-Bold", fontSize=8, fillColor=NAVY))
    for index, (label, value, color) in enumerate(values):
        y = 82 - index * 34
        w = max(6, 360 * value / max_value)
        d.add(String(0, y + 8, label, fontName="Helvetica", fontSize=7.5, fillColor=INK))
        d.add(Rect(92, y, w, 16, 2, 2, fillColor=color, strokeColor=None))
        d.add(String(98 + w, y + 4, f"{value:,} B", fontName="Helvetica-Bold", fontSize=7.3, fillColor=INK))
    return d


def seed_accounting_drawing() -> Drawing:
    d = Drawing(CONTENT_W, 105)
    items = [
        ("8 B", "root seed", TEAL),
        ("128 B", "self-verifying recipe", NAVY),
        ("144 B", "shared UGLUT2", GOLD),
        ("122.54 MB", "exact observation program", ORANGE),
    ]
    x = 0
    widths = [65, 112, 95, 190]
    for (value, label, color), w in zip(items, widths):
        d.add(Rect(x, 45, w, 36, 3, 3, fillColor=color, strokeColor=None))
        text_color = INK if color == GOLD else WHITE
        d.add(String(x + w / 2, 65, value, textAnchor="middle", fontName="Helvetica-Bold", fontSize=9, fillColor=text_color))
        d.add(String(x + w / 2, 52, label, textAnchor="middle", fontName="Helvetica", fontSize=6.4, fillColor=text_color))
        x += w + 5
    d.add(String(0, 24, "The seed regenerates structure. Camera novelty remains explicit evidence.", fontName="Helvetica-Bold", fontSize=8.2, fillColor=NAVY))
    d.add(String(0, 10, "If evidence is baked into the APK or fetched elsewhere, the 8-byte seed selects relocated data; it does not erase it.", fontName="Helvetica", fontSize=7.2, fillColor=SLATE))
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
    canvas.setStrokeColor(HexColor("#C7D3DA"))
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_X, PAGE_H - 11 * mm, PAGE_W - MARGIN_X, PAGE_H - 11 * mm)
    canvas.setFillColor(SLATE)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(MARGIN_X, PAGE_H - 8.5 * mm, "UGTOMS seed-first chrono evidence profile 0.3")
    canvas.drawRightString(PAGE_W - MARGIN_X, 8 * mm, f"{doc.page}")
    canvas.restoreState()


def page_decor(canvas, doc) -> None:
    if doc.page == 1:
        cover_page(canvas, doc)
    else:
        later_page(canvas, doc)


def page_title(title: str, kicker: str) -> list:
    return [p(kicker.upper(), "small"), p(title, "h1")]


def build_story() -> list:
    story = []
    story.extend(
        [
            Spacer(1, 50 * mm),
            p("UGTOMS Seed-First Chrono Evidence", "title"),
            p("Lossless observed-video program, literal UGLUT2 traversal, classical 3D+time gates, and Grove/POCO execution strategy", "subtitle"),
            Spacer(1, 12 * mm),
            p("PROFILE 0.3 - VERIFIED BASELINE + IMPLEMENTATION ROADMAP", "subtitle"),
            Spacer(1, 7 * mm),
            p("Supplied fixture: sam_2353410928515192.mp4", "subtitle"),
            p("Authoring date: 2026-08-30 | RTX 5070 Ti Laptop GPU 12 GB | POCO X7 Pro target", "subtitle"),
            Spacer(1, 27 * mm),
            p("Verdict", "subtitle"),
            p("The substrate now executes a custom exact observation program with no stored pixel map and no conventional video payload. The minimum traversal seed is eight bytes. Arbitrary camera novelty cannot be reconstructed from that seed unless the evidence exists elsewhere; exact novelty therefore remains part of the executable program. Physical 3D is still UNKNOWN until classical calibrated evidence passes promotion gates.", "subtitle"),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Executive verdict", "What is true now"))
    story.append(status_table())
    story.append(Spacer(1, 7))
    story.append(
        p(
            "<b>Implemented outcome:</b> a fixed custom player can regenerate the complete raster traversal from the seed and one shared literal UGLUT2, decode exact novelty, invert UGCODE24, and restore all accepted RGB24 frames and timing. This is a seed-first substrate program, regardless of whether the engineering files retain codec-oriented names.",
            "callout",
        )
    )
    story.extend(
        [
            bullet("New q709 output: 122,540,032 bytes; SHA-256 f1a87daa...564ccd5."),
            bullet("Fresh-process source comparison: PASS for 229/229 RGB24 hashes and every half-open PTS interval."),
            bullet("Address definition: one 8-byte root seed, a 128-byte self-verifying UGTRV1 recipe, and one 144-byte UGLUT2."),
            bullet("No serialized pixel permutation, H.264, AV1, ZIP, MediaCodec bitstream, DINO feature payload, or generated hidden content."),
            bullet("RTX authoring is exact but not real-time: 262.598 seconds for the 9.120-second fixture; peak CUDA allocation 682.031 MiB."),
        ]
    )
    story.append(size_drawing())
    story.append(
        p(
            "The 12.13 MB MP4 is lossy and is not an equal-quality compression baseline. The exact seed-program is 19.3544% of decoded RGB24 and 10.1003 times the source MP4.",
            "caption",
        )
    )
    story.append(PageBreak())

    story.extend(page_title("Seed-first meaning and the hard information boundary", "Eight bytes are real - and limited"))
    story.append(seed_accounting_drawing())
    story.extend(
        [
            p("The literal seed artifact <b>sam_2353410928515192.ugtoms-traversal-seed64</b> is exactly 8 bytes: hex <font name='Courier'>1867BAFA7C80C31F</font>, SHA-256 <font name='Courier'>a55cbc1b...396e978a</font>. The fixed profile supplies recipe seed 1, so only the 64-bit root is stored."),
            p("A fixed decoder maps each 64-bit seed to at most one output. It can therefore regenerate only data implied by its fixed program and that seed. UGLUT2 supplies quantized radius/direction; SplitMix64 supplies deterministic lineage; neither contains the observed colors."),
            p("A seed-only exact result is possible when the scene was originally produced by the same substrate grammar. For an external camera, any sample not implied by prior accepted state is exogenous novelty. Negative memory suppresses repeated facts; it does not turn unseen values into known values."),
            p("A custom APK can hide the evidence in its binary, fetch it from a server, or retain it in memory. In all three cases the eight-byte file is a selector and the evidence has merely moved. A plausible generated replacement would violate the requested non-hallucination rule.", "warning"),
            p("For a fixed deterministic decoder D and seed s:", "h2"),
            Preformatted(
                "structure = D_profile(seed, UGLUT2)\n"
                "observation = structure + exact_novelty\n"
                "seed_only exact  <=>  exact_novelty is empty",
                STYLES["code"],
            ),
            p("The supplied clip does not satisfy the final condition under the tested fixed grammar; its verified exact novelty dominates the file."),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Literal substrate execution", "No picture-sized LUT"))
    story.append(pipeline_drawing())
    story.append(
        Preformatted(
            "a_i = UGTRV1(UGLUT2, root_seed, recipe_seed, i)\n"
            "q_i = T(RGB[a_i])\n"
            "e_i = (q_i - MED(q_left, q_up, q_upper_left)) mod 256\n"
            "decode: entropy^-1 -> predictor^-1 -> T^-1 -> scatter[a_i]",
            STYLES["code"],
        )
    )
    story.extend(
        [
            p("<b>UGLUT2:</b> one 144-byte binary16 table of quantized sine, cosine and log-radius samples. It is a shared substrate dependency, not a raster lookup array."),
            p("<b>UGTRV1:</b> a new 128-byte chrono operator assembled from exact substrate primitives. It binds dimensions, two seeds, operator meaning, UGLUT2 SHA-256 and traversal SHA-256. It serializes no address list."),
            p("<b>Traversal:</b> doubled integer pixel centers; binary16 radius to Q16; direction to Q30; exact radial midpoint and cross-wedge classification; rho20/theta18 order; SplitMix64 lineage; Cartesian address as final tie-break."),
            p("<b>UGCODE24:</b> one reversible three-lane codeword per observed RGB8 sample. The regenerated address carries rho/theta/lineage, so those fields do not consume the same 24 color bits."),
            p("<b>UGRICE1:</b> canonical per-block selection among raw, signed modulo-256 Rice, and custom static 12-bit byte-rANS. All 9,847 blocks in the first full file selected byte-rANS."),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("UGCODE24 validation and exact file result", "The user's three-lane correction"))
    story.append(
        Preformatted(
            "Cr = s8((R-G) mod 256)\n"
            "Cb = s8((B-G) mod 256)\n"
            "A  = floor((5*Cr + 2*Cb)/16)\n"
            "Y  = (G+A) mod 256\n"
            "store [Y,Cb,Cr]\n\n"
            "G = (Y-A) mod 256; R = (G+Cr) mod 256; B = (G+Cb) mod 256",
            STYLES["code"],
        )
    )
    story.append(
        table(
            [
                ["Validation", "Result"],
                ["Full-clip configuration matrix", "29 configurations x 229 frames = 6,641 exact round trips; zero failures"],
                ["All RGB24 inputs", "16,777,216 codewords exhaustively inverted; PASS"],
                ["Best all-intra stream", "q709 [Y,Cb,Cr], 122,773,583 bytes"],
                ["Authored mode selection", "227 q709, 1 prior lift, 1 temporal"],
                ["Authored file", "122,540,032 bytes; 120,576 bytes below first exact file"],
                ["Independent replay", "Original MP4 re-decoded; all RGB24 hashes and PTS intervals exact"],
            ],
            [62 * mm, 97 * mm],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        table(
            [
                ["Exact layout under identical entropy", "UGRICE1 stream bytes", "Finding"],
                ["q709 [Y,Cb,Cr]", "122,773,583", "Smallest measured all-intra"],
                ["Prior q4 [Y,Cb,Cr]", "122,881,215", "Close second"],
                ["Green differences", "123,748,734", "Larger"],
                ["YCoCg-R", "125,562,440", "Larger"],
                ["Lane bitplanes", "316,524,893", "Exact, but QR-like packing loses"],
                ["24-bit grouped bitplanes", "344,847,805", "Exact, but substantially larger"],
                ["Seed/address XOR", "633,216,144", "Destroys useful correlation"],
            ],
            [69 * mm, 39 * mm, 51 * mm],
            compact=True,
        )
    )
    story.append(p("This validates the reversible codeword model and falsifies the assumption that QR-like bit rearrangement itself compresses this clip. The result is the smallest authored exact profile tested, not an absolute optimum.", "warning"))
    story.append(PageBreak())

    story.extend(page_title("RTX and POCO recorder/player path", "Real-time capture plus offline minimization"))
    story.append(
        table(
            [
                ["Target", "Verified capability", "Next implementation"],
                ["RTX 5070 Ti 12 GB", "Exact CUDA gather/predict; 682 MiB peak", "GPU-native traversal, parallel block entropy, seed/grammar search"],
                ["POCO X7 Pro", "API 36, 11.58 GB RAM, Mali-G720 MC7, 332 GB free", "ARM64/NEON recorder/player in editable Grove scene"],
                ["Camera2 back camera", "FULL level, 1280x720 YUV at about 30 fps, REALTIME timestamps", "Dense YUV authority, metadata/IMU binding, no implicit RGB"],
                ["Grove engine", "NativeActivity, GLES3, scene nodes, PTS staging reusable", "Node-bound KCCH392 binding; no bootstrap/fullscreen special case"],
            ],
            [38 * mm, 60 * mm, 61 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("<b>Capture authority:</b> copy and normalize Camera2 <font name='Courier'>YUV_420_888</font> planes immediately, hash them before prediction, and retain sensor PTS plus calibration/crop/exposure metadata. SurfaceTexture and device YUV-to-RGB conversion are presentation only."),
            p("<b>Live path:</b> the phone emits seed/recipe state and exact novelty into journaled chunks. A bounded queue may spill raw authoritative planes or stop explicitly under pressure; it must never silently drop a frame."),
            p("<b>After-the-fact path:</b> the RTX searches additional exact substrate recipes/transforms and rewrites the canonical smallest result found within the declared search budget. General absolute minimality is not computable; the report must say 'smallest measured among tested programs.'"),
            p("<b>Player:</b> native entropy decode, inverse codeword/predictor, seed-regenerated traversal, two-slot publication on half-open PTS boundaries, and texture upload to an ordinary editable scene node."),
            p("Current fixture rate is about 13.44 MB/s, or about 48.4 GB/hour. The old APK-shell replacement projects to at least 129,464,915 bytes before native decoder, signing and alignment deltas. Neither real-time encode nor that APK size is yet device-verified.", "warning"),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Classical monocular 3D plus time", "Geometry must earn promotion"))
    story.append(
        table(
            [
                ["Outcome", "Feasibility", "Evidence requirement / current status"],
                ["Exact 2D + time", "HIGH - VERIFIED", "Complete RGB24+PTS replay"],
                ["Sparse projective support", "CONDITIONAL", "Tracks, non-degenerate motion, robust H/F gates"],
                ["Relative Euclidean support", "CONDITIONAL", "Intrinsics, essential pose, parallax, cheirality; unknown scale"],
                ["Metric geometry", "NOT AVAILABLE", "Measured calibration and scale anchor absent from fixture"],
                ["Dense visible surface", "CONDITIONAL", "Repeated independent support plus bounded uncertainty"],
                ["Hidden backs / closed topology", "NOT IDENTIFIABLE", "Remain UNKNOWN or explicit authored proxy"],
                ["Complete human 4D", "HIGH AMBIGUITY", "Articulation, cloth, occlusion, identity and gauge branches"],
            ],
            [47 * mm, 37 * mm, 75 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("Implemented classical operators include GFTT, forward/backward KLT, seeded homography/fundamental estimation, symmetric-transfer and Sampson residuals, rank-two fundamental projection, essential-manifold projection, four pose branches, triangulation, cheirality, parallax, reprojection and conditioning gates."),
            p("Those operators currently produce guarded hypotheses only. The authored supplied-video file correctly stores empty geometry with <font name='Courier'>UNBOUNDED_UNKNOWN</font>; no mesh, voxel or human surface has been promoted."),
            p("All output primitives are same-time. Temporal continuity is entity/chart lineage, never a face, edge, voxel cell, splat or sheet connecting different source times.", "callout"),
            p("Static pixels are observations too. 'Not detected as moving' is not proof of static support or free space. Every footprint remains a static candidate, independent-motion branch, occluder, unresolved sample or UNKNOWN until positive geometry supports a class."),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Human specialization and negative memory", "Body4D without invented anatomy"))
    story.append(
        table(
            [
                ["May enter a human branch", "Must remain UNKNOWN / PROXY_ONLY"],
                ["Visible 2D joints and parts", "Hidden anatomy and unobserved backs"],
                ["Bounded/cyclic joint alternatives", "Learned identity or body shape as truth"],
                ["Same-time articulated transforms", "Force, biomechanics, medical or biometric claims"],
                ["Visibility and association alternatives", "Closed topology inferred from silhouette"],
                ["Explicitly authored proxy binding", "Cloth/hair/skin continuity without evidence"],
            ],
            [79.5 * mm, 79.5 * mm],
        )
    )
    story.extend(
        [
            p("Body4D, MoGe2, DA3, DINOv3, SAM3 and similar systems may propose masks, features, depth or pose only when their code, weights and configuration are bound. They cannot replace exact residuals or promote geometry."),
            p("DINOv3 is not required by the current seed program. A learned feature is not a bijection back to RGB and correlated model agreement is not independent physical measurement."),
            p("Negative memory stores accepted novelty: birth, tightening, split, chart discontinuity, owner handoff, retraction and checkpoint seal. Omission means no newly accepted fact. It never means disappearance, deletion, occlusion, empty space or mask complement."),
            p("Practical human outputs remain conditional: editable motion proxy, matchmove reference, partial visible support and downstream animation. They are not a recovered complete physical person."),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("File formats and application ROI", "Use custom state where it earns its cost"))
    story.append(
        table(
            [
                ["Boundary", "ROI decision"],
                ["8-byte UGSEED64", "Highest density for traversal selection; only by-reference, never standalone camera evidence"],
                ["UGTC4D / seed program", "Strong exact replay/provenance research; conventional compression advantage unproven"],
                ["JSON/JSONL + JSON Schema", "Highest immediate ROI for editable observations, hypotheses, novelty and receipts"],
                ["Grove JSON / KC packs", "High for editable scene ownership and hot native execution"],
                ["PLY", "First simple derivative for promoted sparse geometry; never canonical evidence"],
                ["glTF 2.0.1 JSON / USDA", "Presentation interchange only after geometry promotion; chrono GLB path not implemented"],
                ["Alembic / OpenUSD / OpenVDB", "Defer until validated time-slice meshes or sparse voxels exist"],
                ["MP4", "Source provenance and conventional playback baseline only; never custom frame payload"],
                ["APK / AAR", "Distribution only after native decoder and physical device evidence"],
                ["PDF", "Human review artifact, never machine authority"],
            ],
            [52 * mm, 107 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("Highest chrono application ROI, in order:", "h2"),
            bullet("Deterministic author/verify and seed-program minimization CLI."),
            bullet("Editable Grove evidence inspector with exact time scrubbing."),
            bullet("Calibrated classical reconstruction workstation."),
            bullet("Native POCO recorder/player with pull-back verification."),
            bullet("Human-specific bounded articulated tooling after calibrated validation."),
            p("The broader repo still supports other high-ROI lanes, including the deterministic local pass planner and offline HTML delivery. These are evidence-adjusted engineering judgments, not revenue forecasts."),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Execution roadmap and acceptance gates", "What makes the end state real"))
    story.append(
        table(
            [
                ["Priority", "Deliverable", "Acceptance evidence"],
                ["P0", "Portable C++ reader", "Python/C++ traversal, entropy, RGB and PTS parity; malformed files fail closed"],
                ["P0", "Native seed-program encoder", "Scalar/NEON parity, journaled streaming, exact crash recovery"],
                ["P0", "Editable KCCH392 scene binding", "Undoable node metadata; no bootstrap or hidden fullscreen object"],
                ["P0", "POCO recorder/player APK", "No MP4/MediaCodec; installed artifact audit; 229-frame fixture replay"],
                ["P0", "Phone capture", "Zero silent drops; plane hashes/PTS/metadata reproduce on phone, C++ and Python"],
                ["P0", "Performance", "30 fps or explicit lossless spool mode; queues, PSS, thermals, energy measured"],
                ["P1", "Geometry record wiring", "Real HYPOTHES/GEOMETRY sections; unsupported fields remain UNKNOWN"],
                ["P1", "Calibrated capture", "Intrinsics, distortion, shutter, scale and independent support gates"],
                ["P2", "Human branch", "Bounded visible joints/parts; no hidden-body promotion"],
            ],
            [18 * mm, 53 * mm, 88 * mm],
            compact=True,
        )
    )
    story.extend(
        [
            p("Phone capture acceptance set: at least 10 seconds static/color/checkerboard and 10 seconds textured motion; monotonic unique sensor timestamps; capture count equals encoded ordinal count; exact pulled-file replay; no silent drops; and a kill-during-capture recovery test."),
            p("Compression kill gate: if seeded UGLUT2 ordering does not beat the same exact predictor/entropy under Cartesian, Morton, Hilbert or unseeded polar ordering, retain the format for execution/provenance but drop compression-superiority claims."),
            p("Geometry kill gate: if calibration, parallax, condition and independent-support gates do not contract uncertainty, materialize only observations/proxies and keep physical geometry UNKNOWN."),
        ]
    )
    story.append(PageBreak())

    story.extend(page_title("Hard nonclaims and local evidence register", "No hallucinated completion"))
    story.append(
        table(
            [
                ["Claim boundary", "Required wording"],
                ["Lossless", "Exact relative to declared PyAV RGB24+PTS decode, not original MP4 bits or photons"],
                ["Seed", "Regenerates traversal/program state; arbitrary camera novelty is retained elsewhere"],
                ["3D", "Exact pixels do not imply depth; projective support does not imply metric XYZ"],
                ["Unknown", "UNKNOWN is not free space, deletion, occlusion or a hidden surface"],
                ["Time", "No primitive crosses source time; continuity is lineage"],
                ["Learned systems", "Proposal/context only; agreement is not independent measurement"],
                ["Phone", "Capability is measured; custom runtime remains unverified until the APK runs"],
                ["Optimality", "Smallest authored among tested profiles, never absolute/global optimum"],
            ],
            [43 * mm, 116 * mm],
            compact=True,
        )
    )
    story.append(p("Primary local evidence", "h2"))
    sources = [
        "spec/UGTOMS_CHRONO_GEOMETRY_CODEC_0_1.md",
        "src/ugts_kc3/chrono_substrate.py; chrono_seed.py; chrono_prediction.py",
        "src/ugts_kc3/chrono_entropy.py; chrono_codec.py; chrono_container.py",
        "src/ugts_kc3/chrono_compile.py; chrono_geometry.py; cli.py",
        "tests/test_chrono_seed.py; test_chrono_substrate.py; test_chrono_prediction.py",
        "tests/test_chrono_entropy.py; test_chrono_codec.py; test_chrono_container.py",
        "Parent sam_2353410928515192.ugtoms-seed-program-lossless-q709.ugtc4d",
        "Parent sam_2353410928515192.ugtoms-seed-program-lossless-q709.receipt.json",
        "Parent sam_2353410928515192.ugtoms-traversal-seed64",
        "Parent TODO.md and SUBSTRATE_ROI_STRATEGY.pdf",
    ]
    story.extend(bullet(source) for source in sources)
    story.append(
        p(
            "Final engineering position: execute every deterministic relation through the substrate, search hard for a compact exact seed program, retain only irreducible novelty, and never confuse omitted evidence with reconstructed physical truth.",
            "callout",
        )
    )
    return story


def build_pdf() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title="UGTOMS Seed-First Chrono Evidence Profile 0.3",
        author="OpenAI Codex with repository evidence",
        subject="Custom lossless seed program, UGLUT2 traversal, chrono geometry and POCO roadmap",
    )
    doc.build(build_story(), onFirstPage=page_decor, onLaterPages=page_decor)
    print(OUTPUT)


if __name__ == "__main__":
    build_pdf()
