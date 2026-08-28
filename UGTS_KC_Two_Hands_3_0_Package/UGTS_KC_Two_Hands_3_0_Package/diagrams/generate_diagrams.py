from pathlib import Path
import math

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Polygon, Rectangle
import matplotlib.image as mpimg
import cairosvg

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'diagrams'

NAVY='#0b2a3b'; TEAL='#188f93'; TEAL_LIGHT='#dceff0'; GOLD='#d9a51b'; GOLD_LIGHT='#f8efd0'
CORAL='#d76a58'; CORAL_LIGHT='#f7dfda'; PURPLE='#6c5aa7'; PURPLE_LIGHT='#e9e4f5'; GREEN='#4e9b67'; GREEN_LIGHT='#e1f0e5'
GRAY='#5c6d73'; LIGHT='#f5f8f9'; WHITE='#ffffff'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.titleweight':'bold'})


def box(ax,xy,w,h,text,fc=WHITE,ec=TEAL,lw=1.8,fontsize=10,rounding=0.05):
    p=FancyBboxPatch(xy,w,h,boxstyle=f'round,pad=0.02,rounding_size={rounding}',facecolor=fc,edgecolor=ec,linewidth=lw)
    ax.add_patch(p); ax.text(xy[0]+w/2,xy[1]+h/2,text,ha='center',va='center',fontsize=fontsize,color=NAVY,wrap=True)
    return p

def arrow(ax,a,b,color=GRAY,rad=0.0,lw=1.6):
    ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=13,color=color,linewidth=lw,connectionstyle=f'arc3,rad={rad}'))


def save(fig,name):
    fig.savefig(OUT/name,dpi=190,bbox_inches='tight',facecolor='white')
    plt.close(fig)

# Architecture
fig,ax=plt.subplots(figsize=(13,7.5)); ax.set_xlim(0,13); ax.set_ylim(0,8); ax.axis('off')
ax.text(0.4,7.55,'UGTS-KC Two Hands 3.0 architecture',fontsize=22,fontweight='bold',color=NAVY)
ax.text(0.4,7.18,'The 2.0 query-first core remains authoritative; production layers compile, interact, replay and render downstream.',fontsize=11,color=GRAY)
ax.add_patch(Rectangle((0.35,5.2),12.3,1.65,facecolor=TEAL_LIGHT,edgecolor='none'))
ax.text(0.55,6.55,'AUTHORITATIVE SUBSTRATE (retained)',fontsize=11,fontweight='bold',color=TEAL)
labels=['Finite grammar\nG','Patterns / fields\nP + F','Kinematics / dynamics\nK + D','Support + compatibility\nS + C','Guards / transitions\nR + T','Topology + lineage\nI + L']
for i,l in enumerate(labels): box(ax,(0.55+i*2.0,5.48),1.72,0.76,l,fc=WHITE,ec=TEAL,fontsize=9)
for i in range(5): arrow(ax,(2.27+i*2.0,5.86),(2.51+i*2.0,5.86),TEAL)
ax.add_patch(Rectangle((0.35,2.92),12.3,1.72,facecolor=GOLD_LIGHT,edgecolor='none'))
ax.text(0.55,4.33,'3.0 PRODUCTION RUNTIME',fontsize=11,fontweight='bold',color=GOLD)
prod=[('Assets / scene\nA',0.55),('Spatial / streaming\nX',2.58),('Geometry compiler\nM',4.61),('Render / materials\nV',6.64),('Two hands\nH',8.67),('Replay / network / editor\nN + E',10.70)]
for l,x in prod: box(ax,(x,3.23),1.75,0.78,l,fc=WHITE,ec=GOLD,fontsize=9)
for i in range(5): arrow(ax,(2.30+i*2.03,3.62),(2.55+i*2.03,3.62),GOLD)
for x in [1.4,3.5,5.5,7.6,9.6,11.55]: arrow(ax,(x,5.2),(x,4.03),GRAY)
ax.add_patch(Rectangle((0.35,0.72),12.3,1.55,facecolor=PURPLE_LIGHT,edgecolor='none'))
ax.text(0.55,1.98,'DOWNSTREAM ENDPOINTS',fontsize=11,fontweight='bold',color=PURPLE)
end=[('glTF runtime\nasset',0.75),('USD authoring\nscene',3.1),('Vulkan / WebGPU\ntargets',5.45),('OpenXR / desktop\ninput',7.8),('SVG preview /\neditor diagnostics',10.15)]
for l,x in end: box(ax,(x,1.02),1.95,0.68,l,fc=WHITE,ec=PURPLE,fontsize=9)
for x in [1.7,4.1,6.45,8.8,11.15]: arrow(ax,(x,2.92),(x,1.72),GRAY)
ax.text(0.45,0.25,'Discrete change remains: support -> compatibility -> guard -> verified proposal -> deterministic commit -> lineage/replay.',fontsize=11,fontweight='bold',color=CORAL)
save(fig,'architecture_3_0.png')

