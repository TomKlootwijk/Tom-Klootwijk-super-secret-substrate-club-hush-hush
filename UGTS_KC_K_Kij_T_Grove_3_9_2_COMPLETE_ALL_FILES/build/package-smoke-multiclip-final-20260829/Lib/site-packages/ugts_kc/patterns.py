from __future__ import annotations
import math
from .mathutil import clamp, distance, lerp, sign_pow

def superellipse(theta: float, a: float=1.0, b: float=1.0, n: float=2.0):
    if a <= 0 or b <= 0 or n <= 0: raise ValueError("a, b and n must be positive")
    p = 2.0/n
    return (a*sign_pow(math.cos(theta), p), b*sign_pow(math.sin(theta), p))

def gielis(theta: float, m: float=6.0, n1: float=1.0, n2: float=1.0, n3: float=1.0,
           a: float=1.0, b: float=1.0, radius_floor: float=1e-12):
    if min(abs(a),abs(b),abs(n1)) <= 0: raise ValueError("a, b and n1 must be nonzero")
    q1=abs(math.cos(m*theta/4.0)/a)**n2
    q2=abs(math.sin(m*theta/4.0)/b)**n3
    denom=max(q1+q2, radius_floor)
    r=denom**(-1.0/n1)
    return (r*math.cos(theta), r*math.sin(theta))

def rose(theta: float, k: float=5.0, a: float=1.0):
    r=a*math.cos(k*theta)
    return (r*math.cos(theta), r*math.sin(theta))

def lissajous(t: float, fx: float=3.0, fy: float=2.0, delta: float=math.pi/2,
              ax: float=1.0, ay: float=1.0):
    return (ax*math.sin(fx*t+delta), ay*math.sin(fy*t))

def epitrochoid(t: float, R: float=5.0, r: float=3.0, d: float=5.0):
    if r == 0: raise ValueError("r must be nonzero")
    q=(R+r)/r
    return ((R+r)*math.cos(t)-d*math.cos(q*t), (R+r)*math.sin(t)-d*math.sin(q*t))

def hypotrochoid(t: float, R: float=5.0, r: float=3.0, d: float=5.0):
    if r == 0: raise ValueError("r must be nonzero")
    q=(R-r)/r
    return ((R-r)*math.cos(t)+d*math.cos(q*t), (R-r)*math.sin(t)-d*math.sin(q*t))

def cycloid(t: float, r: float=1.0):
    return (r*(t-math.sin(t)), r*(1-math.cos(t)))

def trochoid(t: float, r: float=1.0, d: float=0.6):
    return (r*t-d*math.sin(t), r-d*math.cos(t))

def involute(t: float, r: float=1.0):
    return (r*(math.cos(t)+t*math.sin(t)), r*(math.sin(t)-t*math.cos(t)))

def catenary(x: float, a: float=1.0, x0: float=0.0, y0: float=0.0):
    if a <= 0: raise ValueError("a must be positive")
    return a*math.cosh((x-x0)/a)+y0

def clothoid(s: float, A: float=1.0, steps: int=400):
    if A <= 0 or steps < 2: raise ValueError("A>0 and steps>=2 required")
    if s == 0: return (0.0,0.0)
    sign=1.0 if s>=0 else -1.0
    length=abs(s); h=length/steps
    x=y=0.0
    for i in range(steps+1):
        u=i*h
        w=0.5 if i in (0,steps) else 1.0
        phase=u*u/(2*A*A)
        x += w*math.cos(phase)
        y += w*math.sin(phase)
    return (sign*x*h, sign*y*h)

def fermat_spiral(theta: float, a: float=1.0, branch: int=1):
    if branch not in (-1,1): raise ValueError("branch must be -1 or 1")
    r=a*math.sqrt(abs(theta))
    angle=theta if branch==1 else theta+math.pi
    return (r*math.cos(angle), r*math.sin(angle))

def archimedean_spiral(theta: float, a: float=0.0, b: float=0.2):
    r=a+b*theta
    return (r*math.cos(theta), r*math.sin(theta))

