#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ugts36.sclp362 import BoundedBinaryGrammar, LogPolarChart, compile_motion_polyline  # noqa: E402

OUT = ROOT / "report/figures"
OUT.mkdir(parents=True, exist_ok=True)


def save(fig, name: str) -> None:
    fig.savefig(OUT / name, dpi=220, bbox_inches="tight")
    plt.close(fig)


def architecture() -> None:
    fig, ax = plt.subplots(figsize=(12, 5.4))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 5.4)
    ax.axis("off")
    rows = [
        (4.25, "AUTHORITATIVE DEFINITIONS", [
            "Finite cone + spheres", "Log-polar metric", "Time / phase / winding", "Topology + hinge", "Grammar + key schema"
        ]),
        (2.55, "REFERENTIAL EVALUATION", [
            "Support", "Relation + sweep bound", "Compatibility / wrap", "Guard interval", "Branch + grammar"
        ]),
        (0.85, "UGTS HANDOFF", [
            "Verified event", "Transition patch", "Lineage / novelty", "Optional downstream adapters"
        ]),
    ]
    for y, label, boxes in rows:
        ax.text(0.7, y + 1.02, label, fontsize=12, weight="bold")
        width = 10.9 / len(boxes)
        for i, text in enumerate(boxes):
            x = 0.7 + i * width
            patch = FancyBboxPatch((x, y), width - 0.22, 0.85, boxstyle="round,pad=0.08", linewidth=1.3, facecolor="white")
            ax.add_patch(patch)
            ax.text(x + (width - 0.22) / 2, y + 0.425, text, ha="center", va="center", fontsize=9.5, wrap=True)
            if i < len(boxes) - 1:
                ax.add_patch(FancyArrowPatch((x + width - 0.2, y + 0.425), (x + width + 0.02, y + 0.425), arrowstyle="->", mutation_scale=12))
    ax.add_patch(FancyArrowPatch((6, 4.18), (6, 3.45), arrowstyle="-|>", mutation_scale=18, linewidth=1.6))
    ax.add_patch(FancyArrowPatch((6, 2.48), (6, 1.72), arrowstyle="-|>", mutation_scale=18, linewidth=1.6))
    ax.text(6, 0.15, "No rasterization, ray marching or display authority in the 3.6.2 core", ha="center", fontsize=11, weight="bold")
    save(fig, "sclp362_architecture.png")


def cone_geometry() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 5.6))
    T = 2.0
    alpha = math.radians(30)
    h = T * math.cos(alpha)
    R = T * math.sin(alpha)
    tri = Polygon([(-R, h), (0, 0), (R, h)], closed=True, alpha=0.18)
    ax.add_patch(tri)
    ax.plot([-R, 0, R, -R], [h, 0, h, h], linewidth=2)
    ax.plot([0, 0], [0, h], linestyle="--", linewidth=1.5)
    ax.text(0.07, h / 2, r"$h=T\cos\alpha$", fontsize=12)
    ax.text(R / 2, h + 0.08, r"$R=T\sin\alpha$", fontsize=12, ha="center")
    ax.text(R * 0.55, h * 0.45, r"slant $T$", fontsize=12, rotation=60)
    ax.annotate(r"half-angle $\alpha$", xy=(0.23, 0.4), xytext=(0.6, 0.22), arrowprops=dict(arrowstyle="->"), fontsize=11)
    q, z = 0.65, 0.9
    ax.scatter([q], [z], s=60)
    ax.text(q + 0.06, z + 0.03, r"query $(q,z)$", fontsize=11)
    ax.set_aspect("equal")
    ax.set_xlabel("signed meridian radius")
    ax.set_ylabel("axial coordinate")
    ax.set_title("Finite cone: exact SDF by meridian-triangle distance")
    ax.set_xlim(-1.25, 1.35)
    ax.set_ylim(-0.2, 2.0)
    ax.grid(True, alpha=0.25)
    save(fig, "sclp362_cone_geometry.png")


