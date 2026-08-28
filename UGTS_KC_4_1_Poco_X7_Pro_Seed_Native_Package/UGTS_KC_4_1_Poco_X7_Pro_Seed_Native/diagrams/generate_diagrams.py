#!/usr/bin/env python3
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch
import numpy as np

OUT=Path(__file__).resolve().parent
BG='#f7f8fa'; INK='#17212b'; MUTED='#566574'; GREEN='#1f7a5a'; LIME='#8bcf66'; BLUE='#2d6ca2'; AMBER='#b86f1d'; RED='#a33a3a'; LINE='#cbd4dc'

def base(figsize=(14,8)):
    fig,ax=plt.subplots(figsize=figsize,dpi=160)
    fig.patch.set_facecolor(BG); ax.set_facecolor(BG); ax.axis('off')
    return fig,ax

def box(ax,xy,w,h,title,subtitle='',face='white',edge=LINE,title_color=INK):
    x,y=xy
    p=FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.012,rounding_size=0.025',linewidth=1.5,edgecolor=edge,facecolor=face)
    ax.add_patch(p)
    ax.text(x+w/2,y+h*0.64,title,ha='center',va='center',fontsize=13,fontweight='bold',color=title_color)
    if subtitle: ax.text(x+w/2,y+h*0.30,subtitle,ha='center',va='center',fontsize=9.5,color=MUTED,wrap=True)
    return p

def arrow(ax,a,b,color=GREEN,label=''):
    arr=FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=16,linewidth=1.7,color=color)
    ax.add_patch(arr)
    if label:
        ax.text((a[0]+b[0])/2,(a[1]+b[1])/2+0.025,label,ha='center',va='bottom',fontsize=8.5,color=color)

def save(fig,name):
    fig.savefig(OUT/name,bbox_inches='tight',pad_inches=0.15,facecolor=BG)
    plt.close(fig)

# Architecture
fig,ax=base(); ax.set_xlim(0,1);ax.set_ylim(0,1)
ax.text(.03,.94,'UGTS-KC 4.1 Native Spatial Evidence Pipeline',fontsize=22,fontweight='bold',color=INK)
ax.text(.03,.895,'POCO X7 Pro capture path with a single authoritative mutation boundary',fontsize=12,color=MUTED)
xs=[.035,.197,.359,.521,.683,.845]; titles=['Camera + IMU','Seeded analysis','Typed proposals','Ordered verifier','Spatial ledger','KSEED + view']
subs=['YUV luma, timestamps,\naccel/gyro/orientation','160x90, signatures,\nfeatures, keyframes','stable IDs, uncertainty,\nguards, metric state','support -> compatibility\nguard -> confidence\nerror -> uncertainty','verified commit only,\npre/post state hashes','varint/delta/zlib\nCRC/SHA chain\nBayer projection']
faces=['#edf5fa','#edf7f2','#fff8e8','#fff1f1','#e9f6ee','#eef1f7']; edges=[BLUE,GREEN,AMBER,RED,GREEN,BLUE]
for i,x in enumerate(xs):
    box(ax,(x,.55),.13,.22,titles[i],subs[i],faces[i],edges[i])
    if i<len(xs)-1: arrow(ax,(x+.13,.66),(xs[i+1],.66),edges[i+1])
ax.add_patch(Rectangle((.515,.48),.325,.36,fill=False,linestyle='--',linewidth=2,edgecolor=RED))
ax.text(.677,.855,'AUTHORITATIVE CORE',ha='center',fontsize=11,fontweight='bold',color=RED)
box(ax,(.08,.16),.22,.18,'Deterministic demo','offline fallback and route fixture\nexplicitly tagged synthetic','#f1f1f1',MUTED)
box(ax,(.39,.16),.22,.18,'Future SLAM/model','may add pose/depth/semantics\nbut emits proposals only','#f1f1f1',MUTED)
box(ax,(.70,.16),.22,.18,'Device validation','Codex build, install, benchmark,\naccuracy and thermal studies','#f1f1f1',MUTED)
arrow(ax,(.19,.34),(.265,.55),MUTED,'DEMO')
arrow(ax,(.50,.34),(.43,.55),MUTED,'PROPOSALS')
arrow(ax,(.81,.34),(.81,.55),MUTED,'MEASURE')
save(fig,'architecture_native_4_1.png')

