from __future__ import annotations

from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
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


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output" / "pdf" / "UGTOMS_AI_deterministic_knowledge_conduit.pdf"

PAGE_W, PAGE_H = A4
NAVY = colors.HexColor("#071822")
INK = colors.HexColor("#102A36")
CYAN = colors.HexColor("#00BDD0")
CYAN_DARK = colors.HexColor("#007C8B")
MINT = colors.HexColor("#29B987")
GOLD = colors.HexColor("#EFB643")
MAGENTA = colors.HexColor("#C63A7A")
RED = colors.HexColor("#D4515B")
WHITE = colors.white
MUTED = colors.HexColor("#6C838D")
LINE = colors.HexColor("#C9D7DC")
PALE = colors.HexColor("#EFF5F7")


base = getSampleStyleSheet()
styles = {
    "h1": ParagraphStyle(
        "h1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=21,
        leading=24, textColor=NAVY, spaceAfter=7 * mm,
    ),
    "h2": ParagraphStyle(
        "h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.2,
        leading=14.5, textColor=CYAN_DARK, spaceBefore=3 * mm, spaceAfter=2 * mm,
    ),
    "body": ParagraphStyle(
        "body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.25,
        leading=13.1, textColor=INK, spaceAfter=3 * mm,
    ),
    "small": ParagraphStyle(
        "small", parent=base["BodyText"], fontName="Helvetica", fontSize=7.4,
        leading=9.7, textColor=INK,
    ),
    "caption": ParagraphStyle(
        "caption", parent=base["BodyText"], fontName="Helvetica-Oblique", fontSize=7.2,
        leading=9.2, textColor=MUTED, alignment=TA_CENTER, spaceBefore=2 * mm,
    ),
    "quote": ParagraphStyle(
        "quote", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=13.2,
        leading=18, textColor=NAVY,
    ),
    "cover_kicker": ParagraphStyle(
        "cover_kicker", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=8.5,
        leading=11, textColor=CYAN, spaceAfter=4 * mm,
    ),
    "cover_title": ParagraphStyle(
        "cover_title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=35,
        leading=38, textColor=WHITE, spaceAfter=5 * mm,
    ),
    "cover_sub": ParagraphStyle(
        "cover_sub", parent=base["BodyText"], fontName="Helvetica", fontSize=14,
        leading=19, textColor=colors.HexColor("#D6E7EC"), spaceAfter=5 * mm,
    ),
    "cover_meta": ParagraphStyle(
        "cover_meta", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5,
        leading=12, textColor=colors.HexColor("#9FB7C1"),
    ),
    "right": ParagraphStyle(
        "right", parent=base["BodyText"], fontName="Helvetica", fontSize=7.2,
        leading=9, textColor=MUTED, alignment=TA_RIGHT,
    ),
}


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, styles[style])


def table(headers: list[str], rows: list[list[str]], widths: list[float], small: bool = False) -> Table:
    style_name = "small" if small else "body"
    data = [[Paragraph(f"<b>{h}</b>", styles["small"]) for h in headers]]
    data.extend([[Paragraph(cell, styles[style_name]) for cell in row] for row in rows])
    result = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.7 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.7 * mm),
    ]))
    return result


def callout(title: str, text: str, accent=CYAN, background=PALE) -> Table:
    body = Paragraph(f"<b>{title}</b><br/><br/>{text}", styles["body"])
    result = Table([[body]], colWidths=[174 * mm])
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
        ("BOX", (0, 0), (-1, -1), 0.35, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
    ]))
    return result