def logpolar_metric() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 6.4))
    rhos = [-3, -2.4, -1.8, -1.2, -0.6, 0]
    thetas = [i * math.pi / 6 for i in range(12)]
    for rho in rhos:
        r = math.exp(rho)
        circle = plt.Circle((0, 0), r, fill=False, linewidth=1.1)
        ax.add_patch(circle)
        ax.text(r / math.sqrt(2), r / math.sqrt(2), f"rho={rho:g}", fontsize=8)
    for theta in thetas:
        ax.plot([0, math.cos(theta)], [0, math.sin(theta)], linewidth=0.8)
    ax.add_patch(FancyArrowPatch((0.28, 0), (0.52, 0), arrowstyle="<->", mutation_scale=14))
    ax.text(0.4, 0.035, r"$\Delta r=r(e^{\Delta\rho}-1)$", ha="center", fontsize=10)
    ax.text(-0.98, -1.15, r"$ds^2=r^2(d\rho^2+d\theta^2)$" + "\n" + r"$J=rR(\theta)$", fontsize=12)
    ax.set_aspect("equal")
    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-1.2, 1.2)
    ax.set_title("Uniform log-radius steps become multiplicative real-radius shells")
    ax.axis("off")
    save(fig, "sclp362_logpolar_metric.png")


def topology_profiles() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6))
    titles = ["Source half-turn state bundle", "Reflective Klein radial gluing"]
    formulas = [r"$\theta\mapsto\theta+\pi,\;\phi\mapsto-\phi$", r"$\theta\mapsto\pi-\theta,\;\phi\mapsto-\phi$"]
    notes = ["base map orientation-preserving\ninternal orientation flag flips", "angular reflection reverses orientation\nbase quotient is non-orientable"]
    for ax, title, formula, note in zip(axes, titles, formulas, notes):
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 5)
        ax.axis("off")
        ax.add_patch(Rectangle((1, 1), 8, 3, fill=False, linewidth=1.8))
        ax.text(5, 4.45, title, ha="center", fontsize=12, weight="bold")
        ax.text(5, 2.55, formula, ha="center", fontsize=16)
        ax.text(5, 0.35, note, ha="center", fontsize=10)
        ax.add_patch(FancyArrowPatch((8.9, 3.4), (1.1, 1.6), connectionstyle="arc3,rad=0.35", arrowstyle="-|>", mutation_scale=16, linewidth=1.5))
        ax.text(8.15, 3.75, r"$\rho_{max}$", fontsize=10)
        ax.text(1.05, 1.2, r"$\rho_{min}$", fontsize=10)
    save(fig, "sclp362_topology_profiles.png")


def key_layouts() -> None:
    fields = [
        ("rho", 20), ("theta", 18), ("X", 14), ("phi", 12)
    ]
    fig, axes = plt.subplots(2, 1, figsize=(12, 5.6), gridspec_kw={"height_ratios": [1, 1.45]})
    ax = axes[0]
    ax.set_xlim(0, 64)
    ax.set_ylim(0, 1)
    ax.axis("off")
    start = 0
    for name, width in fields:
        ax.add_patch(Rectangle((start, 0.2), width, 0.55, fill=False, linewidth=1.5))
        ax.text(start + width / 2, 0.48, f"{name}\n{width} bits", ha="center", va="center", fontsize=10)
        start += width
    ax.text(0, 0.88, "Contiguous field layout: source bit-range table", fontsize=12, weight="bold")
    ax.text(64, 0.02, "bit 0", ha="right", fontsize=9)
    ax.text(0, 0.02, "bit 63", fontsize=9)

    ax = axes[1]
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 1.6)
    ax.axis("off")
    schedule = [("rho", 19), ("theta", 17), ("X", 13), ("phi", 11), ("rho", 18), ("theta", 16), ("X", 12), ("phi", 10), ("rho", 17), ("theta", 15), ("X", 11), ("phi", 9), ("rho", 16), ("theta", 14), ("X", 10), ("phi", 8)]
    for i, (name, bit) in enumerate(schedule):
        ax.add_patch(Rectangle((i + 0.05, 0.55), 0.9, 0.55, fill=False, linewidth=1.2))
        ax.text(i + 0.5, 0.82, f"{name}{bit}", ha="center", va="center", fontsize=8, rotation=90 if name == "theta" else 0)
    ax.text(0, 1.35, "Morton layout: first 16 output bits of the MSB round-robin schedule", fontsize=12, weight="bold")
    ax.text(8, 0.15, "Two distinct encodings; both have tested pack/unpack round trips", ha="center", fontsize=10)
    save(fig, "sclp362_key_layouts.png")


