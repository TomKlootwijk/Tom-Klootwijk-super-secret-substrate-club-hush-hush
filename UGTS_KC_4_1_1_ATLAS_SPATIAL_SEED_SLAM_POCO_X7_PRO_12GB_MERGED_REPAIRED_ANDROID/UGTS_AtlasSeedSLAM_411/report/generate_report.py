#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report"
FIGURES = REPORT / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)
OUTPUT = REPORT / "UGTS_KC_4_1_1_ATLAS_SPATIAL_SEED_SLAM_POCO_X7_PRO_MERGE_REPORT.pdf"

NAVY = colors.HexColor("#0c1b2f")
TEAL = colors.HexColor("#159a92")
BLUE = colors.HexColor("#4d7cff")
GOLD = colors.HexColor("#d9a51e")
RED = colors.HexColor("#c85b4b")
PALE = colors.HexColor("#edf4f7")
LIGHT_TEAL = colors.HexColor("#e2f4f2")
LIGHT_GOLD = colors.HexColor("#fbf3d5")
LIGHT_RED = colors.HexColor("#f8e5e1")
GRAY = colors.HexColor("#5f6b76")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def box(ax, xy, width, height, text, edge, face="#ffffff", fontsize=9):
    patch = FancyBboxPatch(
        xy,
        width,
        height,
        boxstyle="round,pad=0.02,rounding_size=0.03",
        linewidth=1.5,
        edgecolor=edge,
        facecolor=face,
    )
    ax.add_patch(patch)
    ax.text(
        xy[0] + width / 2,
        xy[1] + height / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        weight="bold",
        wrap=True,
    )


def arrow(ax, start, end, color="#596674"):
    ax.annotate(
        "",
        xy=end,
        xytext=start,
        arrowprops=dict(arrowstyle="->", linewidth=1.4, color=color),
    )