def flow_diagram() -> Drawing:
    drawing = Drawing(174 * mm, 62 * mm)
    box_w = 26 * mm
    box_h = 24 * mm
    gap = 3.4 * mm
    labels = [
        ("HUMAN", "sources\nclaims"),
        ("CANONICAL", "typed ingest\nprovenance"),
        ("UGTOMS", "knowledge\nsubstrate"),
        ("SELECT", "policy + need\nguards"),
        ("MATERIALIZE", "bounded\nanswer"),
        ("PRESENT", "optional LLM\ninterface"),
    ]
    accents = [CYAN, CYAN, MINT, GOLD, MINT, MAGENTA]
    y = 24 * mm
    for index, ((title, subtitle), accent) in enumerate(zip(labels, accents)):
        x = index * (box_w + gap)
        drawing.add(Rect(x, y, box_w, box_h, 3, 3, fillColor=colors.HexColor("#F4F8F9"), strokeColor=accent, strokeWidth=1.1))
        drawing.add(String(x + box_w / 2, y + 15.5 * mm, title, fontName="Helvetica-Bold", fontSize=6.4, textAnchor="middle", fillColor=NAVY))
        for line_index, line in enumerate(subtitle.split("\n")):
            drawing.add(String(x + box_w / 2, y + (9.5 - line_index * 3.3) * mm, line, fontName="Helvetica", fontSize=5.7, textAnchor="middle", fillColor=INK))
        if index < len(labels) - 1:
            x1 = x + box_w
            x2 = x + box_w + gap
            drawing.add(Line(x1 + 0.7 * mm, y + box_h / 2, x2 - 1.2 * mm, y + box_h / 2, strokeColor=MUTED, strokeWidth=0.9))
            drawing.add(Polygon([x2 - 1.2 * mm, y + box_h / 2 + 1.2 * mm, x2, y + box_h / 2, x2 - 1.2 * mm, y + box_h / 2 - 1.2 * mm], fillColor=MUTED, strokeColor=MUTED))
    drawing.add(Rect(0, 2 * mm, 174 * mm, 13 * mm, 3, 3, fillColor=NAVY, strokeColor=NAVY))
    drawing.add(String(87 * mm, 9.3 * mm, "Every authoritative output carries source, version, policy, derivation and an explicit UNKNOWN path.", fontName="Helvetica-Bold", fontSize=7.5, textAnchor="middle", fillColor=WHITE))
    return drawing


def split_model() -> Drawing:
    drawing = Drawing(174 * mm, 57 * mm)
    left = 5 * mm
    right = 92 * mm
    drawing.add(Rect(left, 8 * mm, 77 * mm, 42 * mm, 4, 4, fillColor=colors.HexColor("#FCEFF5"), strokeColor=MAGENTA, strokeWidth=1.2))
    drawing.add(String(left + 38.5 * mm, 43 * mm, "LLM-ONLY ANSWER PATH", fontName="Helvetica-Bold", fontSize=9, textAnchor="middle", fillColor=NAVY))
    for idx, text in enumerate(["Prompt mixes fact, policy and style", "Model predicts plausible tokens", "Confidence may sound stronger than evidence", "Missing knowledge can become invented detail"]):
        drawing.add(String(left + 5 * mm, (35 - idx * 7) * mm, "+ " + text, fontName="Helvetica", fontSize=7, fillColor=INK))
    drawing.add(Rect(right, 8 * mm, 77 * mm, 42 * mm, 4, 4, fillColor=colors.HexColor("#EAF7F2"), strokeColor=MINT, strokeWidth=1.2))
    drawing.add(String(right + 38.5 * mm, 43 * mm, "UGTOMS-CONDUIT PATH", fontName="Helvetica-Bold", fontSize=9, textAnchor="middle", fillColor=NAVY))
    for idx, text in enumerate(["Facts, claims, policy and presentation are typed", "Deterministic gates select permitted material", "Derivation and provenance travel with output", "Missing support returns UNKNOWN or asks a human"]):
        drawing.add(String(right + 5 * mm, (35 - idx * 7) * mm, "+ " + text, fontName="Helvetica", fontSize=7, fillColor=INK))
    return drawing


