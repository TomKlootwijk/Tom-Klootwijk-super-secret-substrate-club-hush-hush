from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Circle, Rectangle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "report" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

NAVY = "#0B1736"
INK = "#14213D"
BLUE = "#4568DC"
CYAN = "#1FB7C9"
TEAL = "#2AA876"
GOLD = "#E0A819"
ORANGE = "#E57A44"
MAGENTA = "#C04C93"
PURPLE = "#7357C5"
RED = "#C94C4C"
GREEN = "#3F9B62"
GRAY = "#65758B"
MID = "#D9E2EF"
LIGHT = "#F5F8FC"
WHITE = "#FFFFFF"
DARK = "#081124"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titleweight": "bold",
    "figure.facecolor": WHITE,
})


def save(fig: plt.Figure, name: str, dpi: int = 220) -> None:
    fig.savefig(OUT / name, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def box(ax, x, y, w, h, title, subtitle="", face=LIGHT, edge=MID, title_color=INK,
        subtitle_color=GRAY, title_size=10, sub_size=8.2, lw=1.5, radius=0.02):
    patch = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.012,rounding_size={radius}",
                           facecolor=face, edgecolor=edge, linewidth=lw)
    ax.add_patch(patch)
    if subtitle:
        ax.text(x + w/2, y + h*0.62, title, ha="center", va="center", color=title_color,
                fontweight="bold", fontsize=title_size, wrap=True)
        ax.text(x + w/2, y + h*0.25, subtitle, ha="center", va="center", color=subtitle_color,
                fontsize=sub_size, wrap=True)
    else:
        ax.text(x + w/2, y + h/2, title, ha="center", va="center", color=title_color,
                fontweight="bold", fontsize=title_size, wrap=True)
    return patch


def arrow(ax, x1, y1, x2, y2, color=GRAY, lw=1.4, style="-|>", mutation=12, connection="arc3"):
    patch = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=mutation,
                            linewidth=lw, color=color, connectionstyle=connection)
    ax.add_patch(patch)
    return patch


def base_axes(figsize=(12.4, 6.6), dark=False):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(DARK if dark else WHITE)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    return fig, ax


def cover_architecture():
    fig, ax = base_axes((12.6, 7.2), dark=True)
    ax.text(0.04, 0.93, "UGTS CHESS GAME-THEORETIC SOLVER 2.0", color=WHITE,
            fontsize=22, fontweight="bold", va="top")
    ax.text(0.04, 0.875, "Classical proof campaign + exact WDL certificates + RTX 5070 Ti Laptop execution profile",
            color="#BFD1F6", fontsize=11.5, va="top")

    stages = [
        ("Exact state", "board + side + rights\nclocks + repetition history", BLUE),
        ("Verified actions", "legal moves + optional\ndraw-claim actions", CYAN),
        ("WDL obligations", "WIN existential\nLOSS universal\nDRAW complete", PURPLE),
        ("Proof campaign", "20 root shards\nleases + candidates\nindependent checks", ORANGE),
        ("Lineage", "SHA-256 nodes\nhash-chained ledger\nportable checkpoint", MAGENTA),
    ]
    x = 0.04
    for i, (title, sub, color) in enumerate(stages):
        box(ax, x, 0.56, 0.165, 0.19, title, sub, face="#111F3F", edge=color,
            title_color=WHITE, subtitle_color="#C8D6EF", title_size=10.2, sub_size=8.3, lw=2)
        if i < len(stages)-1:
            arrow(ax, x+0.165, 0.655, x+0.183, 0.655, color="#6F85AF", lw=1.8)
        x += 0.19

    box(ax, 0.08, 0.25, 0.245, 0.17, "Python proof authority",
        "full rule/history oracle\nWDL certificates\nSQLite campaign checker", face="#102B2A", edge=TEAL,
        title_color=WHITE, subtitle_color="#CAEADF", lw=2)
    box(ax, 0.38, 0.25, 0.245, 0.17, "C++20 host foundation",
        "exact legal kernel + perft\nmate search + fixed point\nCPU packed fallback", face="#1C2344", edge=BLUE,
        title_color=WHITE, subtitle_color="#D3DCF5", lw=2)
    box(ax, 0.68, 0.25, 0.245, 0.17, "Optional CUDA SM120",
        "64-byte position batches\nproposal/fixed-point kernels\nnever final proof authority", face="#2B1B38", edge=MAGENTA,
        title_color=WHITE, subtitle_color="#E9D0E4", lw=2)
    arrow(ax, 0.50, 0.56, 0.205, 0.42, color="#5678B5", connection="arc3,rad=0.1")
    arrow(ax, 0.50, 0.56, 0.505, 0.42, color="#5678B5")
    arrow(ax, 0.50, 0.56, 0.805, 0.42, color="#8E5A95", connection="arc3,rad=-0.1")

    ax.add_patch(FancyBboxPatch((0.05, 0.07), 0.90, 0.095,
                                boxstyle="round,pad=0.014,rounding_size=0.02",
                                facecolor="#162238", edgecolor=GOLD, linewidth=1.5))
    ax.text(0.07, 0.116,
            "Captured root status:  UNKNOWN - 20 exact root obligations; 0 independently verified child WDL values",
            color=WHITE, fontsize=10.4, va="center", fontweight="bold")
    ax.text(0.04, 0.018, "The GPU accelerates proposals. The checker decides what is true.",
            color="#A8B8D8", fontsize=9.5)
    save(fig, "cover_architecture.png")

