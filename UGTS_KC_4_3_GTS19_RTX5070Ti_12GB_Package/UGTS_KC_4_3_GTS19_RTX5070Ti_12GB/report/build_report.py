from __future__ import annotations

import html
import json
import math
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report"
OUT = Path("/mnt/data/UGTS_KC_4_3_GTS19_Foundational_Report.pdf")

if not (ROOT / "evidence" / "VALIDATION_PASS").exists():
    raise SystemExit("validation marker missing; refusing to build report")


def load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def fmt_int(value: int) -> str:
    return f"{value:,}"


def fmt_sec(value: float) -> str:
    if value < 0.001:
        return f"{value * 1_000_000:.1f} µs"
    if value < 1:
        return f"{value * 1000:.1f} ms"
    return f"{value:.3f} s"


def status_pill(status: str) -> str:
    cls = {"EXACT": "good", "UNKNOWN": "warn", "PROVEN": "good", "DISPROVEN": "good"}.get(status, "neutral")
    return f'<span class="pill {cls}">{html.escape(status)}</span>'

fixture = load("fixtures/empty_2x2_result.json")
fixture1 = load("fixtures/empty_1x1_result.json")
attempt = load("evidence/attempt19_bounded.json")
selftest = load("evidence/python_selftest.json")
frontier = load("evidence/opening_frontier.json")
memory = load("evidence/memory_plan_10gib_free.json")
bounds = load("evidence/state_space_bounds.json")
cpp_status = load("evidence/cpp_status.json")
cpp_smoke = load("evidence/cpp_smoke.json")

test_text = (ROOT / "evidence/python_unittest.txt").read_text(encoding="utf-8", errors="replace")
match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+([0-9.]+)s", test_text)
test_count = int(match.group(1)) if match else sum(1 for line in test_text.splitlines() if " ... ok" in line)
test_seconds = float(match.group(2)) if match else 0.0

tiny = fixture["result"]
tiny_stats = tiny["stats"]
attempt_result = attempt["result"]
mem_gib = memory["gib"]

# Project source references supplied with this task.
references = [
    ("P1", "UGTS_KC_2_0_Tom_Klootwijk_Expanded_Substrate.pdf", "state/query/event and lineage foundation"),
    ("P2", "UGTS_KC_Two_Hands_3_0_Interactive_Graphics_Runtime.pdf", "proposal, guard, and deterministic commit discipline"),
    ("P3", "UGTS_KC_3_6_Tom_Klootwijk.pdf", "definition-addressed reproducibility"),
    ("P4", "UGTS_KC_3_6_2_SCLP_Tom_Klootwijk.pdf", "finite packing and explicit guard/failure boundaries"),
    ("P5", "UGTS_KC_3_9_KC_Elizabeth_Vector_Game_Runtime.pdf", "deterministic game-runtime lineage"),
    ("P6", "Unified_Geometric_Topological_Substrate_GPU_Native_Addendum.pdf", "GPU-native state and evidence boundary"),
    ("P7", "UGTS_KC_4_2_General_Operator_Order_Addendum(1).pdf", "explicit operator and order serialization"),
    ("P8", "UGTS_KC_4_2_GO_Solver_Report.pdf", "prior Go rules/search/certificate baseline"),
    ("P9", "UGTS_Versioning_Charter_Phase_1_Foundation_Chronology(1).pdf", "version-lineage discipline"),
]

board_svg_lines = []
for i in range(19):
    pos = 44 + i * 15
    board_svg_lines.append(f'<line x1="44" y1="{pos}" x2="314" y2="{pos}"/>')
    board_svg_lines.append(f'<line x1="{pos}" y1="44" x2="{pos}" y2="314"/>')
board_svg = "".join(board_svg_lines)
star_points = [(3,3),(9,3),(15,3),(3,9),(9,9),(15,9),(3,15),(9,15),(15,15)]
stars = "".join(f'<circle cx="{44+x*15}" cy="{44+y*15}" r="2.8"/>' for x,y in star_points)

architecture_svg = '''
<svg viewBox="0 0 900 390" role="img" aria-label="Exact proof architecture">
  <defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#4f6f88"/></marker></defs>
  <g class="arch-box"><rect x="25" y="125" width="170" height="110" rx="14"/><text x="110" y="160">CPU proof</text><text x="110" y="184">coordinator</text><text class="small" x="110" y="212">DFPN · exact guards</text></g>
  <g class="arch-box accent"><rect x="260" y="55" width="190" height="110" rx="14"/><text x="355" y="92">GPU batch engine</text><text class="small" x="355" y="120">bitplanes · groups</text><text class="small" x="355" y="141">candidate expansion</text></g>
  <g class="arch-box"><rect x="260" y="225" width="190" height="110" rx="14"/><text x="355" y="262">Collision-safe</text><text x="355" y="286">history lookup</text><text class="small" x="355" y="313">persistent superko set</text></g>
  <g class="arch-box"><rect x="515" y="55" width="160" height="110" rx="14"/><text x="595" y="93">GPU hot TT</text><text class="small" x="595" y="121">lossless cache</text><text class="small" x="595" y="142">eviction allowed</text></g>
  <g class="arch-box"><rect x="515" y="225" width="160" height="110" rx="14"/><text x="595" y="262">Host + NVMe</text><text class="small" x="595" y="290">immutable segments</text><text class="small" x="595" y="312">checkpoints</text></g>
  <g class="arch-box proof"><rect x="740" y="125" width="135" height="110" rx="14"/><text x="807" y="164">Verifier</text><text class="small" x="807" y="193">Merkle proof</text><text class="small" x="807" y="214">claim gate</text></g>
  <g class="arrows" marker-end="url(#arrow)"><path d="M195 160 L260 120"/><path d="M195 202 L260 265"/><path d="M450 110 L515 110"/><path d="M450 280 L515 280"/><path d="M675 110 L740 155"/><path d="M675 280 L740 210"/><path d="M355 165 L355 225"/><path d="M595 165 L595 225"/></g>
</svg>
'''

