"""Generate the ELI5 defensive red-team report from captured audit evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
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


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT_DIR = ROOT / "output" / "pdf"
OUTPUT = OUTPUT_DIR / "SARA_3_6_3_Defensive_Red_Team_Audit_2026-08-18.pdf"

NAVY = HexColor("#122033")
INK = HexColor("#1D2939")
MUTED = HexColor("#5E6B7A")
LINE_GREY = HexColor("#D8DEE8")
PAPER = HexColor("#F7F9FC")
BLUE = HexColor("#2563EB")
BLUE_LIGHT = HexColor("#E8F0FF")
GREEN = HexColor("#157347")
GREEN_LIGHT = HexColor("#E7F6ED")
AMBER = HexColor("#A15C00")
AMBER_LIGHT = HexColor("#FFF3D8")
RED = HexColor("#B42318")
RED_LIGHT = HexColor("#FDECEC")
PURPLE = HexColor("#6941C6")
PURPLE_LIGHT = HexColor("#F0EAFF")
WHITE = colors.white


def load_json(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


probe = load_json("security_probe_results.json")
timing = load_json("side_channel_timing.json")
manifest_zip = load_json("manifest_zip.json")
manifest_fs = load_json("manifest_filesystem.json")
bandit = load_json("bandit.json")
pip_audit = load_json("pip_audit_isolated.json")
doc_integrity = load_json("documentation_integrity.json")
secret_scan = load_json("packaged_secret_scan.json")


def register_fonts() -> tuple[str, str, str]:
    candidates = [
        Path(r"C:\Windows\Fonts\aptos.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ]
    bold_candidates = [
        Path(r"C:\Windows\Fonts\aptos-bold.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
    ]
    mono_candidates = [
        Path(r"C:\Windows\Fonts\consola.ttf"),
        Path(r"C:\Windows\Fonts\cour.ttf"),
    ]
    regular = next((p for p in candidates if p.exists()), None)
    bold = next((p for p in bold_candidates if p.exists()), None)
    mono = next((p for p in mono_candidates if p.exists()), None)
    if regular and bold and mono:
        pdfmetrics.registerFont(TTFont("AuditSans", str(regular)))
        pdfmetrics.registerFont(TTFont("AuditSansBold", str(bold)))
        pdfmetrics.registerFont(TTFont("AuditMono", str(mono)))
        return "AuditSans", "AuditSansBold", "AuditMono"
    return "Helvetica", "Helvetica-Bold", "Courier"


FONT, FONT_BOLD, FONT_MONO = register_fonts()
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    name="AuditBody", fontName=FONT, fontSize=9.4, leading=13.2,
    textColor=INK, spaceAfter=6,
))
styles.add(ParagraphStyle(
    name="AuditSmall", fontName=FONT, fontSize=7.8, leading=10.5,
    textColor=MUTED, spaceAfter=4,
))
styles.add(ParagraphStyle(
    name="AuditTiny", fontName=FONT, fontSize=6.5, leading=8.3,
    textColor=MUTED,
))
styles.add(ParagraphStyle(
    name="AuditTitle", fontName=FONT_BOLD, fontSize=27, leading=31,
    textColor=WHITE, alignment=TA_LEFT,
))
styles.add(ParagraphStyle(
    name="AuditSubtitle", fontName=FONT, fontSize=12, leading=17,
    textColor=HexColor("#D8E5FF"),
))
styles.add(ParagraphStyle(
    name="AuditH1", fontName=FONT_BOLD, fontSize=18, leading=22,
    textColor=NAVY, spaceAfter=10,
))
styles.add(ParagraphStyle(
    name="AuditH2", fontName=FONT_BOLD, fontSize=11.5, leading=14,
    textColor=NAVY, spaceBefore=6, spaceAfter=5,
))
styles.add(ParagraphStyle(
    name="AuditCallout", fontName=FONT_BOLD, fontSize=10.5, leading=14,
    textColor=NAVY,
))
styles.add(ParagraphStyle(
    name="AuditTable", fontName=FONT, fontSize=7.4, leading=9.2,
    textColor=INK,
))
styles.add(ParagraphStyle(
    name="AuditTableHead", fontName=FONT_BOLD, fontSize=7.4, leading=9.2,
    textColor=WHITE, alignment=TA_LEFT,
))
styles.add(ParagraphStyle(
    name="AuditMono", fontName=FONT_MONO, fontSize=7.2, leading=9.2,
    textColor=INK,
))


def P(text: str, style: str = "AuditBody") -> Paragraph:
    return Paragraph(text, styles[style])


def bullet(text: str) -> Paragraph:
    return P("- " + text)


def callout(title: str, body: str, color: colors.Color = BLUE, fill: colors.Color = BLUE_LIGHT) -> Table:
    table = Table(
        [[P(title, "AuditCallout")], [P(body, "AuditBody")]],
        colWidths=[174 * mm],
        hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("BOX", (0, 0), (-1, -1), 0.8, color),
        ("LINEBEFORE", (0, 0), (0, -1), 4, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    return table


def status_table(rows: list[tuple[str, str, str]]) -> Table:
    data = [[P("Question", "AuditTableHead"), P("Verdict", "AuditTableHead"), P("Plain-English meaning", "AuditTableHead")]]
    for question, verdict, meaning in rows:
        data.append([P(question, "AuditTable"), P(verdict, "AuditTable"), P(meaning, "AuditTable")])
    table = Table(data, colWidths=[49 * mm, 30 * mm, 95 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE_GREY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PAPER]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def metric_cards(cards: list[tuple[str, str, str, colors.Color, colors.Color]], width: float = 174 * mm) -> Table:
    col_width = width / len(cards)
    title_row = [P(title, "AuditSmall") for title, _, _, _, _ in cards]
    value_row = [Paragraph(value, ParagraphStyle(
        name=f"metric-{i}", parent=styles["AuditH1"], fontSize=19, leading=21,
        textColor=color, alignment=TA_CENTER, spaceAfter=0,
    )) for i, (_, value, _, color, _) in enumerate(cards)]
    note_row = [Paragraph(note, ParagraphStyle(
        name=f"note-{i}", parent=styles["AuditTiny"], alignment=TA_CENTER,
    )) for i, (_, _, note, _, _) in enumerate(cards)]
    fills = [fill for _, _, _, _, fill in cards]
    table = Table([title_row, value_row, note_row], colWidths=[col_width] * len(cards))
    commands = [
        ("BOX", (0, 0), (-1, -1), 0.4, LINE_GREY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]
    for index, fill in enumerate(fills):
        commands.append(("BACKGROUND", (index, 0), (index, -1), fill))
    table.setStyle(TableStyle(commands))
    return table


def severity_badge(label: str) -> Paragraph:
    return Paragraph(f"<b>{label}</b>", ParagraphStyle(
        name=f"badge-{label}", parent=styles["AuditTable"], textColor=WHITE,
        backColor={"HIGH": RED, "MEDIUM": AMBER, "LOW": BLUE, "POSITIVE": GREEN}.get(label, MUTED),
        borderPadding=3, alignment=TA_CENTER,
    ))


def findings_table(rows: list[tuple[str, str, str, str]]) -> Table:
    data = [[P("ID", "AuditTableHead"), P("Risk", "AuditTableHead"), P("Finding", "AuditTableHead"), P("Why it matters", "AuditTableHead")]]
    for ident, severity, finding, impact in rows:
        data.append([P(ident, "AuditTable"), severity_badge(severity), P(finding, "AuditTable"), P(impact, "AuditTable")])
    table = Table(data, colWidths=[13 * mm, 23 * mm, 61 * mm, 77 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE_GREY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PAPER]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def side_channel_chart() -> Drawing:
    cases = timing["cases"]
    labels = [
        ("Scalar 1", cases["scalar_1_bitlength_1"]["median_ms_per_call"]),
        ("One high bit", cases["scalar_single_high_bit_bitlength_256"]["median_ms_per_call"]),
        ("Dense scalar", cases["scalar_n_minus_1_dense_bitlength_256"]["median_ms_per_call"]),
    ]
    max_value = max(value for _, value in labels)
    d = Drawing(500, 150)
    d.add(String(0, 136, "Chosen-scalar public-key timing (median milliseconds per call)", fontName=FONT_BOLD, fontSize=10, fillColor=NAVY))
    for index, (label, value) in enumerate(labels):
        y = 98 - index * 38
        d.add(String(0, y + 7, label, fontName=FONT, fontSize=8, fillColor=INK))
        d.add(Rect(92, y, 360, 18, fillColor=PAPER, strokeColor=LINE_GREY, strokeWidth=0.5))
        width = max(1.5, 360 * value / max_value)
        d.add(Rect(92, y, width, 18, fillColor=PURPLE, strokeColor=None))
        d.add(String(458, y + 5, f"{value:.3f} ms", fontName=FONT_MONO, fontSize=7.5, fillColor=INK))
    d.add(String(0, 0, "A production-grade secret-key implementation should not expose this input-dependent pattern.", fontName=FONT, fontSize=7.5, fillColor=MUTED))
    return d


def attack_flow() -> Drawing:
    d = Drawing(500, 190)
    box_w = 135
    box_h = 48
    xs = [0, 182, 365]
    d.add(String(0, 176, "Two very different paths", fontName=FONT_BOLD, fontSize=10, fillColor=NAVY))
    boxes = [
        (0, 105, BLUE_LIGHT, BLUE, "Public address", "Safe to share"),
        (182, 105, GREEN_LIGHT, GREEN, "Decode public facts", "No private key"),
        (365, 105, GREEN_LIGHT, GREEN, "Cannot spend", "No inverse shortcut"),
        (0, 25, RED_LIGHT, RED, "Stolen mnemonic", "Secret already lost"),
        (182, 25, AMBER_LIGHT, AMBER, "Guess weak passphrase", "Dictionary attack"),
        (365, 25, RED_LIGHT, RED, "Matching wallet", "Funds at risk"),
    ]
    for x, y, fill, stroke, title, note in boxes:
        d.add(Rect(x, y, box_w, box_h, rx=5, ry=5, fillColor=fill, strokeColor=stroke, strokeWidth=1))
        d.add(String(x + 8, y + 29, title, fontName=FONT_BOLD, fontSize=8.5, fillColor=NAVY))
        d.add(String(x + 8, y + 13, note, fontName=FONT, fontSize=7.3, fillColor=MUTED))
    for y in (129, 49):
        d.add(Line(138, y, 177, y, strokeColor=MUTED, strokeWidth=1))
        d.add(Line(172, y + 3, 177, y, strokeColor=MUTED, strokeWidth=1))
        d.add(Line(172, y - 3, 177, y, strokeColor=MUTED, strokeWidth=1))
        d.add(Line(320, y, 360, y, strokeColor=MUTED, strokeWidth=1))
        d.add(Line(355, y + 3, 360, y, strokeColor=MUTED, strokeWidth=1))
        d.add(Line(355, y - 3, 360, y, strokeColor=MUTED, strokeWidth=1))
    return d


def source_table(rows: list[tuple[str, str]]) -> Table:
    data = [[P("Reference", "AuditTableHead"), P("URL", "AuditTableHead")]]
    for label, url in rows:
        data.append([P(label, "AuditTable"), P(url, "AuditTiny")])
    table = Table(data, colWidths=[52 * mm, 122 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE_GREY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PAPER]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def page_header_footer(canvas, doc) -> None:
    canvas.saveState()
    page = doc.page
    width, height = A4
    if page == 1:
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, width, height, fill=1, stroke=0)
        canvas.setFillColor(BLUE)
        canvas.rect(0, 0, 12 * mm, height, fill=1, stroke=0)
    else:
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - 14 * mm, width, 14 * mm, fill=1, stroke=0)
        canvas.setFont(FONT_BOLD, 8)
        canvas.setFillColor(WHITE)
        canvas.drawString(18 * mm, height - 9 * mm, "SARA 3.6.3 DEFENSIVE RED-TEAM AUDIT")
        canvas.setStrokeColor(LINE_GREY)
        canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont(FONT, 7)
        canvas.drawString(18 * mm, 9 * mm, "Authorized local review - public test vectors only")
        canvas.drawRightString(width - 18 * mm, 9 * mm, f"Page {page}")
    canvas.restoreState()


class AuditDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str):
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=22 * mm,
            bottomMargin=19 * mm,
            title="SARA 3.6.3 Defensive Red-Team Audit",
            author="OpenAI Codex for Tom Klootwijk",
            subject="Local defensive feasibility, security, standards and packaging review",
        )
        width, height = A4
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            width - self.leftMargin - self.rightMargin,
            height - self.topMargin - self.bottomMargin,
            id="body",
        )
        self.addPageTemplates(PageTemplate(id="audit", frames=[frame], onPage=page_header_footer))


def cover() -> list:
    return [
        Spacer(1, 35 * mm),
        P("UGTS-KC 3.6.3 SARA", "AuditSubtitle"),
        Spacer(1, 5 * mm),
        P("Defensive Red-Team<br/>Security Audit", "AuditTitle"),
        Spacer(1, 8 * mm),
        P("Does it work, can it be misused, and can it actually hack a wallet?", "AuditSubtitle"),
        Spacer(1, 28 * mm),
        Table(
            [[P("BOTTOM LINE", "AuditTableHead")], [Paragraph(
                "The standards-conformance demo works. The public certificate is secret-free. "
                "But the claimed authorization boundary is a policy sign, not a locked door, "
                "and the pure-Python secret-key path is not safe for production wallet use.",
                ParagraphStyle(name="cover-verdict", parent=styles["AuditCallout"], fontSize=13, leading=18, textColor=WHITE),
            )]],
            colWidths=[155 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), HexColor("#1E3554")),
                ("BOX", (0, 0), (-1, -1), 0.8, HexColor("#6EA8FE")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]),
        ),
        Spacer(1, 31 * mm),
        P("Prepared for Tom Klootwijk", "AuditSubtitle"),
        P("Audit date: 18 August 2026 | Europe/Amsterdam", "AuditSubtitle"),
        P("Scope: local package only; no third-party wallet targeting, key search, transaction signing, broadcasting, or funds access", "AuditSubtitle"),
        PageBreak(),
    ]


def build_story() -> list:
    perf = probe["performance"]
    auth = probe["authorization_gate"]
    input_data = probe["input_resilience"]
    secret = probe["secret_boundary"]
    runtime = probe["runtime_capabilities"]
    validator = probe["validator_strength"]
    bandit_results = bandit.get("results", [])
    pip_vulns = sum(len(item.get("vulns", [])) for item in pip_audit.get("dependencies", []))

    story: list = []
    story.extend(cover())

    story += [
        P("1. Executive answer", "AuditH1"),
        callout(
            "ELI5 verdict: the calculator works; the security fence does not.",
            "The package correctly performs BIP39, BIP32, BIP84, Bech32 and Bech32m public test-vector work. "
            "It cannot turn a public address back into a wallet key. However, any Python caller can skip the separate "
            "authorization function and call the secret-derivation functions directly. That makes the gate advisory, not enforced.",
            RED,
            RED_LIGHT,
        ),
        Spacer(1, 6 * mm),
        status_table([
            ("Does the reference demo actually work?", "PASS", "Yes. The final isolated run passed 195/195 tests in 2.097 seconds; 42 are SARA-focused."),
            ("Does it match public Bitcoin standards vectors?", "PASS", "Yes for the covered vectors: BIP39 seed, three BIP84 addresses, Bech32 v0, and Bech32m v1."),
            ("Can a public Bitcoin address reveal its private key?", "NO", "No practical inverse route was found or implemented. Address decoding returns public script facts only."),
            ("Can it brute-force a random 12-word mnemonic?", "NO", "Not realistically. At this laptop's measured full-derivation rate, expected work is about 1.49e30 years."),
            ("Can a stolen mnemonic plus weak passphrase be attacked?", "YES", "Yes in principle. A one-million-item dictionary is about 38.3 hours expected on this unoptimized Python implementation."),
            ("Is it production wallet code?", "FAIL", "No. Secret objects are loggable, memory is not wiped, and elliptic-curve math is variable-time."),
            ("Is the authorization gate a real access-control boundary?", "FAIL", "No. Direct exported APIs do not require or receive an authorization certificate."),
            ("Is the current extracted copy integrity-clean?", "FAIL", "No. 150/152 manifest entries match; README.md and SECURITY.md differ from the pristine ZIP."),
        ]),
        Spacer(1, 6 * mm),
        P("Overall classification", "AuditH2"),
        metric_cards([
            ("Standards demo", "PASS", "Useful defensive reference", GREEN, GREEN_LIGHT),
            ("Policy enforcement", "FAIL", "Gate is bypassable", RED, RED_LIGHT),
            ("Production wallet", "NO", "Use audited constant-time tooling", RED, RED_LIGHT),
            ("Wallet hacking", "NO", "No search, signing, or network", BLUE, BLUE_LIGHT),
        ]),
        PageBreak(),
    ]

    story += [
        P("2. Scope and method", "AuditH1"),
        P("This was a local, non-destructive red-team review. The word 'red-team' here means trying to break the package's claims and controls using only the supplied code, public test vectors, synthetic inputs, and this laptop. It did not mean attacking a real wallet."),
        P("In scope", "AuditH2"),
        bullet("Clean Python setup and reproducibility."),
        bullet("Pristine ZIP and extracted-file integrity."),
        bullet("Official public standards test vectors and package tests."),
        bullet("Source, dependency, package, secret, parser, runtime, and permission review."),
        bullet("Non-destructive bypass, timing, malformed-input, and local denial-of-service probes."),
        P("Explicitly out of scope", "AuditH2"),
        bullet("No mnemonic enumeration, passphrase spray against a real wallet, private-key search, balance targeting, transaction signing, broadcast, or funds movement."),
        bullet("No live mainnet queries and no attempt to prove ownership of the supplied public address."),
        bullet("No formal cryptographic proof, exhaustive fuzzing, malware analysis, physical memory acquisition, or laboratory side-channel attack."),
        Spacer(1, 5 * mm),
        attack_flow(),
        Spacer(1, 2 * mm),
        callout(
            "What an address is",
            "Think of a Bitcoin address as a letter-box slot. It tells people where a payment can go. It is not the key that opens the box. "
            "The package can inspect that slot; it does not discover the private key behind it.",
            BLUE,
            BLUE_LIGHT,
        ),
        PageBreak(),
    ]

    story += [
        P("3. Setup and reproducibility", "AuditH1"),
        metric_cards([
            ("Final tests", "195/195", "2.097 seconds", GREEN, GREEN_LIGHT),
            ("SARA-focused", "42", "standards and boundary tests", BLUE, BLUE_LIGHT),
            ("Branch coverage", "86%", "SARA module: 86%", BLUE, BLUE_LIGHT),
            ("Demo runtime", "0.361 s", "valid public certificate", GREEN, GREEN_LIGHT),
        ]),
        Spacer(1, 7 * mm),
        P("Test machine", "AuditH2"),
        status_table([
            ("Operating system", "Windows 11 Home", "Version 10.0.26200, build 26200."),
            ("Processor", "Intel Core Ultra 7 255HX", "20 logical processors."),
            ("Memory", "15.42 GiB", "Reported visible system memory."),
            ("Python", "3.12.13", "Isolated .venv-security environment."),
            ("pip", "26.2.1", "Updated before final dependency audit."),
        ]),
        Spacer(1, 6 * mm),
        P("What failed before the green result", "AuditH2"),
        bullet("An editable install with --no-build-isolation initially failed because the clean venv had no local setuptools backend."),
        bullet("The first test discovery then produced four import errors because jsonschema was required by tests but not declared in project metadata."),
        bullet("The validator also requires PyMuPDF through the deprecated fitz import, but that validator dependency is undeclared."),
        bullet("After installing and pinning the missing audit/test tools locally, disabling inherited system packages, and rerunning, all 195 tests passed."),
        callout(
            "Why this matters",
            "A source-tree test can be correct and still be awkward to reproduce. The final pass is real, but another user needs the missing test/validator dependency instructions or metadata to reproduce it cleanly.",
            AMBER,
            AMBER_LIGHT,
        ),
        PageBreak(),
    ]

    story += [
        P("4. Standards conformance: what passed", "AuditH1"),
        P("The strongest positive evidence is not that the package says 'valid'; it is that the code reproduced published public vectors and rejected known invalid encodings."),
        findings_table([
            ("C-01", "POSITIVE", "BIP39 public vector passes", "The official 12-word zero-entropy fixture, checksum geometry, 2,048-word list fingerprint, NFKD handling, PBKDF2-HMAC-SHA512 seed with 2,048 iterations, and TREZOR vector all pass."),
            ("C-02", "POSITIVE", "BIP84 public vectors pass", "The first receiving, second receiving, and first change addresses and compressed public keys match BIP84's published vectors."),
            ("C-03", "POSITIVE", "Bech32 and Bech32m pass", "Covered v0 P2WPKH and v1 32-byte program vectors pass; mixed case, bad checksum, and invalid program length are rejected."),
            ("C-04", "POSITIVE", "Public certificate omits exact secrets", "The returned public certificate contained none of the exact test mnemonic, seed, private scalar, or chain-code values."),
            ("C-05", "POSITIVE", "Runtime stayed local in the probe", "Monkeypatched socket, process, URL, and write-like file APIs were not called by the reference runtime."),
        ]),
        Spacer(1, 6 * mm),
        P("Important limit", "AuditH2"),
        P("The tests show conformance for the covered vectors and branches. They do not prove every BIP edge case, constant-time behavior, secure key custody, authorization, or safe deployment. Coverage was 86%, not 100%, and a test cannot validate a control it never exercises."),
        callout(
            "ELI5",
            "The calculator got the published homework answers right. That proves useful arithmetic. It does not prove the calculator is a safe vault for the master key.",
            GREEN,
            GREEN_LIGHT,
        ),
        PageBreak(),
    ]

    story += [
        P("5. Main finding: the gate is a sign, not a lock", "AuditH1"),
        findings_table([
            ("F-01", "HIGH", "Authorization can be bypassed by design", "derive_bip84_public_certificate accepts a mnemonic, path and passphrase but no authorization object. It directly derives the seed and private HD path."),
            ("F-02", "MEDIUM", "Ownership is self-asserted", "authorize_audit accepts the self-owned known-seed scope without technical proof that the subject or secret belongs to the caller."),
            ("F-03", "LOW", "Exports enlarge the misuse surface", "The package root publicly exports mnemonic_to_seed and master_node_from_seed. This is normal for a library, but it contradicts treating a separate policy function as mandatory enforcement."),
        ]),
        Spacer(1, 7 * mm),
        callout(
            "Demonstrated bypass",
            f"Forbidden scope rejection worked: {not auth['forbidden_scope_authorized']}. "
            f"But direct derivation without an authorization certificate also worked: {auth['direct_derivation_succeeds_without_authorization_certificate']}. "
            "No secret search was performed; the official public test mnemonic was used.",
            RED,
            RED_LIGHT,
        ),
        Spacer(1, 6 * mm),
        P("Risk interpretation", "AuditH2"),
        bullet("Exploit difficulty: trivial for code already able to import the package."),
        bullet("Standalone wallet-theft impact: low, because the caller must already supply a mnemonic and the package has no search, signing, network, or broadcast function."),
        bullet("Assurance impact: high if documentation claims every cryptographic operation is gated."),
        bullet("Correct design choice: either describe authorize_audit honestly as an advisory policy helper, or put secret operations behind a separately authenticated and authorized service boundary."),
        P("Evidence locations", "AuditH2"),
        P("src/ugts36/sara363.py:498-527, 559-583; src/ugts36/__init__.py:123-166; output/security_audit/security_probe_results.json", "AuditMono"),
        PageBreak(),
    ]

    story += [
        P("6. Secret handling and timing", "AuditH1"),
        findings_table([
            ("F-04", "HIGH", "HDNode is easy to log by accident", "Its default repr and dataclasses.asdict include the private scalar and chain code. A debug print, exception context, or generic serializer could expose full wallet authority."),
            ("F-05", "MEDIUM", "Secrets cannot be reliably wiped", "Mnemonic and passphrase are immutable Python strings; seeds and chain codes are immutable bytes; there is no zeroize method."),
            ("F-06", "MEDIUM", "Scalar multiplication is variable-time", "The double-and-add loop branches on secret bits. Chosen-scalar measurements ranged from 0.078 ms to 40.356 ms per call, over 500x."),
        ]),
        Spacer(1, 6 * mm),
        side_channel_chart(),
        Spacer(1, 3 * mm),
        metric_cards([
            ("Shortest median", "0.078 ms", "1-bit scalar", BLUE, BLUE_LIGHT),
            ("High-bit median", "20.598 ms", "262.5x slower", PURPLE, PURPLE_LIGHT),
            ("Dense median", "40.356 ms", "514.3x slower", RED, RED_LIGHT),
        ]),
        Spacer(1, 6 * mm),
        callout(
            "What this does and does not prove",
            "It proves strong input-dependent timing in this implementation. It does not prove a remote key-recovery exploit. A practical side-channel attack would require real secrets, repeated observations, and a capable local or co-resident attacker. "
            "Nevertheless, this is a production blocker: use an audited constant-time secp256k1 implementation or hardware wallet for real keys.",
            AMBER,
            AMBER_LIGHT,
        ),
        PageBreak(),
    ]

    expected_years = perf["expected_128_bit_search_years_at_measured_full_derivation_rate"]
    dictionary_hours = perf["expected_half_of_one_million_passphrase_dictionary_seconds_at_measured_rate"] / 3600.0
    story += [
        P("7. Can it hack a wallet? Feasibility by vector", "AuditH1"),
        metric_cards([
            ("PBKDF2 rate", f"{perf['pbkdf2_seed_derivations_per_second']:.0f}/s", "seed step only", BLUE, BLUE_LIGHT),
            ("Full BIP84 rate", f"{perf['full_bip84_derivations_per_second']:.2f}/s", "pure Python", PURPLE, PURPLE_LIGHT),
            ("Random 12 words", f"{expected_years:.2e} y", "expected at measured rate", GREEN, GREEN_LIGHT),
            ("1M passphrases", f"{dictionary_hours:.1f} h", "expected half-dictionary", RED, RED_LIGHT),
        ]),
        Spacer(1, 7 * mm),
        status_table([
            ("Reverse a public address to a private key", "INFEASIBLE", "No shortcut or capability found. Public decoding reveals only witness and script structure."),
            ("Search a uniform 12-word BIP39 mnemonic", "INFEASIBLE", "Expected 2^127 full trials. The package estimates work but has no enumerator."),
            ("Guess a weak passphrase after mnemonic theft", "FEASIBLE", "BIP39 makes every passphrase a valid seed. A known public address lets an attacker test candidates for a match."),
            ("Use a human-made or low-entropy mnemonic", "DANGEROUS", "Checksum validity proves syntax, not randomness or ownership. BIP39 explicitly targets computer-generated entropy."),
            ("Leak key objects through logs or dumps", "FEASIBLE", "Default repr/asdict expose sensitive fields, and immutable objects can linger in memory."),
            ("Bypass authorize_audit locally", "TRIVIAL", "Call the exported derivation API directly. This does not magically provide a missing mnemonic."),
            ("Steal funds using this package alone", "NO", "There is no transaction signing, broadcast, network, balance, or funds-transfer capability."),
        ]),
        Spacer(1, 6 * mm),
        callout(
            "The realistic attack path",
            "The cryptography is not the easy door. The realistic doors are a stolen mnemonic, a weak passphrase, logging, memory dumps, malware, phishing, or a tampered package. "
            "The package is a calculator that could help verify a guessed secret after the attacker already has a major piece of it; it is not a practical 128-bit brute-force engine.",
            RED,
            RED_LIGHT,
        ),
        PageBreak(),
    ]

    story += [
        P("8. The supplied validator can report a false sense of safety", "AuditH1"),
        findings_table([
            ("F-07", "HIGH", "Stored transcript is trusted as a test run", "The validator reads test_results_3_6_3.txt and checks that it ends in OK. It does not execute the tests."),
            ("F-08", "HIGH", "Capability flags are self-reported", "Network, transaction, and egress values are read from the stored certificate instead of observed from runtime behavior."),
            ("F-09", "MEDIUM", "AST scan is narrow and bypassable", "Only sara363.py and sara_runtime.py are scanned. A synthetic __import__('socket') inside a harmless function evaded both checks."),
            ("F-10", "MEDIUM", "Visual inspection count is hardcoded", "The report field rendered_pages_visually_inspected is always set to 18 and then validated as equal to 18."),
        ]),
        Spacer(1, 7 * mm),
        callout(
            "ELI5",
            "The validator asks the report card whether the student passed, rather than watching the exam. It also checks that a note says 'no network' instead of watching the program's network behavior.",
            AMBER,
            AMBER_LIGHT,
        ),
        Spacer(1, 6 * mm),
        P("Why the pristine validator still matters", "AuditH2"),
        P("It successfully verifies useful static facts: schema validity, content hashes inside the example, operator and claim counts, wordlist fingerprint, public fixture values, and PDF openability. Its final valid=true result must be described as a package-consistency check, not a security certification."),
        P("Evidence locations", "AuditH2"),
        P("tools/validate_sara363_package.py:52, 69-92, 115-168; output/security_audit/validator_pristine_console.txt; output/security_audit/security_probe_results.json", "AuditMono"),
        PageBreak(),
    ]

    story += [
        P("9. Integrity and supply-chain findings", "AuditH1"),
        metric_cards([
            ("Pristine ZIP", "152/152", "manifest hashes match", GREEN, GREEN_LIGHT),
            ("Current copy", "150/152", "two policy docs differ", RED, RED_LIGHT),
            ("Unexpected keys", "0", "pristine secret scan", GREEN, GREEN_LIGHT),
            ("Wheel size", "49,610 B", "code-only artifact", BLUE, BLUE_LIGHT),
        ]),
        Spacer(1, 7 * mm),
        findings_table([
            ("F-11", "MEDIUM", "Current README and SECURITY hashes fail", "Both differ from the pristine ZIP. Removed material includes the named non-negotiable boundary and rejected-capabilities language."),
            ("F-12", "MEDIUM", "Manifest is unsigned and not enforced", "A writer who can replace code can also replace its hash list. Nothing automatically verifies it before import or execution."),
            ("F-13", "LOW", "Wheel omits project data and audit assets", "The wheel contains modules and metadata only. The wordlist, schemas, examples, validator, tests, and evidence PDF are not installed."),
            ("F-14", "LOW", "Test and validator dependencies are undeclared", "jsonschema and PyMuPDF are necessary for advertised source-tree verification but absent from pyproject metadata."),
        ]),
        Spacer(1, 6 * mm),
        P("Permission check", "AuditH2"),
        P("The inspected files inherit Windows ACLs. Tom, SYSTEM, and Administrators have full control; CodexSandboxUsers has read and execute. No Everyone or broad writable Users entry appeared. These are ordinary source-code permissions, not hardened secret-storage permissions."),
        P("Secret scan", "AuditH2"),
        P(f"The pristine scan covered {secret_scan['scanned_files']} UTF-8 text files and {secret_scan['scanned_utf8_bytes']:,} bytes. It found no encoded xprv/WIF value and no suspicious non-empty wallet-secret JSON field. The two mnemonic occurrences are the official public BIP39 vector. Pattern scanning cannot prove absence of encrypted or obfuscated secrets."),
        PageBreak(),
    ]

    story += [
        P("10. Input resilience and local denial of service", "AuditH1"),
        metric_cards([
            ("Random Bech32", "10,000", "zero accepted", GREEN, GREEN_LIGHT),
            ("Bech32 p95", f"{input_data['bech32_latency_p95_microseconds']:.1f} us", "max 20.2 us", GREEN, GREEN_LIGHT),
            ("Path components", "100,000", "accepted without limit", RED, RED_LIGHT),
            ("Trace reuse", "6 -> 12", "entries accumulate", AMBER, AMBER_LIGHT),
        ]),
        Spacer(1, 7 * mm),
        findings_table([
            ("F-15", "LOW", "Derivation paths have no depth limit", "Parsing 100,000 components took only 0.0146 s, but actually deriving them would consume substantial CPU. BIP32 serialized depth is one byte, so a practical cap is expected."),
            ("F-16", "LOW", "Search estimator has no bits upper bound", "A one-million-bit request raised OverflowError. If exposed to untrusted input, extreme integers can become a local resource-abuse vector."),
            ("F-17", "LOW", "Runtime trace grows across repeated runs", "run_reference appends six more entries every time because the trace is never reset."),
            ("F-18", "LOW", "Trace discloses an absolute local path", "The wordlist path reveals the local username and package location. This is minor information leakage."),
        ]),
        Spacer(1, 6 * mm),
        callout(
            "Positive parser result",
            "The random Bech32 probe found no accidental acceptance and no latency spike. This is a useful smoke test, not exhaustive fuzzing or a proof that every parser edge case is safe.",
            GREEN,
            GREEN_LIGHT,
        ),
        PageBreak(),
    ]

    story += [
        P("11. Automated scanner and dependency results", "AuditH1"),
        metric_cards([
            ("Bandit LOC", "6,202", "src, tools, examples", BLUE, BLUE_LIGHT),
            ("High findings", "0", "Bandit", GREEN, GREEN_LIGHT),
            ("Medium findings", "0", "Bandit", GREEN, GREEN_LIGHT),
            ("Low findings", str(len(bandit_results)), "reviewed false positives", AMBER, AMBER_LIGHT),
        ]),
        Spacer(1, 7 * mm),
        status_table([
            ("Bandit static scan", "CLEAN WITH LIMITS", "Five low-severity, medium-confidence items. They are test vectors, an empty optional passphrase, boolean literals, or non-secret path strings."),
            ("pip-audit isolated environment", "0 KNOWN VULNS", f"{len(pip_audit.get('dependencies', []))} installed packages examined; {pip_vulns} known vulnerabilities returned."),
            ("Local project lookup", "SKIPPED", "ugts-kc-363-sara is local and not found on PyPI, so registry vulnerability matching cannot assess its source."),
            ("pip check", "PASS", "No broken installed requirements in the final isolated environment."),
            ("Wheel build", "PASS", "ugts_kc_363_sara-3.6.3-py3-none-any.whl built; SHA-256 4ded3bef063177ae59ddda87a8ad1fea3af13693dd19362b267a44a94e8df677."),
        ]),
        Spacer(1, 6 * mm),
        callout(
            "Do not overread green scanners",
            "Bandit did not detect the advisory authorization boundary, loggable HDNode, weak validator, or policy-document tampering. Automated scanners are one layer of evidence, not the verdict.",
            AMBER,
            AMBER_LIGHT,
        ),
        PageBreak(),
    ]

    story += [
        P("12. Remediation roadmap", "AuditH1"),
        P("Priority 0 - before any real mnemonic or passphrase", "AuditH2"),
        findings_table([
            ("R-01", "HIGH", "Do not market the current gate as enforced", "Either rename it as an advisory policy check or place all secret operations behind a separately authenticated service/API that requires an authorized context."),
            ("R-02", "HIGH", "Replace Python secret-key math", "Use an audited constant-time secp256k1 library or hardware wallet. Keep this code for public vectors and education only."),
            ("R-03", "HIGH", "Make secret objects non-printable", "Set repr=False on secret fields, prevent generic dataclass serialization, minimize lifetime, avoid immutable strings where possible, and prohibit plaintext logging."),
            ("R-04", "HIGH", "Restore and verify policy documents", "Reconcile README.md and SECURITY.md with the pristine ZIP, review the changes, and require signed manifest verification before execution."),
        ]),
        Spacer(1, 6 * mm),
        P("Priority 1 - make verification meaningful", "AuditH2"),
        bullet("Make the validator run tests itself, capture the exit code and fresh timestamp, and reject stale transcripts."),
        bullet("Observe runtime I/O with an allowlist or sandbox instead of trusting stored capability booleans."),
        bullet("Scan the complete installed artifact and dynamic-import patterns; verify the manifest and signature first."),
        bullet("Remove hardcoded visual-inspection claims; generate page renders and record verifiable inspection evidence."),
        bullet("Add explicit developer/test dependency metadata with compatible pins or hashes."),
        P("Priority 2 - resilience and privacy", "AuditH2"),
        bullet("Limit derivation depth to the supported BIP32 range and cap input length before parsing."),
        bullet("Limit search-estimator bits to a documented range, such as 1-256, and return a controlled validation error."),
        bullet("Reset or bound runtime traces and store only a basename or logical wordlist identifier."),
        bullet("Decide whether the wheel is code-only or self-contained; package data accordingly and test the installed wheel."),
        PageBreak(),
    ]

    story += [
        P("13. Evidence map and coverage limits", "AuditH1"),
        P("All audit evidence is under output/security_audit in the package root. The report generator reads the machine-readable JSON files directly."),
        source_table([
            ("Final 195-test run", "output/security_audit/unittest_final_console.txt"),
            ("Branch coverage", "output/security_audit/coverage_report.txt and coverage.json"),
            ("Adversarial probes", "output/security_audit/security_probe_results.json"),
            ("Timing evidence", "output/security_audit/side_channel_timing.json"),
            ("Pristine/current integrity", "output/security_audit/manifest_zip.json and manifest_filesystem.json"),
            ("Policy document comparison", "output/security_audit/documentation_integrity.json"),
            ("Packaged-secret scan", "output/security_audit/packaged_secret_scan.json"),
            ("Static and dependency scans", "output/security_audit/bandit.json and pip_audit_isolated.json"),
            ("Validator run", "output/security_audit/validator_pristine_console.txt"),
            ("Wheel inspection", "output/security_audit/wheel_inspection_console.txt"),
            ("Windows ACLs", "output/security_audit/windows_acl_report.txt"),
            ("Machine profile", "output/security_audit/environment.txt"),
        ]),
        Spacer(1, 6 * mm),
        P("What remains unproven", "AuditH2"),
        bullet("No exhaustive proof of BIP39/BIP32/BIP84/Bech32 correctness beyond covered vectors and branches."),
        bullet("No cryptographic-library certification, secure-code review by multiple independent reviewers, or formal verification."),
        bullet("No practical side-channel key extraction; only a timing-pattern demonstration."),
        bullet("No malware, process-memory dump, backup, browser, clipboard, or user-operational assessment."),
        bullet("No external wallet ownership, balance, or on-chain activity verification."),
        bullet("No offensive testing against any third-party system or secret."),
        callout(
            "Confidence statement",
            "High confidence in the recorded local observations and covered public vectors. Medium confidence in broader parser and packaging conclusions. Low confidence for any claim of production wallet safety, because the design intentionally lacks hardened secret custody and constant-time primitives.",
            BLUE,
            BLUE_LIGHT,
        ),
        PageBreak(),
    ]

    story += [
        P("14. Authoritative references", "AuditH1"),
        P("These standards and guidance were checked on 18 August 2026. Local package claims were judged against primary Bitcoin BIP specifications and current packaging/security guidance."),
        source_table([
            ("S1 - BIP39 mnemonic and PBKDF2", "https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki"),
            ("S2 - BIP32 hierarchical deterministic wallets", "https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki"),
            ("S3 - BIP84 P2WPKH derivation", "https://github.com/bitcoin/bips/blob/master/bip-0084.mediawiki"),
            ("S4 - BIP173 Bech32", "https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki"),
            ("S5 - BIP350 Bech32m", "https://github.com/bitcoin/bips/blob/master/bip-0350.mediawiki"),
            ("S6 - OWASP secrets management", "https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html"),
            ("S7 - Python packaging and package data", "https://packaging.python.org/en/latest/guides/distributing-packages-using-setuptools/"),
        ]),
        Spacer(1, 7 * mm),
        P("Key standard facts used", "AuditH2"),
        bullet("BIP39 specifies 128-256 bits of computer-generated entropy, NFKD normalization, and PBKDF2-HMAC-SHA512 with 2,048 iterations and a 64-byte output."),
        bullet("BIP39 says the scheme is for transporting computer-generated randomness, not for user-created brainwallet sentences."),
        bullet("BIP84 specifies m / purpose' / coin_type' / account' / change / address_index with purpose 84' and publishes the public vectors used here."),
        bullet("OWASP recommends minimizing plaintext secret lifetime, avoiding immutable secret storage where possible, zeroing memory, applying least privilege, and never logging plaintext secrets."),
        bullet("Python packaging guidance requires dependencies and package data to be declared when they are needed by an installed distribution."),
        PageBreak(),
    ]

    story += [
        Spacer(1, 20 * mm),
        P("Final verdict", "AuditH1"),
        callout(
            "Conditionally feasible as a public standards reference. Not approved for real wallet secrets.",
            "The package's covered Bitcoin arithmetic and public certificate pipeline work. The pristine archive is internally consistent, and the runtime showed no network, process, or write behavior in the probe. "
            "However, authorization is not enforced, secret-bearing objects are easy to serialize, elliptic-curve math is variable-time, the validator can produce false confidence, and the current extracted policy documents fail their original hashes.",
            RED,
            RED_LIGHT,
        ),
        Spacer(1, 10 * mm),
        P("Answer to the practical question", "AuditH2"),
        P("No: this is not a serious full-wallet hacking engine. A public address alone does not make a recoverable private key. Uniform 12-word brute force is astronomically infeasible. "
          "Yes: weak operational secrets are still dangerous. If a mnemonic is already stolen, a weak BIP39 passphrase can be tested; accidental repr/asdict logging can reveal key material; and the advisory gate can be ignored by local callers."),
        Spacer(1, 10 * mm),
        metric_cards([
            ("Use for education", "YES", "public vectors only", GREEN, GREEN_LIGHT),
            ("Use for public decode", "YES", "watch-only facts", GREEN, GREEN_LIGHT),
            ("Use for real secrets", "NO", "until P0 fixes", RED, RED_LIGHT),
            ("Treat validator as cert", "NO", "consistency check only", RED, RED_LIGHT),
        ]),
        Spacer(1, 14 * mm),
        P("Report produced from the captured evidence listed on page 13. This is a technical assessment, not a guarantee, financial advice, or authorization to test third-party systems.", "AuditSmall"),
    ]

    return story


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = AuditDocTemplate(str(OUTPUT))
    story = build_story()
    doc.build(story)
    print(f"WROTE {OUTPUT}")
    print(f"BYTES {OUTPUT.stat().st_size}")


if __name__ == "__main__":
    main()