def solve_ladder():
    fig, ax = base_axes((12.2, 5.5))
    ax.text(0.03, 0.93, "What Does 'Solve Classical Chess' Mean?", fontsize=18, color=NAVY, fontweight="bold")
    ax.text(0.03, 0.86, "The package keeps rule correctness, solved positions and a solved initial game visibly separate.", color=GRAY)
    levels = [
        (0.04, 0.16, 0.27, 0.56, "1  RULES SOLVED",
         "Every legal action and transition\nis deterministic and testable.",
         "Implemented", TEAL),
        (0.365, 0.24, 0.27, 0.48, "2  POSITIONS SOLVED",
         "Finite positions close under a\ncomplete proof certificate or\nexact table.",
         "Mate, KQK, KRK and\nbounded WDL fixtures", BLUE),
        (0.69, 0.24, 0.27, 0.48, "3  GAME SOLVED",
         "The orthodox initial position\nreceives a verified\nWIN / DRAW / LOSS value.",
         "Not established\nroot is UNKNOWN", RED),
    ]
    for x,y,w,h,title,body,status,c in levels:
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.018,rounding_size=0.025",
                                    facecolor=LIGHT,edgecolor=c,linewidth=2))
        ax.text(x+w/2,y+h-0.07,title,color=c,fontweight="bold",fontsize=11.2,ha="center")
        ax.text(x+w/2,y+h-0.17,body,color=INK,fontsize=9.0,va="top",ha="center",linespacing=1.35)
        ax.add_patch(FancyBboxPatch((x+0.025,y+0.04),w-0.05,0.12,boxstyle="round,pad=0.01,rounding_size=0.015",
                                    facecolor=WHITE,edgecolor=MID,linewidth=1))
        ax.text(x+w/2,y+0.10,status,ha="center",va="center",color=DARK if c!=RED else RED,
                fontsize=8.8,fontweight="bold",linespacing=1.25)
    arrow(ax,0.31,0.44,0.365,0.48,color=GRAY,lw=2)
    arrow(ax,0.635,0.49,0.69,0.49,color=GRAY,lw=2)
    ax.text(0.03,0.06,"Weak, strong and ultra-weak solution terminology describes proof scope; none is claimed here.",color=RED,fontweight="bold",fontsize=9.6)
    save(fig,"solve_ladder.png")

def source_grounding():
    fig, ax = base_axes((12.5, 6.8))
    ax.text(0.03,0.94,"Source Grounding and Engineering Delta",fontsize=18,color=NAVY,fontweight="bold")
    ax.text(0.03,0.875,"UGTS supplies the authority discipline. Chess rules, WDL logic and CUDA work are application engineering.",color=GRAY)
    sources=[
        ("GN 1.1","support -> compatibility\n-> guard -> event\n-> transition -> lineage",BLUE),
        ("KC 2.0","typed state + topology\nbounded queries\nexplicit degeneracy",CYAN),
        ("Two Hands 3.0","proposal / commit\npre/post hashes\ncheckpoints + replay",TEAL),
        ("Literal 3.6","content-addressed rules\ndependencies\noperation order",GOLD),
        ("SCLP 3.6.2","finite keys\nbounded branching\ncompression audit",PURPLE),
        ("Elizabeth 3.9","deterministic runtime\nsnapshots + CLI\noffline delivery",MAGENTA),
        ("Operator 4.2","parse / dependency\nreduction / event\nreplay orders",ORANGE),
        ("Chess 1.0","exact legal kernel\nmate proofs\nKQK / KRK tables",GREEN),
    ]
    for i,(t,sub,c) in enumerate(sources):
        row=i//4; col=i%4
        x=0.035+col*0.24; y=0.65-row*0.245
        box(ax,x,y,0.21,0.17,t,sub,face=LIGHT,edge=c,title_color=c,subtitle_color=INK,title_size=9.8,sub_size=7.5,lw=1.8)
    box(ax,0.10,0.095,0.80,0.17,"Chess 2.0 engineering delta",
        "FIDE terminal/action semantics - history-correct WDL certificates - 20 root obligations\nportable SQLite campaign - C++20/CUDA adapters - RTX SM120 execution profile",
        face="#EEF4FF",edge=BLUE,title_color=NAVY,subtitle_color=INK,title_size=11.5,sub_size=8.7,lw=2)
    for x in (0.14,0.38,0.62,0.86):
        arrow(ax,x,0.405,0.50,0.265,color=MID,lw=1.2,connection="arc3,rad=0.08")
    ax.text(0.03,0.025,"SARA 3.6.3 was reviewed but its wallet-specific mechanisms were excluded from the chess model.",fontsize=9.0,color=GRAY)
    save(fig,"source_grounding.png")

