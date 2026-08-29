#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ugts5.glyph_sdf import glyph_sdf  # noqa: E402
from ugts5.canonical import load_json  # noqa: E402

FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)

NAVY = "#0b1833"
NAVY2 = "#13264a"
TEAL = "#25b9b2"
CYAN = "#5fd6e6"
BLUE = "#6e8df7"
PURPLE = "#9a78d8"
GOLD = "#e0b331"
CORAL = "#e27266"
GREEN = "#65c68b"
WHITE = "#f7f9fc"
MUTED = "#b8c4d8"
DARK = "#172033"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.titlesize": 15,
})


def box(ax, xy, wh, title, body="", fc=NAVY2, ec=CYAN, title_color=WHITE, body_color=MUTED, lw=2, radius=0.025, align="center", title_size=13, body_size=9.5):
    x, y = xy
    w, h = wh
    patch = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.012,rounding_size={radius}", facecolor=fc, edgecolor=ec, linewidth=lw)
    ax.add_patch(patch)
    ha = "center" if align == "center" else "left"
    tx = x + w/2 if align == "center" else x + 0.03*w
    ax.text(tx, y+h*0.64, title, ha=ha, va="center", color=title_color, fontsize=title_size, fontweight="bold", wrap=True)
    if body:
        ax.text(tx, y+h*0.28, body, ha=ha, va="center", color=body_color, fontsize=body_size, wrap=True, linespacing=1.25)
    return patch


def arrow(ax, a, b, color=CYAN, lw=2.0, style="-|>", mutation=16, connectionstyle="arc3"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=mutation, linewidth=lw, color=color, connectionstyle=connectionstyle))


def base_canvas(title, subtitle=None, figsize=(14, 8)):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(NAVY)
    ax.set_facecolor(NAVY)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.05, 0.94, title, color=WHITE, fontsize=23, fontweight="bold", va="top")
    if subtitle:
        ax.text(0.05, 0.89, subtitle, color=MUTED, fontsize=11, va="top")
    ax.plot([0.05, 0.95], [0.86, 0.86], color=TEAL, linewidth=2)
    return fig, ax