pipeline_svg = '''
<svg viewBox="0 0 980 175" role="img" aria-label="UGTS transition operator order">
  <defs><marker id="a2" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#5a7388"/></marker></defs>
  <g class="pipe">
    <rect x="5" y="50" width="90" height="60" rx="10"/><text x="50" y="76">state</text><text x="50" y="96">support</text>
    <rect x="115" y="50" width="90" height="60" rx="10"/><text x="160" y="76">action</text><text x="160" y="96">query</text>
    <rect x="225" y="50" width="90" height="60" rx="10"/><text x="270" y="76">place</text><text x="270" y="96">proposal</text>
    <rect x="335" y="50" width="90" height="60" rx="10"/><text x="380" y="76">capture</text><text x="380" y="96">closure</text>
    <rect x="445" y="50" width="90" height="60" rx="10"/><text x="490" y="76">own</text><text x="490" y="96">liberties</text>
    <rect x="555" y="50" width="90" height="60" rx="10"/><text x="600" y="76">superko</text><text x="600" y="96">guard</text>
    <rect x="665" y="50" width="90" height="60" rx="10"/><text x="710" y="76">atomic</text><text x="710" y="96">commit</text>
    <rect x="775" y="50" width="90" height="60" rx="10"/><text x="820" y="76">content</text><text x="820" y="96">witness</text>
    <rect x="885" y="50" width="90" height="60" rx="10"/><text x="930" y="76">proof</text><text x="930" y="96">update</text>
  </g>
  <g class="arrows" marker-end="url(#a2)">
    <path d="M95 80 L115 80"/><path d="M205 80 L225 80"/><path d="M315 80 L335 80"/><path d="M425 80 L445 80"/><path d="M535 80 L555 80"/><path d="M645 80 L665 80"/><path d="M755 80 L775 80"/><path d="M865 80 L885 80"/>
  </g>
</svg>
'''

css = r'''
@page {
  size: A4;
  margin: 17mm 17mm 18mm 17mm;
  @top-left { content: "UGTS-KC 4.3 · GTS-19"; font-size: 8.5pt; color: #526273; letter-spacing: .08em; }
  @top-right { content: string(chapter); font-size: 8.5pt; color: #526273; }
  @bottom-left { content: "Foundational proof-search attempt · 29 August 2026"; font-size: 8pt; color: #74808a; }
  @bottom-right { content: counter(page) " / " counter(pages); font-size: 8pt; color: #74808a; }
}
@page cover { margin: 0; @top-left { content: none; } @top-right { content: none; } @bottom-left { content: none; } @bottom-right { content: none; } }
@page separator { margin: 0; @top-left { content: none; } @top-right { content: none; } @bottom-left { content: none; } @bottom-right { content: none; } }

* { box-sizing: border-box; }
html { font-family: "DejaVu Sans", Arial, sans-serif; color: #17242d; font-size: 9.35pt; line-height: 1.46; }
body { margin: 0; }
h1, h2, h3, h4 { color: #0b2f49; line-height: 1.16; margin: 0 0 .55em; break-after: avoid; }
h1 { font-size: 25pt; letter-spacing: -.02em; string-set: chapter content(); }
h2 { font-size: 16.5pt; border-bottom: 1.4px solid #b9c9d5; padding-bottom: 4px; margin-top: 1.15em; string-set: chapter content(); }
h3 { font-size: 12pt; margin-top: 1.1em; }
h4 { font-size: 10.3pt; margin-top: .9em; }
p { margin: 0 0 .72em; }
ul, ol { margin: .3em 0 .75em 1.25em; padding: 0; }
li { margin: .22em 0; }
a { color: #0a628d; text-decoration: none; }
strong { color: #102f43; }
code, pre { font-family: "DejaVu Sans Mono", Consolas, monospace; }
code { font-size: .91em; background: #edf3f6; padding: 1px 3px; border-radius: 3px; }
pre { font-size: 7.75pt; line-height: 1.42; white-space: pre-wrap; overflow-wrap: anywhere; background: #0d2231; color: #e9f4f8; padding: 10px 12px; border-radius: 7px; margin: .6em 0 1em; break-inside: avoid; }
blockquote { border-left: 4px solid #e7a33a; margin: 1em 0; padding: .55em .9em; background: #fff8e8; color: #3d3b31; }
.small { font-size: 8.2pt; color: #5d6973; }
.mono { font-family: "DejaVu Sans Mono", monospace; overflow-wrap: anywhere; }
.nowrap { white-space: nowrap; }
.page-break { break-before: page; }
.keep { break-inside: avoid; }

.cover { page: cover; height: 297mm; position: relative; overflow: hidden; background: linear-gradient(145deg, #071827 0%, #0c3348 57%, #0d6570 100%); color: white; padding: 26mm 25mm; }
.cover .eyebrow { text-transform: uppercase; letter-spacing: .18em; font-size: 10pt; opacity: .78; }
.cover h1 { color: white; font-size: 34pt; max-width: 138mm; margin-top: 17mm; }
.cover .subtitle { font-size: 15pt; line-height: 1.4; max-width: 138mm; color: #d9edf0; }
.cover .board { position: absolute; right: -18mm; bottom: 13mm; width: 129mm; height: 129mm; opacity: .42; }
.cover .board line { stroke: #d3f0ed; stroke-width: 1; }
.cover .board circle { fill: #d3f0ed; }
.cover .status-card { position: absolute; left: 25mm; bottom: 29mm; width: 102mm; background: rgba(255,255,255,.105); border: 1px solid rgba(255,255,255,.3); border-radius: 12px; padding: 12px 15px; }
.cover .status-card .label { font-size: 8.5pt; text-transform: uppercase; letter-spacing: .12em; color: #b7dde0; }
.cover .status-card .value { font-size: 19pt; font-weight: 700; margin: 3px 0; }
.cover .meta { position: absolute; top: 26mm; right: 24mm; text-align: right; font-size: 8.5pt; color: #c1d7df; }

.separator { page: separator; height: 297mm; padding: 40mm 28mm; background: #0b2f49; color: white; display: flex; flex-direction: column; justify-content: center; }
.separator .num { font-size: 65pt; font-weight: 800; color: #4fb5b6; line-height: .85; }
.separator h1 { color: white; font-size: 32pt; max-width: 145mm; margin: 8mm 0 5mm; }
.separator p { color: #c7dce5; max-width: 145mm; font-size: 12pt; }

.lede { font-size: 11.2pt; color: #304b5b; }
.callout { border-radius: 8px; padding: 10px 12px; margin: .8em 0 1em; break-inside: avoid; }
.callout.warn { background: #fff4dc; border-left: 5px solid #dc8e18; }
.callout.good { background: #e8f7f1; border-left: 5px solid #17815f; }
.callout.info { background: #eaf3f8; border-left: 5px solid #26789f; }
.callout.danger { background: #fbe9e8; border-left: 5px solid #b6473e; }
.callout .title { font-weight: 700; color: #13364a; margin-bottom: 3px; }

.pill { display: inline-block; font-weight: 700; font-size: 8pt; letter-spacing: .06em; padding: 2px 7px; border-radius: 999px; vertical-align: 1px; }
.pill.good { color: #0b6247; background: #d9f1e7; }
.pill.warn { color: #8a5200; background: #ffedc8; }
.pill.neutral { color: #46545d; background: #e8ecef; }

.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: .8em 0 1em; }
.grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: .8em 0 1em; }
.metric { background: #f1f5f7; border: 1px solid #d9e3e8; border-radius: 8px; padding: 9px 10px; break-inside: avoid; }
.metric .k { text-transform: uppercase; letter-spacing: .08em; font-size: 7.4pt; color: #64747f; }
.metric .v { font-size: 17pt; font-weight: 700; color: #0b4567; margin-top: 2px; }
.metric .d { font-size: 7.8pt; color: #65727a; margin-top: 2px; }

.table-wrap { margin: .6em 0 1em; break-inside: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 8.35pt; }
th { text-align: left; background: #0f405e; color: white; padding: 6px 7px; font-weight: 600; }
td { border-bottom: 1px solid #d7e0e5; padding: 5px 7px; vertical-align: top; }
tr:nth-child(even) td { background: #f5f8fa; }
.num { text-align: right; font-variant-numeric: tabular-nums; }

.toc { margin-top: 7mm; }
.toc h2 { border: 0; }
.toc ol { list-style: none; margin: 0; }
.toc li { margin: 3px 0; border-bottom: 1px dotted #c7d1d7; }
.toc a { display: block; padding: 2px 0; color: #173d54; }
.toc a::after { content: leader('.') target-counter(attr(href), page); float: right; color: #6b7880; }

.equation { background: #f2f6f8; border: 1px solid #d7e2e8; border-radius: 7px; padding: 9px 12px; margin: .7em 0 1em; text-align: center; font-family: "DejaVu Serif", serif; font-size: 11pt; break-inside: avoid; }
.architecture, .pipeline { margin: 1em 0; break-inside: avoid; }
.architecture svg, .pipeline svg { width: 100%; height: auto; }
.arch-box rect { fill: #f2f7f9; stroke: #6f8ea1; stroke-width: 1.5; }
.arch-box.accent rect { fill: #dff2f1; stroke: #269396; }
.arch-box.proof rect { fill: #fff0d2; stroke: #d68c1d; }
.arch-box text { text-anchor: middle; font-size: 18px; font-weight: 700; fill: #173b50; }
.arch-box text.small { font-size: 13px; font-weight: 400; fill: #4f6674; }
.arrows path { fill: none; stroke: #4f6f88; stroke-width: 2; }
.pipe rect { fill: #edf4f7; stroke: #658599; }
.pipe text { text-anchor: middle; font-size: 13px; fill: #173b50; font-weight: 600; }

.memory-bar { display: flex; height: 20px; width: 100%; border-radius: 6px; overflow: hidden; margin: 6px 0; font-size: 7pt; color: white; text-align: center; line-height: 20px; }
.memory-bar span:nth-child(1) { background: #175f82; width: 46%; }
.memory-bar span:nth-child(2) { background: #248ba0; width: 23%; }
.memory-bar span:nth-child(3) { background: #43a8a6; width: 16%; }
.memory-bar span:nth-child(4) { background: #7dbba8; width: 8%; }
.memory-bar span:nth-child(5) { background: #a6c991; width: 7%; }

.checklist { list-style: none; margin-left: 0; }
.checklist li { position: relative; padding-left: 20px; margin: 5px 0; }
.checklist li::before { content: "✓"; position: absolute; left: 0; color: #17815f; font-weight: 800; }
.crosslist { list-style: none; margin-left: 0; }
.crosslist li { position: relative; padding-left: 20px; margin: 5px 0; }
.crosslist li::before { content: "×"; position: absolute; left: 1px; color: #b6473e; font-weight: 800; }

.footnote { font-size: 7.5pt; color: #68757d; border-top: 1px solid #d9e0e4; padding-top: 5px; margin-top: 1em; }
.ref { font-size: 8pt; }
.file-tree { columns: 2; column-gap: 12mm; font-family: "DejaVu Sans Mono", monospace; font-size: 7.4pt; line-height: 1.5; }
'''