def figure_merge():
    path = FIGURES / "merge_lineage.png"
    fig, ax = plt.subplots(figsize=(11, 4.3))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 4.3)
    ax.axis("off")
    box(ax, (0.3, 2.55), 3.0, 1.05, "AVAILABLE SOURCE\n3.9.4.1 repaired Camera2 + SLAM", "#4d7cff", "#eaf0ff")
    box(ax, (0.3, 0.65), 3.0, 1.05, "AVAILABLE REPORT\n4.1.0 Spatial Seed Native contract", "#159a92", "#e2f4f2")
    box(ax, (4.0, 1.55), 3.0, 1.15, "4.1.1 CLEAN FUSION\nsource reimplementation, not byte patch", "#d9a51e", "#fbf3d5")
    box(ax, (7.8, 2.55), 2.8, 1.05, "ACTIVE FRONT END\nCamera2 + IMU + SLAM", "#4d7cff", "#eaf0ff")
    box(ax, (7.8, 0.65), 2.8, 1.05, "MERGED AUTHORITY\nKSEED + verifier + native seed", "#159a92", "#e2f4f2")
    arrow(ax, (3.3, 3.08), (4.0, 2.35))
    arrow(ax, (3.3, 1.18), (4.0, 1.92))
    arrow(ax, (7.0, 2.25), (7.8, 3.08))
    arrow(ax, (7.0, 1.95), (7.8, 1.18))
    ax.text(5.5, 0.12, "The unavailable 4.1.0 source ZIP is not silently claimed as merged code.", ha="center", fontsize=9, color="#9c3b32", weight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def figure_architecture():
    path = FIGURES / "architecture.png"
    fig, ax = plt.subplots(figsize=(12, 6.0))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis("off")
    box(ax, (0.25, 4.15), 1.7, 1.05, "Camera2 YUV\n+ IMU", "#4d7cff", "#eaf0ff")
    box(ax, (2.25, 4.15), 1.75, 1.05, "FAST/BRIEF\n+ matching", "#4d7cff", "#eaf0ff")
    box(ax, (4.3, 4.15), 1.75, 1.05, "Visual motion\n+ triangulation", "#4d7cff", "#eaf0ff")
    box(ax, (6.35, 4.15), 1.75, 1.05, "SpatialProposal\nproposal only", "#d9a51e", "#fbf3d5")
    box(ax, (8.4, 4.15), 1.75, 1.05, "Eight-gate\nverifier", "#c85b4b", "#f8e5e1")
    box(ax, (10.45, 4.15), 1.3, 1.05, "Map +\nledger", "#159a92", "#e2f4f2")
    for x1, x2 in ((1.95, 2.25), (4.0, 4.3), (6.05, 6.35), (8.1, 8.4), (10.15, 10.45)):
        arrow(ax, (x1, 4.68), (x2, 4.68))
    box(ax, (0.25, 1.8), 2.3, 1.05, "Seed128 + native schedule\nstable IDs, bounded samples", "#159a92", "#e2f4f2")
    box(ax, (3.0, 1.8), 2.1, 1.05, "FrameEvidence\nno raw frames by default", "#4d7cff", "#eaf0ff")
    box(ax, (5.55, 1.8), 2.15, 1.05, "Pre/post state hashes\nreason-coded decisions", "#d9a51e", "#fbf3d5")
    box(ax, (8.15, 1.8), 2.0, 1.05, "KSEED 4.1\nCRC + zlib + SHA chain", "#159a92", "#e2f4f2")
    box(ax, (10.55, 1.8), 1.2, 1.05, "PLY /\npreview", "#777777", "#f1f1f1")
    arrow(ax, (2.55, 2.33), (3.0, 2.33))
    arrow(ax, (5.1, 2.33), (5.55, 2.33))
    arrow(ax, (7.7, 2.33), (8.15, 2.33))
    arrow(ax, (10.15, 2.33), (10.55, 2.33))
    arrow(ax, (1.4, 2.85), (1.1, 4.15))
    arrow(ax, (4.05, 2.85), (6.95, 4.15))
    arrow(ax, (6.65, 2.85), (10.9, 4.15))
    arrow(ax, (11.1, 4.15), (9.1, 2.85))
    ax.text(6, 0.55, "Only the verifier can turn an observation into an authoritative map mutation.", ha="center", fontsize=12, weight="bold", color="#0c1b2f")
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def figure_kseed():
    path = FIGURES / "kseed_layout.png"
    fig, ax = plt.subplots(figsize=(12, 5.3))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 5.3)
    ax.axis("off")
    ax.text(0.3, 4.88, "128-byte session header", fontsize=13, weight="bold")
    fields = [
        ("magic/version", 0.9), ("flags", 0.55), ("seed 128", 1.35), ("start time", 1.0),
        ("size/fps/budget", 1.5), ("profile SHA-256", 2.0), ("calibration SHA-256", 2.0), ("CRC32", 0.7)
    ]
    x = 0.3
    total = sum(w for _, w in fields)
    scale = 11.4 / total
    for label, width in fields:
        width *= scale
        rect = Rectangle((x, 4.05), width, 0.58, facecolor="#eaf0ff", edgecolor="#4d7cff", linewidth=1.2)
        ax.add_patch(rect)
        ax.text(x + width / 2, 4.34, label, ha="center", va="center", fontsize=8, wrap=True)
        x += width
    ax.text(0.3, 3.42, "64-byte chunk header + stored payload", fontsize=13, weight="bold")
    chunk_fields = [
        ("type/flags", 1.0), ("sequence/count", 1.2), ("decoded/stored length", 1.6),
        ("decoded/stored CRC32", 1.7), ("schema", 0.7), ("SHA-256 chain", 2.5), ("stored payload", 3.1)
    ]
    x = 0.3
    total = sum(w for _, w in chunk_fields)
    scale = 11.4 / total
    for index, (label, width) in enumerate(chunk_fields):
        width *= scale
        face = "#e2f4f2" if index >= 5 else "#fbf3d5"
        edge = "#159a92" if index >= 5 else "#d9a51e"
        rect = Rectangle((x, 2.55), width, 0.58, facecolor=face, edgecolor=edge, linewidth=1.2)
        ax.add_patch(rect)
        ax.text(x + width / 2, 2.84, label, ha="center", va="center", fontsize=8, wrap=True)
        x += width
    ax.text(0.3, 1.85, "Chunk order", fontsize=13, weight="bold")
    labels = ["frame evidence", "keyframes", "ledger", "Morton voxels", "calibration", "60-byte summary"]
    x = 0.35
    for index, label in enumerate(labels):
        width = 1.65 if index < 5 else 2.0
        box(ax, (x, 0.88), width, 0.58, label, "#159a92" if index < 5 else "#c85b4b", "#e2f4f2" if index < 5 else "#f8e5e1", 8)
        if index < len(labels) - 1:
            arrow(ax, (x + width, 1.17), (x + width + 0.2, 1.17))
        x += width + 0.25
    ax.text(6, 0.25, 'H_i = SHA256(H_(i-1) || chunk_header[0:32] || stored_payload)', ha="center", fontsize=11, family="monospace")
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def figure_verifier():
    path = FIGURES / "verifier.png"
    fig, ax = plt.subplots(figsize=(12, 4.4))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 4.4)
    ax.axis("off")
    names = [
        "1 ID", "2 support", "3 compatibility", "4 guard", "5 confidence", "6 numeric", "7 uncertainty", "8 metric"
    ]
    x = 0.25
    for index, name in enumerate(names):
        box(ax, (x, 2.25), 1.18, 0.75, name, "#c85b4b", "#f8e5e1", 8)
        if index < len(names) - 1:
            arrow(ax, (x + 1.18, 2.62), (x + 1.36, 2.62))
        x += 1.43
    box(ax, (1.25, 0.55), 3.3, 0.9, "REJECT\nstate hash unchanged + reason code", "#c85b4b", "#f8e5e1", 10)
    box(ax, (7.35, 0.55), 3.3, 0.9, "ACCEPT\none mutation + pre/post hashes", "#159a92", "#e2f4f2", 10)
    arrow(ax, (3.0, 2.25), (2.9, 1.45), "#c85b4b")
    arrow(ax, (9.0, 2.25), (9.0, 1.45), "#159a92")
    ax.text(6, 3.72, "Ordered proposal verification", ha="center", fontsize=15, weight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def figure_compression(summary: dict):
    path = FIGURES / "compression.png"
    raw = summary["raw_input_bytes"]
    stored = summary["stored_bytes"]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    bars = ax.bar(["synthetic luma input", "KSEED evidence"], [raw, stored])
    ax.set_yscale("log")
    ax.set_ylabel("bytes (log scale)")
    ax.set_title("Release fixture storage - evidence ratio, not image reconstruction")
    for bar, value in zip(bars, [raw, stored]):
        ax.text(bar.get_x() + bar.get_width()/2, value * 1.15, f"{value:,} B", ha="center", va="bottom", weight="bold")
    ratio = raw / stored
    ax.text(0.5, 0.12, f"{ratio:.2f}x raw-input/evidence ratio in this host fixture only", transform=ax.transAxes, ha="center", color="#9c3b32", weight="bold")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def figure_validation(validation: dict):
    path = FIGURES / "validation.png"
    checks = validation["checks"]
    names = [item["name"].replace("_", " ") for item in checks]
    values = [1 if item["status"] == "PASS" else 0 for item in checks]
    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    y = list(range(len(names)))
    ax.barh(y, values)
    ax.set_yticks(y, names)
    ax.set_xlim(0, 1.15)
    ax.set_xticks([])
    ax.invert_yaxis()
    ax.set_title("Completed host/source gates")
    for index, value in enumerate(values):
        ax.text(1.02, index, "PASS" if value else "FAIL", va="center", weight="bold")
    ax.text(0.5, -0.12, "Android assemble and physical POCO measurements remain separate promotion gates.", transform=ax.transAxes, ha="center", color="#9c3b32", weight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def figure_device_gates():
    path = FIGURES / "device_gates.png"
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 4.5)
    ax.axis("off")
    rows = [
        ("Source/core tests", "PASS", "#e2f4f2", "#159a92"),
        ("KSEED independent integrity", "PASS", "#e2f4f2", "#159a92"),
        ("Android SDK/NDK assemble", "NOT RUN", "#fbf3d5", "#d9a51e"),
        ("POCO install + camera", "DEVICE", "#fbf3d5", "#d9a51e"),
        ("latency / thermal / battery", "MEASURE", "#f8e5e1", "#c85b4b"),
        ("SLAM / route accuracy", "STUDY", "#f8e5e1", "#c85b4b"),
    ]
    y = 3.75
    for label, status, face, edge in rows:
        box(ax, (0.55, y), 7.3, 0.48, label, edge, face, 9)
        box(ax, (8.35, y), 2.0, 0.48, status, edge, face, 9)
        y -= 0.62
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def footer(canvas, doc):
    canvas.saveState()
    width, height = A4
    if doc.page == 1:
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, width, height, stroke=0, fill=1)
    else:
        canvas.setStrokeColor(colors.HexColor("#b8c3cc"))
        canvas.line(18 * mm, height - 13 * mm, width - 18 * mm, height - 13 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GRAY)
        canvas.drawString(18 * mm, height - 10 * mm, "UGTS-KC 4.1.1 Atlas Spatial Seed SLAM Fusion")
        canvas.drawRightString(width - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def p(text, style):
    return Paragraph(text, style)


def table(data, widths, header=True, small=False):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    styles = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#8f9ba6")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.4 if small else 8.2),
    ]
    if header:
        styles += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
        start = 1
    else:
        start = 0
    for row in range(start, len(data)):
        if (row - start) % 2 == 0:
            styles.append(("BACKGROUND", (0, row), (-1, row), PALE))
    t.setStyle(TableStyle(styles))
    return t