def save(fig, name):
    fig.savefig(FIG / name, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def architecture():
    fig, ax = base_canvas("UGTS Foundation 5.0 Architecture", "Unicode literal, field semantics, converse topology and packed execution remain inside one audited authority chain")
    box(ax, (0.05, 0.68), (0.17, 0.12), "Literal Unicode", "exact scalars • NFC • UTF-8\nsyntax + surface ports", ec=BLUE)
    box(ax, (0.255, 0.68), (0.17, 0.12), "OperatorCell", "content hash • types • laws\nsemantics • exactness", ec=TEAL)
    box(ax, (0.46, 0.68), (0.17, 0.12), "Canonical Glyph SDF", "capsule-union field\nfont profile remains separate", ec=PURPLE, title_size=11.5)
    box(ax, (0.665, 0.68), (0.17, 0.12), "Signed Set Field", "membership • inclusion\nunion • intersection • complement", ec=GOLD, title_size=12)
    box(ax, (0.84, 0.68), (0.11, 0.12), "Klein", "reflect\nswap\ntoggle", ec=CORAL)
    for x1, x2 in [(0.22,0.255),(0.425,0.46),(0.63,0.665),(0.835,0.84)]:
        arrow(ax, (x1,0.74),(x2,0.74))

    box(ax, (0.08, 0.45), (0.20, 0.13), "Cold Unicode Atlas", "literal key -> complete cell\ncontent-addressed definitions", ec=TEAL)
    box(ax, (0.40, 0.45), (0.20, 0.13), "Hot 16-slot Codebook", "4-bit local alias\nfamily + κ converse bit", ec=GOLD)
    box(ax, (0.72, 0.45), (0.20, 0.13), "Packed Node 32", "Δρ • Δθ • path • flags\nseparate integrity parity", ec=PURPLE)
    arrow(ax, (0.28,0.515),(0.40,0.515), color=GOLD)
    arrow(ax, (0.60,0.515),(0.72,0.515), color=PURPLE)

    labels = [
        (0.035, 0.13, "SUPPORT", TEAL, 11.5),
        (0.175, 0.16, "COMPATIBILITY", BLUE, 10.5),
        (0.345, 0.11, "GUARD", GOLD, 11.5),
        (0.465, 0.17, "VERIFIED\nPROPOSAL", CORAL, 10.5),
        (0.645, 0.19, "DETERMINISTIC\nCOMMIT", GREEN, 10.0),
        (0.845, 0.12, "LINEAGE", PURPLE, 11.0),
    ]
    for x,w,t,c,fs in labels:
        box(ax, (x,0.20),(w,0.10),t,"",fc="#101d39",ec=c,lw=2,title_size=fs)
    for i in range(len(labels)-1):
        x = labels[i][0] + labels[i][1]
        x2 = labels[i+1][0]
        arrow(ax,(x,0.25),(x2,0.25),color=WHITE,lw=1.3,mutation=11)
    ax.text(0.5,0.10,"Pure operator evaluation proposes evidence; only the retained UGTS chain may change authoritative state.",ha="center",color=WHITE,fontsize=12,fontweight="bold")
    save(fig, "architecture.png")

def operator_cell():
    fig, ax = base_canvas("Anatomy of a Unicode OperatorCell", "One literal key co-addresses three distinct faces without collapsing their types")
    box(ax,(0.37,0.36),(0.26,0.26),"OperatorCell", "stable ID • version • SHA-256\nprovenance • exactness • capabilities", fc="#182744", ec=WHITE, lw=3)
    items = [
        ((0.06,0.66),(0.23,0.13),"Literal", "∈ • U+2208 • UTF-8\nnormalization + syntax", BLUE),
        ((0.71,0.66),(0.23,0.13),"Typed Semantics", "Element[T] × Set[T] -> Bool\nφ_A(x) ≤ 0", GOLD),
        ((0.06,0.37),(0.23,0.13),"Glyph SDF", "canonical stroke geometry\nG∋(-x,y)=G∈(x,y)", PURPLE),
        ((0.71,0.37),(0.23,0.13),"Set-Field Action", "predicate / transform\ncapability ladder", TEAL),
        ((0.06,0.09),(0.23,0.13),"Surface Ports", "∈ : element,set\n∋ : set,element", CORAL),
        ((0.71,0.09),(0.23,0.13),"Klein Converse", "swap operands • reflect θ\nκ xor 1 • o -> -o", GREEN),
    ]
    for xy,wh,t,b,c in items:
        box(ax,xy,wh,t,b,ec=c)
        start = (xy[0]+wh[0],xy[1]+wh[1]/2) if xy[0] < 0.3 else (xy[0],xy[1]+wh[1]/2)
        end = (0.37,0.49) if xy[0] < 0.3 else (0.63,0.49)
        arrow(ax,start,end,color=c,lw=1.8)
    ax.text(0.5,0.28,"G_U ≠ E_U ≠ F_U, but all are resolved by the same literal Unicode cell.",ha="center",color=WHITE,fontsize=14,fontweight="bold")
    save(fig, "operator_cell.png")


def set_field_algebra():
    fig, ax = base_canvas("Set Theory as Signed Set Fields", "Negative = inside, zero = boundary, positive = outside")
    equations = [
        ("Membership", r"$x \in A \Longleftrightarrow \phi_A(x) \leq 0$", BLUE),
        ("Union", r"$\phi_{A\cup B}=\min(\phi_A,\phi_B)$", TEAL),
        ("Intersection", r"$\phi_{A\cap B}=\max(\phi_A,\phi_B)$", PURPLE),
        ("Complement", r"$\phi_{X\setminus A}=-\phi_A$", GOLD),
        ("Difference", r"$\phi_{A\setminus B}=\max(\phi_A,-\phi_B)$", CORAL),
        ("Symmetric difference", r"$\max(\min(\phi_A,\phi_B),-\max(\phi_A,\phi_B))$", GREEN),
    ]
    ys=[0.66,0.49,0.32]
    for i,(name,eq,c) in enumerate(equations):
        x=0.055 if i%2==0 else 0.525
        y=ys[i//2]
        box(ax,(x,y),(0.42,0.13),name,eq,ec=c,align="left",body_size=12)
    box(ax,(0.09,0.08),(0.82,0.13),"Capability rule", "The sign algebra is exact for set membership. Exact Euclidean-distance status is retained only when separately proved;\notherwise the result is a metric field, bound, residual or signed membership oracle.",ec=WHITE,fc="#1a2948",align="left",body_size=9.2)
    save(fig,"set_field_algebra.png")

def klein_square():
    fig, ax = base_canvas("Klein-Converse Commuting Square", "The local transform is an involution; winding and lineage separately remember that a wrap occurred")
    box(ax,(0.08,0.58),(0.31,0.16),"Direct cell", "(U, a, b, θ, κ, o)\nexample: (∈, x, A, θ, 0, +1)",ec=BLUE)
    box(ax,(0.61,0.58),(0.31,0.16),"Converse cell", "(U˘, b, a, π-θ, κ⊕1, -o)\nexample: (∋, A, x, π-θ, 1, -1)",ec=CORAL)
    arrow(ax,(0.39,0.66),(0.61,0.66),color=GOLD,lw=3)
    ax.text(0.50,0.70,"K",ha="center",color=GOLD,fontsize=18,fontweight="bold")
    box(ax,(0.12,0.27),(0.24,0.12),"E_U(a,b)", "typed truth value",ec=TEAL)
    box(ax,(0.64,0.27),(0.24,0.12),"E_U˘(b,a)", "same typed truth value",ec=TEAL)
    arrow(ax,(0.235,0.58),(0.235,0.39),color=WHITE)
    arrow(ax,(0.765,0.58),(0.765,0.39),color=WHITE)
    arrow(ax,(0.36,0.33),(0.64,0.33),color=GREEN,lw=3)
    ax.text(0.50,0.37,"=",ha="center",color=GREEN,fontsize=24,fontweight="bold")
    ax.text(0.50,0.17,"K² = identity on literal, ports, chart orientation and κ. Lineage records winding +2 instead of erasing history.",ha="center",color=WHITE,fontsize=12,fontweight="bold")
    save(fig,"klein_converse_square.png")


def atlas_packing():
    fig, ax = base_canvas("Two-Level Lookup and Packed Execution", "Global Unicode identity stays cold; hot SIMD state stores only a hash-bound local alias")
    box(ax,(0.05,0.56),(0.24,0.22),"Cold atlas", "20 shipped OperatorCells\nexact Unicode literal key\nglyph + semantics + hashes",ec=TEAL)
    box(ax,(0.38,0.56),(0.24,0.22),"Hot codebook", "16 slots\n14 occupied + 2 reserved\nslot=(family<<1)|κ",ec=GOLD)
    box(ax,(0.71,0.56),(0.24,0.22),"Node batch", "32-bit words\nΔρ + Δθ + path + flags\nper-node parity",ec=PURPLE)
    arrow(ax,(0.29,0.67),(0.38,0.67),color=GOLD,lw=3)
    arrow(ax,(0.62,0.67),(0.71,0.67),color=PURPLE,lw=3)
    box(ax,(0.08,0.20),(0.20,0.14),"Scalar oracle", "authoritative decode\nround-trip + parity",ec=WHITE)
    box(ax,(0.40,0.20),(0.20,0.14),"AVX2", "8 lanes\nfull-lane masks",ec=BLUE)
    box(ax,(0.72,0.20),(0.20,0.14),"NEON", "4 lanes\nprofile contract",ec=GREEN)
    for x in [0.18,0.50,0.82]:
        arrow(ax,(0.83,0.56),(x,0.34),color=MUTED,lw=1.5,connectionstyle="arc3,rad=0.15" if x<0.5 else "arc3,rad=-0.15")
    ax.text(0.5,0.10,"Unknown slot, hash mismatch, parity failure or insufficient event margin => reject.",ha="center",color=CORAL,fontsize=13,fontweight="bold")
    save(fig,"atlas_codebook_packing.png")


def bit_layout():
    fig, ax = base_canvas("Packed Set-Field Node 32", "The semantic/topological κ bit is inside the 4-bit operator slot; integrity parity remains bit 31")
    fields = [
        (31,31,"P",CORAL),
        (30,27,"OP",GOLD),
        (26,19,"Δρ",TEAL),
        (18,11,"Δθ",BLUE),
        (10,3,"PATH",PURPLE),
        (2,1,"F",GREEN),
        (0,0,"A",WHITE),
    ]
    total_x0=0.06; total_w=0.88; y=0.48; h=0.22
    cursor=total_x0
    for hi,lo,label,c in fields:
        width=(hi-lo+1)/32*total_w
        ax.add_patch(Rectangle((cursor,y),width,h,facecolor=c,edgecolor=NAVY,linewidth=2))
        txt_color=NAVY if c in [GOLD,TEAL,GREEN,WHITE] else WHITE
        ax.text(cursor+width/2,y+h*0.58,label,ha="center",va="center",color=txt_color,fontsize=14,fontweight="bold")
        ax.text(cursor+0.003,y+h+0.03,str(hi),ha="left",va="bottom",color=MUTED,fontsize=8)
        cursor+=width
    ax.text(0.06,0.41,"P  integrity parity",color=CORAL,fontsize=10,fontweight="bold")
    ax.text(0.20,0.41,"OP  family[2:0] + κ",color=GOLD,fontsize=10,fontweight="bold")
    ax.text(0.41,0.41,"Δρ  signed int8",color=TEAL,fontsize=10,fontweight="bold")
    ax.text(0.57,0.41,"Δθ  cyclic uint8",color=BLUE,fontsize=10,fontweight="bold")
    ax.text(0.72,0.41,"PATH  8 branch decisions",color=PURPLE,fontsize=10,fontweight="bold")
    ax.text(0.92,0.41,"F / A",color=GREEN,fontsize=10,fontweight="bold")
    ax.text(0.07,0.32,"operator_id = (family << 1) | κ",color=GOLD,fontsize=13,fontweight="bold")
    ax.text(0.57,0.32,"Klein flip: κ ^= 1;  Δθ = -Δθ mod 256; recompute P",color=WHITE,fontsize=12,ha="center")
    box(ax,(0.10,0.12),(0.80,0.12),"Stream header is mandatory", "atlas hash • codebook hash • ρ scale/bias • θ origin • 256-bin period • grammar identity • error budget • event margin • CRC",ec=CORAL,align="left",body_size=9.0)
    save(fig,"packed_node_layout.png")

def glyph_plate():
    pairs = [("∈","∋"),("∉","∌"),("⊂","⊃"),("⊆","⊇"),("⊄","⊅"),("⊈","⊉"),("⊊","⊋")]
    fig, axes = plt.subplots(2,7,figsize=(15,5.4))
    fig.patch.set_facecolor(NAVY)
    xs=np.linspace(-1.1,1.1,180); ys=np.linspace(-1.1,1.1,180)
    X,Y=np.meshgrid(xs,ys)
    for col,(a,b) in enumerate(pairs):
        for row,literal in enumerate([a,b]):
            ax=axes[row,col]
            Z=np.vectorize(lambda x,y:glyph_sdf(literal,float(x),float(y)))(X,Y)
            ax.contourf(X,Y,Z,levels=[-10,0,10],colors=[TEAL,NAVY2],alpha=1)
            ax.contour(X,Y,Z,levels=[0],colors=[WHITE],linewidths=1.1)
            ax.set_aspect("equal"); ax.set_xlim(-1.1,1.1); ax.set_ylim(-1.1,1.1); ax.axis("off")
            ax.set_title(literal,color=WHITE,fontsize=24,pad=3)
    fig.text(0.012,0.68,"DIRECT",rotation=90,ha="center",va="center",color=BLUE,fontsize=10,fontweight="bold")
    fig.text(0.012,0.30,"CONVERSE",rotation=90,ha="center",va="center",color=CORAL,fontsize=10,fontweight="bold")
    fig.suptitle("Canonical UGTS Converse Glyph Fields",color=WHITE,fontsize=22,fontweight="bold",y=0.99)
    fig.text(0.5,0.02,"Each lower glyph is the x-reflection of the upper glyph in the canonical capsule-union profile. Font-specific outlines remain separate.",ha="center",color=MUTED,fontsize=10)
    fig.subplots_adjust(left=0.03,right=0.995,bottom=0.08,top=0.90,wspace=0.10,hspace=0.08)
    save(fig,"glyph_converse_plate.png")

def exactness_ladder():
    fig, ax = base_canvas("Set-Field Capability Ladder", "A Unicode cell carries the strongest capability actually established - never the strongest label available")
    levels=[
        ("1  EXACT SDF","Euclidean distance to a declared boundary",GREEN),
        ("2  METRIC SIGNED SET FIELD","d(x,A) - d(x,X∖A) in a declared metric",TEAL),
        ("3  CONSERVATIVE DISTANCE BOUND","one-sided or interval-safe distance information",BLUE),
        ("4  IMPLICIT SIGNED RESIDUAL","correct sign, not exact distance",PURPLE),
        ("5  SIGNED MEMBERSHIP FIELD","-1 inside, +1 outside on a finite/typed universe",GOLD),
        ("6  SYMBOLIC MEMBERSHIP ORACLE","typed predicate with no numeric-distance claim",CORAL),
    ]
    y=0.72
    for title,body,c in levels:
        box(ax,(0.12,y),(0.76,0.095),title,body,ec=c,align="left")
        y-=0.105
    ax.text(0.5,0.065,"Global subset, equality and emptiness certificates require finite exhaustion or a continuous-domain proof. A sampled LUT does not promote itself.",ha="center",color=WHITE,fontsize=11,fontweight="bold")
    save(fig,"exactness_ladder.png")


def lineage_graph():
    fig, ax = base_canvas("Canonical Release Identity and Parent Graph", "Version 5.0 is major inside its foundation component; it does not silently supersede unrelated runtimes, applications or platform branches")
    parents=[
        (0.05,"Literal Referential\n3.6.0",TEAL),
        (0.20,"BEA\n3.6.1",PURPLE),
        (0.35,"SCLP\n3.6.2",BLUE),
        (0.50,"GPU Native\n1.1.0",GOLD),
        (0.65,"General Operator\n4.2.0",CORAL),
        (0.80,"IQ Field\n3.9.3",GREEN),
    ]
    for x,t,c in parents:
        box(ax,(x,0.64),(0.14,0.12),t,"",ec=c)
        arrow(ax,(x+0.07,0.64),(0.50,0.48),color=c,lw=1.6)
    box(ax,(0.29,0.27),(0.42,0.20),"UGTS Foundation / Unicode Set-Field and Klein-Converse Atlas 5.0.0", "ugts.foundation.unicode-set-field-klein-converse@5.0.0\nlegacy alias: UGTS-KC 5.0",ec=WHITE,fc="#182744",lw=3)
    ax.text(0.5,0.13,"Major version, explicit parent graph, no false global ladder.",ha="center",color=GOLD,fontsize=14,fontweight="bold")
    save(fig,"release_parent_graph.png")


def validation_summary():
    fig, ax = base_canvas("Executable Release Evidence", "Captured from the accompanying package on 29 August 2026")
    metrics=[
        ("83","Python tests","all PASS",TEAL),
        ("3","JSON Schemas","zero errors",BLUE),
        ("1","C++20 native test","PASS",PURPLE),
        ("20","OperatorCells","hash-verified",GOLD),
        ("64","New mechanisms","USF001-USF064",CORAL),
        ("24","Claims ledger rows","admit / bound / reject",GREEN),
    ]
    for i,(n,title,body,c) in enumerate(metrics):
        row=i//3; col=i%3
        x=0.07+col*0.31; y=0.60-row*0.27
        patch=FancyBboxPatch((x,y),0.25,0.19,boxstyle="round,pad=0.012,rounding_size=0.025",facecolor="#142442",edgecolor=c,linewidth=2)
        ax.add_patch(patch)
        ax.text(x+0.125,y+0.125,n,ha="center",va="center",color=WHITE,fontsize=27,fontweight="bold")
        ax.text(x+0.125,y+0.055,title+"\n"+body,ha="center",va="center",color=MUTED,fontsize=9.5,linespacing=1.35)
    ax.text(0.5,0.14,"Evidence proves package conformance and bounded examples - not universality, physical-device speed or independent scientific validation.",ha="center",color=WHITE,fontsize=11,fontweight="bold")
    save(fig,"validation_summary.png")


if __name__ == "__main__":
    architecture(); operator_cell(); set_field_algebra(); klein_square(); atlas_packing(); bit_layout(); glyph_plate(); exactness_ladder(); lineage_graph(); validation_summary()
    print(json.dumps({"figures": sorted(p.name for p in FIG.glob("*.png"))}, indent=2))