# Geometry pipeline
fig,ax=plt.subplots(figsize=(13,5.8)); ax.set_xlim(0,13); ax.set_ylim(0,6); ax.axis('off')
ax.text(0.35,5.55,'Geometry compilation with separate error budgets',fontsize=21,fontweight='bold',color=NAVY)
steps=[('Authoritative\npattern / field',0.45,TEAL_LIGHT,TEAL),('Adaptive sampling\ncurve or grid',2.65,GOLD_LIGHT,GOLD),('Frame / gradient\nderivatives',4.85,PURPLE_LIGHT,PURPLE),('Derived mesh\ntube / iso-surface',7.05,GREEN_LIGHT,GREEN),('Bounds + LOD +\ncollision proxy',9.25,CORAL_LIGHT,CORAL),('Render / export\nnon-authoritative',11.45,TEAL_LIGHT,TEAL)]
for text,x,fc,ec in steps:
    box(ax,(x,3.25),1.45,1.02,text,fc=fc,ec=ec,fontsize=9)
for i in range(len(steps)-1): arrow(ax,(steps[i][1]+1.45,3.76),(steps[i+1][1],3.76),GRAY)
contracts=[('world error',0.9),('collision error',3.3),('screen-space pixels',5.7),('normal error',8.2),('topology status',10.65)]
for text,x in contracts: box(ax,(x,1.35),1.55,0.65,text,fc=WHITE,ec=NAVY,fontsize=9)
ax.text(0.45,2.45,'Every derived representation carries an explicit contract:',fontsize=11,fontweight='bold',color=NAVY)
arrow(ax,(6.5,3.2),(6.5,2.05),CORAL)
ax.text(0.45,0.55,'A visually acceptable triangle mesh is not automatically collision-safe or event-authoritative.',fontsize=11,fontweight='bold',color=CORAL)
save(fig,'geometry_compiler_pipeline.png')

# Bimanual calculus
fig,ax=plt.subplots(figsize=(12.5,6.8)); ax.set_xlim(-4.2,7.2); ax.set_ylim(-3.2,3.5); ax.set_aspect('equal'); ax.axis('off')
ax.text(-4.0,3.1,'KC Two Hands bimanual transform calculus',fontsize=21,fontweight='bold',color=NAVY)
# initial
ax.text(-3.8,2.45,'Anchor',fontsize=13,fontweight='bold',color=TEAL)
L0=(-3.0,0.3); R0=(-0.7,0.3); M0=((-3.0-0.7)/2,0.3)
for p,label in [(L0,'L0'),(R0,'R0')]:
    ax.add_patch(Circle(p,0.23,facecolor=TEAL_LIGHT,edgecolor=TEAL,linewidth=2)); ax.text(*p,label,ha='center',va='center',fontweight='bold',color=NAVY)
