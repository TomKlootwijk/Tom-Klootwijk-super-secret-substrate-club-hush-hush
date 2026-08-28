from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Circle, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle

from ugts36.phonetics_nl import generate_lexicon

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "report" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

NAVY = "#0d2b3a"
TEAL = "#16979b"
GOLD = "#d4a21b"
CORAL = "#cf6a5a"
PURPLE = "#6b5d96"
GREEN = "#3f8d6a"
LIGHT = "#edf6f6"
LIGHT_GOLD = "#fbf5e4"
LIGHT_PURPLE = "#f2eff8"
GREY = "#66737b"
DARK = "#15252e"

plt.rcParams.update({
    "font.family": "Inter",
    "font.size": 11,
    "axes.titlesize": 16,
    "axes.labelsize": 12,
})


def box(ax, x, y, w, h, text, fc=LIGHT, ec=TEAL, fontsize=11, lw=1.7, text_color=DARK):
    patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.018,rounding_size=0.025", facecolor=fc, edgecolor=ec, linewidth=lw)
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize, color=text_color, wrap=True)
    return patch


def arrow(ax, start, end, color=GREY, style="-|>", lw=1.6, connectionstyle="arc3,rad=0.0", linestyle="-"):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=13, linewidth=lw, color=color, connectionstyle=connectionstyle, linestyle=linestyle))