def grammar_growth() -> None:
    chart = LogPolarChart()
    grammar = BoundedBinaryGrammar(1.0, math.radians(25), 0.001, max_depth=6, max_symbols=100000)
    expansion = grammar.expand([0, 1, 0, 1], depth=4, rho=-1.2, chirality=1, chart=chart)
    points = compile_motion_polyline(expansion)
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.6))
    depths = list(range(0, 7))
    axes[0].plot(depths, [2**d for d in depths], marker="o")
    axes[0].set_xlabel("grammar depth")
    axes[0].set_ylabel("forward symbols")
    axes[0].set_title("Explicit exponential growth, bounded by policy")
    axes[0].grid(True, alpha=0.3)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    axes[1].plot(xs, ys, linewidth=1.2)
    axes[1].scatter([xs[0], xs[-1]], [ys[0], ys[-1]], s=30)
    axes[1].set_aspect("equal", adjustable="datalim")
    axes[1].set_title("Compiled apex path (geometry only, not rendering)")
    axes[1].axis("off")
    save(fig, "sclp362_grammar_growth.png")


def compression_audit() -> None:
    metrics = json.loads((ROOT / "data/sclp362_source_width_metrics.json").read_text())
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    names = ["coordinate\nkey", "SDF sign\nonly", "kinematic\nstate word"]
    ratios = [row["ratio"] for row in metrics]
    bars = ax.bar(names, ratios)
    ax.set_ylabel("nominal bit-width ratio")
    ax.set_title("Source width ratios: mathematically exact widths, semantically non-equivalent records")
    ax.grid(axis="y", alpha=0.25)
    for bar, value in zip(bars, ratios):
        ax.text(bar.get_x() + bar.get_width()/2, value + 0.8, f"{value:.3g}x", ha="center")
    ax.text(1.0, 5.0, "Not promoted to compression metrics\nwithout reconstruction/error equivalence", ha="center", fontsize=10)
    save(fig, "sclp362_compression_audit.png")


def handoff() -> None:
    fig, ax = plt.subplots(figsize=(11.5, 2.5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 2.5)
    ax.axis("off")
    labels = ["support", "compatibility", "guard interval", "verified event", "transition", "lineage"]
    for i, label in enumerate(labels):
        x = 0.3 + i * 1.9
        ax.add_patch(FancyBboxPatch((x, 0.8), 1.55, 0.75, boxstyle="round,pad=0.08", fill=False, linewidth=1.3))
        ax.text(x + 0.775, 1.175, label, ha="center", va="center", fontsize=10)
        if i < len(labels)-1:
            ax.add_patch(FancyArrowPatch((x+1.57, 1.175), (x+1.85, 1.175), arrowstyle="->", mutation_scale=13))
    ax.text(6, 2.12, "SCLP 3.6.2 returns authority to the canonical UGTS query/event sequence", ha="center", fontsize=12, weight="bold")
    ax.text(6, 0.25, "One-bit fields remain route/predicate metadata; continuous residual, uncertainty and identity remain separate", ha="center", fontsize=9.5)
    save(fig, "sclp362_event_handoff.png")


if __name__ == "__main__":
    architecture()
    cone_geometry()
    logpolar_metric()
    topology_profiles()
    key_layouts()
    grammar_growth()
    compression_audit()
    handoff()
    print("generated SCLP 3.6.2 figures")
