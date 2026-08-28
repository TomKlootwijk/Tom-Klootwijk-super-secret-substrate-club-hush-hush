#!/usr/bin/env python3
"""Generate the UGTS-KC 3.9.4 Bayer Direct release report and figures."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image as RLImage,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfbase.pdfmetrics import stringWidth

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "report"
FIG_DIR = REPORT_DIR / "figures"
PDF_PATH = REPORT_DIR / "UGTS_KC_3_9_4_Bayer_Direct_Native_Tom_Klootwijk.pdf"
APK_PATH = ROOT / "dist" / "UGTS_KC_Bayer_Direct_3_9_4_arm64-v8a.apk"
SO_PATH = ROOT / "validation" / "freestanding_build" / "libugts_kc_bayer.so"
MONTAGE_PATH = ROOT / "preview" / "bayer_modes_montage.png"
PREVIEW_PATH = ROOT / "preview" / "bayer_direct_preview.png"
CATALOG_PATH = ROOT / "spec" / "bayer_direct_mechanisms_M610_M629.csv"
BENCH_PATH = ROOT / "validation" / "host_benchmark_summary.json"

OLD_APK_BYTES = 1_040_086
OLD_SO_BYTES = 992_256
DATE_TEXT = "28 August 2026"

NAVY = "#0b1733"
NAVY2 = "#17264b"
CYAN = "#23c4d9"
TEAL = "#2ec4a6"
BLUE = "#4c78ff"
PURPLE = "#8e6de9"
GOLD = "#e2b73b"
ORANGE = "#ed8a42"
RED = "#d55d5d"
PALE = "#eef4fb"
PALE2 = "#f6f8fc"
INK = "#111827"
MUTED = "#58677d"
WHITE = "#ffffff"
GREEN = "#3ca66b"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def rounded_box(draw: ImageDraw.ImageDraw, box, fill, outline, radius=18, width=3):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def centered_text(draw: ImageDraw.ImageDraw, box, text: str, fnt, fill=WHITE, line_gap=4):
    x0, y0, x1, y1 = box
    lines = text.split("\n")
    bboxes = [draw.textbbox((0, 0), line, font=fnt) for line in lines]
    heights = [b[3] - b[1] for b in bboxes]
    total_h = sum(heights) + line_gap * (len(lines) - 1)
    y = y0 + (y1 - y0 - total_h) / 2
    for line, bbox, h in zip(lines, bboxes, heights):
        w = bbox[2] - bbox[0]
        draw.text((x0 + (x1 - x0 - w) / 2, y), line, font=fnt, fill=fill)
        y += h + line_gap


def arrow(draw: ImageDraw.ImageDraw, start, end, color=GOLD, width=5):
    draw.line([start, end], fill=color, width=width)
    ang = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 16
    for delta in (2.55, -2.55):
        p = (end[0] + length * math.cos(ang + delta), end[1] + length * math.sin(ang + delta))
        draw.line([end, p], fill=color, width=width)


def generate_architecture(path: Path):
    W, H = 1800, 820
    im = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(im)
    d.text((70, 42), "UGTS-KC 3.9.4 - Bayer Direct native hot path", font=font(48, True), fill=WHITE)
    d.text((70, 102), "Direct field samples become pixels; geometry presentation systems are absent from the APK.", font=font(26), fill="#aebbd4")

    boxes = [
        (70, 245, 330, 465, "typed seed + tick\nmode + profile", CYAN),
        (380, 245, 680, 465, "integer field\nF_mode(x,y,q)", TEAL),
        (730, 245, 990, 465, "8x8 Bayer\nthreshold 0..63", PURPLE),
        (1040, 245, 1270, 465, "4-level\nRGB565 palette", ORANGE),
        (1320, 245, 1600, 465, "ANativeWindow\nlock / write / post", BLUE),
    ]
    for i, (x0, y0, x1, y1, label, col) in enumerate(boxes):
        rounded_box(d, (x0, y0, x1, y1), NAVY2, col, radius=20, width=4)
        centered_text(d, (x0+14, y0+10, x1-14, y1-10), label, font(30, True))
        if i < len(boxes) - 1:
            arrow(d, (x1 + 12, (y0+y1)//2), (boxes[i+1][0] - 12, (y0+y1)//2))

    rounded_box(d, (1265, 565, 1650, 710), "#172c36", GREEN, radius=16, width=3)
    centered_text(d, (1280, 576, 1635, 698), "Android system compositor\nscales to the panel\n(downstream only)", font(24, True))
    arrow(d, (1460, 477), (1460, 553), color=GREEN, width=4)

    rounded_box(d, (70, 560, 1190, 710), "#341a27", RED, radius=16, width=3)
    centered_text(
        d,
        (90, 574, 1170, 698),
        "NOT IN THE INSTALLABLE HOT PATH\nscene - mesh - texture - shader - camera - lighting - depth\nOpenGL ES - Vulkan - ray traversal - ray marching",
        font(22, True),
        fill="#ffd9df",
    )
    d.text((70, 755), "Authoritative state remains in definitions, events and lineage. The display is a replaceable projection.", font=font(25), fill="#b9c7df")
    im.save(path, optimize=True)


def generate_bayer(path: Path):
    matrix = [
         0,48,12,60,3,51,15,63,
        32,16,44,28,35,19,47,31,
         8,56,4,52,11,59,7,55,
        40,24,36,20,43,27,39,23,
         2,50,14,62,1,49,13,61,
        34,18,46,30,33,17,45,29,
        10,58,6,54,9,57,5,53,
        42,26,38,22,41,25,37,21,
    ]
    W, H = 1200, 1060
    im = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(im)
    d.text((50, 35), "Exact 8x8 Bayer threshold permutation", font=font(46, True), fill=INK)
    d.text((50, 95), "Every threshold 0..63 occurs once. The matrix is a deterministic quantizer, not frame history.", font=font(25), fill=MUTED)
    cell = 102
    ox, oy = 185, 180
    for y in range(8):
        for x in range(8):
            v = matrix[y*8+x]
            t = v/63
            bg = (int(12 + 54*t), int(28 + 170*t), int(58 + 150*t))
            x0, y0 = ox+x*cell, oy+y*cell
            d.rectangle((x0,y0,x0+cell,y0+cell), fill=bg, outline=WHITE, width=3)
            txt = str(v)
            fnt = font(31, True)
            bb = d.textbbox((0,0), txt, font=fnt)
            d.text((x0+(cell-(bb[2]-bb[0]))/2, y0+(cell-(bb[3]-bb[1]))/2-3), txt, font=fnt, fill=WHITE if v < 43 else INK)
    formula = "k = min(3, floor((4*L + 4*B8[x mod 8,y mod 8]) / 256))"
    rounded_box(d, (90, 1025-100, 1110, 1025-20), PALE, BLUE, radius=15, width=3)
    centered_text(d, (105, 930, 1095, 1000), formula, font(25, True), fill=INK)
    im.save(path, optimize=True)


def draw_log_bars(draw, x0, y0, width, height, pairs):
    # pairs: label, old, new, color
    maxv = max(v for _, o, n, _ in pairs for v in (o,n))
    logmax = math.log10(maxv)
    barw = width // (len(pairs)*2 + len(pairs)+1)
    cursor = x0 + barw
    for label, old, new, col in pairs:
        for name, value, fill in [("supplied", old, "#9aa7ba"), ("3.9.4", new, col)]:
            bh = int((math.log10(value) / logmax) * height)
            draw.rounded_rectangle((cursor, y0+height-bh, cursor+barw, y0+height), radius=8, fill=fill)
            val = f"{value:,} B"
            fnt = font(22, True)
            bb = draw.textbbox((0,0), val, font=fnt)
            draw.text((cursor+(barw-(bb[2]-bb[0]))/2, y0+height-bh-34), val, font=fnt, fill=INK)
            nm = name
            f2 = font(20)
            bb = draw.textbbox((0,0), nm, font=f2)
            draw.text((cursor+(barw-(bb[2]-bb[0]))/2, y0+height+10), nm, font=f2, fill=MUTED)
            cursor += barw
        ratio = old/new
        txt = f"{label}: {ratio:.1f}x smaller"
        f3 = font(23, True)
        bb = draw.textbbox((0,0), txt, font=f3)
        center = cursor - barw
        draw.text((center-(bb[2]-bb[0])/2, y0+height+58), txt, font=f3, fill=col)
        cursor += barw


def generate_size_chart(path: Path):
    W, H = 1500, 900
    im = Image.new("RGB", (W,H), WHITE)
    d = ImageDraw.Draw(im)
    d.text((60,38), "Size-first release comparison", font=font(48, True), fill=INK)
    d.text((60,98), "Log-scaled bars compare the supplied 3.9.2 native artifacts with the new Bayer Direct payload.", font=font(26), fill=MUTED)
    draw_log_bars(d, 120, 180, 1260, 500, [
        ("APK", OLD_APK_BYTES, APK_PATH.stat().st_size, BLUE),
        ("native .so", OLD_SO_BYTES, SO_PATH.stat().st_size, TEAL),
    ])
    apk_reduction = (1-APK_PATH.stat().st_size/OLD_APK_BYTES)*100
    so_reduction = (1-SO_PATH.stat().st_size/OLD_SO_BYTES)*100
    rounded_box(d, (120,770,1380,860), PALE, CYAN, radius=16, width=3)
    centered_text(d, (135,780,1365,850), f"APK reduction {apk_reduction:.3f}%  |  native-library reduction {so_reduction:.3f}%  |  zero assets and zero DEX", font(24, True), fill=INK)
    im.save(path, optimize=True)


def generate_budget(path: Path):
    bench = json.loads(BENCH_PATH.read_text())
    W, H = 1500, 900
    im = Image.new("RGB", (W,H), NAVY)
    d = ImageDraw.Draw(im)
    d.text((60,38), "Runtime budget: bounded pixels, bounded cadence", font=font(48, True), fill=WHITE)
    d.text((60,100), "The host benchmark is reference evidence only; mobile performance remains a physical-device gate.", font=font(25), fill="#b6c4dc")
    cards = [
        ("Internal lattice", "480 x 216 reference", CYAN),
        ("Samples / frame", f"{480*216:,}", TEAL),
        ("RGB565 buffer", f"{480*216*2/1024:.1f} KiB", PURPLE),
        ("30 Hz traffic", f"{480*216*2*30/(1024**2):.2f} MiB/s", ORANGE),
        ("Host median", f"{bench['median_mpix_s']:.3f} MPix/s", BLUE),
        ("Host equivalent", f"{bench['median_fps_at_480x216']:.3f} fps", GOLD),
    ]
    cols = 3
    card_w, card_h = 410, 230
    gapx, gapy = 55, 50
    ox, oy = 70, 190
    for i,(title,value,col) in enumerate(cards):
        c=i%cols;r=i//cols
        x0=ox+c*(card_w+gapx); y0=oy+r*(card_h+gapy)
        rounded_box(d,(x0,y0,x0+card_w,y0+card_h),NAVY2,col,radius=22,width=4)
        d.text((x0+28,y0+28),title,font=font(25,True),fill="#bcd0ec")
        centered_text(d,(x0+15,y0+70,x0+card_w-15,y0+card_h-15),value,font(38,True),fill=WHITE)
    rounded_box(d,(70,760,1430,850),"#341a27",RED,radius=14,width=3)
    centered_text(d,(90,770,1410,840),"No physical Android FPS, power, thermal, or sustained-pacing result is claimed. Measure on the target phone before promotion.",font(24,True),fill="#ffd7dc")
    im.save(path,optimize=True)


def generate_package_anatomy(path: Path):
    W,H=1500,780
    im=Image.new("RGB",(W,H),WHITE)
    d=ImageDraw.Draw(im)
    d.text((55,35),"Final APK anatomy",font=font(48,True),fill=INK)
    d.text((55,96),"Six payload records plus two directory entries; one compressed arm64 shared object carries the application.",font=font(25),fill=MUTED)
    items=[
        ("AndroidManifest.xml","2,980 B source length / 1,080 B compressed",BLUE),
        ("resources.arsc","864 B / 291 B compressed",TEAL),
        ("libugts_kc_bayer.so","6,656 B / 3,679 B compressed",PURPLE),
        ("APK v1 metadata","MANIFEST.MF + SF + RSA",ORANGE),
        ("APK v2 block","1,562 B",GOLD),
    ]
    y=175
    for title,sub,col in items:
        rounded_box(d,(80,y,1420,y+88),PALE2,col,radius=14,width=3)
        d.text((110,y+17),title,font=font(27,True),fill=INK)
        d.text((560,y+22),sub,font=font(23),fill=MUTED)
        y+=103
    rounded_box(d,(80,690,1420,755),"#eaf7ef",GREEN,radius=13,width=3)
    centered_text(d,(95,697,1405,747),"Absent: classes.dex - assets - textures - meshes - shaders - Java/Kotlin runtime - GL/Vulkan libraries",font(23,True),fill="#1d5c3a")
    im.save(path,optimize=True)


def generate_figures():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    generate_architecture(FIG_DIR / "architecture.png")
    generate_bayer(FIG_DIR / "bayer_matrix.png")
    generate_size_chart(FIG_DIR / "size_comparison.png")
    generate_budget(FIG_DIR / "runtime_budget.png")
    generate_package_anatomy(FIG_DIR / "apk_anatomy.png")


class ReportDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kw):
        super().__init__(filename, **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        self.addPageTemplates(PageTemplate(id="all", frames=[frame], onPage=self._page))

    def _page(self, canvas, doc):
        canvas.saveState()
        page = canvas.getPageNumber()
        if page > 1:
            canvas.setStrokeColor(colors.HexColor(CYAN))
            canvas.setLineWidth(1.2)
            canvas.line(18*mm, A4[1]-15*mm, A4[0]-18*mm, A4[1]-15*mm)
            canvas.setFont("Helvetica-Bold", 8.5)
            canvas.setFillColor(colors.HexColor(NAVY))
            canvas.drawString(18*mm, A4[1]-11.5*mm, "UGTS-KC 3.9.4 | Bayer Direct Native Edition")
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.HexColor(MUTED))
            canvas.drawRightString(A4[0]-18*mm, A4[1]-11.5*mm, "Tom Klootwijk Signature Edition")
            canvas.setStrokeColor(colors.HexColor("#cad4e3"))
            canvas.line(18*mm, 13*mm, A4[0]-18*mm, 13*mm)
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(A4[0]-18*mm, 8.5*mm, f"Page {page}")
            canvas.drawString(18*mm, 8.5*mm, "Compression and device performance remain evidence-gated.")
        canvas.restoreState()


def P(text, style):
    return Paragraph(text, style)


def img(path: Path, width_mm: float, max_height_mm: float | None = None):
    im = Image.open(path)
    w,h=im.size
    width=width_mm*mm
    height=width*h/w
    if max_height_mm is not None and height > max_height_mm*mm:
        height=max_height_mm*mm
        width=height*w/h
    return RLImage(str(path), width=width, height=height)


def styled_table(data, col_widths, header=True, font_size=8.3, row_bgs=True):
    t=Table(data, colWidths=col_widths, repeatRows=1 if header else 0, hAlign="LEFT")
    styles=[
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),5),
        ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,0),(-1,-1),5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("GRID",(0,0),(-1,-1),0.45,colors.HexColor("#9aa7b9")),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),font_size),
        ("TEXTCOLOR",(0,0),(-1,-1),colors.HexColor(INK)),
    ]
    if header:
        styles += [
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor(NAVY)),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ]
    if row_bgs:
        start=1 if header else 0
        for i in range(start,len(data)):
            if (i-start)%2==0:
                styles.append(("BACKGROUND",(0,i),(-1,i),colors.HexColor(PALE2)))
    t.setStyle(TableStyle(styles))
    return t


def callout(text, styles, color=CYAN, bg="#eaf8fb"):
    table=Table([[P(text, styles["callout"])]],colWidths=[174*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor(bg)),
        ("BOX",(0,0),(-1,-1),1.2,colors.HexColor(color)),
        ("LEFTPADDING",(0,0),(-1,-1),10),
        ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("TOPPADDING",(0,0),(-1,-1),8),
        ("BOTTOMPADDING",(0,0),(-1,-1),8),
    ]))
    return table


def section_title(n: str, title: str, styles):
    return P(f"<font color='{CYAN}'>{n}</font> {title}", styles["h1"])


def build_styles():
    s=getSampleStyleSheet()
    styles={}
    styles["cover_title"]=ParagraphStyle("cover_title",parent=s["Title"],fontName="Helvetica-Bold",fontSize=32,leading=36,textColor=colors.HexColor(NAVY),spaceAfter=7)
    styles["cover_sub"]=ParagraphStyle("cover_sub",parent=s["Normal"],fontName="Helvetica-Bold",fontSize=16,leading=21,textColor=colors.HexColor(BLUE),spaceAfter=9)
    styles["cover_meta"]=ParagraphStyle("cover_meta",parent=s["Normal"],fontName="Helvetica",fontSize=10.5,leading=15,textColor=colors.HexColor(MUTED),alignment=TA_CENTER)
    styles["h1"]=ParagraphStyle("h1",parent=s["Heading1"],fontName="Helvetica-Bold",fontSize=21,leading=25,textColor=colors.HexColor(NAVY),spaceAfter=8,keepWithNext=True)
    styles["h2"]=ParagraphStyle("h2",parent=s["Heading2"],fontName="Helvetica-Bold",fontSize=14.5,leading=18,textColor=colors.HexColor(BLUE),spaceBefore=8,spaceAfter=5,keepWithNext=True)
    styles["body"]=ParagraphStyle("body",parent=s["BodyText"],fontName="Helvetica",fontSize=9.6,leading=14,textColor=colors.HexColor(INK),spaceAfter=6)
    styles["small"]=ParagraphStyle("small",parent=styles["body"],fontSize=8.2,leading=11.2,textColor=colors.HexColor(MUTED),spaceAfter=4)
    styles["bullet"]=ParagraphStyle("bullet",parent=styles["body"],leftIndent=13,firstLineIndent=-8,bulletIndent=3,spaceAfter=3)
    styles["callout"]=ParagraphStyle("callout",parent=styles["body"],fontName="Helvetica-Bold",fontSize=9.8,leading=14,spaceAfter=0)
    styles["code"]=ParagraphStyle("code",parent=styles["body"],fontName="Courier",fontSize=8.0,leading=11.2,leftIndent=7,rightIndent=7,borderColor=colors.HexColor("#ccd6e4"),borderWidth=0.6,borderPadding=7,backColor=colors.HexColor("#f4f7fb"),spaceAfter=8)
    styles["caption"]=ParagraphStyle("caption",parent=styles["small"],fontName="Helvetica-Oblique",alignment=TA_CENTER,spaceBefore=3,spaceAfter=6)
    styles["table"]=ParagraphStyle("table",parent=styles["small"],fontSize=7.5,leading=9.3,textColor=colors.HexColor(INK),spaceAfter=0)
    styles["table_head"]=ParagraphStyle("table_head",parent=styles["table"],fontName="Helvetica-Bold",textColor=colors.white)
    return styles


def build_pdf():
    styles=build_styles()
    apk_bytes=APK_PATH.stat().st_size
    so_bytes=SO_PATH.stat().st_size
    apk_sha=sha256(APK_PATH)
    so_sha=sha256(SO_PATH)
    bench=json.loads(BENCH_PATH.read_text())
    with CATALOG_PATH.open(newline="",encoding="utf-8") as f:
        catalog=list(csv.DictReader(f))

    doc=ReportDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=18*mm,
        rightMargin=18*mm,
        topMargin=22*mm,
        bottomMargin=18*mm,
        title="UGTS-KC 3.9.4 Bayer Direct Native Edition",
        author="Tom Klootwijk Signature Edition",
        subject="Tiny native Android application using direct integer fields and Bayer ordered dithering",
    )
    story=[]

    # Cover
    story += [Spacer(1,8*mm),P("UGTS-KC 3.9.4",styles["cover_title"]),P("BAYER DIRECT NATIVE EDITION",styles["cover_sub"]),
              P("Tiny arm64 Android application, direct integer fields, ordered dithering and explicit performance boundaries",styles["cover_meta"]),Spacer(1,8*mm),
              img(MONTAGE_PATH,174,80),P("Four deterministic 4-level field programs: Grove, shell, Kij lattice and SCLP cone/shell.",styles["caption"]),Spacer(1,5*mm)]
    cover_data=[
        [P("Release",styles["table_head"]),P("Measured result",styles["table_head"])],
        [P("Native application",styles["table"]),P(f"{apk_bytes:,}-byte arm64-v8a APK, API 26+, test-signed",styles["table"])],
        [P("Native hot library",styles["table"]),P(f"{so_bytes:,} bytes; imports only libandroid.so and libc.so",styles["table"])],
        [P("Presentation path",styles["table"]),P("ANativeWindow CPU buffer -> RGB565 -> Android compositor",styles["table"])],
        [P("Explicit exclusions",styles["table"]),P("No DEX, asset, mesh, texture, shader, OpenGL ES, Vulkan, ray traversal or ray marching",styles["table"])],
        [P("Status",styles["table"]),P("Executable candidate and source package; physical-phone install/performance not claimed",styles["table"])],
    ]
    story += [styled_table(cover_data,[48*mm,126*mm],font_size=8.6),Spacer(1,8*mm),
              P(f"Prepared for Tom Klootwijk - Signature Edition - Version 3.9.4 - {DATE_TEXT}",styles["cover_meta"]),PageBreak()]

    # 1 Executive
    story += [section_title("1.","Executive decision",styles),
              P("Version 3.9.4 makes compression and bounded presentation the first design constraints. It does not attempt to make the 3.9.3 IQ field renderer smaller. Instead, it defines a separate Bayer Direct profile whose installable hot path contains only native lifecycle code, four integer field programs, an exact 8x8 ordered-dither matrix and four RGB565 palettes.",styles["body"]),
              callout("DECISION - GO. Use a direct finite display lattice and Bayer palette projection. Exclude scene, mesh, texture, shader, graphics-pipeline and ray machinery from the native APK. Preserve the UGTS event/state substrate upstream and keep display output downstream.",styles,color=GREEN,bg="#ebf8f0"),
              P("Top-priority acceptance order",styles["h2"]),
              styled_table([
                  [P("Priority",styles["table_head"]),P("Release rule",styles["table_head"]),P("Measured state",styles["table_head"])],
                  [P("1. Size",styles["table"]),P("Single ABI, no asset/DEX/shader payload, size-first native linking and compression.",styles["table"]),P(f"APK {apk_bytes:,} B; .so {so_bytes:,} B",styles["table"])],
                  [P("2. Work bound",styles["table"]),P("Finite 480-class RGB565 surface at nominal 30 Hz; no history buffer.",styles["table"]),P("103,680 reference samples/frame; 202.5 KiB",styles["table"])],
                  [P("3. Direct output",styles["table"]),P("Evaluate F(x,y,q), apply Bayer threshold, post pixel. No scene traversal.",styles["table"]),P("Four deterministic CRC baselines",styles["table"])],
                  [P("4. Evidence",styles["table"]),P("Separate host evidence from target-device claims.",styles["table"]),P("11 tests pass; phone gates pending",styles["table"])],
              ],[24*mm,94*mm,56*mm],font_size=8.2),
              P("Result in one sentence",styles["h2"]),
              P("The application is a tiny NativeActivity that synthesizes a retro, animated field image directly into the next Android native window buffer, with ordered dithering replacing continuous color and the operating system compositor performing only the final panel scaling.",styles["body"]),PageBreak()]

    # 2 lineage
    story += [section_title("2.","Continuity with the formal substrate",styles),
              P("This release is an additive presentation-profile delta over the 3.9.3 substrate. It does not renumber or remove earlier mechanisms. It appends M610-M629, bringing the combined engineering/source catalog range to M001-M629.",styles["body"]),
              P("The decision follows explicit boundaries already present in the supplied project sources:",styles["body"]),
              styled_table([
                [P("Source",styles["table_head"]),P("Relevant boundary",styles["table_head"]),P("3.9.4 use",styles["table_head"])],
                [P("UGTS-KC 3.6.2 SCLP, pp. 1-2, 11-12",styles["table"]),P("The authoritative object is typed state/relations, not an image, mesh or ray-marched volume; rasterization and ray marching are explicitly excluded from the core.",styles["table"]),P("Direct field queries feed an optional display projection.",styles["table"])],
                [P("UGTS-KC 2.0, pp. 2, 12-15",styles["table"]),P("The core is not a renderer; reconstructibility and compact state require measured error and event density.",styles["table"]),P("Frames reconstruct from seed/tick; no image history is authoritative.",styles["table"])],
                [P("KC Two Hands 3.0, pp. 5-10",styles["table"]),P("Rendering stays downstream; hot records should remain compact while mesh/material data stays cold.",styles["table"]),P("The cold graphics layer is entirely absent from the APK.",styles["table"])],
                [P("UGTS-GN 1.1, pp. 9-13",styles["table"]),P("Packed records reduce traffic only under an error contract; compression is not correctness or speed by itself.",styles["table"]),P("RGB565 and 480-class resolution are explicit, testable contracts.",styles["table"])],
                [P("KC Elizabeth 3.9, pp. 2-4",styles["table"]),P("Small inspectable records, deterministic runtime and self-contained delivery are pragmatic design choices.",styles["table"]),P("Single native library, no network assets, deterministic frame identity.",styles["table"])],
              ],[43*mm,77*mm,54*mm],font_size=7.6),
              Spacer(1,3*mm),
              callout("Important distinction: a screen still requires a finite pixel surface. 'No rasterization' in this profile means no triangle/mesh graphics rasterizer and no ray-based image solver. Each final pixel is a direct bounded query of an integer field. The Android compositor is an unavoidable downstream display endpoint, not substrate authority.",styles,color=GOLD,bg="#fff8df"),PageBreak()]

    # 3 architecture
    story += [section_title("3.","Bayer Direct architecture",styles),
              img(FIG_DIR/"architecture.png",174,93),P("Figure 1. Direct field-to-pixel path. The only downstream system stage is native window posting and compositor scaling.",styles["caption"]),
              P("Formal state",styles["h2"]),
              P("q_BD = (seed, tick, mode, palette, width, height, flags)",styles["code"]),
              P("For each finite output coordinate (x,y), the selected field produces L in [0,255]. The exact Bayer threshold selects one of four palette entries. The algorithm has no object list, visibility pass, depth buffer, material graph, camera or frame-history dependency.",styles["body"]),
              P("Canonical UGTS handoff",styles["h2"]),
              P("field definition + state -> support / compatibility / guard (when application events require them) -> deterministic transition + lineage -> optional Bayer Direct display projection",styles["code"]),
              callout("The display projection never commits gameplay, topology, ownership or lineage. It can be deleted or replaced without changing authoritative substrate records.",styles),PageBreak()]

    # 4 visual programs
    story += [section_title("4.","Bounded field programs",styles),
              P("The APK includes four compact visual programs. They are deliberately formulaic rather than asset-driven. Each program is a finite nested loop over the current buffer and uses integer arithmetic, bitwise hashes, triangular waves and an approximate norm.",styles["body"]),
              img(MONTAGE_PATH,174,80),P("Figure 2. Reference output montage generated from the same C core used by the APK.",styles["caption"]),
              styled_table([
                [P("Mode",styles["table_head"]),P("Field construction",styles["table_head"]),P("Visual role",styles["table_head"])],
                [P("0 Grove",styles["table"]),P("Vertical luminance, trunk/branch lines, bounded leaf halos, stars and ring phase.",styles["table"]),P("Organic flagship identity without geometry assets.",styles["table"])],
                [P("1 Shell",styles["table"]),P("Approximate radial norm, finite moving center, periodic shell phase and spokes.",styles["table"]),P("High-motion ordered-dither test.",styles["table"])],
                [P("2 Kij lattice",styles["table"]),P("Hashed 8-pixel cells, XOR lattice, diagonal guards and central mark.",styles["table"]),P("Dense local-frequency and compression stress.",styles["table"])],
                [P("3 SCLP",styles["table"]),P("Cone edge relation, finite stripe field, radial shell and parity wrap accent.",styles["table"]),P("Direct visual reference to packed cone/shell mechanisms.",styles["table"])],
              ],[28*mm,95*mm,51*mm],font_size=8.0),
              P("At nominal 30 Hz, the mode changes every 450 ticks, approximately every 15 seconds. No touch/input layer is bundled; that omission is intentional for this minimal release.",styles["small"]),PageBreak()]

    # 5 Bayer
    story += [section_title("5.","Ordered-dither quantization",styles),
              img(FIG_DIR/"bayer_matrix.png",145,129),P("Figure 3. Exact 64-state threshold matrix embedded as 64 bytes in the C source.",styles["caption"]),
              P("Let B8 be the threshold at the pixel's position modulo eight and let L be the field luminance. The output level is:",styles["body"]),
              P("k = min(3, floor((4 * L + 4 * B8) / 256))",styles["code"]),
              P("A four-entry palette then maps k to RGB565. Ordered dithering spreads quantization error deterministically in space. It does not create additional information, remove the need for a pixel buffer or guarantee perfect anti-aliasing. The exact matrix permutation and four fixed-mode CRC values are unit-tested.",styles["body"]),PageBreak()]

    # 6 Android direct buffer
    story += [section_title("6.","Native Android display path",styles),
              P("The application uses android.app.NativeActivity and exports ANativeActivity_onCreate from a single arm64 shared object. Window callbacks acquire and release ANativeWindow ownership, while a native thread locks, writes and posts the next finite buffer.",styles["body"]),
              P("Window and lifecycle sequence",styles["h2"]),
              P("onCreate -> register native callbacks -> onNativeWindowCreated -> acquire -> setBuffersGeometry -> start producer -> lock -> write -> unlockAndPost -> pause/focus idle -> stop/join before window release",styles["code"]),
              styled_table([
                [P("Contract",styles["table_head"]),P("Implementation",styles["table_head"]),P("Reason",styles["table_head"])],
                [P("Format",styles["table"]),P("Request RGB565; support RGBA8888/RGBX8888 fallback.",styles["table"]),P("16-bit hot buffer while tolerating device format decisions.",styles["table"])],
                [P("Resolution",styles["table"]),P("480 along the long axis; derive other axis, align to 8, clamp 160..320.",styles["table"]),P("Fixed sample budget independent of panel resolution.",styles["table"])],
                [P("Cadence",styles["table"]),P("33,333 microsecond nominal wait; 50,000 microsecond idle wait.",styles["table"]),P("Bounded work and low idle activity.",styles["table"])],
                [P("Dependencies",styles["table"]),P("DT_NEEDED: libandroid.so and libc.so only.",styles["table"]),P("No EGL, GLES, Vulkan, C++ runtime or app framework library.",styles["table"])],
                [P("Page alignment",styles["table"]),P("AArch64 LOAD segments aligned to 0x4000.",styles["table"]),P("Recorded ELF property; device loading still must be verified.",styles["table"])],
              ],[31*mm,91*mm,52*mm],font_size=8.0),
              callout("Physical-device status: the APK was not installed or benchmarked on the target phone in this build environment. Source, ELF, manifest and signatures are verified; Android loader/compositor behavior remains an acceptance gate.",styles,color=RED,bg="#fff0f1"),PageBreak()]

    # 7 compression design
    story += [section_title("7.","Compression architecture",styles),
              P("Compression is achieved mainly by deleting representation layers, not by applying a heavier archive codec. The field programs are code and small state; the image is reconstructed every frame. Nothing equivalent to a full scene, texture atlas or precomputed animation is stored.",styles["body"]),
              styled_table([
                [P("Design choice",styles["table_head"]),P("Size/performance consequence",styles["table_head"])],
                [P("Single arm64-v8a ABI",styles["table"]),P("No duplicate native payload for x86, x86_64 or armeabi-v7a.",styles["table"])],
                [P("C hot path and hidden visibility",styles["table"]),P("One exported symbol; section garbage collection removes unused code.",styles["table"])],
                [P("-Oz + LTO + stripped ELF",styles["table"]),P("6,656-byte library while retaining lifecycle and four modes.",styles["table"])],
                [P("No C++ standard library",styles["table"]),P("No libc++ payload or exception/unwind metadata.",styles["table"])],
                [P("No DEX and no app assets",styles["table"]),P("No Java/Kotlin bytecode, textures, fonts, meshes, scene JSON or shaders.",styles["table"])],
                [P("RGB565 + low internal lattice",styles["table"]),P("Two bytes/sample and bounded fill traffic; compositor handles final scale.",styles["table"])],
                [P("Seed/tick reconstruction",styles["table"]),P("No frame cache or prior-image dependency; deterministic CRC regression.",styles["table"])],
              ],[62*mm,112*mm],font_size=8.4),
              P("Compression boundary",styles["h2"]),
              P("The 110.2x and 149.1x comparisons below are byte-width comparisons against the supplied 3.9.2 APK and stripped native library. They do not imply equal functionality: 3.9.4 intentionally removes the richer graphics, input, assets and scene path from the hot application.",styles["body"]),PageBreak()]

    # 8 size measurement
    story += [section_title("8.","Measured package size",styles),
              img(FIG_DIR/"size_comparison.png",174,104),P("Figure 4. Exact file-size comparison. The chart uses logarithmic height because the new payload is two orders of magnitude smaller.",styles["caption"]),
              styled_table([
                [P("Artifact",styles["table_head"]),P("Supplied 3.9.2",styles["table_head"]),P("3.9.4",styles["table_head"]),P("Reduction",styles["table_head"])],
                [P("Signed APK",styles["table"]),P(f"{OLD_APK_BYTES:,} B",styles["table"]),P(f"{apk_bytes:,} B",styles["table"]),P(f"{OLD_APK_BYTES/apk_bytes:.2f}x smaller; {(1-apk_bytes/OLD_APK_BYTES)*100:.3f}%",styles["table"])],
                [P("Stripped native library",styles["table"]),P(f"{OLD_SO_BYTES:,} B",styles["table"]),P(f"{so_bytes:,} B",styles["table"]),P(f"{OLD_SO_BYTES/so_bytes:.2f}x smaller; {(1-so_bytes/OLD_SO_BYTES)*100:.3f}%",styles["table"])],
              ],[45*mm,41*mm,35*mm,53*mm],font_size=8.5),
              P("The final APK contains eight ZIP entries, two of which are directories. The only executable payload is the 6,656-byte arm64 shared object. The APK's compressed payload plus v1/v2 signing records totals 9,438 bytes.",styles["body"]),
              P(f"APK SHA-256: {apk_sha}",styles["code"]),
              P(f"Native library SHA-256: {so_sha}",styles["code"]),PageBreak()]

    # 9 performance
    story += [section_title("9.","Performance design and evidence",styles),
              img(FIG_DIR/"runtime_budget.png",174,104),P("Figure 5. Bounded traffic and host-reference throughput. Host results are not target-phone results.",styles["caption"]),
              P("Reference host measurement",styles["h2"]),
              P(f"Five x86_64 Linux runs rendered 600 frames each at 480x216. Median throughput was {bench['median_mpix_s']:.3f} million pixels/s, equivalent to {bench['median_fps_at_480x216']:.3f} full reference frames/s. Every run ended with CRC32 9f8347c1. This shows the C algorithm is deterministic and far below a desktop CPU's capacity; it does not predict Android sustained pacing, power or thermal behavior.",styles["body"]),
              P("Target-device metrics required before a performance claim",styles["h2"]),
              styled_table([
                [P("Metric",styles["table_head"]),P("Required evidence",styles["table_head"])],
                [P("Install/load",styles["table"]),P("Package installs, NativeActivity launches, library resolves and survives lifecycle recreation.",styles["table"])],
                [P("Frame production",styles["table"]),P("p50/p95/p99 producer time and missed 30 Hz intervals for 10- and 30-minute runs.",styles["table"])],
                [P("Buffer contract",styles["table"]),P("Actual width, height, stride and format returned by ANativeWindow_lock.",styles["table"])],
                [P("Power/thermal",styles["table"]),P("Battery discharge, CPU frequency residency, thermal status and device skin temperature.",styles["table"])],
                [P("Memory",styles["table"]),P("RSS/PSS and compositor buffer allocation, not merely APK bytes.",styles["table"])],
              ],[42*mm,132*mm],font_size=8.3),PageBreak()]

    # 10 package anatomy / signing
    story += [section_title("10.","APK contents, signature and install boundary",styles),
              img(FIG_DIR/"apk_anatomy.png",174,91),P("Figure 6. Final install package anatomy.",styles["caption"]),
              P("The bundled candidate is signed with a self-signed 2048-bit RSA test certificate using both JAR/v1 records and an APK Signature Scheme v2 block. The package includes the public certificate fingerprint in validation evidence, but no private signing key is delivered.",styles["body"]),
              styled_table([
                [P("Field",styles["table_head"]),P("Value",styles["table_head"])],
                [P("Package ID",styles["table"]),P("nl.tomklootwijk.ugtskc.bayer.poco",styles["table"])],
                [P("Version",styles["table"]),P("versionCode 394; versionName 3.9.4-bayer-direct-v001",styles["table"])],
                [P("ABI / SDK",styles["table"]),P("arm64-v8a only; minSdk 26; targetSdk 36",styles["table"])],
                [P("v2 certificate SHA-256",styles["table"]),P("f100337d7c5fe902714c6d942fe48ce71300aa98aae4c27a6386bd0511f561f7",styles["table"])],
                [P("Certificate status",styles["table"]),P("Self-signed test build; replace for production distribution.",styles["table"])],
              ],[47*mm,127*mm],font_size=8.2),
              P("Install candidate",styles["h2"]),
              P("adb install -r dist/UGTS_KC_Bayer_Direct_3_9_4_arm64-v8a.apk",styles["code"]),
              callout("The APK is structurally and cryptographically verified in the package, but an actual Android install was not available in this environment. Treat the first target-phone launch as an acceptance test, not as a foregone benchmark result.",styles,color=GOLD,bg="#fff8df"),PageBreak()]

    # 11 validation
    story += [section_title("11.","Validation evidence",styles),
              P("The release tests the deterministic quantizer, native binary, APK contents, binary manifest and both signature layers. These checks establish internal package consistency and the stated exclusions.",styles["body"]),
              styled_table([
                [P("Gate",styles["table_head"]),P("Result",styles["table_head"]),P("Evidence",styles["table_head"])],
                [P("Bayer permutation",styles["table"]),P("PASS",styles["table"]),P("Values are exactly 0..63 once each.",styles["table"])],
                [P("Mode regression",styles["table"]),P("PASS",styles["table"]),P("Four fixed RGB565 CRC32 results.",styles["table"])],
                [P("Integer hot core",styles["table"]),P("PASS",styles["table"]),P("No float/double tokens or functions in core source.",styles["table"])],
                [P("ELF architecture/size",styles["table"]),P("PASS",styles["table"]),P("AArch64 DYN, 6,656 bytes.",styles["table"])],
                [P("Dynamic dependencies",styles["table"]),P("PASS",styles["table"]),P("Only libandroid.so and libc.so.",styles["table"])],
                [P("NativeActivity entry",styles["table"]),P("PASS",styles["table"]),P("ANativeActivity_onCreate exported.",styles["table"])],
                [P("APK size budget",styles["table"]),P("PASS",styles["table"]),P("9,438 bytes, below 16 KiB test ceiling.",styles["table"])],
                [P("APK contents",styles["table"]),P("PASS",styles["table"]),P("No assets, DEX or shader paths.",styles["table"])],
                [P("Manifest identity",styles["table"]),P("PASS",styles["table"]),P("Package/version/lib match; no uses-feature elements.",styles["table"])],
                [P("v1 signature",styles["table"]),P("PASS",styles["table"]),P("jarsigner verifies; self-signed warning expected.",styles["table"])],
                [P("v2 signature",styles["table"]),P("PASS",styles["table"]),P("Digest, certificate and signing block independently verified.",styles["table"])],
              ],[46*mm,24*mm,104*mm],font_size=7.9),
              P("Combined result: 11/11 release tests pass. The wider 3.9.3 substrate test suite is not duplicated in this minimal app ZIP; this delta validates the presentation profile and packaged application.",styles["body"]),PageBreak()]

    # 12 mechanisms first half
    story += [section_title("12.","Mechanism catalog M610-M619",styles),
              P("These ten entries define the direct display, quantizer, state and field layer.",styles["body"])]
    data=[[P("ID",styles["table_head"]),P("Domain",styles["table_head"]),P("Mechanism",styles["table_head"]),P("Formal definition / status",styles["table_head"])]]
    for row in catalog[:10]:
        status=f"{row['formal_definition']} <font color='{MUTED}'>[{row['validation']}]</font>"
        data.append([P(row['id'],styles["table"]),P(row['domain'],styles["table"]),P(row['mechanism'],styles["table"]),P(status,styles["table"])])
    story += [styled_table(data,[16*mm,27*mm,47*mm,84*mm],font_size=7.2),PageBreak()]

    # 13 mechanisms second half
    story += [section_title("13.","Mechanism catalog M620-M629",styles),
              P("These ten entries define exclusions, build compression, lifecycle, validation and governance.",styles["body"])]
    data=[[P("ID",styles["table_head"]),P("Domain",styles["table_head"]),P("Mechanism",styles["table_head"]),P("Formal definition / status",styles["table_head"])]]
    for row in catalog[10:]:
        status=f"{row['formal_definition']} <font color='{MUTED}'>[{row['validation']}]</font>"
        data.append([P(row['id'],styles["table"]),P(row['domain'],styles["table"]),P(row['mechanism'],styles["table"]),P(status,styles["table"])])
    story += [styled_table(data,[16*mm,27*mm,47*mm,84*mm],font_size=7.2),PageBreak()]

    # 14 reproduction/boundary
    story += [section_title("14.","Reproduction, package map and evidence boundary",styles),
              P("Standard source rebuild",styles["h2"]),
              P("Install JDK 17+, Android SDK platform 36, Android Gradle Plugin 8.13.2, CMake 3.22.1 and Android NDK r29 (29.0.14206865), then run:",styles["body"]),
              P("gradle :app:assembleRelease",styles["code"]),
              P("The included ultra-small APK was produced from the same C sources using a freestanding AArch64 link and a verified APK v2 signer because a complete Android SDK/NDK installation was unavailable in the build container. The source Gradle/CMake project is the recommended production rebuild path.",styles["body"]),
              P("Package map",styles["h2"]),
              styled_table([
                [P("Path",styles["table_head"]),P("Contents",styles["table_head"])],
                [P("app/",styles["table"]),P("NativeActivity manifest, Gradle/CMake project and Bayer Direct C sources.",styles["table"])],
                [P("dist/",styles["table"]),P("Test-signed arm64-v8a install candidate.",styles["table"])],
                [P("spec/",styles["table"]),P("Formal definition, JSON profile and M610-M629 catalog.",styles["table"])],
                [P("preview/",styles["table"]),P("Deterministic mode images and montage.",styles["table"])],
                [P("tests/",styles["table"]),P("11 package/core regression tests.",styles["table"])],
                [P("tools/",styles["table"]),P("Host preview, binary-manifest patcher, key generator and APK v2 sign/verify tools.",styles["table"])],
                [P("validation/",styles["table"]),P("ELF/APK inspections, benchmark runs, signatures and release metrics.",styles["table"])],
                [P("report/",styles["table"]),P("This PDF, report generator and figures.",styles["table"])],
              ],[43*mm,131*mm],font_size=8.2),
              P("Final evidence boundary",styles["h2"]),
              callout("This release proves the exact contents and hashes of a very small native Android package, deterministic host output, a valid AArch64 ELF and internally verified APK signatures. It does not prove target-phone installation, compositor format selection, sustained frame pacing, thermal behavior, battery use, crash-free lifecycle or production signing. Those remain named-device measurements.",styles,color=RED,bg="#fff0f1"),
              P("Attribution",styles["h2"]),
              P("Prepared as UGTS-KC 3.9.4 - Bayer Direct Native Edition for Tom Klootwijk. 'Signature Edition' is release attribution, not independent legal proof of authorship, ownership, patentability, priority or chain of title. Third-party Android platform names and standards remain the property of their respective owners.",styles["small"]),
              P("Reference sources",styles["h2"]),
              P("Supplied project sources: UGTS-KC 3.6.2 SCLP; UGTS-KC 2.0; KC Two Hands 3.0; UGTS-GN 1.1; KC Elizabeth 3.9; and the immediate UGTS-KC 3.9.2/3.9.3 packages. Platform implementation references: Android NDK NativeActivity and ANativeWindow documentation.",styles["small"])]

    doc.build(story)


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    generate_figures()
    build_pdf()
    print(PDF_PATH)

if __name__ == "__main__":
    main()
