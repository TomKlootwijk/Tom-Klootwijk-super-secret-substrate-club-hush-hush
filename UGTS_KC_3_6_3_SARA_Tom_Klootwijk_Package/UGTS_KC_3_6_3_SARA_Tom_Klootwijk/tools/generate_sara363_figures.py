#!/usr/bin/env python3
from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "report" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

NAVY = "#0D2B3A"
TEAL = "#16979B"
GOLD = "#D4A21B"
CORAL = "#CF6A5A"
PURPLE = "#6B5D96"
GREEN = "#3F8D6A"
LIGHT = "#EDF6F6"
LIGHTPURPLE = "#F2EFF8"
LIGHTGOLD = "#FBF5E4"
GREY = "#66737B"
REDLIGHT = "#FAECE9"


def save(fig, name):
    fig.savefig(OUT / name, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def box(ax, xy, width, height, text, face=LIGHT, edge=TEAL, fontsize=9, weight="normal"):
    patch = FancyBboxPatch(
        xy,
        width,
        height,
        boxstyle="round,pad=0.02,rounding_size=0.03",
        linewidth=1.4,
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
        color=NAVY,
        fontweight=weight,
        wrap=True,
    )
    return patch


def arrow(ax, start, end, color=GREY, lw=1.5):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=12, linewidth=lw, color=color))


# 1. Architecture
fig, ax = plt.subplots(figsize=(14, 5.2))
ax.set_xlim(0, 14)
ax.set_ylim(0, 5.2)
ax.axis("off")
ax.text(0.1, 4.85, "UGTS-KC 3.6.3 SARA: public deterministic wallet pipeline", fontsize=17, fontweight="bold", color=NAVY)
labels = [
    ("Entropy\nENT", LIGHTGOLD, GOLD),
    ("Checksum\nhinge", LIGHTGOLD, GOLD),
    ("11-bit\nword cells", LIGHTPURPLE, PURPLE),
    ("Mnemonic\nNFKD", LIGHTPURPLE, PURPLE),
    ("PBKDF2 seed\ntransient", REDLIGHT, CORAL),
    ("BIP32\nkey tree", LIGHT, TEAL),
    ("BIP84\nroute", LIGHT, TEAL),
    ("Public key\nHASH160", LIGHT, TEAL),
    ("Script +\nBech32", LIGHTGOLD, GOLD),
    ("Public-only\ncertificate", "#EAF5EF", GREEN),
]
xs = [0.2, 1.55, 2.9, 4.25, 5.6, 7.0, 8.35, 9.7, 11.05, 12.4]
for i, ((label, face, edge), x) in enumerate(zip(labels, xs)):
    box(ax, (x, 2.4), 1.15, 1.15, label, face, edge, 8.5, "bold" if i in {0, 4, 9} else "normal")
    if i < len(labels) - 1:
        arrow(ax, (x + 1.15, 2.98), (xs[i + 1], 2.98))
box(ax, (2.55, 0.18), 5.35, 0.78, "AUTHORIZED AUDIT\npublic vectors | self-owned | watch-only | test networks | metrics", "#EAF5EF", GREEN, 7.2, "bold")
arrow(ax, (5.9, 0.96), (6.95, 2.38), GREEN)
box(ax, (8.25, 0.18), 5.4, 0.78, "REJECTED\nthird-party secrets | enumeration | signing | broadcast | transfer", REDLIGHT, CORAL, 7.2, "bold")
arrow(ax, (10.95, 0.96), (12.9, 2.38), CORAL)
ax.text(0.2, 1.45, "Secret values are transient and never serialized; only public commitments and reason codes cross the certificate boundary.", fontsize=10.2, color=GREY)
save(fig, "sara363_architecture.png")

# 2. Word cells
fig, ax = plt.subplots(figsize=(13, 4.6))
ax.set_xlim(0, 13)
ax.set_ylim(0, 4.6)
ax.axis("off")
ax.text(0.1, 4.25, "BIP39 as an ordered 1D cell complex", fontsize=17, fontweight="bold", color=NAVY)
ax.text(0.1, 3.75, "128 entropy bits + 4 checksum bits = 132 bits = 12 cells x 11 bits", fontsize=11, color=GREY)
for i in range(12):
    x = 0.35 + i * 1.03
    face = LIGHTPURPLE if i < 11 else LIGHTGOLD
    edge = PURPLE if i < 11 else GOLD
    Rectangle((x, 2.0), 0.92, 1.05, linewidth=1.3, edgecolor=edge, facecolor=face)
    ax.add_patch(Rectangle((x, 2.0), 0.92, 1.05, linewidth=1.3, edgecolor=edge, facecolor=face))
    ax.text(x + 0.46, 2.67, f"cell {i}", ha="center", va="center", fontsize=8, color=NAVY, fontweight="bold")
    ax.text(x + 0.46, 2.32, "11 bits", ha="center", va="center", fontsize=8, color=GREY)
    if i < 11:
        arrow(ax, (x + 0.92, 2.53), (x + 1.02, 2.53), PURPLE, 1.0)
