"""Generate the measured ELI5 conformance report as a polished PDF."""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "SARA_3_6_3_CUDA_Conformance_ELI5_Report.pdf"
MAX_METRICS = ROOT / "output" / "benchmark_metrics_max_batch.json"
MID_METRICS = ROOT / "output" / "benchmark_metrics.json"
SINGLE_METRICS = ROOT / "output" / "benchmark_metrics_single_item.json"

NAVY = colors.HexColor("#102A43")
BLUE = colors.HexColor("#1F6FEB")
CYAN = colors.HexColor("#19A7AE")
GREEN = colors.HexColor("#16803C")
PALE_GREEN = colors.HexColor("#E8F5EC")
PALE_BLUE = colors.HexColor("#EAF2FF")
PALE_ORANGE = colors.HexColor("#FFF2DD")
ORANGE = colors.HexColor("#B85C00")
RED = colors.HexColor("#B42318")
LIGHT = colors.HexColor("#F5F7FA")
MID = colors.HexColor("#D5DEE8")
TEXT = colors.HexColor("#233244")
MUTED = colors.HexColor("#526579")


def load_metrics(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not all(data["correctness"].values()):
        raise RuntimeError(f"Refusing to report a non-passing result: {path}")
    return data


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def cell(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def flow_diagram() -> Drawing:
    drawing = Drawing(170 * mm, 33 * mm)
    labels = [
        ("Public BIP39 words", "plus TREZOR"),
        ("PBKDF2-SHA512", "2,048 rounds"),
        ("64-byte seed", "exact match"),
        ("BIP32 tree", "5 child edges"),
        ("6 verified nodes", "private + chain + pub"),
    ]
    box_w = 29 * mm
    gap = 5.5 * mm
    x = 1 * mm
    for i, (top, bottom) in enumerate(labels):
        fill = PALE_GREEN if i in (2, 4) else PALE_BLUE
        stroke = GREEN if i in (2, 4) else BLUE
        drawing.add(Rect(x, 8 * mm, box_w, 18 * mm, 3 * mm, 3 * mm, fillColor=fill, strokeColor=stroke))
        drawing.add(String(x + box_w / 2, 19 * mm, top, textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.1, fillColor=NAVY))
        drawing.add(String(x + box_w / 2, 13 * mm, bottom, textAnchor="middle", fontName="Helvetica", fontSize=6.5, fillColor=MUTED))
        if i < len(labels) - 1:
            arrow_x = x + box_w + 1.1 * mm
            drawing.add(String(arrow_x, 16.5 * mm, ">", fontName="Helvetica-Bold", fontSize=12, fillColor=CYAN))
        x += box_w + gap
    return drawing


def speedup_chart(bip39_speedup: float, bip32_speedup: float) -> Drawing:
    drawing = Drawing(170 * mm, 40 * mm)
    entries = [("BIP39 seed derivation", bip39_speedup, BLUE), ("BIP32 full vector path", bip32_speedup, CYAN)]
    maximum = max(value for _, value, _ in entries)
    for row, (label, value, color) in enumerate(entries):
        y = (24 - row * 16) * mm
        drawing.add(String(0, y + 4.5 * mm, label, fontName="Helvetica-Bold", fontSize=8.5, fillColor=NAVY))
        drawing.add(Rect(54 * mm, y, 92 * mm, 7 * mm, 2 * mm, 2 * mm, fillColor=LIGHT, strokeColor=MID))
        width = 92 * mm * value / maximum
        drawing.add(Rect(54 * mm, y, width, 7 * mm, 2 * mm, 2 * mm, fillColor=color, strokeColor=color))
        drawing.add(String(150 * mm, y + 1.3 * mm, f"{value:,.1f}x", fontName="Helvetica-Bold", fontSize=10, fillColor=NAVY))
    drawing.add(String(54 * mm, 0.5 * mm, "Large-batch throughput relative to this single CPU implementation", fontName="Helvetica-Oblique", fontSize=7.3, fillColor=MUTED))
    return drawing


def on_page(canvas, document) -> None:
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(MID)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 15 * mm, width - 18 * mm, 15 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10.5 * mm, "SARA 3.6.3 CUDA fixed-vector conformance - measured report")
    canvas.drawRightString(width - 18 * mm, 10.5 * mm, f"Page {document.page}")
    canvas.restoreState()


def build() -> Path:
    large = load_metrics(MAX_METRICS)
    medium = load_metrics(MID_METRICS)
    single = load_metrics(SINGLE_METRICS)

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=29,
        textColor=NAVY, alignment=TA_LEFT, spaceAfter=8 * mm,
    )
    subtitle = ParagraphStyle(
        "Subtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=12, leading=17,
        textColor=MUTED, spaceAfter=7 * mm,
    )
    h1 = ParagraphStyle(
        "H1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=21,
        textColor=NAVY, spaceBefore=3 * mm, spaceAfter=4 * mm,
    )
    h2 = ParagraphStyle(
        "H2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=15,
        textColor=BLUE, spaceBefore=3 * mm, spaceAfter=2 * mm,
    )
    body = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.4, leading=14,
        textColor=TEXT, spaceAfter=2.6 * mm,
    )
    small = ParagraphStyle(
        "Small", parent=body, fontSize=7.7, leading=10.5, textColor=MUTED, spaceAfter=1.5 * mm,
    )
    table_head = ParagraphStyle(
        "TableHead", parent=body, fontName="Helvetica-Bold", fontSize=8.2, leading=10, textColor=colors.white,
    )
    table_cell = ParagraphStyle(
        "TableCell", parent=body, fontSize=7.8, leading=10.2, spaceAfter=0,
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold", parent=table_cell, fontName="Helvetica-Bold", textColor=NAVY,
    )
    callout = ParagraphStyle(
        "Callout", parent=body, fontName="Helvetica-Bold", fontSize=11, leading=16, textColor=GREEN,
        alignment=TA_CENTER, borderColor=GREEN, borderWidth=1, borderPadding=10, backColor=PALE_GREEN,
        spaceBefore=3 * mm, spaceAfter=5 * mm,
    )
    warning = ParagraphStyle(
        "Warning", parent=body, fontSize=9, leading=13.5, textColor=ORANGE,
        borderColor=ORANGE, borderWidth=0.8, borderPadding=8, backColor=PALE_ORANGE,
        spaceBefore=2 * mm, spaceAfter=4 * mm,
    )
    code = ParagraphStyle(
        "Code", parent=small, fontName="Courier", fontSize=6.7, leading=9, textColor=TEXT,
        backColor=LIGHT, borderPadding=6, borderColor=MID, borderWidth=0.5,
    )

    document = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=21 * mm, title="SARA 3.6.3 CUDA Conformance ELI5 Report",
        author="Codex, measured against SARA 3.6.3 and published BIP vectors",
        subject="Correctness, performance, feasibility, and remaining engineering gaps",
    )
    story = []

    # Cover and decision.
    story += [Spacer(1, 18 * mm), p("SARA 3.6.3 CUDA Conformance", title)]
    story += [p("An ELI5 report on what genuinely worked, measured performance, feasibility, and the exact remaining engineering and misuse-boundary gaps.", subtitle)]
    story += [p("VERDICT: THE FIXED-VECTOR CRYPTOGRAPHIC PIPELINE WORKS", callout)]
    story += [flow_diagram(), Spacer(1, 5 * mm)]
    verdict_data = [
        [cell("Question", table_head), cell("Evidence-based answer", table_head)],
        [cell("Did real CUDA execute?", table_cell_bold), cell("Yes. Native sm_120 code ran on the NVIDIA GeForce RTX 5070 Ti Laptop GPU.", table_cell)],
        [cell("Were the outputs correct?", table_cell_bold), cell("Yes. BIP39 and all six BIP32 vector-1 nodes matched published bytes on CPU and GPU.", table_cell)],
        [cell("Was it repeatable?", table_cell_bold), cell("Yes. Every output in seven large timed runs matched byte-for-byte.", table_cell)],
        [cell("Was it actually accelerated?", table_cell_bold), cell("Yes for large parallel batches: 76.6x BIP39 and 547.8x BIP32 throughput versus this single CPU implementation.", table_cell)],
        [cell("Is this a wallet recovery tool?", table_cell_bold), cell("No. It has no candidate source, arbitrary secret input, address target, search loop, or target comparison.", table_cell)],
    ]
    verdict_table = Table(verdict_data, colWidths=[49 * mm, 116 * mm], repeatRows=1)
    verdict_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("BOX", (0, 0), (-1, -1), 0.6, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, MID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [verdict_table, Spacer(1, 4 * mm)]
    story += [p(f"Measured on {date(2026, 8, 18).isoformat()} in Europe/Amsterdam. Report inputs are the saved benchmark JSON files, native run logs, compiler resource report, CTest result, and the unchanged SARA 3.6.3 Python implementation.", small)]

    story += [PageBreak(), p("1. ELI5: what was tested?", h1)]
    story += [p("Imagine a very precise recipe. The same ingredients must always make the same cake. BIP39 turns a public example phrase and passphrase into a 64-byte seed. BIP32 then grows a family tree of keys from that seed. Every branch has an exact expected answer.", body)]
    story += [p("The test gave both the CPU and GPU the same published recipe. It checked the answer after BIP39, then checked the private scalar, chain code, and compressed public key at every BIP32 node. A one-byte difference anywhere would fail the run.", body)]
    story += [p("Why repeat one public example thousands of times?", h2)]
    story += [p("A GPU wins by doing many independent jobs at once. Repeating the same immutable public vector measures parallel throughput without adding a candidate list or a target-search mechanism. It is like timing 65,536 identical, openly published math worksheets - not guessing a private worksheet.", body)]
    story += [p("What 'literal SARA' means here", h2)]
    story += [p("The CUDA functions follow the same transitions as <b>mnemonic_to_seed</b>, <b>master_node_from_seed</b>, <b>ckd_private</b>, and <b>compressed_public_key</b> in <b>src/ugts36/sara363.py</b>. A separate script evaluated the same fixtures through that unchanged Python source, and every node passed.", body)]
    story += [p("This benchmark is not an SGP4 orbital simulation and makes no satellite-navigation claim. The earlier CUDA project contributed its proven Windows/CUDA build and timing patterns only.", warning)]

    story += [p("2. Exact correctness evidence", h1)]
    correctness_rows = [
        [cell("Gate", table_head), cell("Coverage", table_head), cell("Result", table_head)],
        [cell("BIP39 CPU", table_cell_bold), cell("PBKDF2-HMAC-SHA512, 2,048 rounds, 64-byte published seed", table_cell), cell("PASS", table_cell_bold)],
        [cell("BIP39 GPU", table_cell_bold), cell("All 65,536 outputs in each of 7 large runs", table_cell), cell("PASS", table_cell_bold)],
        [cell("BIP32 CPU", table_cell_bold), cell("Master plus 5 edges; hardened and normal; 6 public vector nodes", table_cell), cell("PASS", table_cell_bold)],
        [cell("BIP32 GPU", table_cell_bold), cell("All 6 nodes, then all 4,096 complete paths in each of 7 runs", table_cell), cell("PASS", table_cell_bold)],
        [cell("Repeatability", table_cell_bold), cell("Byte-for-byte outputs across timed runs", table_cell), cell("PASS", table_cell_bold)],
        [cell("CTest", table_cell_bold), cell("Native quick conformance test through CMake/CTest", table_cell), cell("1/1 PASS", table_cell_bold)],
        [cell("SARA pytest", table_cell_bold), cell("Targeted upstream tests/test_sara363.py", table_cell), cell("42/42 PASS", table_cell_bold)],
        [cell("Literal SARA", table_cell_bold), cell("Independent fixed-vector execution through unmodified sara363.py", table_cell), cell("PASS", table_cell_bold)],
    ]
    correctness_table = Table(correctness_rows, colWidths=[34 * mm, 106 * mm, 25 * mm], repeatRows=1)
    correctness_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("BOX", (0, 0), (-1, -1), 0.6, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, MID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white), ("TEXTCOLOR", (2, 1), (2, -1), GREEN),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [correctness_table, Spacer(1, 3 * mm)]
    story += [p("The important distinction: a program can run without being correct. Here, correctness is tied to external published bytes, not merely to a zero exit code or CPU/GPU agreement.", body)]

    story += [PageBreak(), p("3. Measured performance", h1)]
    device = large["device"]
    story += [p(f"Hardware: <b>{device['name']}</b>, compute capability {device['compute_capability']}, CUDA driver API {device['driver_version']}, CUDA runtime {device['runtime_version']}. Build: Visual Studio 2022, CUDA 12.8, native and virtual sm_120 code, Release configuration.", body)]
    perf_rows = [
        [cell("Workload", table_head), cell("CPU mean", table_head), cell("1 GPU item", table_head), cell("Large GPU batch", table_head), cell("Large throughput", table_head)],
        [cell("BIP39 seed", table_cell_bold), cell(f"{large['cpu']['bip39_ms_per_operation']:.3f} ms/op", table_cell), cell(f"{single['gpu']['bip39_mean_batch_ms']:.3f} ms", table_cell), cell(f"{large['gpu']['bip39_mean_batch_ms']:.3f} ms / {large['configuration']['bip39_batch']:,}", table_cell), cell(f"{large['gpu']['bip39_operations_per_second']:,.1f} ops/s", table_cell_bold)],
        [cell("BIP32 vector-1 path", table_cell_bold), cell(f"{large['cpu']['bip32_vector1_ms_per_path']:.3f} ms/path", table_cell), cell(f"{single['gpu']['bip32_mean_batch_ms']:.3f} ms", table_cell), cell(f"{large['gpu']['bip32_mean_batch_ms']:.3f} ms / {large['configuration']['bip32_batch']:,}", table_cell), cell(f"{large['gpu']['bip32_paths_per_second']:,.1f} paths/s", table_cell_bold)],
    ]
    perf_table = Table(perf_rows, colWidths=[37 * mm, 28 * mm, 28 * mm, 39 * mm, 33 * mm], repeatRows=1)
    perf_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("BOX", (0, 0), (-1, -1), 0.6, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, MID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white), ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [perf_table, Spacer(1, 4 * mm)]
    story += [speedup_chart(large["throughput_speedup_vs_single_cpu"]["bip39"], large["throughput_speedup_vs_single_cpu"]["bip32_vector1_path"])]
    story += [p(f"BIP39 also sustained <b>{large['gpu']['pbkdf2_rounds_per_second']:,.1f} PBKDF2 rounds/s</b>. The BIP32 batch sustained <b>{large['gpu']['bip32_ckd_edges_per_second']:,.1f} child-derivation edges/s</b> across the five-edge path.", body)]
    story += [p("ELI5 interpretation: one child doing one worksheet on the GPU is slow because the whole classroom must open first. Give the classroom thousands of worksheets, and many children work at the same time. That is why single-item GPU latency loses to the CPU while large-batch throughput wins strongly.", warning)]
    scaling_rows = [
        [cell("Scale point", table_head), cell("BIP39 ops/s", table_head), cell("BIP32 paths/s", table_head)],
        [cell("1 item", table_cell_bold), cell(f"{single['gpu']['bip39_operations_per_second']:,.1f}", table_cell), cell(f"{single['gpu']['bip32_paths_per_second']:,.1f}", table_cell)],
        [cell("Medium batch", table_cell_bold), cell(f"{medium['gpu']['bip39_operations_per_second']:,.1f} ({medium['configuration']['bip39_batch']:,} items)", table_cell), cell(f"{medium['gpu']['bip32_paths_per_second']:,.1f} ({medium['configuration']['bip32_batch']:,} items)", table_cell)],
        [cell("Large batch", table_cell_bold), cell(f"{large['gpu']['bip39_operations_per_second']:,.1f} ({large['configuration']['bip39_batch']:,} items)", table_cell), cell(f"{large['gpu']['bip32_paths_per_second']:,.1f} ({large['configuration']['bip32_batch']:,} items)", table_cell)],
    ]
    scaling_table = Table(scaling_rows, colWidths=[49 * mm, 58 * mm, 58 * mm], repeatRows=1)
    scaling_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("BOX", (0, 0), (-1, -1), 0.6, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, MID), ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [p("Observed scaling", h2), scaling_table]

    story += [PageBreak(), p("4. What seriously works - and what that proves", h1)]
    proof_rows = [
        [cell("Proven", table_head), cell("Not proven by this test", table_head)],
        [cell("CUDA can reproduce the published BIP39 seed exactly.", table_cell), cell("Arbitrary-language Unicode normalization on the GPU.", table_cell)],
        [cell("CUDA can generate BIP32 master and private child nodes.", table_cell), cell("Full wallet-format compatibility or device-wallet import/export.", table_cell)],
        [cell("Normal BIP32 edges work because secp256k1 compressed public keys are produced on-device.", table_cell), cell("BIP44, BIP49, BIP84, legacy address projection, or blockchain discovery.", table_cell)],
        [cell("Both hardened and normal edges match the complete official vector-1 path.", table_cell), cell("All official vectors, malformed-input behavior, or invalid-child retry coverage.", table_cell)],
        [cell("Large fixed batches get real GPU throughput acceleration.", table_cell), cell("Candidate generation, target matching, wallet recovery, or useful search coverage.", table_cell)],
    ]
    proof_table = Table(proof_rows, colWidths=[82.5 * mm, 82.5 * mm], repeatRows=1)
    proof_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("BOX", (0, 0), (-1, -1), 0.6, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, MID), ("BACKGROUND", (0, 1), (0, -1), PALE_GREEN),
        ("BACKGROUND", (1, 1), (1, -1), PALE_ORANGE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [proof_table, Spacer(1, 4 * mm)]
    story += [p("So: yes, the implemented cryptographic route seriously works for the published inputs and operations tested. No, that result must not be inflated into a claim that an arbitrary wallet, address type, recovery scenario, or search space is solved.", callout)]
    story += [p("Compression claim", h2)]
    story += [p("This benchmark tests deterministic cryptographic transformations, not data compression. It does not measure compression ratio, decompression fidelity, geometric reconstruction, or visual output. Any earlier compression result remains a separate claim and is neither strengthened nor weakened by this BIP39/BIP32 run.", body)]

    story += [p("5. Exact remaining engineering gaps", h1)]
    gap_rows = [
        [cell("Gap", table_head), cell("Why it matters", table_head), cell("Current status", table_head)],
        [cell("General NFKD", table_cell_bold), cell("BIP39 requires Unicode NFKD for arbitrary text.", table_cell), cell("Frozen ASCII fixture is already normalized.", table_cell)],
        [cell("Mnemonic validation", table_cell_bold), cell("Word-list membership and checksum matter before seed derivation.", table_cell), cell("Handled by SARA Python, not this GPU kernel.", table_cell)],
        [cell("More BIP vectors", table_cell_bold), cell("Leading-zero and invalid-edge cases catch subtle arithmetic bugs.", table_cell), cell("Only BIP32 vector 1 and one BIP39 vector are pinned.", table_cell)],
        [cell("Extended-key serialization", table_cell_bold), cell("xprv/xpub include versions, depth, fingerprints, child numbers, and Base58Check.", table_cell), cell("Raw node fields are checked; serialization is absent.", table_cell)],
        [cell("Wallet/address layers", table_cell_bold), cell("Real wallet compatibility needs path conventions, HASH160, scripts, and address encodings.", table_cell), cell("Deliberately absent.", table_cell)],
        [cell("Production optimization", table_cell_bold), cell("Resource pressure limits occupancy and wastes throughput.", table_cell), cell("Correctness-first baseline only.", table_cell)],
        [cell("Security review", table_cell_bold), cell("Secret-handling code needs constant-time review, zeroization, fuzzing, and independent audit.", table_cell), cell("Not performed; do not use with secrets.", table_cell)],
        [cell("Search/recovery layer", table_cell_bold), cell("Would require candidates, arbitrary inputs, projections, and target comparison.", table_cell), cell("Intentionally not implemented.", table_cell)],
    ]
    gap_table = Table(gap_rows, colWidths=[42 * mm, 70 * mm, 53 * mm], repeatRows=1)
    gap_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("BOX", (0, 0), (-1, -1), 0.6, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, MID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [gap_table]

    story += [PageBreak(), p("6. GPU engineering diagnosis", h1)]
    story += [p("The compiler's own resource report explains why this is a baseline, not an optimized library:", body)]
    resource_rows = [
        [cell("Kernel", table_head), cell("Registers/thread", table_head), cell("Stack/thread", table_head), cell("Spills", table_head)],
        [cell("BIP39 batch", table_cell_bold), cell("254", table_cell), cell("4,304 bytes", table_cell), cell("128-byte stores + 128-byte loads", table_cell)],
        [cell("BIP32 batch", table_cell_bold), cell("253", table_cell), cell("4,080 bytes", table_cell), cell("0 reported", table_cell)],
        [cell("BIP32 conformance", table_cell_bold), cell("232", table_cell), cell("4,080 bytes", table_cell), cell("0 reported", table_cell)],
    ]
    resource_table = Table(resource_rows, colWidths=[49 * mm, 35 * mm, 35 * mm, 46 * mm], repeatRows=1)
    resource_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("BOX", (0, 0), (-1, -1), 0.6, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, MID), ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [resource_table, Spacer(1, 4 * mm)]
    story += [p("Most likely optimization order", h2)]
    optimizations = [
        "Reduce SHA-512 message-schedule and HMAC temporary lifetime so fewer registers and local bytes remain live.",
        "Precompute immutable HMAC ipad/opad states for the public benchmark fixture.",
        "Replace the simple field reducer and generic inversion with reviewed secp256k1-specific routines.",
        "Tune block size from measured occupancy and profile memory stalls, instruction mix, and achieved occupancy.",
        "Separate conformance code from optimized throughput kernels while retaining the same external-vector gates.",
        "Add all official BIP32 edge-case vectors plus differential and randomized tests before trusting any optimization.",
    ]
    for number, item in enumerate(optimizations, 1):
        story += [p(f"<b>{number}.</b> {item}", body)]
    story += [p("These changes could improve the fixed-vector primitive benchmark. They do not require or imply adding a credential-search interface.", warning)]

    story += [p("7. How far the misuse boundary moved", h1)]
    boundary_rows = [
        [cell("Present in delivered code", table_head), cell("Still absent", table_head)],
        [cell("GPU SHA-512 and HMAC-SHA512", table_cell), cell("Runtime mnemonic/passphrase input", table_cell)],
        [cell("GPU PBKDF2-HMAC-SHA512/2048", table_cell), cell("Candidate lists, masks, mutation, or enumeration", table_cell)],
        [cell("GPU BIP32 master and private CKD", table_cell), cell("User-selectable derivation paths", table_cell)],
        [cell("GPU secp256k1 compressed public projection", table_cell), cell("Address projection and arbitrary target input", table_cell)],
        [cell("Parallel repetition of one public vector", table_cell), cell("Target comparison, discovery loop, or recovery output", table_cell)],
        [cell("Measured primitive throughput", table_cell), cell("Blockchain access, signing, or transactions", table_cell)],
    ]
    boundary_table = Table(boundary_rows, colWidths=[82.5 * mm, 82.5 * mm], repeatRows=1)
    boundary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("BOX", (0, 0), (-1, -1), 0.6, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, MID), ("BACKGROUND", (0, 1), (0, -1), PALE_BLUE),
        ("BACKGROUND", (1, 1), (1, -1), PALE_ORANGE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [boundary_table, Spacer(1, 4 * mm)]
    story += [p("This is the exact boundary for this delivery. It shows that deterministic wallet primitives can be GPU-native and fast in parallel. It deliberately stops before the components that would turn primitive evaluation into credential search. This describes what this assistant delivered; it is not a universal claim about every AI system's policies.", body)]

    story += [PageBreak(), p("8. Reproduction and evidence map", h1)]
    story += [p("One-command Windows reproduction", h2)]
    story += [p("&amp; .\\scripts\\build_windows.ps1", code)]
    story += [p("The script pins Visual Studio 2022, CUDA 12.8, sm_120, Release mode, CTest, the full measured benchmark, and the independent literal-SARA check. Its external build directory is intentionally short to avoid the Windows/MSBuild path-length failure observed during validation.", body)]
    evidence_rows = [
        [cell("Artifact", table_head), cell("Purpose", table_head)],
        [cell("include/sara363_cuda/crypto.cuh", table_cell_bold), cell("Portable host/device SHA-512, HMAC, PBKDF2, secp256k1, and BIP32 operators", table_cell)],
        [cell("src/main.cu", table_cell_bold), cell("Immutable fixtures, CUDA kernels, exact checks, timing, repeatability, and JSON output", table_cell)],
        [cell("scripts/verify_against_sara.py", table_cell_bold), cell("Independent execution through the unchanged literal SARA 3.6.3 source", table_cell)],
        [cell("output/benchmark_metrics_max_batch.json", table_cell_bold), cell("Large-batch machine-readable metrics used in this report", table_cell)],
        [cell("output/benchmark_metrics_single_item.json", table_cell_bold), cell("Single-item latency evidence", table_cell)],
        [cell("output/max_batch_benchmark_run.txt", table_cell_bold), cell("Human-readable full run and PASS evidence", table_cell)],
        [cell("docs/TRACEABILITY.md", table_cell_bold), cell("Literal SARA operator mapping", table_cell)],
        [cell("docs/SAFETY_SCOPE.md", table_cell_bold), cell("Structural input/search boundary audit", table_cell)],
    ]
    evidence_table = Table(evidence_rows, colWidths=[70 * mm, 95 * mm], repeatRows=1)
    evidence_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("BOX", (0, 0), (-1, -1), 0.6, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, MID), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [evidence_table]

    story += [p("9. Final answer in plain language", h1)]
    story += [p("<b>It works:</b> the GPU computed the intended BIP39 and complete BIP32 vector-1 transformations correctly, on real hardware, repeatedly, and substantially faster in large batches than this single CPU implementation.", body)]
    story += [p("<b>It is not magic:</b> a single job is much slower on this GPU baseline, the kernels are resource-heavy, and correctness has only been established for the pinned public vectors and covered operators.", body)]
    story += [p("<b>It is not wallet recovery:</b> the delivered program cannot accept a private phrase, generate guesses, choose arbitrary paths, derive wallet addresses, accept a target, or search for a match. The measured rate is cryptographic primitive throughput, not a recovered-wallet claim.", body)]
    story += [p("The honest feasibility conclusion is therefore: <b>GPU-native SARA seed and HD-tree primitives are feasible and already functionally correct as a conformance baseline. Production-grade wallet compatibility, security hardening, broader conformance, and performance tuning remain real work. Credential-search functionality is outside this delivery.</b>", callout)]

    story += [p("Sources", h2)]
    sources = [
        "Bitcoin BIP 39: https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki",
        "Trezor BIP39 vectors: https://github.com/trezor/python-mnemonic/blob/master/vectors.json",
        "Bitcoin BIP 32 test vectors: https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki#test-vectors",
        "Local literal source: src/ugts36/sara363.py in the SARA 3.6.3 package",
        "Local measured evidence: cuda_conformance/output/*.json and *.txt",
    ]
    for item in sources:
        story += [p(item, small)]
    story += [Spacer(1, 3 * mm), p("Measurement caveat: timings are observations from one laptop state, compiler build, batch configuration, and power/thermal condition. They are not guaranteed performance on other machines. No statistical confidence interval or profiler-derived occupancy measurement is claimed.", small)]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return OUTPUT


if __name__ == "__main__":
    print(build())