def cover(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setStrokeColor(colors.HexColor("#113644"))
    canvas.setLineWidth(0.5)
    for x in range(-100, 800, 36):
        canvas.line(x, 0, x + 185, PAGE_H)
    canvas.setFillColor(CYAN)
    canvas.rect(18 * mm, 24 * mm, 24 * mm, 2 * mm, fill=1, stroke=0)
    canvas.setFont("Helvetica", 6.7)
    canvas.setFillColor(colors.HexColor("#91AAB4"))
    canvas.drawString(18 * mm, 16 * mm, "CONCEPT NOTE - PROPOSED ARCHITECTURE, NOT A SAFETY OR TRUTH CERTIFICATION")
    canvas.restoreState()


def later(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(WHITE)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 11 * mm, PAGE_W, 11 * mm, fill=1, stroke=0)
    canvas.setFillColor(CYAN)
    canvas.rect(0, PAGE_H - 11 * mm, 28 * mm, 1.3 * mm, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(WHITE)
    canvas.drawString(18 * mm, PAGE_H - 7.2 * mm, "UGTOMS AI - DETERMINISTIC KNOWLEDGE CONDUIT")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 12 * mm, PAGE_W - 18 * mm, 12 * mm)
    canvas.setFont("Helvetica", 6.6)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 8.5 * mm, "Concept note v0.1 | 30 August 2026 | Tom Klootwijk")
    canvas.drawRightString(PAGE_W - 18 * mm, 8.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def story() -> list:
    items = [
        Spacer(1, 38 * mm),
        p("UGTOMS AI APPLICATIONS", "cover_kicker"),
        p("Deterministic Knowledge Conduit", "cover_title"),
        p("Restructuring AI around human knowledge storage, verified distribution, and individual need.", "cover_sub"),
        Spacer(1, 9 * mm),
        p("Tom Klootwijk | UGTOMS concept note v0.1", "cover_meta"),
        p("30 August 2026 | Companion to the UGTOMS cross-domain pilot overview", "cover_meta"),
        Spacer(1, 16 * mm),
        p("Core proposition", "cover_kicker"),
        p("The model should not be the memory, the authority, the policy engine, and the narrator at the same time. UGTOMS separates those roles. Human knowledge becomes typed, versioned, attributable substrate; deterministic gates select what applies; an LLM may remain as an optional interface, never the source of truth.", "cover_sub"),
        PageBreak(),
    ]

    items.extend([
        p("The restructuring", "h1"),
        callout(
            "Position",
            "UGTOMS reorganizes AI from a free-form answer generator into a controlled conduit. It stores claims with meaning and lineage, selects them under explicit rules, materializes only supported outputs, and returns UNKNOWN when the substrate does not justify an answer.",
            CYAN,
        ),
        Spacer(1, 4 * mm),
        flow_diagram(),
        p("A technically honest correction", "h2"),
        p("Calling conventional LLMs floating-point brute forcers captures a real frustration but is not technically precise. They are learned statistical functions, commonly executed with floating-point, reduced-precision, or quantized matrix arithmetic. They compress and interpolate patterns; they do not merely enumerate answers. Their central limitation is different: next-token plausibility is not an inherent truth, provenance, permission, or applicability check.", "body"),
        split_model(),
        p("The complete change is architectural: separate source memory, claim semantics, deterministic selection, user policy, derivation, presentation, and action authority. A probabilistic model can still be excellent at proposing links, summarizing, translating, and conversing, while being structurally unable to silently promote a guess into an authoritative fact.", "body"),
        PageBreak(),
    ])

    items.extend([
        p("Applications centered on individual need", "h1"),
        p("Individualization is a deterministic materialization profile, not an invitation to manipulate the user. The profile should be inspectable, consented, reversible, and limited to what is needed for the task.", "body"),
        table(
            ["Application", "UGTOMS role", "Individual materialization", "Authority boundary"],
            [
                ["Education", "Prerequisites, concepts, examples, exercises, misconceptions, and mastery evidence as typed relations.", "Language, reading level, accessibility, prior mastery, pace, and learning goal.", "Tutor may adapt explanation; curriculum facts and assessment rules remain versioned."],
                ["Healthcare support", "Guidelines, observations, contraindications, evidence levels, and care pathways with provenance.", "Condition, language, accessibility, consent, and clinician-approved context.", "No autonomous diagnosis. Missing or conflicting support escalates to a qualified human."],
                ["Law and civic services", "Statutes, versions, jurisdiction, eligibility rules, forms, deadlines, and cited decisions.", "Jurisdiction, role, language, case facts, permissions, and requested procedure.", "Not legal authority; preserve exact source text and effective dates."],
                ["Engineering and manufacturing", "Requirements, components, tolerances, procedures, hazards, evidence, and standards adapters.", "Machine, material, operator qualification, revision, and task stage.", "Simulation, conformance, metrology, and human release remain mandatory."],
                ["Science", "Datasets, methods, assumptions, units, models, claims, counterclaims, and reproducible derivations.", "Field, instrument, uncertainty need, compute budget, and desired abstraction.", "Model-generated hypotheses remain proposals until evidence closes the claim."],
                ["Personal knowledge", "A private lifelong graph of sources, decisions, skills, memories, permissions, and unresolved questions.", "Current goal, privacy boundary, attention budget, device, and preferred explanation style.", "The person owns correction and deletion controls; sensitive context does not leak into shared output."],
                ["Institutions", "Policies, procedures, ownership, dependencies, exceptions, incident evidence, and change lineage.", "Role, clearance, location, competence, and active responsibility.", "Access rules and accountability must be explicit and independently auditable."],
                ["Agents and automation", "Typed goals, capabilities, preconditions, budgets, action routes, receipts, rollback, and approval gates.", "User-approved risk, scope, deadline, and resource constraints.", "LLM proposes; deterministic policy and external systems authorize and commit."],
            ],
            [29 * mm, 56 * mm, 47 * mm, 42 * mm],
            small=True,
        ),
        Spacer(1, 4 * mm),
        callout(
            "Like I am five",
            "Instead of asking a storyteller to remember every book and never make anything up, give it a labeled library, a rule card, and a receipt printer. It may explain the right pages in a way that fits you. If the right page is missing, it must say so rather than invent one.",
            MINT,
            colors.HexColor("#EAF7F2"),
        ),
        PageBreak(),
    ])

    items.extend([
        p("What makes the conduit deterministic", "h1"),
        table(
            ["Layer", "Required behavior", "Failure behavior"],
            [
                ["Canonical knowledge", "Typed identities, claims, units, scope, version, source, rights, confidence class, and contradiction links.", "Unsupported input is preserved literally or quarantined; it is not silently normalized into a claim."],
                ["Selection", "Deterministic query plan over role, task, permissions, policy, time, location, and evidence requirements.", "Ambiguity returns alternatives, requests missing context, or yields UNKNOWN."],
                ["Derivation", "Versioned bounded operators with declared inputs, outputs, numeric domains, tolerances, and proof or trace hooks.", "Out-of-domain, unsafe, or non-convergent operations fail closed."],
                ["Personalization", "An inspectable profile changes ordering, detail, language, accessibility, examples, and pace.", "It must not rewrite source facts, hide relevant risk, or infer sensitive traits without authority."],
                ["Presentation", "Templates or an optional LLM turn selected material into readable language while preserving citations and claim labels.", "Generated wording cannot add unsupported facts; validators compare it with the selected substrate."],
                ["Action", "Capabilities, preconditions, budgets, approvals, receipts, idempotency, and rollback are separate from conversation.", "No verified route means no commit. A plausible sentence is never permission to act."],
                ["Update and memory", "New observations enter as proposed novelty, pass source and compatibility checks, then receive content-addressed lineage.", "Conflicts remain visible; history is not rewritten to create false certainty."],
            ],
            [35 * mm, 83 * mm, 56 * mm],
            small=True,
        ),
        p("Tests stay, but move out of the creative hot path", "h2"),
        p("Tests are not the product, yet they are how a deterministic conduit earns trust. Authoring should stay fast. Conformance runs at publication, decoder, policy, deployment, and high-risk action boundaries. Golden vectors, independent readers, malformed-input rejection, provenance checks, tolerance budgets, and action receipts prevent the substrate from becoming deterministic theater.", "body"),
        callout(
            "Minimum acceptance rule",
            "Two implementations must agree on canonical identity and declared output; every answer must expose its source and transformation route; missing support must remain missing; and personalization must be reversible without changing authoritative knowledge.",
            GOLD,
            colors.HexColor("#FFF7E7"),
        ),
        PageBreak(),
    ])

    items.extend([
        p("Boundaries and first build", "h1"),
        p("What UGTOMS does not solve by determinism alone", "h2"),
        table(
            ["Risk", "Why it remains", "Required response"],
            [
                ["False source", "A deterministic pipeline can reproduce wrong or malicious information perfectly.", "Source reputation, contradiction handling, independent evidence, human governance, and revocation."],
                ["Ontology bias", "Typed categories can exclude people or encode one institution's worldview.", "Plural profiles, appeal paths, visible assumptions, community review, and literal residual preservation."],
                ["Privacy", "Individual need often requires sensitive context.", "Local-first profiles, minimum disclosure, purpose limits, encryption, audit, deletion, and consent."],
                ["Stale knowledge", "Versioned truth can still be out of date.", "Effective dates, freshness rules, dependency invalidation, and explicit stale-state output."],
                ["Over-automation", "A correct description is not necessarily authority to act.", "Separate knowledge, recommendation, authorization, execution, receipt, and rollback layers."],
                ["Universal-codec overclaim", "Different domains retain different semantics and evidence requirements.", "Use a common envelope and adapter contract, not one forced byte layout or one universal truth model."],
            ],
            [35 * mm, 70 * mm, 69 * mm],
            small=True,
        ),
        p("Small first pilot", "h2"),
        table(
            ["Step", "Deliverable", "Observable pass"],
            [
                ["1", "Ingest one bounded technical manual and its revision history into typed claims plus literal source blocks.", "Every claim points to exact source, scope, version, and rights."],
                ["2", "Define three user profiles: novice operator, qualified technician, and auditor.", "Same authority; different order, detail, vocabulary, and permitted operations."],
                ["3", "Run deterministic selection and template materialization before adding an LLM presenter.", "Identical inputs produce identical claim sets and hashes."],
                ["4", "Add the LLM only as translator, explainer, question parser, and proposal generator.", "Unsupported additions are rejected; citations survive paraphrase."],
                ["5", "Add one bounded agent action with preview, approval, idempotency, receipt, and rollback.", "No action occurs without a verified route and explicit authority."],
            ],
            [15 * mm, 93 * mm, 66 * mm],
            small=True,
        ),
        Spacer(1, 4 * mm),
        callout(
            "The compact thesis",
            "Human knowledge is the durable substrate. UGTOMS is the typed conduit. Deterministic gates decide what applies. Individual profiles decide how it is materialized. LLMs remain valuable as probabilistic interfaces and proposal engines, but they do not get to define truth, permission, or irreversible action.",
            CYAN,
        ),
        Spacer(1, 4 * mm),
        p("Corpus anchors: GSP4 deterministic support/compatibility/guard flow; UGTS-GN packed state and verified-event routing; Foundation content-addressed operator cells; KSEED evidence/novelty ledger; current UGTS ECS, visual graph, polar LUT and Bayer pilot. These demonstrate recurring mechanisms, not a completed universal AI product.", "caption"),
        p("Document status: conceptual application note. No claim of AGI, guaranteed truth, regulatory approval, or universal interoperability.", "right"),
    ])
    return items


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title="UGTOMS AI - Deterministic Knowledge Conduit",
        author="Tom Klootwijk",
        subject="Conceptual AI applications for UGTOMS as a deterministic human-knowledge conduit",
    )
    doc.build(story(), onFirstPage=cover, onLaterPages=later)
    print(OUTPUT)


if __name__ == "__main__":
    main()