# Build dynamic tables.
reference_rows = "".join(
    f"<tr><td><strong>{rid}</strong></td><td class='mono'>{html.escape(name)}</td><td>{html.escape(role)}</td></tr>"
    for rid, name, role in references
)

memory_rows = "".join(
    f"<tr><td>{label}</td><td class='num'>{mem_gib[key]:.3f} GiB</td><td>{purpose}</td></tr>"
    for label, key, purpose in [
        ("Free VRAM supplied to planner", "free_vram", "Example only; target must query runtime"),
        ("Safety reserve", "safety_reserve", "Display/driver variance and allocation margin"),
        ("Usable after reserve", "usable", "Pool distributed below"),
        ("GPU TT cache", "transposition_cache", "Hot proof/state handles; eviction allowed"),
        ("Frontier", "frontier", "Most-proving and expansion records"),
        ("Batch workspace", "batch_workspace", "Bitplanes, group/liberty/capture buffers"),
        ("Proof staging", "proof_staging", "Deltas awaiting durable commit"),
        ("Optional heuristic", "optional_heuristic", "Ordering only; reclaimable"),
    ]
)

html_doc = f'''<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="author" content="UGTS project"><meta name="description" content="Exactness-first game-theoretic search attempt for unrestricted 19x19 Go"><title>UGTS-KC 4.3 GTS-19 Foundational Report</title><style>{css}</style></head>
<body>
<section class="cover">
  <div class="eyebrow">Unified Geometric Topological Substrate · Knowledge Component 4.3</div>
  <div class="meta">Version 4.3.0<br>29 August 2026<br>Foundational release</div>
  <h1>GTS-19: an exactness-first game-theoretic attempt for unrestricted 19×19 Go</h1>
  <p class="subtitle">A pinned mathematical game, collision-safe superko identity, proof-number architecture, GPU/host/NVMe execution plan, validation evidence, and Codex work package for an RTX 5070 Ti 12 GB laptop target.</p>
  <div class="status-card">
    <div class="label">Empty 19×19 root</div>
    <div class="value">UNKNOWN</div>
    <div>A bounded attempt was executed. No game-theoretic winner is claimed.</div>
  </div>
  <svg class="board" viewBox="0 0 358 358" aria-label="19 by 19 Go board"><g>{board_svg}</g><g>{stars}</g></svg>
</section>

<section class="page-break">
  <h1>Document control</h1>
  <div class="grid2">
    <div class="metric"><div class="k">Document</div><div class="v">UGTS-KC 4.3</div><div class="d">GTS-19 foundational report</div></div>
    <div class="metric"><div class="k">Proof target</div><div class="v">19×19</div><div class="d">area · PSK · 7.5 komi</div></div>
    <div class="metric"><div class="k">Hardware target</div><div class="v">12 GB VRAM</div><div class="d">user-specified laptop edition</div></div>
    <div class="metric"><div class="k">Root status</div><div class="v">UNKNOWN</div><div class="d">claim gate remains closed</div></div>
  </div>
  <div class="callout danger"><div class="title">Claim boundary</div>This release does not solve unrestricted 19×19 Go. It defines the exact target, proves the target is finite, supplies sound proof semantics and implementation scaffolding, validates miniature exact results, and records a bounded 19×19 attempt whose status remains <strong>UNKNOWN</strong>.</div>
  <h2>What “unrestricted” means here</h2>
  <p>The mathematical game has no artificial move cap, depth cap, or opening restriction. Practical executions may be bounded by nodes, time, RAM, VRAM, temperature, or disk. Such a stop is operational, not semantic: it returns <code>UNKNOWN</code>.</p>
  <h2>Version relationship</h2>
  <p>KC 4.3 is additive to the KC 4.2 Go solver baseline [P8]. It preserves deterministic rules, exact miniature search, serialized state, and certificates, then adds a pinned 19×19 proof target, threshold proof-number formulation, full-history symmetry constraints, compact GPU layouts, durable storage design, laptop memory policy, claim gates, and a Codex milestone ledger.</p>
  <div class="toc">
    <h2>Contents</h2>
    <ol>
      <li><a href="#executive">1 · Executive determination</a></li>
      <li><a href="#target">2 · Exact game and rules profile</a></li>
      <li><a href="#math">3 · Game-theoretic formulation</a></li>
      <li><a href="#ugts">4 · UGTS operator order</a></li>
      <li><a href="#identity">5 · Exact identity, superko, and symmetry</a></li>
      <li><a href="#search">6 · Search architecture</a></li>
      <li><a href="#gpu">7 · RTX-laptop execution design</a></li>
      <li><a href="#storage">8 · Storage, checkpoints, and certificates</a></li>
      <li><a href="#validation">9 · Validation evidence</a></li>
      <li><a href="#codex">10 · Codex implementation programme</a></li>
      <li><a href="#risks">11 · Failure modes and claim controls</a></li>
      <li><a href="#package">12 · Package map and reproduction</a></li>
      <li><a href="#sources">Appendix · Source integration register</a></li>
    </ol>
  </div>
</section>

<section class="separator"><div class="num">01</div><h1 id="executive">Executive determination</h1><p>The problem is mathematically precise and finite. The delivered implementation is a serious proof-search foundation, but the full 19×19 value remains open in this release.</p></section>

<section>
  <h1>Executive determination</h1>
  <p class="lede">UGTS-KC 4.3 converts “solve Go” into an auditable sequence of exact propositions. It separates what is proven, what is merely implemented, what is measured, and what remains unknown.</p>
  <div class="grid3">
    <div class="metric"><div class="k">Tiny fixture</div><div class="v">{tiny['winner'].title()} {abs(tiny['value_points']):g}</div><div class="d">empty 2×2, exact</div></div>
    <div class="metric"><div class="k">Opening classes</div><div class="v">{selftest['opening_d4_classes_including_pass']}</div><div class="d">55 placements + pass</div></div>
    <div class="metric"><div class="k">19×19 attempt</div><div class="v">{attempt_result['status']}</div><div class="d">threshold score₂ ≥ {attempt_result['threshold2']}</div></div>
  </div>
  <h2>What has been established</h2>
  <ul class="checklist">
    <li>A canonical 19×19 game profile is fully serialized.</li>
    <li>The game is finite under positional superko and two-pass termination.</li>
    <li>Half-point integer utility makes outcome and threshold arithmetic exact.</li>
    <li>Win/loss is represented as an AND/OR proof proposition.</li>
    <li>State identity includes the complete repetition context.</li>
    <li>D4 reduction is defined over board and history together.</li>
    <li>The exact 2×2 regression result is reproduced and certificate-verified.</li>
    <li>Python tests and a dependency-free C++ CPU smoke build pass in the captured evidence.</li>
  </ul>
  <h2>What has not been established</h2>
  <ul class="crosslist">
    <li>No threshold proof for the empty 19×19 root has completed.</li>
    <li>No complete CUDA legal-expansion kernel has been validated.</li>
    <li>No production persistent superko set or NVMe transposition database is finished.</li>
    <li>No standalone 19×19 strategy/proof DAG exists.</li>
    <li>No winner, exact margin, practical solve time, or storage requirement is known.</li>
  </ul>
  <div class="callout info"><div class="title">Useful outcome of the attempt</div>The release replaces an unbounded aspiration with an exact target, a falsifiable claim protocol, working reference code, hardware-aware interfaces, and a staged implementation path. That is meaningful progress without pretending the root was solved.</div>
</section>

<section class="page-break" id="target">
  <h1>2 · Exact game and rules profile</h1>
  <p class="lede">“Standard Go” is not precise enough for a proof. A different scoring system, komi, repetition rule, suicide policy, or end protocol defines a different game. KC 4.3 therefore pins one target.</p>
  <div class="table-wrap"><table>
    <thead><tr><th>Field</th><th>Canonical value</th><th>Reason for serialization</th></tr></thead>
    <tbody>
      <tr><td>Board</td><td>19×19, empty</td><td>Defines topology and root</td></tr>
      <tr><td>First player</td><td>Black</td><td>Part of game state</td></tr>
      <tr><td>Scoring</td><td>Area</td><td>Deterministic terminal utility</td></tr>
      <tr><td>Komi</td><td>7.5 (<code>komi2=15</code>)</td><td>Avoids draws and floating point</td></tr>
      <tr><td>Repetition</td><td>Positional superko</td><td>Makes history semantically relevant</td></tr>
      <tr><td>Suicide</td><td>Illegal</td><td>Changes legal actions and values</td></tr>
      <tr><td>End</td><td>Two consecutive passes</td><td>Explicit terminal condition</td></tr>
      <tr><td>Move/depth cap</td><td>None in game definition</td><td>Unrestricted target</td></tr>
    </tbody>
  </table></div>
  <h2>Profile identity</h2>
  <pre>UGTS-GO19-AREA-PSK-K7.5-v1
configs/go19_canonical.toml
objective: Black can force final score₂ ≥ 1</pre>
  <p>The rules object travels with every checkpoint, certificate, benchmark, and result. A run with 6.5 komi or situational superko is not a continuation of this proof unless it is used only for non-authoritative experimentation.</p>
  <h2>Terminal score</h2>
  <div class="equation">U₂(S) = 2(A<sub>B</sub> − A<sub>W</sub>) − 15</div>
  <p>An empty region counts for one player only when all bordering stones belong to that player; mixed or unbordered regions are neutral. The score is an odd integer in half-point units, so zero cannot occur.</p>
  <div class="callout warn"><div class="title">No post-game dead-stone negotiation</div>The canonical proof target ends and scores mechanically after two passes. Introducing human adjudication would make the terminal function underspecified; a different protocol would need a new profile.</div>
</section>

<section class="page-break" id="math">
  <h1>3 · Game-theoretic formulation</h1>
  <h2>State and minimax value</h2>
  <div class="equation">S = (B, p, r, H, B<sub>−1</sub>)</div>
  <p><em>B</em> is the 361-point board; <em>p</em> is the player to act; <em>r</em> is the pass counter; <em>H</em> is the exact set of prior boards used by positional superko; and <em>B</em><sub>−1</sub> is retained for lineage/cross-profile audit.</p>
  <div class="equation">V(S) = max<sub>a∈L(S)</sub> V(T(S,a)) for Black; &nbsp; min<sub>a∈L(S)</sub> V(T(S,a)) for White</div>
  <p>Terminal states use <em>U</em><sub>2</sub>. This recursion defines the game-theoretic score. It says nothing about the cost of computing it.</p>
  <h2>Why the unrestricted game is finite</h2>
  <p>Every non-pass move under positional superko must produce a board absent from the exact history. At most <span class="mono">3^361</span> board colorings exist. A single pass may occur between non-pass moves, but a second consecutive pass ends the game. Therefore no legal play can be infinite.</p>
  <div class="grid3">
    <div class="metric"><div class="k">Colorings</div><div class="v">3<sup>361</sup></div><div class="d">≈10<sup>{bounds['board_colorings_log10']:.1f}</sup></div></div>
    <div class="metric"><div class="k">Score values</div><div class="v">{bounds['possible_score_values']}</div><div class="d">odd values −737…707</div></div>
    <div class="metric"><div class="k">Threshold questions</div><div class="v">≤{bounds['max_binary_threshold_questions']}</div><div class="d">to isolate exact margin</div></div>
  </div>
  <p class="small">These are logical bounds. They are not tractability estimates and do not imply the laptop can enumerate the state space.</p>
  <h2>Threshold propositions</h2>
  <div class="equation">W<sub>t</sub>(S) ≡ “Black can force U₂ ≥ t from S”</div>
  <p>At a Black node, the proposition is an OR over legal children. At a White node, it is an AND. For the win/loss question, <em>t</em>=1. Proof-number search can focus on the most proving frontier while retaining a binary truth condition.</p>
  <div class="table-wrap"><table>
    <thead><tr><th>Node</th><th>Proof number</th><th>Disproof number</th></tr></thead>
    <tbody>
      <tr><td>Terminal true</td><td>0</td><td>∞</td></tr>
      <tr><td>Terminal false</td><td>∞</td><td>0</td></tr>
      <tr><td>Unknown leaf</td><td>1</td><td>1</td></tr>
      <tr><td>OR (Black)</td><td>min child pn</td><td>sum child dn</td></tr>
      <tr><td>AND (White)</td><td>sum child pn</td><td>min child dn</td></tr>
    </tbody>
  </table></div>
</section>

<section class="page-break" id="ugts">
  <h1>4 · UGTS operator order</h1>
  <p class="lede">The substrate contribution is not a decorative vocabulary. It forces the transition to be a sequence of explicit queries, guards, commits, witnesses, and replayable proof updates [P1–P7].</p>
  <div class="pipeline">{pipeline_svg}</div>
  <h2>Point-move semantics</h2>
  <ol>
    <li>Query an empty point and establish board-topology support.</li>
    <li>Propose placement without mutating the committed state.</li>
    <li>Compute all adjacent opponent components.</li>
    <li>Remove components with no liberties.</li>
    <li>Recompute the placed stone's component after capture.</li>
    <li>Reject forbidden suicide.</li>
    <li>Reject a resulting board in the positional-superko set.</li>
    <li>Atomically commit board, player, pass reset, history insertion, and lineage.</li>
    <li>Emit deterministic content/state witnesses.</li>
    <li>Update proof/disproof data only after every guard passes.</li>
  </ol>
  <h2>Why order is semantic</h2>
  <p>Checking own liberties before removing captured opponents rejects legal captures. Checking superko against a provisional pre-capture board tests the wrong state. Updating a proof number before durable child identity is confirmed can corrupt an entire certificate. The operator sequence is therefore versioned alongside the rules.</p>
  <div class="callout good"><div class="title">Atomicity invariant</div>A move either fails without changing state or commits a complete, replayable successor. GPU work may be speculative; the proof graph sees only verified commits.</div>
  <h2>Pass semantics</h2>
  <p>Pass preserves the board, swaps the player, and increments the consecutive-pass count. It is explicitly exempt from positional board repetition. Two passes produce a terminal state. Any non-pass move resets the counter.</p>
</section>

<section class="page-break" id="identity">
  <h1>5 · Exact identity, superko, and symmetry</h1>
  <h2>Board equality is not state equality</h2>
  <p>Under superko, two nodes with the same current stones can have different legal futures because their prior-board sets differ. A board hash plus player is therefore an unsound transposition key. KC 4.3's Python oracle keys on board, player, pass count, previous board, and the complete sorted history set.</p>
  <div class="callout danger"><div class="title">Forbidden optimization</div>Never reuse an exact proof value merely because current-board hashes match. A hash may select a candidate record; collision-safe complete identity must confirm it.</div>
  <h2>Persistent production identity</h2>
  <p>Copying all of <em>H</em> into each 19×19 node is impractical. The production design uses a persistent content-addressed set: a child history root is derived from the parent root and the inserted exact board object. GPU and host hash tables cache handles, while immutable NVMe segments retain collision-auditable bytes.</p>
  <h2>D4 symmetry</h2>
  <p>Rotation/reflection is sound only when applied to the current board, every history board, and previous-board lineage. With that condition, the empty root's 361 placements collapse exactly to 55 D4 orbits. Pass adds one class, so the first action frontier has <strong>56</strong> canonical classes.</p>
  <div class="grid2">
    <div class="metric"><div class="k">Raw first actions</div><div class="v">362</div><div class="d">361 placements + pass</div></div>
    <div class="metric"><div class="k">D4 exact classes</div><div class="v">56</div><div class="d">validated by selftest</div></div>
  </div>
  <h2>Compact board encoding</h2>
  <p>Two bits encode empty, Black, and White. A 361-point board uses 722 bits, rounded to <strong>91 bytes</strong>. For GPU operations, two six-word bitplanes use 96 bytes and make occupancy masks inexpensive. Metadata and history handles remain in separate arrays.</p>
  <pre>storage:  361 points × 2 bits = 722 bits = 91 bytes
gpu:      6 × uint64 black + 6 × uint64 white = 96 bytes
identity: compact board + exact history-root handle + collision audit</pre>
</section>

<section class="separator"><div class="num">02</div><h1 id="search">Search and execution</h1><p>A sound proof coordinator can exploit GPU batches and storage hierarchy without allowing a heuristic or cache collision to decide truth.</p></section>

<section>
  <h1>6 · Search architecture</h1>
  <div class="architecture">{architecture_svg}</div>
  <h2>Reference and production roles</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Component</th><th>Authority</th><th>Version 4.3 state</th></tr></thead>
    <tbody>
      <tr><td>Python engine</td><td>Readable transition/scoring oracle</td><td>Implemented and tested</td></tr>
      <tr><td>Python alpha-beta</td><td>Exact tiny-board regression</td><td>Implemented; not 19×19 scale</td></tr>
      <tr><td>Python PNS</td><td>Transparent threshold semantics</td><td>Implemented; bounded explicit tree</td></tr>
      <tr><td>C++17 engine</td><td>CPU production baseline</td><td>Transition/scoring smoke implementation</td></tr>
      <tr><td>CUDA occupancy</td><td>Candidate acceleration only</td><td>Implemented scaffold; not full legality</td></tr>
      <tr><td>Persistent history/TT</td><td>Production exact identity</td><td>Specified; implementation milestone</td></tr>
      <tr><td>Standalone proof DAG</td><td>19×19 claim evidence</td><td>Specified; not implemented</td></tr>
    </tbody>
  </table></div>
  <h2>Score-threshold campaign</h2>
  <p>The first campaign asks whether Black can force <code>score2 ≥ 1</code>. A proven root means a Black win; a disproven root means a White win. Only after that result is independently checked should additional thresholds be solved to isolate the exact margin.</p>
  <h2>Move ordering versus proof</h2>
  <p>Captures, center proximity, neural policy, tactical patterns, or prior statistics may decide which child is examined first. They cannot remove a child from an AND quantifier, declare a terminal, set a proof number to zero, or produce an exact score bound without a checkable witness.</p>
  <h2>Transposition records</h2>
  <p>Hot records store proof/disproof numbers, expansion state, compact state/history handles, and child ranges. Cold immutable records retain exact board bytes, persistent-history nodes, lineage, terminal score witnesses, and certificate links. Evicting a GPU cache entry may slow the run but must not lose durable proof state.</p>
</section>

<section class="page-break" id="gpu">
  <h1>7 · RTX-laptop execution design</h1>
  <p class="lede">The target is the user's RTX 5070 Ti laptop configuration with 12 GB nominal VRAM. KC 4.3 avoids architecture-number assumptions and sizes allocations from runtime free memory.</p>
  <h2>Allocation policy</h2>
  <p>Call <code>cudaMemGetInfo</code> after selecting the device. Preserve 18% of the reported free amount. The table below is an <strong>example for 10 GiB free</strong>, not a claim that 10 GiB will be available.</p>
  <div class="memory-bar"><span>TT 46%</span><span>frontier 23%</span><span>batch 16%</span><span>proof 8%</span><span>heur. 7%</span></div>
  <div class="table-wrap"><table>
    <thead><tr><th>Pool</th><th class="num">Example size</th><th>Role</th></tr></thead><tbody>{memory_rows}</tbody>
  </table></div>
  <h2>CUDA implementation boundary</h2>
  <p>The delivered kernel forms exact empty-point masks from black/white bitplanes. This is the first, easily differential-tested stage. A production child batch must still perform group labeling, captures, own-liberty/suicide, exact superko, deterministic encoding, and reference comparison.</p>
  <div class="callout warn"><div class="title">No GPU proof claim in this build</div>The artifact build host's evidence validates the CPU path. The CUDA files are source scaffolding for the target laptop and must be compiled and differentially tested there before becoming proof-authoritative.</div>
  <h2>Laptop-safe operation</h2>
  <ul>
    <li>Adapt batch size after allocation failure or thermal throttling.</li>
    <li>Use watchdog-friendly kernels when the GPU drives the display.</li>
    <li>Checkpoint before suspend, driver update, or long battery operation.</li>
    <li>Keep optional neural ordering memory reclaimable.</li>
    <li>Record exact legal children and proof updates per second—not only raw candidates.</li>
  </ul>
  <h2>Expected bottleneck hierarchy</h2>
  <p>For an exact superko-aware campaign, state identity, irregular history membership, durable TT traffic, and proof graph growth are likely to dominate before simple occupancy arithmetic. The architecture therefore treats the GPU as one layer of a proof system rather than as a self-contained brute-force oracle.</p>
</section>

<section class="page-break" id="storage">
  <h1>8 · Storage, checkpoints, and certificates</h1>
  <h2>Content-addressed history</h2>
  <pre>history_root(parent) + exact inserted board
    -> collision-checked persistent-set node
    -> history_root(child)
    -> immutable segment + SHA-256 manifest</pre>
  <p>GPU caches can use compact hashes, but every proof-changing hit must resolve to collision-safe content. Probabilistic filters may accelerate misses or trigger exact lookups; they cannot reject a legal move by themselves.</p>
  <h2>Checkpoint transaction</h2>
  <ol>
    <li>Stop selecting new batches.</li>
    <li>Finish or discard uncommitted GPU work.</li>
    <li>Flush proof deltas to a write-ahead log.</li>
    <li>Seal immutable segment files.</li>
    <li>Hash segments and write a canonical manifest.</li>
    <li>Atomically replace the checkpoint pointer.</li>
    <li>Reopen and sample-verify before resuming.</li>
  </ol>
  <h2>Two certificate levels</h2>
  <div class="grid2">
    <div class="callout info"><div class="title">Recomputation certificate · delivered</div>Serializes root/rules/result/digests. An independent process reruns the tiny exact solver and confirms the value. Suitable for regression, not a giant standalone proof.</div>
    <div class="callout warn"><div class="title">Strategy/proof DAG · required later</div>Must quantify every relevant child, validate terminal scores, preserve complete history identity, and verify from a clean implementation before a 19×19 solved claim.</div>
  </div>
  <h2>Claim gate</h2>
  <p><code>scripts/claim_gate.py</code> rejects an unfinished result. Even a root proof number of zero is not publishable in 4.3 without the full certificate format and independent verifier. The package intentionally makes overclaiming harder than printing a search log.</p>
</section>

<section class="separator"><div class="num">03</div><h1 id="validation">Evidence and implementation programme</h1><p>Every reported success below comes from captured package evidence. The 19×19 run is explicitly bounded and remains unknown.</p></section>

<section>
  <h1>9 · Validation evidence</h1>
  <div class="grid3">
    <div class="metric"><div class="k">Python tests</div><div class="v">{test_count}/{test_count}</div><div class="d">{fmt_sec(test_seconds)}</div></div>
    <div class="metric"><div class="k">C++ CPU</div><div class="v">PASS</div><div class="d">configure · build · smoke</div></div>
    <div class="metric"><div class="k">19×19 root</div><div class="v">{attempt_result['status']}</div><div class="d">bounded PNS attempt</div></div>
  </div>
  <h2>Exact empty 2×2 regression</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Measure</th><th>Captured value</th></tr></thead>
    <tbody>
      <tr><td>Status</td><td>{status_pill(fixture['status'])}</td></tr>
      <tr><td>Game-theoretic result</td><td>{tiny['winner'].title()} by {abs(tiny['value_points']):g} points</td></tr>
      <tr><td>Half-point utility</td><td><code>{tiny['value2']}</code></td></tr>
      <tr><td>Best move</td><td><code>{html.escape(tiny['best_move_coord'])}</code></td></tr>
      <tr><td>Nodes</td><td>{fmt_int(tiny_stats['nodes'])}</td></tr>
      <tr><td>Terminal nodes</td><td>{fmt_int(tiny_stats['terminals'])}</td></tr>
      <tr><td>Alpha-beta cutoffs</td><td>{fmt_int(tiny_stats['cutoffs'])}</td></tr>
      <tr><td>TT entries</td><td>{fmt_int(tiny_stats['tt_entries'])}</td></tr>
      <tr><td>Maximum ply</td><td>{fmt_int(tiny_stats['max_ply'])}</td></tr>
      <tr><td>Certificate verification</td><td>{status_pill('EXACT')} recomputed and digest-checked</td></tr>
    </tbody>
  </table></div>
  <p class="small">The node count reflects this 4.3 reference solver and its principal-variation reconstruction; it need not match KC 4.2's search accounting.</p>
  <h2>Bounded empty 19×19 attempt</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Measure</th><th>Captured value</th></tr></thead>
    <tbody>
      <tr><td>Status</td><td>{status_pill(attempt_result['status'])}</td></tr>
      <tr><td>Threshold</td><td>Black score₂ ≥ {attempt_result['threshold2']}</td></tr>
      <tr><td>Expanded nodes</td><td>{fmt_int(attempt_result['expanded_nodes'])}</td></tr>
      <tr><td>Generated nodes</td><td>{fmt_int(attempt_result['generated_nodes'])}</td></tr>
      <tr><td>Proof number</td><td>{fmt_int(attempt_result['proof_number'])}</td></tr>
      <tr><td>Disproof number</td><td>{fmt_int(attempt_result['disproof_number'])}</td></tr>
      <tr><td>Maximum explored ply</td><td>{fmt_int(attempt_result['max_ply'])}</td></tr>
      <tr><td>Elapsed</td><td>{fmt_sec(attempt_result['elapsed_seconds'])}</td></tr>
    </tbody>
  </table></div>
  <div class="callout warn"><div class="title">Interpretation</div>Both proof and disproof numbers remained nonzero when the node budget ended. The only valid conclusion is <strong>UNKNOWN</strong>. The run validates transition, score-threshold, and status plumbing; it does not indicate which player wins.</div>
  <h2>C++ smoke evidence</h2>
  <p>Configure/build/smoke exit codes were {cpp_status['configure']}/{cpp_status['build']}/{cpp_status['smoke']}. The smoke executable reported {cpp_smoke['initial_legal_including_pass']} legal initial actions on 5×5 including pass and produced packed bitplanes and a deterministic diagnostic digest.</p>
</section>

<section class="page-break" id="codex">
  <h1>10 · Codex implementation programme</h1>
  <p class="lede">Codex receives a repository-level contract, a ready-to-paste prompt, executable acceptance gates, and ordered milestones. The first target is semantic parity—not an unverifiable performance rewrite.</p>
  <h2>Read/run order</h2>
  <ol>
    <li><code>codex/AGENTS.md</code></li>
    <li><code>docs/EXACTNESS_CONTRACT.md</code></li>
    <li><code>docs/FORMAL_SPEC.md</code></li>
    <li><code>docs/GPU_ARCHITECTURE.md</code></li>
    <li><code>codex/TASKS.md</code></li>
    <li><code>codex/acceptance.sh</code> or <code>acceptance.ps1</code></li>
  </ol>
  <h2>Milestone ladder</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Milestone</th><th>Deliverable</th><th>Exit gate</th></tr></thead>
    <tbody>
      <tr><td>M0</td><td>Reproduce Python/C++ evidence on target</td><td>All baseline gates pass</td></tr>
      <tr><td>M1</td><td>C++ transition/scoring parity</td><td>≥1,000,000 differential transitions, zero mismatches</td></tr>
      <tr><td>M2</td><td>Persistent exact history + NVMe checkpoint</td><td>Restart/collision-injection audit passes</td></tr>
      <tr><td>M3</td><td>Production DFPN coordinator</td><td>Fixture values/certificates match</td></tr>
      <tr><td>M4</td><td>Full exact CUDA expansion</td><td>10,000,000 child comparisons, zero mismatches</td></tr>
      <tr><td>M5</td><td>Proof-safe reductions</td><td>On/off equivalence and witnesses</td></tr>
      <tr><td>M6</td><td>Progressive board-size campaign</td><td>Independent exact verification</td></tr>
      <tr><td>M7</td><td>Empty 19×19 threshold 1</td><td>Root pn=0 or dn=0 plus certificate</td></tr>
      <tr><td>M8</td><td>Exact score margin</td><td>One of 723 scores isolated</td></tr>
    </tbody>
  </table></div>
  <h2>First Codex assignment</h2>
  <blockquote>Implement a deterministic cross-language trace format and differential harness. Compare legal actions, captures, exact board transitions, pass state, positional-superko rejection, terminal recognition, and area score between Python and C++. Minimize every mismatch into a permanent fixture. Do not begin proof-authoritative CUDA work before parity passes.</blockquote>
  <h2>Why this ordering matters</h2>
  <p>A fast legality kernel with one rare ko or capture error can produce a compact, internally consistent, completely false proof. Differential tests and collision injection are therefore foundational performance work: they protect every later optimization.</p>
</section>

<section class="page-break" id="risks">
  <h1>11 · Failure modes and claim controls</h1>
  <div class="table-wrap"><table>
    <thead><tr><th>Failure mode</th><th>Consequence</th><th>Control</th></tr></thead>
    <tbody>
      <tr><td>Board-only TT key</td><td>Illegal superko transposition</td><td>Complete history identity; injected-collision tests</td></tr>
      <tr><td>Hash collision treated as equality</td><td>False legal/repetition/proof value</td><td>Exact content comparison and immutable bytes</td></tr>
      <tr><td>GPU race changes child order/content</td><td>Non-reproducible or missing children</td><td>Deterministic encoding and CPU differential audit</td></tr>
      <tr><td>Proof counter wraps</td><td>False zero or bound</td><td>Saturating declared-width arithmetic</td></tr>
      <tr><td>Neural estimate stored as bound</td><td>Heuristic becomes false proof</td><td>Ordering-only type separation</td></tr>
      <tr><td>Incomplete checkpoint</td><td>Lost or inconsistent proof graph</td><td>WAL, immutable segments, atomic pointer, hashes</td></tr>
      <tr><td>Rules drift</td><td>Solves a different game</td><td>Profile/root digest on every artifact</td></tr>
      <tr><td>Budget stop mislabeled final</td><td>Overclaim</td><td><code>UNKNOWN</code> status and claim gate</td></tr>
      <tr><td>Local decomposition ignores ko threats</td><td>Unsound pruning</td><td>Certified interfaces and external-threat accounting</td></tr>
      <tr><td>Laptop thermal/driver interruption</td><td>Corruption or lost work</td><td>short kernels, adaptive batches, frequent checkpoints</td></tr>
    </tbody>
  </table></div>
  <h2>Publication checklist for a future solved claim</h2>
  <ul class="checklist">
    <li>Canonical rules and empty-root digests match.</li>
    <li>Root proof or disproof number is exactly zero.</li>
    <li>Every quantified child and terminal score is represented or independently derivable.</li>
    <li>Complete repetition identity is verifiable.</li>
    <li>All segment and Merkle hashes verify.</li>
    <li>A clean independent implementation accepts the certificate.</li>
    <li>Result is reproduced after checkpoint restore.</li>
    <li>Remaining assumptions and hardware faults are disclosed.</li>
  </ul>
  <div class="callout danger"><div class="title">Current gate state</div>Closed. The package's bounded root run is UNKNOWN and the standalone 19×19 proof verifier is not yet implemented.</div>
</section>

<section class="page-break" id="package">
  <h1>12 · Package map and reproduction</h1>
  <h2>Core directories</h2>
  <div class="file-tree">
README.md<br>
AGENTS.md<br>
pyproject.toml<br>
src/ugts_go19/<br>
&nbsp;&nbsp;engine.py<br>
&nbsp;&nbsp;exact.py<br>
&nbsp;&nbsp;pns.py<br>
&nbsp;&nbsp;symmetry.py<br>
&nbsp;&nbsp;codec.py<br>
&nbsp;&nbsp;certificate.py<br>
cpp/<br>
&nbsp;&nbsp;CMakeLists.txt<br>
&nbsp;&nbsp;src/go_state.cpp<br>
&nbsp;&nbsp;cuda/packed_kernels.cu<br>
&nbsp;&nbsp;cuda/gpu_probe.cu<br>
configs/<br>
schemas/<br>
docs/<br>
codex/<br>
scripts/<br>
tests/<br>
fixtures/<br>
evidence/<br>
baseline/
  </div>
  <h2>Linux/macOS reproduction</h2>
  <pre>python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
./codex/acceptance.sh</pre>
  <h2>Windows PowerShell reproduction</h2>
  <pre>python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
.\codex\acceptance.ps1</pre>
  <h2>Target-laptop GPU probe</h2>
  <pre>python scripts/hardware_probe.py evidence/local_hardware.json
cmake -S cpp -B build-cuda -DUGTS_ENABLE_CUDA=ON `
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=native
cmake --build build-cuda --config Release</pre>
  <h2>Integrity</h2>
  <p><code>SHA256SUMS.txt</code> covers release files except itself and transient build caches. <code>scripts/verify_release.py</code> checks the manifest. The external PDF and ZIP hashes are supplied with delivery because a file cannot reliably embed its own final hash.</p>
  <h2>Recommended first target run</h2>
  <p>Run M0 and M1 only. Capture hardware and compiler versions, build both references, regenerate tiny certificates, then implement the cross-language differential harness. Do not launch a long 19×19 campaign until exact history/checkpoint and full CUDA legality gates exist.</p>
</section>

<section class="page-break">
  <h1>Conclusion</h1>
  <p class="lede">KC 4.3 does not turn a 12 GB laptop into a magic exhaustive oracle. It turns the request into a precise, finite, testable proof programme whose failures are visible and whose eventual success would be independently checkable.</p>
  <p>The strongest current statements are:</p>
  <ul>
    <li>the canonical unrestricted game is well-defined and finite;</li>
    <li>the first-action symmetry reduction is exact;</li>
    <li>miniature exact search and certificates work;</li>
    <li>the CPU reference path passes captured validation;</li>
    <li>the GPU, storage, and proof interfaces are specified for Codex;</li>
    <li>the empty 19×19 root remains <strong>UNKNOWN</strong>.</li>
  </ul>
  <div class="callout good"><div class="title">Foundation delivered</div>The accompanying ZIP is designed to be opened directly as a Codex repository. Its acceptance gates preserve correctness while Codex ports semantics to C++, completes exact CUDA expansion, implements durable history/TT storage, and advances the progressive proof campaign.</div>
  <h2>Upgrade identifier</h2>
  <pre>UGTS-KC 4.3.0 · GTS-19
proof profile: UGTS-GO19-AREA-PSK-K7.5-v1
hardware target: RTX 5070 Ti Laptop · 12 GB VRAM (user specified)
root outcome: UNKNOWN</pre>
</section>

<section class="page-break" id="sources">
  <h1>Appendix · Source integration register</h1>
  <p>The following project documents were supplied as the substrate lineage. KC 4.3 uses them as conceptual/provenance inputs and preserves the prior Go package under <code>baseline/</code> when available. No unrelated wallet or spatial-scanning semantics enter the Go rules.</p>
  <div class="table-wrap"><table><thead><tr><th>ID</th><th>Artifact</th><th>Integrated role</th></tr></thead><tbody>{reference_rows}</tbody></table></div>
  <h2>Normative files in the 4.3 package</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>File</th><th>Normative scope</th></tr></thead>
    <tbody>
      <tr><td><code>configs/go19_canonical.toml</code></td><td>Rules and proof objective</td></tr>
      <tr><td><code>docs/FORMAL_SPEC.md</code></td><td>State, transition, utility, minimax, threshold semantics</td></tr>
      <tr><td><code>docs/EXACTNESS_CONTRACT.md</code></td><td>Allowed and forbidden optimizations</td></tr>
      <tr><td><code>schemas/*.json</code></td><td>Certificate and checkpoint serialization</td></tr>
      <tr><td><code>codex/AGENTS.md</code></td><td>Agent invariant and claim discipline</td></tr>
    </tbody>
  </table></div>
  <p class="footnote">Generated from captured release evidence on 29 August 2026. Floating-point values in timing tables are measurements of this artifact build only; they are not predictions for the target laptop.</p>
</section>
</body></html>'''

html_path = REPORT / "UGTS_KC_4_3_GTS19_report.html"
html_path.write_text(html_doc, encoding="utf-8")

try:
    from weasyprint import HTML
except Exception as exc:
    raise SystemExit(f"WeasyPrint is required for this report build: {exc}")

HTML(filename=str(html_path), base_url=str(ROOT)).write_pdf(str(OUT))

# Also keep a copy inside the package for a self-contained archive.
shutil.copy2(OUT, ROOT / "UGTS_KC_4_3_GTS19_Foundational_Report.pdf")
print(OUT)