# KSEED layout
fig,ax=base();ax.set_xlim(0,1);ax.set_ylim(0,1)
ax.text(.03,.94,'KSEED 4.1 Binary Container',fontsize=22,fontweight='bold',color=INK)
ax.text(.03,.895,'Seed plus measured evidence deltas - bounded, streamable, integrity chained',fontsize=12,color=MUTED)
ax.add_patch(Rectangle((.04,.66),.92,.12,facecolor='white',edgecolor=INK,linewidth=1.5))
segments=[(.04,.08,'Magic + version\n16 B',BLUE),(.12,.12,'seed + start\n16 B',GREEN),(.24,.08,'analysis\n8 B',AMBER),(.32,.32,'profile hash\n32 B',BLUE),(.64,.32,'calibration hash + reserved + CRC\n56 B',GREEN)]
for x,w,t,c in segments:
    ax.add_patch(Rectangle((x,.66),w,.12,facecolor=c+'22',edgecolor=c,linewidth=1.2));ax.text(x+w/2,.72,t,ha='center',va='center',fontsize=9,color=INK)
ax.text(.04,.81,'128-byte session header',fontsize=11,fontweight='bold',color=INK)
for j,(y,title,sub,color) in enumerate([
    (.45,'Frame chunks','time/index deltas, int16 IMU, luma signature, Morton feature deltas',BLUE),
    (.29,'Event chunks','79-byte canonical proposals + pre/post ledger hashes',GREEN),
    (.13,'Final summary','counts, raw bytes, exact complete stored byte count',AMBER)]):
    ax.add_patch(FancyBboxPatch((.04,y),.92,.105,boxstyle='round,pad=.008',facecolor='white',edgecolor=color,linewidth=1.6))
    ax.text(.065,y+.068,title,fontsize=12,fontweight='bold',color=color)
    ax.text(.24,y+.068,sub,fontsize=10,color=MUTED)
    ax.text(.065,y+.025,'64 B chunk header: type | flags | sequence | sizes | raw CRC | stored CRC | SHA-256 chain',fontsize=8.7,color=INK)
ax.text(.50,.04,'Compression is selected only when zlib saves more than its margin.',ha='center',fontsize=10,color=RED,fontweight='bold')
save(fig,'kseed_layout_4_1.png')

# Seed boundary
fig,ax=base();ax.set_xlim(0,1);ax.set_ylim(0,1)
ax.text(.03,.94,'What the Seed Recreates - and What It Cannot',fontsize=22,fontweight='bold',color=INK)
ax.text(.03,.895,'The format avoids the false claim that a random seed can reproduce unstored reality.',fontsize=12,color=MUTED)
box(ax,(.05,.18),.40,.60,'Deterministically recreated','sample order\nstable IDs and namespaces\nkeyframe tie-breaks\nsynthetic demo route\nprocedural display\nrecord ordering', '#eaf6ef',GREEN,GREEN)
box(ax,(.55,.18),.40,.60,'Measured deltas still required','timestamps\nIMU summaries\nluma statistics/signature\nsparse feature values\naccepted event data\nuncertainty and hashes', '#fff2ee',RED,RED)
arrow(ax,(.45,.48),(.55,.48),AMBER,'SEED + EVIDENCE')
ax.text(.50,.09,'A seed is not encryption, not raw-image compression, and not a scene reconstruction by itself.',ha='center',fontsize=11,fontweight='bold',color=RED)
save(fig,'seed_boundary_4_1.png')