ax.plot([L0[0],R0[0]],[L0[1],R0[1]],color=TEAL,linewidth=2)
ax.add_patch(Polygon([(M0[0]-0.55,-0.3),(M0[0]+0.55,-0.3),(M0[0]+0.55,0.7),(M0[0]-0.55,0.7)],closed=True,facecolor=TEAL_LIGHT,edgecolor=NAVY,linewidth=1.5))
ax.text(M0[0],-0.55,'object initial',ha='center',color=GRAY)
# current
ax.text(1.0,2.45,'Current',fontsize=13,fontweight='bold',color=GOLD)
L1=(1.0,-0.3); R1=(4.8,1.1); M1=((1.0+4.8)/2,0.4)
for p,label in [(L1,'L1'),(R1,'R1')]:
    ax.add_patch(Circle(p,0.27,facecolor=GOLD_LIGHT,edgecolor=GOLD,linewidth=2)); ax.text(*p,label,ha='center',va='center',fontweight='bold',color=NAVY)
ax.plot([L1[0],R1[0]],[L1[1],R1[1]],color=GOLD,linewidth=2)
angle=math.atan2(R1[1]-L1[1],R1[0]-L1[0]); w,h=1.4,1.0
corners=[]
for x,y in [(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)]:
    corners.append((M1[0]+x*math.cos(angle)-y*math.sin(angle),M1[1]+x*math.sin(angle)+y*math.cos(angle)))
ax.add_patch(Polygon(corners,closed=True,facecolor=GOLD_LIGHT,edgecolor=NAVY,linewidth=1.5))
ax.text(M1[0],M1[1]-1.0,'translated + scaled + aligned + twisted',ha='center',color=GRAY)
arrow(ax,(-0.2,1.7),(0.8,1.7),CORAL,lw=2)
box(ax,(-3.6,-2.55),2.15,0.82,'midpoint\ntranslation',fc=WHITE,ec=TEAL,fontsize=10)
box(ax,(-0.9,-2.55),2.15,0.82,'separation ratio\nscale',fc=WHITE,ec=GOLD,fontsize=10)
box(ax,(1.8,-2.55),2.15,0.82,'pair-axis\nalignment',fc=WHITE,ec=PURPLE,fontsize=10)
box(ax,(4.5,-2.55),2.15,0.82,'wrist orientation\ntwist',fc=WHITE,ec=CORAL,fontsize=10)
ax.text(-3.7,-3.0,'Low confidence or degenerate separation returns a bounded rejection state; object identity is unchanged.',fontsize=10.5,fontweight='bold',color=CORAL)
save(fig,'two_hands_calculus.png')

# Event commit
fig,ax=plt.subplots(figsize=(13,5.7)); ax.set_xlim(0,13); ax.set_ylim(0,6); ax.axis('off')
ax.text(0.35,5.52,'Parallel proposal, deterministic authoritative commit',fontsize=21,fontweight='bold',color=NAVY)
box(ax,(0.55,3.5),1.65,0.9,'CPU event\nproposals',fc=TEAL_LIGHT,ec=TEAL)
box(ax,(0.55,1.95),1.65,0.9,'GPU event\nproposals',fc=PURPLE_LIGHT,ec=PURPLE)
box(ax,(2.85,2.7),1.9,1.05,'Support +\ncompatibility +\nguard/error verifier',fc=GOLD_LIGHT,ec=GOLD,fontsize=9)
box(ax,(5.45,2.7),1.75,1.05,'Deterministic order\ntime / priority /\nsource / ID',fc=CORAL_LIGHT,ec=CORAL,fontsize=9)
box(ax,(7.9,2.7),1.75,1.05,'Conflict policy\npriority / merge /\nreject',fc=WHITE,ec=NAVY,fontsize=9)
box(ax,(10.35,2.7),1.95,1.05,'Atomic scene /\ntopology / dynamics\npatch',fc=GREEN_LIGHT,ec=GREEN,fontsize=9)
for a,b in [((2.2,3.95),(2.85,3.4)),((2.2,2.4),(2.85,3.05)),((4.75,3.22),(5.45,3.22)),((7.2,3.22),(7.9,3.22)),((9.65,3.22),(10.35,3.22))]: arrow(ax,a,b,GRAY)
box(ax,(8.45,0.85),3.3,0.76,'lineage + novelty + replay log',fc=PURPLE_LIGHT,ec=PURPLE,fontsize=10)
arrow(ax,(11.3,2.7),(10.1,1.63),PURPLE)
ax.text(0.55,0.75,'Unchecked shader writes never become gameplay authority.',fontsize=12,fontweight='bold',color=CORAL)
save(fig,'event_commit_pipeline.png')