def save(fig, name):
    fig.savefig(OUT / name, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# 1. Referential architecture
fig, ax = plt.subplots(figsize=(13, 7.3))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
ax.text(0.02, 0.96, "UGTS-KC 3.6: definitions live inside the substrate", fontsize=22, weight="bold", color=NAVY, va="top")
ax.text(0.02, 0.905, "A literal, content-addressed definition graph drives instances, queries and events.", fontsize=12.5, color=GREY, va="top")
# substrate boundary
outer = FancyBboxPatch((0.035,0.08),0.93,0.77,boxstyle="round,pad=0.012,rounding_size=0.025",facecolor="#fbfcfc",edgecolor=NAVY,linewidth=2.2)
ax.add_patch(outer)
ax.text(0.055,0.815,"AUTHORITATIVE SUBSTRATE DOCUMENT",color=NAVY,weight="bold",fontsize=12)
box(ax,0.07,0.61,0.19,0.13,"Definition registry\ngeometry | topology | operators",fc=LIGHT,ec=TEAL)
box(ax,0.30,0.61,0.17,0.13,"Canonical records\nSHA-256 content addresses",fc=LIGHT_GOLD,ec=GOLD)
box(ax,0.51,0.61,0.17,0.13,"Dependency DAG\nexplicit references",fc=LIGHT_PURPLE,ec=PURPLE)
box(ax,0.72,0.61,0.19,0.13,"Instances\nliteral values + state",fc="#eef7ef",ec=GREEN)
arrow(ax,(0.26,0.675),(0.30,0.675),TEAL)
arrow(ax,(0.47,0.675),(0.51,0.675),GOLD)
arrow(ax,(0.68,0.675),(0.72,0.675),PURPLE)
box(ax,0.11,0.36,0.20,0.12,"Phase-ordered evaluator\nparse -> resolve -> construct",fc="#f7fafb",ec=NAVY)
box(ax,0.40,0.36,0.20,0.12,"Query kernel\nsupport -> compatibility -> guard",fc=LIGHT,ec=TEAL)
box(ax,0.69,0.36,0.20,0.12,"Transition + lineage\nstate patch + event record",fc=LIGHT_GOLD,ec=GOLD)
arrow(ax,(0.815,0.61),(0.79,0.48),GREEN,connectionstyle="arc3,rad=0.08")
arrow(ax,(0.72,0.675),(0.26,0.48),GREY,connectionstyle="arc3,rad=0.28")
arrow(ax,(0.31,0.42),(0.40,0.42),NAVY)
arrow(ax,(0.60,0.42),(0.69,0.42),TEAL)
box(ax,0.16,0.15,0.18,0.095,"Verified event log\nirreducible novelty",fc="#fff5f1",ec=CORAL,fontsize=10.5)
box(ax,0.41,0.15,0.18,0.095,"Definition query\ndefinition_at(id)",fc=LIGHT_PURPLE,ec=PURPLE,fontsize=10.5)
box(ax,0.66,0.15,0.18,0.095,"Optional adapters\nprojection | hardware",fc="#f7fafb",ec=GREY,fontsize=10.5)
arrow(ax,(0.76,0.36),(0.29,0.245),CORAL,connectionstyle="arc3,rad=-0.08")
arrow(ax,(0.50,0.36),(0.50,0.245),PURPLE)
arrow(ax,(0.79,0.36),(0.75,0.245),GREY)
ax.text(0.5,0.035,"Referential closure is bounded: definitions may describe other definitions, but unresolved IDs, invalid hashes and cycles are rejected.",ha="center",va="center",fontsize=10.5,color=GREY)
save(fig,"architecture_referential.png")

# 2. Dutch order hinge
fig, ax = plt.subplots(figsize=(12, 6.5))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
ax.text(0.02,0.95,"Dutch number order as an explicit connector hinge",fontsize=21,weight="bold",color=NAVY,va="top")
ax.text(0.02,0.895,"Example: 23 has place semantics 20 + 3, but the spoken graph is drie - en - twintig.",fontsize=12.5,color=GREY,va="top")
ax.text(0.17,0.78,"NUMERAL / PLACE CHART",ha="center",weight="bold",color=NAVY,fontsize=12)
box(ax,0.05,0.55,0.20,0.14,"20\ntens place",fc=LIGHT_GOLD,ec=GOLD,fontsize=13)
box(ax,0.30,0.55,0.20,0.14,"3\nunit place",fc=LIGHT,ec=TEAL,fontsize=13)
arrow(ax,(0.25,0.62),(0.30,0.62),GREY)
ax.text(0.275,0.67,"+",ha="center",color=GREY,fontsize=15)
ax.text(0.76,0.78,"SPOKEN / MORPHOLOGICAL CHART",ha="center",weight="bold",color=NAVY,fontsize=12)
box(ax,0.57,0.55,0.13,0.14,"drie\nunit root",fc=LIGHT,ec=TEAL,fontsize=12)
box(ax,0.73,0.55,0.10,0.14,"en\nHINGE",fc="#fff1ed",ec=CORAL,fontsize=12)
box(ax,0.86,0.55,0.12,0.14,"twintig\ntens word",fc=LIGHT_GOLD,ec=GOLD,fontsize=11)
arrow(ax,(0.70,0.62),(0.73,0.62),CORAL)
arrow(ax,(0.83,0.62),(0.86,0.62),CORAL)
# mapping arrows
arrow(ax,(0.40,0.55),(0.635,0.69),TEAL,connectionstyle="arc3,rad=-0.25",linestyle="--")
arrow(ax,(0.15,0.55),(0.92,0.69),GOLD,connectionstyle="arc3,rad=-0.28",linestyle="--")
ax.text(0.515,0.46,"semantic transposition",ha="center",color=PURPLE,weight="bold")
box(ax,0.10,0.21,0.80,0.14,"H_en(place=(20,3)) = spoken=(3, 'en', 20)\nInvariant: numeric value stays 23. The connector has structural role but zero place magnitude.",fc=LIGHT_PURPLE,ec=PURPLE,fontsize=12)
ax.text(0.5,0.105,"This is a typed map between two charts, not evidence that language changes arithmetic.",ha="center",fontsize=11,color=GREY)
save(fig,"dutch_hinge_23.png")

# 3. Number 19 pipeline
fig, ax = plt.subplots(figsize=(13, 6.5))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
ax.text(0.02,0.95,"19: three independent representations connected by typed transforms",fontsize=21,weight="bold",color=NAVY,va="top")
ax.text(0.02,0.895,"The shared count is recorded as a coincidence. The decimal value remains 19 throughout.",fontsize=12.5,color=GREY,va="top")
# binary strip
bits="10011"; xs=[0.08+i*0.075 for i in range(5)]
ax.text(0.22,0.77,"binary encoding",ha="center",weight="bold",color=NAVY)
for i,(x,b) in enumerate(zip(xs,bits)):
    active=b=='1'
    c=Circle((x,0.66),0.035,facecolor=CORAL if active else "white",edgecolor=CORAL if active else GREY,linewidth=1.8)
    ax.add_patch(c); ax.text(x,0.66,b,ha="center",va="center",weight="bold",color="white" if active else GREY,fontsize=13)
    ax.text(x,0.59,str(2**(4-i)),ha="center",fontsize=9,color=GREY)
ax.text(0.22,0.52,"popcount = 3",ha="center",color=CORAL,weight="bold",fontsize=12)
# phonetics
ax.text(0.53,0.77,"Dutch profile",ha="center",weight="bold",color=NAVY)
for x,seg in zip([0.44,0.53,0.62],["ne","gen","tien"]):
    box(ax,x-0.045,0.615,0.09,0.09,seg,fc=LIGHT,ec=TEAL,fontsize=12)
ax.text(0.53,0.52,"declared pulse count = 3",ha="center",color=TEAL,weight="bold",fontsize=12)
# triangle
ax.text(0.82,0.77,"chosen embedding",ha="center",weight="bold",color=NAVY)
tri=[(0.82,0.72),(0.72,0.55),(0.92,0.55)]
ax.add_patch(Polygon(tri,closed=True,facecolor="#dff1f1",edgecolor=TEAL,linewidth=2))
for i,p in enumerate(tri,1):
    ax.add_patch(Circle(p,0.018,facecolor=CORAL,edgecolor="white",linewidth=1))
    ax.text(p[0],p[1]+0.035,str(i),ha="center",fontsize=9,color=GREY)
ax.text(0.82,0.49,"3 pulses -> triangle",ha="center",color=PURPLE,weight="bold",fontsize=12)
# arrows and conclusion
arrow(ax,(0.37,0.64),(0.41,0.64),GREY)
arrow(ax,(0.66,0.64),(0.70,0.64),GREY)
box(ax,0.16,0.20,0.68,0.15,"value(19) = 19\nbinary(19) = 10011, Hamming weight = 3\nphonetic_profile_nl(19) = ne | gen | tien, pulse count = 3\ncomparison = equal counts; geometry = user-selected 3-vertex embedding",fc=LIGHT_GOLD,ec=GOLD,fontsize=11.5)
ax.text(0.5,0.085,"No zero is deleted from the number; zeros are merely inactive positions in one feature projection.",ha="center",fontsize=11,color=GREY)
save(fig,"number19_typed_pipeline.png")

# 4. Evaluation order
fig, ax = plt.subplots(figsize=(14, 4.6))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
ax.text(0.02,0.92,"Normative operation order",fontsize=21,weight="bold",color=NAVY,va="top")
stages=[
("0","parse"),("1","normalize"),("2","resolve refs"),("3","construct"),("4","transform"),
("5","support"),("6","compatibility"),("7","guard/root"),("8","transition"),("9","lineage/log")]
colors=[GREY,TEAL,PURPLE,GOLD,CORAL,TEAL,PURPLE,CORAL,GOLD,GREEN]
for i,((num,label),color) in enumerate(zip(stages,colors)):
    x=0.025+i*0.096
    box(ax,x,0.43,0.082,0.18,f"{num}\n{label}",fc="white",ec=color,fontsize=10.5,lw=2)
    if i<9: arrow(ax,(x+0.082,0.52),(x+0.096,0.52),GREY,lw=1.2)
ax.text(0.5,0.28,"Definition dependencies are topologically sorted inside phases; composition order is serialized and traceable.",ha="center",fontsize=11.5,color=GREY)
box(ax,0.18,0.08,0.64,0.11,"Reject before execution: duplicate ID | unknown reference | bad content hash | undeclared cycle | schema mismatch",fc="#fff1ed",ec=CORAL,fontsize=11)
save(fig,"evaluation_order.png")

# 5. Hinge calculus
fig, ax = plt.subplots(figsize=(12, 7.0))
ax.set_xlim(0,1); ax.set_ylim(0,1); ax.axis("off")
ax.text(0.02,0.95,"Hinge calculus: one interface, three concrete forms",fontsize=21,weight="bold",color=NAVY,va="top")
box(ax,0.08,0.75,0.84,0.10,"H = (pivot, state, map, guard, invariant)",fc=LIGHT_GOLD,ec=GOLD,fontsize=15)
# continuous
ax.text(0.18,0.66,"continuous geometric hinge",ha="center",weight="bold",color=NAVY)
pivot=(0.18,0.45)
ax.add_patch(Circle(pivot,0.018,facecolor=CORAL,edgecolor=CORAL))
ax.plot([pivot[0],0.34],[pivot[1],0.45],color=GREY,linewidth=3)
ax.plot([pivot[0],0.29],[pivot[1],0.57],color=TEAL,linewidth=3)
ax.add_patch(Arc(pivot,0.18,0.18,theta1=0,theta2=47,color=GOLD,linewidth=2))
ax.text(0.27,0.50,r"$R_{p}(\theta)$",fontsize=13,color=GOLD)
ax.text(0.18,0.31,"fixed pivot; differentiable state",ha="center",fontsize=10.5,color=GREY)
# discrete
ax.text(0.50,0.66,"discrete parity hinge",ha="center",weight="bold",color=NAVY)
box(ax,0.41,0.49,0.12,0.09,"h=0\nroute A",fc=LIGHT,ec=TEAL,fontsize=11)
box(ax,0.58,0.49,0.12,0.09,"h=1\nroute B",fc=LIGHT_PURPLE,ec=PURPLE,fontsize=11)
arrow(ax,(0.53,0.535),(0.58,0.535),CORAL)
ax.text(0.555,0.59,"guarded event",ha="center",fontsize=9.5,color=CORAL)
ax.text(0.55,0.31,"bit selects a map; state remains separate",ha="center",fontsize=10.5,color=GREY)
# connector
ax.text(0.82,0.66,"connector / parse hinge",ha="center",weight="bold",color=NAVY)
box(ax,0.72,0.50,0.09,0.08,"unit",fc=LIGHT,ec=TEAL,fontsize=11)
box(ax,0.83,0.50,0.08,0.08,"en",fc="#fff1ed",ec=CORAL,fontsize=11)
box(ax,0.93,0.50,0.06,0.08,"tens",fc=LIGHT_GOLD,ec=GOLD,fontsize=9.5)
arrow(ax,(0.81,0.54),(0.83,0.54),CORAL,lw=1.2)
arrow(ax,(0.91,0.54),(0.93,0.54),CORAL,lw=1.2)
ax.text(0.84,0.31,"zero place magnitude; nonzero graph role",ha="center",fontsize=10.5,color=GREY)
box(ax,0.14,0.10,0.72,0.12,"Order matters: H2 ∘ H1 is not generally H1 ∘ H2.\nUGTS 3.6 stores hinge-chain order as data and includes it in the deterministic trace.",fc=LIGHT_PURPLE,ec=PURPLE,fontsize=12)
save(fig,"hinge_calculus.png")

# 6. Topology gluing
fig, ax = plt.subplots(figsize=(13, 6.5))
ax.set_xlim(0,1); ax.set_ylim(0,1); ax.axis("off")
ax.text(0.02,0.95,"Topology is explicit gluing, sheet state and routing",fontsize=21,weight="bold",color=NAVY,va="top")
# mobius rectangle
ax.text(0.18,0.80,"orientation-reversing quotient",ha="center",weight="bold",color=NAVY)
ax.add_patch(Rectangle((0.06,0.52),0.25,0.18,facecolor=LIGHT,edgecolor=TEAL,linewidth=2))
arrow(ax,(0.06,0.61),(0.31,0.61),TEAL,lw=2)
arrow(ax,(0.31,0.57),(0.06,0.57),CORAL,lw=2)
ax.text(0.185,0.48,"(0,y) ~ (w,h-y)\norientation flips after one wrap",ha="center",fontsize=10.5,color=GREY)
# sheets
ax.text(0.50,0.80,"same coordinate, different sheet",ha="center",weight="bold",color=NAVY)
box(ax,0.39,0.61,0.22,0.09,"sheet 1 | phase B | x",fc=LIGHT_PURPLE,ec=PURPLE,fontsize=10.5)
box(ax,0.39,0.43,0.22,0.09,"sheet 0 | phase A | x",fc=LIGHT,ec=TEAL,fontsize=10.5)
ax.plot([0.50,0.50],[0.52,0.61],color=CORAL,linestyle="--",linewidth=1.8)
ax.text(0.52,0.565,"no coupling",color=CORAL,fontsize=10,va="center")
# hourglass
ax.text(0.82,0.80,"four-sector event router",ha="center",weight="bold",color=NAVY)
center=(0.82,0.56)
polys=[[(0.82,0.56),(0.68,0.70),(0.68,0.59)],[(0.82,0.56),(0.96,0.70),(0.96,0.59)],[(0.82,0.56),(0.68,0.42),(0.68,0.53)],[(0.82,0.56),(0.96,0.42),(0.96,0.53)]]
for poly,c,label,pos in zip(polys,[LIGHT_PURPLE,LIGHT,LIGHT_GOLD,"#eef7ef"],["B","A","C","D"],[(0.72,0.63),(0.92,0.63),(0.72,0.49),(0.92,0.49)]):
    ax.add_patch(Polygon(poly,closed=True,facecolor=c,edgecolor=GREY,linewidth=1.2))
    ax.text(*pos,label,ha="center",va="center",weight="bold",color=NAVY)
ax.add_patch(Circle(center,0.018,facecolor=CORAL,edgecolor="white"))
ax.text(0.82,0.37,"guard locus selects branch; parity may swap routes",ha="center",fontsize=10.5,color=GREY)
box(ax,0.12,0.12,0.76,0.13,"Topology records what is identified, transported or routed.\nIt does not imply physical self-intersection, free energy, self-assembly or coupling without a declared compatibility law.",fc="#fff1ed",ec=CORAL,fontsize=11.5)
save(fig,"topology_gluing.png")

# 7. Dutch atlas chart
entries=generate_lexicon()
values=[e.value for e in entries]
syll=[e.syllable_count for e in entries]
pop=[e.popcount for e in entries]
match=[e.value for e in entries if e.pulse_match]
fig, ax = plt.subplots(figsize=(13, 5.2))
ax.plot(values,syll,label="Dutch profile pulse count",linewidth=2.0,color=TEAL)
ax.plot(values,pop,label="binary popcount",linewidth=1.7,color=PURPLE,alpha=0.85)
ax.scatter(match,[lex.syllable_count for lex in entries if lex.pulse_match],s=26,color=CORAL,label="equal feature counts",zorder=5)
ax.set_title("Bounded 0..99 Dutch pulse profile versus binary Hamming weight",loc="left",weight="bold",color=NAVY,pad=14)
ax.set_xlabel("integer value")
ax.set_ylabel("count")
ax.set_xlim(0,99); ax.set_ylim(-0.1,7.1)
ax.grid(True,axis="y",alpha=0.25)
ax.legend(frameon=False,ncol=3,loc="upper left")
ax.text(0.99,-0.22,"28 matches under the shipped profile; this is a lexicon-dependent comparison, not a numeric law.",transform=ax.transAxes,ha="right",fontsize=10.5,color=GREY)
for spine in ("top","right"):
    ax.spines[spine].set_visible(False)
save(fig,"dutch_number_atlas.png")

# 8. Definition graph from example
raw=json.loads((ROOT/'examples/ugts_kc_3_6_example.json').read_text(encoding='utf-8'))
fig, ax = plt.subplots(figsize=(13, 7.2))
ax.set_xlim(0,1); ax.set_ylim(0,1); ax.axis('off')
ax.text(0.02,0.96,"Example definition dependency graph",fontsize=21,weight='bold',color=NAVY,va='top')
positions={
'def:number-literal-v1':(0.06,0.72),
'op:binary-radix-v1':(0.30,0.78),
'op:active-bits-v1':(0.53,0.78),
'op:nl-lexeme-v1':(0.30,0.52),
'op:syllable-pulse-v1':(0.53,0.52),
'op:count-compare-v1':(0.76,0.68),
'geom:pulse-polygon-v1':(0.76,0.42),
'topo:nl-en-hinge-v1':(0.76,0.20),
'topo:mobius-wrap-v1':(0.06,0.23),
'event:sdf-zero-v1':(0.06,0.43),
'schedule:canonical-3-6':(0.30,0.23),
}
for rec in raw['definitions']:
    x,y=positions[rec['id']]
    fc=LIGHT if rec['provenance']['class']=='source-derived' else LIGHT_PURPLE if rec['provenance']['class']=='engineering-derived' else LIGHT_GOLD
    ec=TEAL if rec['provenance']['class']=='source-derived' else PURPLE if rec['provenance']['class']=='engineering-derived' else GOLD
    box(ax,x,y,0.19,0.095,rec['id'].replace(':','\n',1),fc=fc,ec=ec,fontsize=9.2)
for rec in raw['definitions']:
    sx,sy=positions[rec['id']]
    for dep in rec['dependencies']:
        dx,dy=positions[dep]
        arrow(ax,(dx+0.19,dy+0.0475),(sx,sy+0.0475),GREY,lw=1.1,connectionstyle='arc3,rad=0.08')
ax.text(0.55,0.08,"Content hashes verify nodes; the loader rejects unknown IDs and dependency cycles.",ha='center',fontsize=11,color=GREY)
save(fig,'definition_graph.png')

print(f"generated {len(list(OUT.glob('*.png')))} figures in {OUT}")