def authority_chain():
    fig, ax=base_axes((12.5,4.2))
    ax.text(0.03,0.91,"One Chess Action Through the Canonical UGTS Authority Chain",fontsize=18,color=NAVY,fontweight="bold")
    stages=[
        ("WHERE?","piece/ray support",CYAN),
        ("MATCH?","turn, occupancy, type",PURPLE),
        ("READY?","castle/EP/promotion",GOLD),
        ("CHECKED?","king safety + terminals",BLUE),
        ("CHANGE","atomic board/rights/clocks",ORANGE),
        ("REMEMBER","history counts + hashes",TEAL),
    ]
    x=0.03
    for i,(q,s,c) in enumerate(stages):
        box(ax,x,0.38,0.14,0.25,q,s,face=LIGHT,edge=c,title_color=c,subtitle_color=INK,title_size=10.5,sub_size=8.2,lw=2)
        if i<len(stages)-1: arrow(ax,x+0.14,0.505,x+0.162,0.505,color=GRAY,lw=1.8)
        x+=0.165
    ax.add_patch(FancyBboxPatch((0.10,0.12),0.80,0.13,boxstyle="round,pad=0.012,rounding_size=0.02",facecolor="#FFF6E5",edgecolor=GOLD,linewidth=1.4))
    ax.text(0.50,0.185,"A CPU, GPU, human interface or heuristic engine may propose a move. None may bypass the checker.",ha="center",va="center",color=INK,fontweight="bold",fontsize=10)
    save(fig,"authority_chain.png")