def rational_quadratic_bezier(p0,p1,p2,t: float,w: float=1.0):
    t=clamp(t,0.0,1.0); u=1.0-t
    den=u*u+2*w*u*t+t*t
    if abs(den)<1e-15: raise ValueError("degenerate rational denominator")
    return tuple((u*u*p0[i]+2*w*u*t*p1[i]+t*t*p2[i])/den for i in range(len(p0)))

def cubic_bezier(p0,p1,p2,p3,t: float):
    t=clamp(t,0.0,1.0); u=1.0-t
    return tuple(u**3*p0[i]+3*u*u*t*p1[i]+3*u*t*t*p2[i]+t**3*p3[i] for i in range(len(p0)))

def open_uniform_knots(n_ctrl: int, degree: int):
    if n_ctrl < degree+1: raise ValueError("not enough control points")
    n=n_ctrl-1; m=n+degree+1
    knots=[]
    for j in range(m+1):
        if j<=degree: knots.append(0.0)
        elif j>=m-degree: knots.append(1.0)
        else: knots.append((j-degree)/(m-2*degree))
    return knots

def _basis(i,p,t,knots):
    if p==0:
        if (knots[i] <= t < knots[i+1]) or (t==1.0 and knots[i+1]==1.0 and knots[i] < 1.0):
            return 1.0
        return 0.0
    left=0.0; right=0.0
    d1=knots[i+p]-knots[i]
    d2=knots[i+p+1]-knots[i+1]
    if d1>0: left=(t-knots[i])/d1*_basis(i,p-1,t,knots)
    if d2>0: right=(knots[i+p+1]-t)/d2*_basis(i+1,p-1,t,knots)
    return left+right

def bspline(control, t: float, degree: int=3, knots=None):
    t=clamp(t,0.0,1.0)
    if knots is None: knots=open_uniform_knots(len(control),degree)
    dims=len(control[0]); out=[0.0]*dims
    for i,p in enumerate(control):
        b=_basis(i,degree,t,knots)
        for d in range(dims): out[d]+=b*p[d]
    return tuple(out)

def nurbs(control, weights, t: float, degree: int=3, knots=None):
    if len(control)!=len(weights): raise ValueError("control/weight size mismatch")
    t=clamp(t,0.0,1.0)
    if knots is None: knots=open_uniform_knots(len(control),degree)
    dims=len(control[0]); out=[0.0]*dims; den=0.0
    for i,p in enumerate(control):
        b=_basis(i,degree,t,knots)*weights[i]
        den+=b
        for d in range(dims): out[d]+=b*p[d]
    if abs(den)<1e-15: raise ValueError("degenerate NURBS denominator")
    return tuple(x/den for x in out)

def reuleaux_triangle_points(width: float=2.0, samples_per_arc: int=64):
    if width<=0 or samples_per_arc<2: raise ValueError("invalid width/sampling")
    h=math.sqrt(3)*width/2
    A=(-width/2,-h/3); B=(width/2,-h/3); C=(0,2*h/3)
    # Ordered boundary: B -> C around A, C -> A around B, A -> B around C.
    specs=[(A,0.0,math.pi/3),
           (B,2*math.pi/3,math.pi),
           (C,-2*math.pi/3,-math.pi/3)]
    pts=[]
    for center,a0,a1 in specs:
        for j in range(samples_per_arc):
            q=j/(samples_per_arc-1); ang=a0+q*(a1-a0)
            pts.append((center[0]+width*math.cos(ang), center[1]+width*math.sin(ang)))
    return pts

def power_nearest(point, sites):
    if not sites: raise ValueError("sites required")
    best=None; best_val=float('inf')
    for i,site in enumerate(sites):
        pos=site[0]; weight=site[1] if len(site)>1 else 0.0
        val=sum((point[d]-pos[d])**2 for d in range(len(point)))-weight
        if val<best_val: best_val=val; best=i
    return best,best_val

def medial_midpoints(boundary_a, boundary_b):
    if not boundary_a or not boundary_b: return []
    out=[]
    for p in boundary_a:
        q=min(boundary_b,key=lambda z:distance(p,z))
        out.append(lerp(p,q,0.5))
    return out