# Scene and spatial
fig,ax=plt.subplots(figsize=(13,6.5)); ax.set_xlim(0,13); ax.set_ylim(0,7); ax.axis('off')
ax.text(0.35,6.55,'Scene composition and hybrid spatial pruning',fontsize=21,fontweight='bold',color=NAVY)
box(ax,(0.6,4.9),1.6,0.72,'World node',fc=TEAL_LIGHT,ec=TEAL)
box(ax,(0.45,3.4),1.9,0.72,'Interactive sculpture',fc=GOLD_LIGHT,ec=GOLD,fontsize=9)
box(ax,(2.7,3.4),1.9,0.72,'Gyroid instance',fc=PURPLE_LIGHT,ec=PURPLE,fontsize=9)
box(ax,(0.45,1.9),1.9,0.72,'Gielis tube asset',fc=WHITE,ec=NAVY,fontsize=9)
box(ax,(2.7,1.9),1.9,0.72,'Gyroid mesh asset',fc=WHITE,ec=NAVY,fontsize=9)
arrow(ax,(1.4,4.9),(1.4,4.12)); arrow(ax,(1.7,4.9),(3.45,4.12),rad=-0.1)
arrow(ax,(1.4,3.4),(1.4,2.62),GOLD); arrow(ax,(3.65,3.4),(3.65,2.62),PURPLE)
ax.text(0.55,1.25,'Assets are reusable payloads; nodes retain transform, tags and lineage.',fontsize=10.5,color=GRAY)
# spatial right
box(ax,(6.2,4.95),1.55,0.7,'Scene bounds',fc=TEAL_LIGHT,ec=TEAL)
box(ax,(8.25,4.95),1.55,0.7,'BVH',fc=GOLD_LIGHT,ec=GOLD)
box(ax,(10.3,4.95),1.55,0.7,'Frustum / ray',fc=PURPLE_LIGHT,ec=PURPLE)
box(ax,(6.2,3.35),1.55,0.7,'Streaming cells',fc=WHITE,ec=NAVY,fontsize=9)
box(ax,(8.25,3.35),1.55,0.7,'Local support',fc=WHITE,ec=TEAL,fontsize=9)
box(ax,(10.3,3.35),1.55,0.7,'Compatibility',fc=WHITE,ec=CORAL,fontsize=9)
box(ax,(8.25,1.65),1.55,0.7,'Exact guard /\nrelation',fc=GREEN_LIGHT,ec=GREEN,fontsize=9)
arrow(ax,(7.75,5.3),(8.25,5.3)); arrow(ax,(9.8,5.3),(10.3,5.3)); arrow(ax,(7.0,4.95),(7.0,4.05)); arrow(ax,(9.0,4.95),(9.0,4.05)); arrow(ax,(11.1,4.95),(11.1,4.05))
arrow(ax,(7.0,3.35),(8.55,2.35)); arrow(ax,(9.0,3.35),(9.0,2.35)); arrow(ax,(11.1,3.35),(9.5,2.35))
ax.text(6.0,0.75,'Conventional indexing complements - rather than replaces - UGTS support and compatibility.',fontsize=10.8,fontweight='bold',color=CORAL)
save(fig,'scene_spatial_runtime.png')