ax.text(11.7, 1.72, "last cell contains\nentropy tail + CS", ha="center", fontsize=9, color=GOLD, fontweight="bold")
box(ax, (0.5, 0.45), 5.2, 0.75, "word index i in [0,2047] -> committed wordlist entry L[i]", LIGHT, TEAL, 10)
box(ax, (6.15, 0.45), 6.0, 0.75, "checksum guard passes only when observed CS = prefix_CS(SHA256(ENT))", LIGHTGOLD, GOLD, 10)
save(fig, "sara363_word_cells.png")

# 3. HD tree
fig, ax = plt.subplots(figsize=(12, 6.2))
ax.set_xlim(0, 12)
ax.set_ylim(0, 6.2)
ax.axis("off")
ax.text(0.2, 5.85, "BIP32 derivation topology: normal and hardened edges are different", fontsize=17, fontweight="bold", color=NAVY)
box(ax, (5.0, 4.7), 2.0, 0.75, "master node m\n(k, chain code)", LIGHT, TEAL, 10, "bold")
box(ax, (1.0, 3.2), 2.4, 0.75, "normal child i < 2^31\npublic child possible from xpub", LIGHTPURPLE, PURPLE, 9)
box(ax, (4.8, 3.2), 2.4, 0.75, "hardened child i'\nrequires parent private material", LIGHTGOLD, GOLD, 9)
box(ax, (8.6, 3.2), 2.4, 0.75, "sibling branch\nseparate chain code", LIGHT, TEAL, 9)
arrow(ax, (5.65, 4.7), (2.2, 3.95), PURPLE)
arrow(ax, (6.0, 4.7), (6.0, 3.95), GOLD)
arrow(ax, (6.35, 4.7), (9.8, 3.95), TEAL)
box(ax, (4.25, 1.75), 3.5, 0.75, "BIP84 route\nm / 84' / 0' / 0' / 0 / 0", "#EAF5EF", GREEN, 10, "bold")
arrow(ax, (6.0, 3.2), (6.0, 2.5), GREEN)
box(ax, (4.25, 0.45), 3.5, 0.75, "leaf -> public key -> HASH160 -> P2WPKH address", LIGHT, TEAL, 10)
arrow(ax, (6.0, 1.75), (6.0, 1.2), TEAL)
ax.text(0.8, 0.55, "A 32-bit parent fingerprint is a routing hint, not collision-free identity.", fontsize=10, color=GREY)
save(fig, "sara363_hd_tree.png")

# 4. Address anatomy
fig, ax = plt.subplots(figsize=(13, 4.9))
ax.set_xlim(0, 13)
ax.set_ylim(0, 4.9)
ax.axis("off")
ax.text(0.15, 4.55, "Public address anatomy and exact decode fixture", fontsize=17, fontweight="bold", color=NAVY)
address = "bc1q7ydrtdn8z62xhslqyqtyt38mm4e2c4h3mxjkug"
ax.text(0.3, 3.65, address, fontsize=16, family="monospace", color=NAVY)
segments = [
    (0.35, 2.45, 1.05, "bc", "network HRP", LIGHT, TEAL),
    (1.55, 2.45, 0.65, "1", "separator", LIGHTPURPLE, PURPLE),
    (2.35, 2.45, 0.65, "q", "v0", LIGHTGOLD, GOLD),
    (3.15, 2.45, 5.7, "7ydr...c4h3", "5-bit data -> 20-byte witness program", LIGHT, TEAL),
    (9.05, 2.45, 2.35, "mxjkug", "6-char checksum", LIGHTGOLD, GOLD),
]
for x, y, w, text, note, face, edge in segments:
    box(ax, (x, y), w, 0.85, text, face, edge, 10, "bold")
    ax.text(x + w/2, y - 0.18, note, ha="center", va="top", fontsize=8.5, color=GREY)
box(ax, (0.7, 0.45), 5.4, 0.8, "witness program: f11a35b66716946bc3e0201645c4fbdd72ac56f1", LIGHT, TEAL, 9)
box(ax, (6.45, 0.45), 5.4, 0.8, "scriptPubKey: 0014f11a35b66716946bc3e0201645c4fbdd72ac56f1", LIGHTPURPLE, PURPLE, 9)
ax.text(0.7, 1.55, "Valid checksum and P2WPKH classification are public structural facts; they do not reveal a seed or private key.", fontsize=10, color=CORAL, fontweight="bold")
save(fig, "sara363_address_anatomy.png")