def callout(text, style, background, border):
    t = Table([[Paragraph(text, style)]], colWidths=[174 * mm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("BOX", (0, 0), (-1, -1), 1.2, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def main():
    validation = json.loads((ROOT / "validation/release_validation.json").read_text())
    fixture = json.loads((ROOT / "samples/atlas_seed_slam_411_fixture_summary.json").read_text())
    provenance = json.loads((ROOT / "provenance/SOURCE_BASELINE.json").read_text())
    java_files = list((ROOT / "core/src/main/java").rglob("*.java")) + list((ROOT / "app/src/main/java").rglob("*.java")) + list((ROOT / "seednative/src/main/java").rglob("*.java"))
    cpp_files = list((ROOT / "native").rglob("*.cpp")) + list((ROOT / "seednative/src/main/cpp").rglob("*.cpp"))
    source_lines = sum(len(path.read_text(errors="ignore").splitlines()) for path in java_files + cpp_files)
    file_count = sum(1 for path in ROOT.rglob("*") if path.is_file())

    merge_img = figure_merge()
    arch_img = figure_architecture()
    kseed_img = figure_kseed()
    verifier_img = figure_verifier()
    compression_img = figure_compression(fixture)
    validation_img = figure_validation(validation)
    gates_img = figure_device_gates()

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=30, leading=34, textColor=colors.white, alignment=TA_LEFT, spaceAfter=12))
    styles.add(ParagraphStyle(name="CoverSub", parent=styles["Normal"], fontName="Helvetica", fontSize=15, leading=20, textColor=colors.HexColor("#a9d9e0"), spaceAfter=10))
    styles.add(ParagraphStyle(name="CoverMeta", parent=styles["Normal"], fontName="Helvetica", fontSize=10.5, leading=15, textColor=colors.white))
    styles.add(ParagraphStyle(name="H1x", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=NAVY, spaceBefore=4, spaceAfter=10))
    styles.add(ParagraphStyle(name="H2x", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13.5, leading=17, textColor=TEAL, spaceBefore=8, spaceAfter=6))
    styles.add(ParagraphStyle(name="Bodyx", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.4, leading=13.2, textColor=colors.HexColor("#26333e"), spaceAfter=7))
    styles.add(ParagraphStyle(name="Smallx", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.7, leading=10.2, textColor=colors.HexColor("#35434e"), spaceAfter=4))
    styles.add(ParagraphStyle(name="Captionx", parent=styles["BodyText"], fontName="Helvetica-Oblique", fontSize=7.8, leading=10, textColor=GRAY, alignment=TA_CENTER, spaceBefore=2, spaceAfter=8))
    styles.add(ParagraphStyle(name="Calloutx", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=9, leading=12.5, textColor=NAVY))
    styles.add(ParagraphStyle(name="Codex", parent=styles["Code"], fontName="Courier", fontSize=7.8, leading=10, leftIndent=5, rightIndent=5, backColor=colors.HexColor("#f1f4f6"), borderPadding=6, spaceAfter=7))

    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title="UGTS-KC 4.1.1 Atlas Spatial Seed SLAM Fusion",
        author="Tom Klootwijk project context - requester-supplied attribution",
        subject="POCO X7 Pro Android Camera2/SLAM, Spatial Seed Native and KSEED merge report",
    )
    story = []

    # Cover
    story += [Spacer(1, 26 * mm), p("UGTS-KC 4.1.1", styles["CoverTitle"]), p("ATLAS SPATIAL SEED SLAM FUSION", styles["CoverSub"]), Spacer(1, 5 * mm), p("POCO X7 Pro 12 GB Android merge and repair", styles["CoverSub"]), Spacer(1, 12 * mm)]
    cover_table = Table([
        ["Capture", "Camera2 YUV + Android IMU"],
        ["SLAM", "FAST/BRIEF, matching, visual motion, guarded triangulation, semi-dense fusion"],
        ["Authority", "Eight-gate proposals, deterministic ledger, stable IDs, pre/post hashes"],
        ["Storage", "KSEED 4.1 seed plus measured evidence deltas"],
        ["Native", "arm64-v8a C++ seed/CRC module with Java oracle/fallback"],
        ["Status", "Host/source validated; Android assemble and physical POCO run pending"],
    ], colWidths=[32 * mm, 128 * mm], hAlign="LEFT")
    cover_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#13283f")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#54708d")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [cover_table, Spacer(1, 18 * mm), p("Prepared 28 August 2026", styles["CoverMeta"]), p("Release type: complete source handoff; no newly built APK or physical-phone benchmark claimed", styles["CoverMeta"]), PageBreak()]

    # Executive
    story += [p("1. Executive merge decision", styles["H1x"])]
    story += [callout("DECISION - RELEASE AS 4.1.1. Preserve the repaired Camera2/SLAM application, add the documented Spatial Seed/KSEED/native authority layer, and keep every observation proposal-only until the ordered verifier accepts it.", styles["Calloutx"], LIGHT_TEAL, TEAL), Spacer(1, 4 * mm)]
    story += [p("The delivered application is a hybrid native Android scanner: the available 3.9.4.1 Java Camera2 and SLAM source remains the active front end, while a new arm64 C++/JNI module supplies deterministic seed scheduling and CRC acceleration. The platform-independent Java core remains the behavioral oracle and map authority. This reduces integration risk while importing the most important 4.1 mechanisms: seed/evidence separation, stable IDs, proposal gates, state hashes and KSEED storage.", styles["Bodyx"])]
    story += [Image(str(arch_img), width=174 * mm, height=87 * mm), p("Figure 1. Merged capture, authority and storage path.", styles["Captionx"])]
    story += [table([
        ["Priority", "4.1.1 implementation result"],
        ["Accuracy", "Camera intrinsics where available, IMU rotation compensation, guarded matches/triangulation, metric anchor boundary"],
        ["Efficiency", "Single latest-frame queue, bounded features/voxels/keyframes, adjacent-keyframe heavy data only, arm64-only native module"],
        ["Compression", "No raw frames by default; delta/varint/Morton records; zlib only when smaller; exact stored-size summary"],
        ["Integrity", "Header/chunk CRC32, SHA-256 chain, deterministic proposal and pre/post state hashes"],
        ["File size", "No AndroidX, OpenCV, network stack or bundled model weights; R8/resource shrinking retained"],
    ], [34*mm, 140*mm])]
    story += [PageBreak()]

    # Source merge
    story += [p("2. Source lineage and non-negotiable merge boundary", styles["H1x"]), Image(str(merge_img), width=174 * mm, height=68 * mm), p("Figure 2. Available implementation source and available 4.1 specification are visibly separated.", styles["Captionx"])]
    story += [callout("SOURCE BOUNDARY. The complete UGTS-KC 4.1.0 source ZIP was not present in the active workspace. This release therefore reimplements the documented 4.1 KSEED and authority contract against the available repaired 3.9.4.1 source. It is not a byte-identical patch of an unavailable tree.", styles["Calloutx"], LIGHT_RED, RED), Spacer(1, 4 * mm)]
    story += [table([
        ["Source", "Available form", "Treatment"],
        ["UGTS-KC 3.9.4.1 repaired Android", "ZIP source", "Direct extracted baseline; Gradle repair, Camera2, IMU, SLAM, export and host tooling retained"],
        ["UGTS-KC 4.1.0 Spatial Seed Native", "Technical PDF", "KSEED framing, verifier order, seed/evidence boundary, synthetic isolation, native profile and promotion gates reconstructed"],
        ["KC Atlas 3.9.3", "PDF + earlier package lineage", "Observation versus authority, uncertainty, stable IDs, replay and Android bridge discipline retained"],
        ["KC Two Hands 3.0 / SCLP / UGTS-GN", "Project PDFs", "Proposal/commit, finite packing, precision and compression boundaries retained"],
    ], [42*mm, 34*mm, 98*mm], small=True)]
    story += [p("No global mechanism catalog was renumbered in this repair. The source report and available packages contain overlapping historical catalog ranges; 4.1.1 records implementation capabilities and contracts without silently rewriting those catalogs.", styles["Bodyx"])]
    story += [PageBreak()]

    # Front end
    story += [p("3. Camera2, IMU and SLAM front end", styles["H1x"])]
    story += [p("The active front end remains focused on the requested scanner rather than replacing it with a storage demonstration. Camera2 acquires YUV_420_888 through an ImageReader with maxImages=2 and acquireLatestImage backpressure. Luma is resampled directly; no RGB conversion is required for feature work. Android orientation and linear-acceleration samples are timestamped against camera frames.", styles["Bodyx"])]
    story += [table([
        ["Stage", "Implemented behavior", "Bound / limitation"],
        ["Features", "Deterministic FAST-9 and fixed 256-bit BRIEF", "1,100 feature default; texture-dependent"],
        ["Matching", "Compact LSH candidates, mutual/ratio guards", "Repetitive texture can remain ambiguous"],
        ["Motion", "IMU-rotation-compensated epipolar direction", "Translation scale is relative before anchor"],
        ["Sparse geometry", "Positive-depth, ray-gap, parallax and reprojection-guarded triangulation", "No global bundle adjustment"],
        ["Semi-dense", "Adjacent-keyframe plane sweep and confidence-weighted voxel fusion", "Not learned dense depth; bounded work"],
        ["Loop closure", "Signature candidate recorded", "Commit deferred until geometric bundle adjustment exists"],
        ["Scale", "Known-distance camera displacement anchor", "Anchor sets scale; it does not remove drift"],
    ], [32*mm, 83*mm, 59*mm], small=True)]
    story += [p("The app keeps the higher-detail camera preview as a downstream aid because scanning accuracy matters. The Bayer path is optional and never replaces measured luma or map authority.", styles["Bodyx"])]
    story += [Preformatted("Camera/IMU -> measured frame evidence -> tracking proposal\n           -> eight-gate verification -> accepted keyframe/map mutation", styles["Codex"]), PageBreak()]

    # Seed
    story += [p("4. Spatial seed, stable identity and reconstructibility", styles["H1x"])]
    story += [p("Every session carries a 128-bit Seed128. It deterministically schedules bounded pixel samples, creates stable proposal/keyframe/session identifiers and recreates the synthetic fixture. The seed is stored in the KSEED header. The narrow C++ module implements the same SplitMix64 schedule and CRC32 behavior as the Java oracle.", styles["Bodyx"])]
    story += [callout("The seed does not reconstruct unstored photons. Real luma statistics, IMU summaries, accepted map evidence, uncertainty and event data remain measured records. The seed is not encryption.", styles["Calloutx"], LIGHT_GOLD, GOLD)]
    story += [Spacer(1, 4*mm), table([
        ["Object", "Identity rule", "Persistence"],
        ["Session", "Seed + session ID + start time", "KSEED header"],
        ["Proposal", "Seed-derived stable proposal ID", "Ledger decision"],
        ["Keyframe", "Seed-derived stable keyframe ID; integer sequence retained", "Keyframe chunk"],
        ["Voxel", "Signed 21-bit x/y/z cell encoded into exact Morton key", "Sorted key delta"],
        ["State", "SHA-256 chain over prior state, canonical proposal and committed effect", "Pre/post hashes"],
    ], [34*mm, 78*mm, 62*mm])]
    story += [p("Coordinates remain measurements, not identity. A stable node may accumulate new evidence or move after an accepted event without being silently replaced by coordinate coincidence.", styles["Bodyx"])]
    story += [PageBreak()]

    # Verifier
    story += [p("5. Proposal verification and ledger authority", styles["H1x"]), Image(str(verifier_img), width=174*mm, height=64*mm), p("Figure 3. The verifier evaluates all required gates in a fixed order.", styles["Captionx"])]
    story += [table([
        ["Gate", "Reject reason", "Purpose"],
        ["Identifier", "identifier_invalid", "Stable and schema-safe proposal/entity IDs"],
        ["Support", "outside_support", "Observation lies inside admitted local evidence support"],
        ["Compatibility", "incompatible", "Camera/state/mode/topology policy agrees"],
        ["Guard class", "guard_tangency / coincident / unknown", "Only predeclared classes commit"],
        ["Confidence", "confidence_below_floor", "Measured confidence clears policy"],
        ["Numeric margin", "numeric_error_exceeds_margin", "Finite numerical error stays within event margin"],
        ["Uncertainty", "uncertainty_exceeds_policy", "Uncertainty remains below application maximum"],
        ["Metric", "metric_unavailable", "Metric claims require an accepted metric anchor"],
    ], [32*mm, 54*mm, 88*mm], small=True)]
    story += [p("Rejected proposals retain their canonical proposal hash and reason but leave the authoritative state hash unchanged. Accepted proposals receive one ordered mutation, a sequence number and distinct pre/post hashes. Camera, IMU, synthetic and future model outputs use the same record shape.", styles["Bodyx"])]
    story += [PageBreak()]

    # KSEED
    story += [p("6. KSEED 4.1 stream format", styles["H1x"]), Image(str(kseed_img), width=174*mm, height=77*mm), p("Figure 4. Reconstructed 4.1 framing implemented by the Java writer and independent readers.", styles["Captionx"])]
    story += [p("The 128-byte header declares version, storage mode, seed, start time, analysis dimensions, requested frame rate, feature budget and two SHA-256 profile commitments. CRC32 covers header bytes 0-123.", styles["Bodyx"])]
    story += [p("Each 64-byte chunk header declares type, flags, sequence, record count, decoded/stored lengths, decoded/stored CRC32 values and schema ID in its first 32 bytes. The last 32 bytes carry the chained hash. Replay stops at the first framing, sequence, CRC, zlib, chain or summary failure.", styles["Bodyx"])]
    story += [Preformatted("H_i = SHA256(H_(i-1) || C_i[0:32] || stored_payload)\nH_-1 = SHA256(\"KSEED41-CHAIN\")", styles["Codex"])]
    story += [table([
        ["Chunk", "Records"],
        ["Frame evidence", "Delta frame/time, dimensions, luma/gradient summaries, feature/match/inlier counts, int16 quaternion and inertial hints"],
        ["Keyframes", "Delta ID/time, stable ID, quantized pose, signature"],
        ["Ledger", "Decision records, canonical proposal hash, pre/post hashes, reason and fields"],
        ["Voxels", "Unsigned-sorted Morton-key deltas, intensity, confidence and observation count"],
        ["Calibration", "Camera source, calibrated flag, scale state, metric scale, voxel size and native status"],
        ["Summary", "Frames/keyframes/events/voxels/raw bytes/stored bytes plus rejection, state and chunk counts"],
    ], [38*mm, 136*mm], small=True)]
    story += [PageBreak()]

    # Compression
    story += [p("7. Compression, efficiency and file-size discipline", styles["H1x"]), Image(str(compression_img), width=150*mm, height=84*mm), p("Figure 5. The release fixture ratio compares discarded raw luma bytes with retained evidence; it is not equal-information image compression.", styles["Captionx"])]
    ratio = fixture["raw_input_bytes"] / fixture["stored_bytes"]
    story += [table([
        ["Fixture metric", "Measured host result"],
        ["Analysis frames", f"{fixture['frames']} synthetic frames at {fixture['analysis_width']}x{fixture['analysis_height']}"],
        ["Raw luma input", f"{fixture['raw_input_bytes']:,} bytes"],
        ["Keyframes / events / voxels", f"{fixture['keyframes']} / {fixture['events']} / {fixture['voxels']}"],
        ["KSEED size", f"{fixture['stored_bytes']:,} bytes"],
        ["Nominal ratio", f"{ratio:.2f}x raw-input bytes / retained evidence bytes"],
        ["Fixture SHA-256", sha256(ROOT / "samples/atlas_seed_slam_411_fixture.kseed")],
        ["Final SHA chain", fixture["final_chain_sha256"]],
    ], [52*mm, 122*mm], small=True)]
    story += [p("Compression uses delta timestamps/frame indices, quantized inertial values, base-128 varints and Morton key deltas. Zlib level 1 is accepted only when compressed bytes plus a 16-byte margin are smaller than raw payload bytes, so compression never expands a chunk merely to satisfy a policy label.", styles["Bodyx"])]
    story += [callout("A finite key, sign, seed or compact state word is not complete geometry. File-size gains remain conditional on the explicit evidence and reconstruction contract.", styles["Calloutx"], LIGHT_GOLD, GOLD), PageBreak()]

    # Native/build
    story += [p("8. Android and native implementation", styles["H1x"])]
    story += [table([
        ["Module", "Role", "Authority"],
        ["app", "Camera2, ImageReader, IMU, UI, thermal tiers, document export, synthetic source", "Adapter and presentation"],
        ["core", "Features, matching, SLAM, proposals, verifier, ledger, KSEED writer/reader", "Behavioral oracle and map authority"],
        ["seednative", "arm64-v8a JNI bridge", "Optional accelerator; no map mutation"],
        ["native/core", "Portable SplitMix64 schedule and CRC32", "Host-tested native oracle"],
        ["tools", "Build, bootstrap, source checks, KSEED inspection, PLY conversion, packaging", "Independent verification"],
    ], [28*mm, 91*mm, 55*mm])]
    story += [p("The Gradle handoff keeps the repaired verified bootstrap. It downloads pinned Gradle 8.13, verifies the required distribution SHA-256 and rejects unsafe ZIP paths before execution. The Android source pins SDK 36, AGP 8.13.2, NDK 29.0.14206865, CMake 3.22.1, Java 17 and arm64-v8a for the native module.", styles["Bodyx"])]
    story += [Preformatted("./gradlew --bootstrap-self-test\n./gradlew :app:clean :app:assembleRelease\nadb install -r app/build/outputs/apk/release/app-release.apk", styles["Codex"])]
    story += [p(f"Current source counts: {len(java_files)} Java files, {len(cpp_files)} C++ files and approximately {source_lines:,} Java/C++ source lines. The package contains no generated Gradle, build, .cxx, IDE or Python cache tree.", styles["Bodyx"])]
    story += [PageBreak()]

    # Synthetic/Bayer
    story += [p("9. Synthetic isolation and Bayer projection", styles["H1x"])]
    story += [p("If camera permission or startup fails, the user can run a deterministic 300-frame maximum fixture. It has a fixed seed, generated luma, bounded camera model and synthetic motion. The session flag is set, every proposal carries tag bit 31 and the on-screen banner says that the data is DEMO and not real-world evidence.", styles["Bodyx"])]
    story += [table([
        ["Control", "Implemented guarantee"],
        ["Session seed", "Fixed deterministic demo seed; exported in KSEED header"],
        ["Proposal tag", "Bit 31 in SpatialProposal tags"],
        ["Chunk flag", "Synthetic fixture flag in KSEED chunks"],
        ["UI", "Visible DEMO banner"],
        ["Export", "Synthetic state flag in final summary"],
        ["Boundary", "Never mixed silently with camera evidence"],
    ], [46*mm, 128*mm])]
    story += [p("Bayer4Level implements an exact 8x8 ordered threshold and four output levels 0, 85, 170 and 255. It is a downstream projection utility only. The active scanning view remains the camera preview plus bounded feature/map overlay because the requested application prioritizes tracking accuracy.", styles["Bodyx"])]
    story += [callout("Neither Bayer display nor synthetic data can commit authority outside the same proposal verifier.", styles["Calloutx"], LIGHT_TEAL, TEAL), PageBreak()]

    # Validation
    story += [p("10. Validation completed", styles["H1x"]), Image(str(validation_img), width=168*mm, height=88*mm), p("Figure 6. All completed host and source gates passed.", styles["Captionx"])]
    story += [table([
        ["Gate", "Result", "Evidence"],
        ["Java core", "PASS", "8,465 retained assertions plus 24,369 seed/KSEED assertions"],
        ["Portable C++", "PASS", "10,004 schedule/CRC assertions"],
        ["Android/JNI bridge stub", "PASS", "Java 17 shell compilation against Android mock surface"],
        ["Gradle bootstrap", "PASS", "Self-test plus local fake-distribution hash/extract/execute test"],
        ["Source contract", "PASS", "Permissions, dependencies, Camera2, verifier, KSEED, native pins and cache exclusions"],
        ["KSEED inspector", "PASS", "Independent Python framing, CRC, zlib, chain and summary verification"],
        ["Legacy reader", "PASS", "Previous .ugtsscan sample remains inspectable"],
        ["Python/JSON", "PASS", "All tool scripts compile; all JSON parses"],
    ], [40*mm, 24*mm, 110*mm], small=True)]
    story += [p("A corrupted KSEED byte is rejected by host tests. Deterministic encoding produces identical bytes from the same SessionData. The checked-in fixture's summary stored_bytes equals its actual file length.", styles["Bodyx"])]
    story += [PageBreak()]

    # Device gates
    story += [p("11. Android and physical-device promotion gates", styles["H1x"]), Image(str(gates_img), width=174*mm, height=71*mm), p("Figure 7. Completed source evidence remains separate from unexecuted phone claims.", styles["Captionx"])]
    story += [p("The packaging environment did not contain Android SDK Platform 36 plus NDK 29 and did not have a physical POCO X7 Pro connected. Therefore this release does not contain a newly built APK and does not assert camera startup, sustained FPS, memory, thermal, battery, metric error or route correctness.", styles["Bodyx"])]
    story += [table([
        ["Mandatory device record", "Required observation"],
        ["Identity", "Exact phone model, 12 GB edition, OS/security build, ABI, GPU and display mode"],
        ["Capture", "Camera ID, actual YUV dimensions, actual cadence, intrinsics source and dropped frames"],
        ["Latency", "p50/p95/p99 analysis and KSEED write latency"],
        ["Resources", "Peak Java/native memory, bytes/minute, 5/15/30 minute thermal and battery traces"],
        ["Integrity", "Export/pull, independent KSEED inspection and deterministic replay evidence"],
        ["Accuracy", "Known-distance controls, drift, false/missed events and equal-error calibrated baseline"],
    ], [48*mm, 126*mm])]
    story += [PageBreak()]

    # Boundaries
    story += [p("12. Accuracy, security and evidence boundaries", styles["H1x"])]
    story += [table([
        ["Topic", "What 4.1.1 establishes", "What it does not establish"],
        ["SLAM", "Sparse/semi-dense relative visual-inertial reference path", "Metric VIO, learned dense depth, bundle adjustment or certified topology recognition"],
        ["Metric scale", "Known-distance anchor transaction", "Drift removal or global calibration"],
        ["Integrity", "Changed bytes, chunk order and chain failures are detectable", "Operator identity, truthful place/time, uncompromised hardware or legal custody"],
        ["Seed", "Deterministic schedules, stable IDs and fixtures", "Encryption or reconstruction of unstored photons"],
        ["Compression", "Measured retained-evidence byte reduction", "Equal-information image compression or universal phone ratio"],
        ["Native", "Portable C++ core compiles and passes host tests", "Android ABI load or performance until SDK/device build"],
        ["Safety", "Reason-coded observations and explicit unknown states", "Medical, structural, evacuation or legal certification"],
    ], [29*mm, 72*mm, 73*mm], small=True)]
    story += [callout("Stop or simplify the system whenever numeric error or uncertainty exceeds the event margin, synthetic and real evidence cannot be separated, loop closure would require an unimplemented optimizer, KSEED integrity fails, or a conventional calibrated scanner is more accurate or efficient at equal error.", styles["Calloutx"], LIGHT_RED, RED)]
    story += [PageBreak()]

    # Package map
    story += [p("13. Package map and reproducibility", styles["H1x"])]
    story += [table([
        ["Path", "Contents"],
        ["app/", "Camera2/IMU Android shell, UI, thermal control, synthetic demo, KSEED document export"],
        ["core/", "SLAM, verifier, ledger, seed schedule, Bayer utility, KSEED writer/reader and legacy codec"],
        ["seednative/", "Android arm64-v8a library and JNI bridge"],
        ["native/", "Portable C++ seed/CRC implementation and host tests"],
        ["contracts/", "Frame-observation and spatial-proposal schemas"],
        ["spec/", "KSEED binary contract, authority contract and JSON profile"],
        ["samples/", "Deterministic KSEED fixture, inspection summary and retained legacy sample"],
        ["tools/", "Build, bootstrap, host tests, source checks, KSEED inspector, PLY conversion, manifest and release packaging"],
        ["validation/", "Machine-readable validation results and independent KSEED inspection"],
        ["provenance/ + sources/", "Source lineage, substrate alignment and merge boundary"],
        ["report/", "This PDF and reproducible report generator"],
        ["checksums/ + manifest/", "Release SHA-256 inventory and package map"],
    ], [38*mm, 136*mm], small=True)]
    story += [p(f"At report-generation time the source tree contains {file_count} files before final checksums/manifest regeneration. Final release inventory and content-root checks are produced after the PDF is inserted into the package.", styles["Bodyx"])]
    story += [Preformatted("./tools/generate_kseed_fixture.sh\n./tools/run_all_validation.sh\npython3 tools/generate_manifest.py\npython3 tools/verify_release.py <release.zip>", styles["Codex"])]
    story += [PageBreak()]

    # Closing
    story += [p("14. Final release definition", styles["H1x"])]
    story += [p("UGTS-KC 4.1.1 Atlas Spatial Seed SLAM Fusion is a repaired, compact Android source handoff in which Camera2/IMU observations feed a bounded monocular SLAM front end; stable seed-derived identifiers and measured frame evidence feed an ordered proposal verifier; only accepted proposals mutate keyframe, voxel or metric state; every decision carries reason and hash lineage; and KSEED stores a streamable seed-plus-evidence record with CRC32, conditional zlib and a SHA-256 chain.", styles["Bodyx"])]
    story += [callout("RELEASE STATUS. Complete source, host validation, independent KSEED fixture and technical report are delivered. Android assemble, production signing, physical POCO installation and device accuracy/thermal measurements remain the next promotion stage.", styles["Calloutx"], LIGHT_TEAL, TEAL), Spacer(1, 6*mm)]
    story += [table([
        ["Identifier", "Value"],
        ["Version", "4.1.1"],
        ["Codename", "Atlas Spatial Seed SLAM Fusion"],
        ["Target", "POCO X7 Pro 12 GB, arm64-v8a"],
        ["Default storage", "KSEED 4.1"],
        ["Application ID", "org.ugts.atlas.slam.pocox7pro"],
        ["Build pins", "SDK 36, AGP 8.13.2, Gradle 8.13, NDK 29.0.14206865, CMake 3.22.1, Java 17"],
        ["Host validation", validation["status"]],
        ["Android APK", "Not produced in this environment"],
        ["Physical device", "Not tested in this environment"],
        ["Merge claim", provenance["merge_claim"]],
    ], [48*mm, 126*mm], small=True)]
    story += [Spacer(1, 8*mm), p("Prepared for the Tom Klootwijk project context. Requester-supplied attribution is not independent legal proof of identity, authorship, ownership, priority, patentability or chain of title.", styles["Smallx"])]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUTPUT)


if __name__ == "__main__":
    main()