def state_identity():
    fig, ax=base_axes((12.5,6.2))
    ax.text(0.03,0.94,"Exact Identity: Position Is Not Complete Game State",fontsize=18,color=NAVY,fontweight="bold")
    ax.text(0.03,0.875,"Repetition, move-count claims and proof replay require explicit history context.",color=GRAY)
    fields=[
        ("Board","64 squares",BLUE),("Side","white / black",CYAN),("Castling","KQkq mask",PURPLE),
        ("Legal EP right","only if capture is legal",GOLD),("Halfmove","50 / 75 move",ORANGE),("Fullmove","lineage label",MAGENTA),
    ]
    for i,(t,s,c) in enumerate(fields):
        x=0.04+(i%3)*0.31; y=0.63-(i//3)*0.20
        box(ax,x,y,0.27,0.13,t,s,face=LIGHT,edge=c,title_color=c,subtitle_color=INK,lw=1.8)
    box(ax,0.15,0.16,0.31,0.14,"Position SHA-256","board + side + rights + counters",face="#EEF4FF",edge=BLUE,title_color=BLUE,subtitle_color=INK,lw=2)
    box(ax,0.54,0.16,0.31,0.14,"Game-state SHA-256","position + sorted repetition counts + profile",face="#EAF8F2",edge=TEAL,title_color=TEAL,subtitle_color=INK,lw=2)
    for x in (0.175,0.485,0.795): arrow(ax,x,0.43,0.305,0.30,color=MID,connection="arc3,rad=0.12")
    for x in (0.175,0.485,0.795): arrow(ax,x,0.43,0.695,0.30,color=MID,connection="arc3,rad=-0.12")
    ax.text(0.04,0.055,"A 64-bit key is permitted as an index. It is never accepted as the complete proof identity.",color=RED,fontweight="bold",fontsize=9.5)
    save(fig,"state_identity.png")


def wdl_calculus():
    fig, ax=base_axes((12.5,6.2))
    ax.text(0.03,0.94,"Four-Valued WDL Proof Calculus",fontsize=18,color=NAVY,fontweight="bold")
    ax.text(0.03,0.875,"Values are always from the side-to-move perspective; cutoffs stay UNKNOWN.",color=GRAY)
    cards=[
        (0.04,"WIN","exists one verified legal action\nwhose child is LOSS","OR witness",GREEN),
        (0.28,"LOSS","every legal action is covered\nand every child is WIN","AND coverage",RED),
        (0.52,"DRAW","no winning action + verified draw\naction/terminal/closed complement","complete no-win strategy",BLUE),
        (0.76,"UNKNOWN","any edge, history, dead-position\nor checker obligation remains open","safe incomplete status",PURPLE),
    ]
    for x,t,body,label,c in cards:
        ax.add_patch(FancyBboxPatch((x,0.43),0.20,0.29,boxstyle="round,pad=0.015,rounding_size=0.024",facecolor=LIGHT,edgecolor=c,linewidth=2))
        ax.text(x+0.10,0.66,t,ha="center",va="center",color=c,fontweight="bold",fontsize=16)
        ax.text(x+0.10,0.545,body,ha="center",va="center",color=INK,fontsize=8.6,wrap=True)
        ax.text(x+0.10,0.465,label,ha="center",va="center",color=GRAY,fontstyle="italic",fontsize=8.2)
    ax.add_patch(FancyBboxPatch((0.08,0.17),0.84,0.13,boxstyle="round,pad=0.013,rounding_size=0.02",facecolor="#FFF7E9",edgecolor=GOLD,linewidth=1.5))
    ax.text(0.50,0.235,"Claimable threefold/50-move draws are optional actions. Checkmate outranks the automatic 75-move rule.",ha="center",va="center",color=INK,fontweight="bold",fontsize=9.8)
    ax.text(0.03,0.055,"No-mate-within-N, an engine evaluation of 0.00, or a GPU fixed point on an incomplete graph is not a draw proof.",color=RED,fontweight="bold",fontsize=9.3)
    save(fig,"wdl_calculus.png")


def certificate_flow():
    fig, ax=base_axes((12.4,5.8))
    ax.text(0.03,0.93,"Candidate Certificate and Independent Promotion",fontsize=18,color=NAVY,fontweight="bold")
    stages=[
        (0.04,"Worker","leases one shard\nsearches / retrogrades",PURPLE),
        (0.25,"Candidate","full reconstructible node\nchild coverage + hashes",ORANGE),
        (0.46,"Checker","regenerates legal actions\nreplays history + proof",TEAL),
        (0.67,"Campaign ledger","records checker hash\nchanges status to verified",BLUE),
        (0.84,"Root aggregate","consumes verified\nchild WDL values only",MAGENTA),
    ]
    for i,(x,t,s,c) in enumerate(stages):
        box(ax,x,0.49,0.14 if i!=4 else 0.13,0.22,t,s,face=LIGHT,edge=c,title_color=c,subtitle_color=INK,title_size=10,sub_size=8,lw=2)
        if i<len(stages)-1: arrow(ax,x+(0.14 if i!=4 else 0.13),0.60,stages[i+1][0],0.60,color=GRAY,lw=1.8)
    bad=[("score / PV","heuristic"),("64-bit hit","index"),("GPU hash","proposal"),("unverified table","external")]
    for i,(a,b) in enumerate(bad):
        x=0.12+i*0.205
        box(ax,x,0.19,0.16,0.105,a,b,face="#FFF0F0",edge=RED,title_color=RED,subtitle_color=GRAY,title_size=9,sub_size=7.7,lw=1.2)
        arrow(ax,x+0.08,0.295,0.53,0.49,color=RED,lw=1.0,style="-[",connection="arc3,rad=0.15")
    ax.text(0.03,0.07,"Promotion is an event with evidence; a worker never writes authoritative WDL directly.",color=RED,fontweight="bold",fontsize=9.5)
    save(fig,"certificate_flow.png")


def root_obligations():
    workload=json.loads((ROOT/"examples/campaign/initial_depth4_workloads.json").read_text())
    rows=workload["shards"]
    fig,ax=base_axes((12.7,7.2))
    ax.text(0.03,0.95,"The Classical Initial Position Becomes 20 Exact Root Obligations",fontsize=18,color=NAVY,fontweight="bold")
    ax.text(0.03,0.895,"Each child has a full FEN, position hash, game-state hash and repetition-count record.",color=GRAY)
    colors=[BLUE,CYAN,PURPLE,GOLD,ORANGE,TEAL,MAGENTA,GREEN]
    for i,row in enumerate(rows):
        col=i%5; rr=i//5
        x=0.035+col*0.19; y=0.68-rr*0.145
        c=colors[i%len(colors)]
        title=f"{i+1:02d}  {row['move_uci']}"
        sub=f"depth-4 paths: {row['exact_depth4_leaf_paths']:,}\nWDL: UNKNOWN"
        box(ax,x,y,0.165,0.105,title,sub,face=LIGHT,edge=c,title_color=c,subtitle_color=INK,title_size=9.2,sub_size=7.6,lw=1.4)
    ax.add_patch(FancyBboxPatch((0.10,0.07),0.80,0.105,boxstyle="round,pad=0.012,rounding_size=0.02",facecolor="#EEF4FF",edgecolor=BLUE,linewidth=1.5))
    ax.text(0.50,0.122,f"Exact depth-4 legal workload: {workload['total_exact_leaf_paths']:,} leaf paths   |   verified child values: 0   |   root: UNKNOWN",ha="center",va="center",color=INK,fontweight="bold",fontsize=10)
    save(fig,"root_obligations.png")


def campaign_ledger():
    fig,ax=base_axes((12.5,6.2))
    ax.text(0.03,0.94,"Portable SQLite Campaign Ledger",fontsize=18,color=NAVY,fontweight="bold")
    ax.text(0.03,0.875,"Coordination state is mutable; proof records and event hashes make changes auditable.",color=GRAY)
    box(ax,0.05,0.57,0.22,0.18,"jobs table","20 obligations\nlease owner/expiry\ncandidate/checker paths",face=LIGHT,edge=BLUE,title_color=BLUE,subtitle_color=INK,lw=2)
    box(ax,0.39,0.57,0.22,0.18,"events table","append-only sequence\nprev hash + event hash\nreason-coded actions",face=LIGHT,edge=MAGENTA,title_color=MAGENTA,subtitle_color=INK,lw=2)
    box(ax,0.73,0.57,0.22,0.18,"meta table","root FEN + hashes\nrules profile\ncomponent identity",face=LIGHT,edge=TEAL,title_color=TEAL,subtitle_color=INK,lw=2)
    arrow(ax,0.27,0.66,0.39,0.66,color=GRAY,lw=1.8)
    arrow(ax,0.61,0.66,0.73,0.66,color=GRAY,lw=1.8)
    chain=[("genesis",0.08,GOLD),("initialize",0.27,BLUE),("lease",0.46,PURPLE),("candidate",0.65,ORANGE),("verify/reject",0.84,TEAL)]
    for i,(t,x,c) in enumerate(chain):
        ax.add_patch(Circle((x,0.31),0.052,facecolor=WHITE,edgecolor=c,linewidth=2))
        ax.text(x,0.31,t,ha="center",va="center",fontsize=8.1,color=c,fontweight="bold")
        if i<len(chain)-1: arrow(ax,x+0.052,0.31,chain[i+1][1]-0.052,0.31,color=GRAY,lw=1.7)
    ax.text(0.50,0.16,"Campaign files use paths relative to the database directory, so the checkpoint verifies after extraction on another machine.",ha="center",color=INK,fontweight="bold",fontsize=9.5)
    ax.text(0.03,0.055,"Captured ledger: 20 unresolved jobs, 1 initialization event, valid hash chain, root UNKNOWN.",color=RED,fontweight="bold",fontsize=9.5)
    save(fig,"campaign_ledger.png")


def bounded_results():
    mate=json.loads((ROOT/"examples/campaign/bounded_wdl_mate_over_claim.json").read_text())
    initial=json.loads((ROOT/"examples/campaign/bounded_wdl_initial_depth2.json").read_text())
    fig,ax=base_axes((12.4,5.9))
    ax.text(0.03,0.93,"Two Bounded Results, Two Different Proof Statuses",fontsize=18,color=NAVY,fontweight="bold")
    ax.add_patch(FancyBboxPatch((0.05,0.24),0.40,0.54,boxstyle="round,pad=0.018,rounding_size=0.026",facecolor="#EBF7F0",edgecolor=TEAL,linewidth=2))
    ax.text(0.25,0.70,"Mate Overrides Optional Claim",ha="center",color=TEAL,fontweight="bold",fontsize=13)
    ax.text(0.08,0.62,"Position",fontweight="bold",color=INK); ax.text(0.18,0.62,"KQK, halfmove clock 100",color=INK)
    ax.text(0.08,0.54,"Available action",fontweight="bold",color=INK); ax.text(0.22,0.54,"claim 50-move draw",color=INK)
    ax.text(0.08,0.46,"Winning witness",fontweight="bold",color=INK); ax.text(0.22,0.46,"Qa4#",color=INK)
    ax.text(0.08,0.38,"Result",fontweight="bold",color=INK); ax.text(0.18,0.38,mate["root"]["value"].upper(),color=GREEN,fontweight="bold",fontsize=13)
    ax.text(0.08,0.30,f"nodes: {mate['nodes_searched']}  exact: {str(mate['root']['exact']).lower()}",color=GRAY)

    ax.add_patch(FancyBboxPatch((0.55,0.24),0.40,0.54,boxstyle="round,pad=0.018,rounding_size=0.026",facecolor="#F3EFFB",edgecolor=PURPLE,linewidth=2))
    ax.text(0.75,0.70,"Initial Position, Depth 2",ha="center",color=PURPLE,fontweight="bold",fontsize=13)
    ax.text(0.58,0.62,"Root legal moves",fontweight="bold",color=INK); ax.text(0.74,0.62,"20",color=INK)
    ax.text(0.58,0.54,"Searched nodes",fontweight="bold",color=INK); ax.text(0.74,0.54,f"{initial['nodes_searched']:,}",color=INK)
    ax.text(0.58,0.46,"Cutoffs",fontweight="bold",color=INK); ax.text(0.74,0.46,f"{initial['cutoffs']:,}",color=INK)
    ax.text(0.58,0.38,"Result",fontweight="bold",color=INK); ax.text(0.68,0.38,initial["root"]["value"].upper(),color=PURPLE,fontweight="bold",fontsize=13)
    ax.text(0.58,0.30,"No cutoff is relabeled as DRAW.",color=GRAY)
    ax.text(0.03,0.08,"The first certificate closes an existential proof. The second records useful work without overstating what it proves.",color=RED,fontweight="bold",fontsize=9.5)
    save(fig,"bounded_results.png")


def tablebase_counts():
    q=json.loads((ROOT/"data/kqk.tb.json").read_text()); r=json.loads((ROOT/"data/krk.tb.json").read_text())
    labels=["Win","Loss","Draw","Invalid"]
    qv=[q["outcome_counts"][k] for k in ("win","loss","draw","invalid")]
    rv=[r["outcome_counts"][k] for k in ("win","loss","draw","invalid")]
    fig,ax=plt.subplots(figsize=(11.8,5.8)); fig.patch.set_facecolor(WHITE)
    x=range(len(labels)); width=0.36
    ax.bar([i-width/2 for i in x],qv,width,label="KQK")
    ax.bar([i+width/2 for i in x],rv,width,label="KRK")
    ax.set_xticks(list(x),labels); ax.set_ylabel("dense 19-bit cells")
    ax.set_ylim(0,245000)
    ax.set_title("Bundled Exact Three-Piece WDL/DTM Tables",loc="left",fontsize=18,color=NAVY,pad=24)
    ax.grid(axis="y",alpha=0.2); ax.legend(frameon=False,loc="upper right")
    for i,v in enumerate(qv): ax.text(i-width/2,v+3500,f"{v:,}",ha="center",fontsize=7.5,rotation=22)
    for i,v in enumerate(rv): ax.text(i+width/2,v+3500,f"{v:,}",ha="center",fontsize=7.5,rotation=22)
    ax.text(0.01,0.97,f"KQK max DTM {q['max_dtm_plies']} plies   |   KRK max DTM {r['max_dtm_plies']} plies   |   524,288 addresses each",
            transform=ax.transAxes,va="top",color=GRAY,fontsize=8.8)
    fig.subplots_adjust(top=0.82,bottom=0.14,left=0.08,right=0.97)
    save(fig,"tablebase_counts.png")

def native_architecture():
    fig,ax=base_axes((12.5,6.1))
    ax.text(0.03,0.94,"Native C++20 Foundation and Its Boundary",fontsize=18,color=NAVY,fontweight="bold")
    modules=[
        (0.04,0.60,"core.cpp","FEN, legal moves, perft\nstate/repetition hashes",BLUE),
        (0.28,0.60,"search.cpp","deterministic alpha-beta\nfinite mate proof",PURPLE),
        (0.52,0.60,"retrograde_cpu.cpp","generic monotone W/L\nfixed-point demo",TEAL),
        (0.76,0.60,"sha256.cpp","independent content\nhashing",GOLD),
        (0.18,0.30,"ugts-chess2","info / perft / search / prove\nretro-demo / root-shards",ORANGE),
        (0.58,0.30,"ugts-chess-gpu","packed batch / CPU fallback\noptional CUDA / device info",MAGENTA),
    ]
    for x,y,t,s,c in modules: box(ax,x,y,0.20,0.15,t,s,face=LIGHT,edge=c,title_color=c,subtitle_color=INK,title_size=10,sub_size=8,lw=1.8)
    for x in (0.14,0.38,0.62,0.86): arrow(ax,x,0.60,x if x<0.5 else 0.68,0.45,color=MID,lw=1.3,connection="arc3,rad=0.1")
    ax.add_patch(FancyBboxPatch((0.08,0.09),0.84,0.11,boxstyle="round,pad=0.012,rounding_size=0.02",facecolor="#FFF7E8",edgecolor=GOLD,linewidth=1.4))
    ax.text(0.50,0.145,"C++ is an independent legality/performance oracle. Full claim/history WDL authority remains in the Python checker in this release.",ha="center",va="center",color=INK,fontweight="bold",fontsize=9.5)
    save(fig,"native_architecture.png")


def gpu_protocol():
    fig,ax=base_axes((12.5,5.7))
    ax.text(0.03,0.93,"Packed Proposal Protocol",fontsize=18,color=NAVY,fontweight="bold")
    ax.text(0.03,0.86,"The same binary batch is executed by CPU fallback or CUDA, then compared with the Python oracle.",color=GRAY)
    fields=[("12 bitboards","12 x 64-bit occupancy"),("turn/rights/EP","small exact flags"),("move counters","bounded integers"),("reserved","version expansion")]
    x=0.05
    widths=[0.34,0.20,0.20,0.13]
    colors=[BLUE,PURPLE,GOLD,MID]
    for (t,s),w,c in zip(fields,widths,colors):
        box(ax,x,0.58,w,0.14,t,s,face=LIGHT,edge=c,title_color=c if c!=MID else GRAY,subtitle_color=INK,title_size=9.5,sub_size=7.8,lw=1.5)
        x+=w+0.012
    ax.text(0.50,0.50,"PackedPosition = exactly 64 bytes",ha="center",color=NAVY,fontweight="bold",fontsize=11)
    box(ax,0.10,0.23,0.21,0.14,"Python batch writer","UGTSCB20 header\n+ N position records",face="#EEF4FF",edge=BLUE,title_color=BLUE,subtitle_color=INK,lw=1.8)
    box(ax,0.395,0.23,0.21,0.14,"CPU or CUDA expander","up to 256 move16\nproposals per position",face="#F3EFFB",edge=PURPLE,title_color=PURPLE,subtitle_color=INK,lw=1.8)
    box(ax,0.69,0.23,0.21,0.14,"Independent compare","sort/deduplicate UCI\nexact mismatch list",face="#EAF8F2",edge=TEAL,title_color=TEAL,subtitle_color=INK,lw=1.8)
    arrow(ax,0.31,0.30,0.395,0.30,color=GRAY,lw=1.8); arrow(ax,0.605,0.30,0.69,0.30,color=GRAY,lw=1.8)
    ax.text(0.03,0.075,"Captured host fallback: 4 positions, 97 proposed moves, 97 verified moves, 0 mismatches.",color=TEAL,fontweight="bold",fontsize=9.5)
    save(fig,"gpu_protocol.png")


def rtx_memory():
    profile=json.loads((ROOT/"spec/rtx5070ti_profile.json").read_text())
    fig,ax=plt.subplots(figsize=(12.4,6.0)); fig.patch.set_facecolor(WHITE)
    total=profile["nominal_vram_mib"]; alloc=profile["allocation_mib"]
    order=["transposition_and_proof_index","frontier_positions","move_matrix_and_counts","retrograde_edges_and_counters","checkpoint_staging","scratch"]
    labels=["proof index","frontier","moves","retrograde","checkpoint","scratch"]
    colors=[BLUE,CYAN,PURPLE,ORANGE,TEAL,GOLD]
    left=0
    for key,label,c in zip(order,labels,colors):
        val=alloc[key]
        ax.barh([0],[val],left=left,height=0.32,label=f"{label} {val/1024:.1f} GiB",color=c)
        if val>=700: ax.text(left+val/2,0,label,ha="center",va="center",fontsize=7.5,color=WHITE,fontweight="bold")
        left+=val
    ax.barh([0],[profile["reserved_headroom_mib"]],left=left,height=0.32,label="reserved headroom 3.0 GiB",color="#D870C2")
    ax.text(left+profile["reserved_headroom_mib"]/2,0,"headroom",ha="center",va="center",fontsize=7.5,color=INK,fontweight="bold")
    ax.set_xlim(0,total); ax.set_ylim(-0.75,0.75); ax.set_yticks([]); ax.set_xlabel("MiB of nominal 12,288 MiB")
    ax.legend(ncol=3,frameon=False,loc="lower center",bbox_to_anchor=(0.5,-0.38),fontsize=8.0)
    ax.set_title("RTX 5070 Ti Laptop 12 GB Starting Memory Plan",loc="left",fontsize=18,color=NAVY,pad=28)
    ax.text(0.0,1.02,"Runtime free-memory inspection overrides nominal capacity. Allocation failure reduces the batch.",transform=ax.transAxes,color=GRAY,fontsize=9.5)
    ax.text(0.01,0.88,"9 GiB solver budget",transform=ax.transAxes,color=BLUE,fontweight="bold",fontsize=11)
    ax.text(0.80,0.88,"3 GiB reserved",transform=ax.transAxes,color=GRAY,fontweight="bold",fontsize=11)
    ax.text(0.01,0.74,"Initial batch 131,072 | minimum 16,384 | 256 threads/block | 3 streams",transform=ax.transAxes,color=INK,fontsize=9.0)
    ax.text(0.01,0.64,"Target profile: SM120 / compute capability 12.0 | CUDA 12.8 or newer",transform=ax.transAxes,color=INK,fontsize=9.0)
    ax.text(0.01,0.10,"Not a measurement: the packaging host had no nvcc and no physical RTX device.",transform=ax.transAxes,color=RED,fontweight="bold",fontsize=9.2)
    fig.subplots_adjust(top=0.76,bottom=0.23,left=0.06,right=0.98)
    save(fig,"rtx_memory.png")

def codex_workflow():
    fig,ax=base_axes((12.5,6.2))
    ax.text(0.03,0.94,"Codex Promotion Workflow on the Laptop",fontsize=18,color=NAVY,fontweight="bold")
    steps=[
        ("1","Capture device","nvidia-smi, driver,\nfree VRAM, power mode",BLUE),
        ("2","Build SM120","CMake preset\nCUDA 12.8+",PURPLE),
        ("3","Differential test","CPU/Python/CUDA\nmove sets identical",TEAL),
        ("4","Measure","latency, throughput,\nVRAM, thermal, power",GOLD),
        ("5","Extend proof DAG","disk-backed records\nCRC/SHA + checkpoints",ORANGE),
        ("6","Close shards","candidate -> checker\n-> verified WDL",MAGENTA),
    ]
    for i,(num,t,s,c) in enumerate(steps):
        col=i%3; row=i//3
        x=0.05+col*0.31; y=0.58-row*0.27
        ax.add_patch(Circle((x+0.03,y+0.08),0.032,facecolor=c,edgecolor="none"))
        ax.text(x+0.03,y+0.08,num,ha="center",va="center",color=WHITE,fontweight="bold")
        box(ax,x+0.07,y,0.22,0.16,t,s,face=LIGHT,edge=c,title_color=c,subtitle_color=INK,title_size=9.8,sub_size=8,lw=1.7)
        if col<2: arrow(ax,x+0.29,y+0.08,x+0.38,y+0.08,color=GRAY,lw=1.5)
        elif row==0: arrow(ax,0.94,y+0.08,0.08,0.39,color=GRAY,lw=1.5,connection="arc3,rad=-0.25")
    ax.add_patch(FancyBboxPatch((0.09,0.08),0.82,0.10,boxstyle="round,pad=0.012,rounding_size=0.02",facecolor="#FFF0F0",edgecolor=RED,linewidth=1.4))
    ax.text(0.50,0.13,"Any move mismatch, history ambiguity, incomplete AND coverage or hash failure blocks proof promotion.",ha="center",va="center",color=RED,fontweight="bold",fontsize=9.6)
    save(fig,"codex_workflow.png")


def validation_dashboard():
    metrics=[("Python tests",92,"pass"),("C++ CTest",3,"pass"),("Perft checks",20,"pass"),("Root shards",20,"valid"),("GPU diff moves",97,"0 mismatch"),("Tablebases",2,"hash-valid")]
    fig,ax=base_axes((12.4,5.8))
    ax.text(0.03,0.93,"Captured Host Validation Dashboard",fontsize=18,color=NAVY,fontweight="bold")
    for i,(name,val,status) in enumerate(metrics):
        col=i%3; row=i//3; x=0.05+col*0.31; y=0.57-row*0.25
        c=[TEAL,BLUE,PURPLE,GOLD,ORANGE,MAGENTA][i]
        ax.add_patch(FancyBboxPatch((x,y),0.27,0.17,boxstyle="round,pad=0.014,rounding_size=0.02",facecolor=LIGHT,edgecolor=c,linewidth=1.8))
        ax.text(x+0.135,y+0.105,f"{val:,}",ha="center",va="center",color=c,fontweight="bold",fontsize=18)
        ax.text(x+0.135,y+0.055,name,ha="center",va="center",color=INK,fontweight="bold",fontsize=9.5)
        ax.text(x+0.135,y+0.018,status,ha="center",va="center",color=GRAY,fontsize=8.2)
    ax.text(0.05,0.15,"Schemas: 26 records across 5 schema files | clean-install wheel: 332,019 bytes | mate certificate: 4 nodes verified",color=INK,fontweight="bold",fontsize=9.5)
    ax.text(0.05,0.075,"Evidence boundary: host timing is environment-specific; CUDA compile and physical-laptop measurements are pending.",color=RED,fontweight="bold",fontsize=9.3)
    save(fig,"validation_dashboard.png")


def roadmap():
    fig,ax=base_axes((12.4,6.1))
    ax.text(0.03,0.94,"Path Toward a Game-Theoretic Result",fontsize=18,color=NAVY,fontweight="bold")
    phases=[
        ("A","Freeze\nauthority","rules + history\nschemas + legal oracles",TEAL,"DONE"),
        ("B","Proof\ninfrastructure","portable campaign\ndisk DAG + checkers",BLUE,"FOUNDATION"),
        ("C","Exact endgame\ngrowth","external adapters\nmaterial partitions",PURPLE,"OPEN"),
        ("D","Complete draw\nlogic","dead-position certs\nclosed SCC arguments",GOLD,"OPEN"),
        ("E","Root shard\nclosure","parallel exact search\nmerge verified WDL",ORANGE,"OPEN"),
        ("F","Initial\npromotion","WIN / DRAW / LOSS\ncomplete certificate",MAGENTA,"GATE"),
    ]
    for i,(letter,title,body,c,status) in enumerate(phases):
        x=0.035+i*0.16
        ax.add_patch(Circle((x+0.065,0.69),0.043,facecolor=c,edgecolor="none"))
        ax.text(x+0.065,0.69,letter,ha="center",va="center",color=WHITE,fontweight="bold",fontsize=11)
        box(ax,x,0.35,0.135,0.25,title,body,face=LIGHT,edge=c,title_color=c,subtitle_color=INK,title_size=8.7,sub_size=7.1,lw=1.6)
        ax.text(x+0.0675,0.285,status,ha="center",color=c,fontweight="bold",fontsize=7.9)
        if i<len(phases)-1: arrow(ax,x+0.135,0.69,x+0.16,0.69,color=GRAY,lw=1.7)
    ax.add_patch(FancyBboxPatch((0.07,0.07),0.86,0.105,boxstyle="round,pad=0.012,rounding_size=0.02",facecolor="#FFF7E8",edgecolor=GOLD,linewidth=1.4))
    ax.text(0.50,0.122,"Progress is measured by closed, independently verifiable obligations - not by Elo, depth, nodes or GPU occupancy alone.",ha="center",va="center",color=INK,fontweight="bold",fontsize=9.0)
    save(fig,"roadmap.png")

def package_map():
    fig,ax=base_axes((12.4,6.2))
    ax.text(0.03,0.94,"Accompanying ZIP: Complete Codex Handoff",fontsize=18,color=NAVY,fontweight="bold")
    box(ax,0.38,0.74,0.24,0.12,"UGTS_KC_CHESS_2_0","source + specs + evidence",face=NAVY,edge=NAVY,title_color=WHITE,subtitle_color="#D8E5FF",title_size=11,sub_size=8.5,lw=2)
    branches=[
        (0.04,0.52,"src/ugts_chess","Python exact oracle\nWDL + campaign",BLUE),
        (0.28,0.52,"cpp/","C++20 + CUDA\nCMake SM120 presets",PURPLE),
        (0.52,0.52,"examples/campaign","portable SQLite +\n20 root shards",ORANGE),
        (0.76,0.52,"data/","KQK + KRK\ncompressed exact tables",TEAL),
        (0.04,0.23,"spec/","formal definition\n104 mechanisms + schemas",GOLD),
        (0.28,0.23,"scripts/","host + Windows build\nCodex campaign",MAGENTA),
        (0.52,0.23,"validation/","tests + perft + hashes\nGPU differential",GREEN),
        (0.76,0.23,"report/ + docs/","PDF/DOCX foundation\nhandoff and method",CYAN),
    ]
    for x,y,t,s,c in branches:
        box(ax,x,y,0.20,0.15,t,s,face=LIGHT,edge=c,title_color=c,subtitle_color=INK,title_size=9.7,sub_size=8,lw=1.7)
        arrow(ax,0.50,0.74,x+0.10,y+0.15,color=MID,lw=1.2,connection="arc3,rad=0.08")
    ax.text(0.03,0.075,"Uploaded UGTS source PDFs are referenced by hash and not redistributed. Build artifacts are separated from source evidence.",color=GRAY,fontsize=9.3)
    save(fig,"package_map.png")


def main():
    for fn in [cover_architecture,solve_ladder,source_grounding,authority_chain,state_identity,wdl_calculus,
               certificate_flow,root_obligations,campaign_ledger,bounded_results,tablebase_counts,
               native_architecture,gpu_protocol,rtx_memory,codex_workflow,validation_dashboard,roadmap,package_map]:
        fn()
    print(json.dumps({"generated":[p.name for p in sorted(OUT.glob("*.png"))]},indent=2))


if __name__ == "__main__":
    main()