# 5. Security boundary
fig, ax = plt.subplots(figsize=(12, 5.8))
ax.set_xlim(0, 12)
ax.set_ylim(0, 5.8)
ax.axis("off")
ax.text(0.2, 5.45, "Authorized defensive audit boundary", fontsize=17, fontweight="bold", color=NAVY)
box(ax, (0.45, 0.65), 5.1, 4.1, "", "#EAF5EF", GREEN)
box(ax, (6.45, 0.65), 5.1, 4.1, "", REDLIGHT, CORAL)
ax.text(3.0, 4.35, "ALLOWED", ha="center", fontsize=15, color=GREEN, fontweight="bold")
ax.text(9.0, 4.35, "REJECTED", ha="center", fontsize=15, color=CORAL, fontweight="bold")
allowed = ["Official BIP test vectors", "Self-owned known mnemonic/seed", "Public address or descriptor decode", "Regtest / signet / testnet", "Checksum and search-space metrics"]
rejected = ["Third-party mainnet key search", "Mnemonic permutation enumeration", "Passphrase spraying / private-key scan", "Transaction signing or broadcast", "Funds transfer or balance targeting"]
for i, text in enumerate(allowed):
    ax.text(0.85, 3.65 - i*0.62, "✓  " + text, fontsize=11, color=NAVY)
for i, text in enumerate(rejected):
    ax.text(6.85, 3.65 - i*0.62, "✕  " + text, fontsize=11, color=NAVY)
ax.text(0.5, 0.2, "The reference runtime has no network client, candidate generator, signing API or transaction path.", fontsize=10, color=GREY)
save(fig, "sara363_security_boundary.png")

# 6. Search metrics
fig, ax = plt.subplots(figsize=(11, 5.6))
labels = ["toy 20-bit\n@ 10^6/s", "BIP39 128-bit\n@ 10^15/s", "P2WPKH 160-bit\n@ 10^15/s", "secp256k1 256-bit\n@ 10^15/s"]
values = [0.524288 / 31557600.0, (2**127)/(1e15*31557600.0), (2**159)/(1e15*31557600.0), (2**255)/(1e15*31557600.0)]
ax.bar(range(len(values)), values, edgecolor=NAVY, linewidth=1.0)
ax.set_yscale("log")
ax.set_xticks(range(len(values)), labels)
ax.set_ylabel("Expected years (log scale)")
ax.set_title("Uniform expected-search time: estimator only, no candidate generation", color=NAVY, fontweight="bold")
ax.grid(axis="y", alpha=0.25)
for i, value in enumerate(values):
    text = f"{value:.2e} y" if value >= 0.01 else f"{value*31557600:.3f} s"
    ax.text(i, value*1.6, text, ha="center", fontsize=9, color=NAVY)
ax.text(0.02, 0.96, "Optimistic rates favor the attacker; real PBKDF2 and EC work is slower.", transform=ax.transAxes, fontsize=8.5, color=GREY, va="top")
save(fig, "sara363_search_metrics.png")

# 7. Handoff
fig, ax = plt.subplots(figsize=(13, 3.8))
ax.set_xlim(0, 13)
ax.set_ylim(0, 3.8)
ax.axis("off")
ax.text(0.1, 3.45, "SARA certification returns to the canonical UGTS event calculus", fontsize=17, fontweight="bold", color=NAVY)
labels = ["SARA public\ncertificate", "support", "compatibility", "guard", "verified\nevent", "transition", "lineage"]
colors = [("#EAF5EF", GREEN), (LIGHT, TEAL), (LIGHTPURPLE, PURPLE), (LIGHTGOLD, GOLD), ("#EAF5EF", GREEN), (LIGHT, TEAL), (LIGHTPURPLE, PURPLE)]
xs = [0.3, 2.25, 3.9, 5.55, 7.2, 9.15, 10.95]
widths = [1.55, 1.25, 1.35, 1.15, 1.45, 1.35, 1.35]
for i, label in enumerate(labels):
    face, edge = colors[i]
    box(ax, (xs[i], 1.45), widths[i], 0.85, label, face, edge, 9.5, "bold" if i in {0,4} else "normal")
    if i < len(labels)-1:
        arrow(ax, (xs[i]+widths[i], 1.88), (xs[i+1], 1.88), GREY)
ax.text(0.35, 0.65, "A valid event requires authorized scope, valid schema/checksum/derivation and zero secret egress.", fontsize=10.5, color=GREY)
save(fig, "sara363_ugts_handoff.png")

print(f"wrote figures to {OUT}")