# Standards/interchange
fig,ax=plt.subplots(figsize=(12.5,6.5)); ax.set_xlim(0,12.5); ax.set_ylim(0,7); ax.axis('off')
ax.text(0.35,6.55,'Interchange and backend targets',fontsize=21,fontweight='bold',color=NAVY)
box(ax,(4.45,2.75),3.3,1.25,'KC Two Hands 3.0\nscene + event schema',fc=TEAL_LIGHT,ec=TEAL,fontsize=13)
targets=[('glTF 2.0\nruntime assets',(0.65,4.8),GOLD_LIGHT,GOLD),('OpenUSD\nauthoring scene',(0.65,1.15),PURPLE_LIGHT,PURPLE),('Vulkan 1.4\nnative target',(9.4,4.8),CORAL_LIGHT,CORAL),('WebGPU / WGSL\nportable target',(9.4,1.15),GREEN_LIGHT,GREEN),('OpenXR\nhand adapter',(4.75,5.1),WHITE,NAVY),('MaterialX / OCIO\nlook + color',(4.75,0.55),WHITE,NAVY)]
for text,xy,fc,ec in targets: box(ax,xy,2.35,0.86,text,fc=fc,ec=ec,fontsize=10)
cent=(6.1,3.38)
for text,xy,fc,ec in targets:
    end=(xy[0]+1.175,xy[1]+0.43)
    arrow(ax,cent,end,ec,rad=0.05)
ax.text(0.65,0.35,'Exports are downstream artifacts; standards targets do not replace authoritative event/lineage records.',fontsize=10.8,fontweight='bold',color=CORAL)
save(fig,'interchange_targets.png')

# Validation counts
fig,ax=plt.subplots(figsize=(11.5,6.2));
labels=['Source baseline\nM001-M197','KC 2.0 additions\nM198-M257','KC 3.0 additions\nM258-M329','Passing tests']
values=[197,60,72,117]; colors=[NAVY,TEAL,GOLD,PURPLE]
bars=ax.bar(labels,values,color=colors,width=0.62)
ax.set_title('KC Two Hands 3.0 package counts',fontsize=20,color=NAVY,pad=18)
ax.set_ylabel('Count'); ax.set_ylim(0,225); ax.grid(axis='y',alpha=0.22)
for b,v in zip(bars,values): ax.text(b.get_x()+b.get_width()/2,v+5,str(v),ha='center',fontweight='bold',fontsize=13,color=NAVY)
ax.text(0.01,-0.19,'Extended catalog total: 329 mechanisms. Test count includes the retained 47-test KC 2.0 suite and 70 new tests.',transform=ax.transAxes,fontsize=10.5,color=GRAY)
for spine in ['top','right']: ax.spines[spine].set_visible(False)
save(fig,'validation_counts.png')

# Before/after rasterized sandbox
before_png=OUT/'_sandbox_before.png'; after_png=OUT/'_sandbox_after.png'
cairosvg.svg2png(url=str(ROOT/'examples/output/sandbox_before.svg'),write_to=str(before_png),output_width=1100,output_height=720)
cairosvg.svg2png(url=str(ROOT/'examples/output/sandbox_after.svg'),write_to=str(after_png),output_width=1100,output_height=720)
fig,ax=plt.subplots(figsize=(13,5.1)); ax.axis('off')
img1=mpimg.imread(before_png); img2=mpimg.imread(after_png)
canvas_ax1=fig.add_axes([0.02,0.08,0.47,0.80]); canvas_ax1.imshow(img1); canvas_ax1.axis('off'); canvas_ax1.set_title('Before authoritative hand event',fontsize=13,fontweight='bold',color=NAVY)
canvas_ax2=fig.add_axes([0.51,0.08,0.47,0.80]); canvas_ax2.imshow(img2); canvas_ax2.axis('off'); canvas_ax2.set_title('After deterministic two-hand transform commit',fontsize=13,fontweight='bold',color=NAVY)
fig.suptitle('Runnable KC Two Hands sandbox vertical slice',fontsize=21,fontweight='bold',color=NAVY,y=0.98)
fig.text(0.5,0.015,'Both images are deterministic CPU/SVG projections; the event log and scene state remain authoritative.',ha='center',fontsize=10.5,color=CORAL,fontweight='bold')
save(fig,'sandbox_before_after.png')
before_png.unlink(missing_ok=True); after_png.unlink(missing_ok=True)