# POCO runtime/thermal
fig,ax=base();ax.set_xlim(0,1);ax.set_ylim(0,1)
ax.text(.03,.94,'POCO X7 Pro 12 GB Runtime Policy',fontsize=22,fontweight='bold',color=INK)
ax.text(.03,.895,'Requested operating points are reduced conservatively as Android thermal status rises.',fontsize=12,color=MUTED)
labels=['Cool 0-1','Moderate 2','Severe 3','Critical 4','Emergency 5+']
fps=[30,24,15,10,0];features=[128,80,64,40,24]
for i,l in enumerate(labels):
    x=.05+i*.185; h=.54*(fps[i]/30 if fps[i] else .12)
    c=[GREEN,LIME,AMBER,'#d85b32',RED][i]
    ax.add_patch(FancyBboxPatch((x,.21),.15,.57,boxstyle='round,pad=.008',facecolor='white',edgecolor=c,linewidth=1.7))
    ax.text(x+.075,.73,l,ha='center',fontsize=11,fontweight='bold',color=c)
    ax.add_patch(Rectangle((x+.035,.27),.08,h,facecolor=c,alpha=.75))
    ax.text(x+.075,.245,f'{fps[i]} fps' if fps[i] else 'pause',ha='center',fontsize=10,fontweight='bold',color=INK)
    ax.text(x+.075,.17,f'{features[i]} features',ha='center',fontsize=9,color=MUTED)
ax.text(.05,.10,'Named flavor: arm64-v8a | camera request: 1280x720 @ 30 | display request: 120 Hz | raw frames: off',fontsize=10.5,color=INK)
save(fig,'poco_runtime_4_1.png')

# Validation
fig,ax=base();ax.set_xlim(0,1);ax.set_ylim(0,1)
ax.text(.03,.94,'Release Validation and Promotion Gates',fontsize=22,fontweight='bold',color=INK)
ax.text(.03,.895,'Source evidence is separated from Android build and physical-device claims.',fontsize=12,color=MUTED)
rows=[
('Portable C++ core','23 / 23','PASS',GREEN),
('Android C++ mock syntax','9 / 9','PASS',GREEN),
('Source contract','43 / 43','PASS',GREEN),
('KSEED CRC + SHA chain','complete','PASS',GREEN),
('Android SDK/NDK assemble','not run','CODEX',AMBER),
('POCO install + camera','not run','DEVICE',AMBER),
('Latency / thermal / battery','not measured','DEVICE',RED),
('SLAM / route accuracy','not measured','STUDY',RED),
]
for i,(name,val,status,c) in enumerate(rows):
    y=.78-i*.083
    ax.add_patch(FancyBboxPatch((.05,y-.045),.90,.065,boxstyle='round,pad=.006',facecolor='white',edgecolor=LINE,linewidth=1))
    ax.text(.075,y-.012,name,fontsize=11,color=INK,va='center')
    ax.text(.67,y-.012,val,fontsize=10,color=MUTED,va='center',ha='right')
    ax.add_patch(FancyBboxPatch((.76,y-.038),.16,.05,boxstyle='round,pad=.004',facecolor=c+'22',edgecolor=c,linewidth=1.3))
    ax.text(.84,y-.012,status,fontsize=9.5,fontweight='bold',color=c,ha='center',va='center')
ax.text(.50,.06,'The package is a source handoff, not a claimed APK or phone benchmark.',ha='center',fontsize=11,fontweight='bold',color=RED)
save(fig,'validation_4_1.png')

# Storage fixture
fig,ax=plt.subplots(figsize=(12,7),dpi=160);fig.patch.set_facecolor(BG);ax.set_facecolor(BG)
labels=['Raw synthetic luma','KSEED 4.1']; values=[17_280_000,79_053]
colors=[MUTED,GREEN]
bars=ax.bar(labels,values,color=colors,width=.55)
ax.set_yscale('log');ax.set_ylabel('Bytes (log scale)',color=INK);ax.grid(axis='y',alpha=.25)
ax.set_title('Deterministic Host Fixture Storage',fontsize=20,fontweight='bold',loc='left',color=INK,pad=18)
ax.text(-.49,2.6e7,'300 synthetic frames -> 63 keyframes -> 592 events',fontsize=11,color=MUTED)
for b,v in zip(bars,values): ax.text(b.get_x()+b.get_width()/2,v*1.15,f'{v:,} B',ha='center',fontsize=11,fontweight='bold',color=INK)
ax.text(.5,.02,'218.59x ratio in this fixture only - not a phone benchmark or compression guarantee.',transform=ax.transAxes,ha='center',fontsize=11,fontweight='bold',color=RED)
for spine in ['top','right']:ax.spines[spine].set_visible(False)
save(fig,'storage_fixture_4_1.png')
