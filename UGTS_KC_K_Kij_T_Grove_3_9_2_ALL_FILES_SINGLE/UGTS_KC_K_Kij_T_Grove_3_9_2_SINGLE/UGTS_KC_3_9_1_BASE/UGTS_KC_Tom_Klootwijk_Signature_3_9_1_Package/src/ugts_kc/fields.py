from __future__ import annotations
import math
from .mathutil import distance, lerp

def superquadric_field(p, scales=(1.0,1.0,1.0), e1=1.0, e2=1.0):
    if min(scales)<=0 or e1<=0 or e2<=0: raise ValueError("positive scales/exponents required")
    x,y,z=(p[i]/scales[i] for i in range(3))
    xy=(abs(x)**(2.0/e2)+abs(y)**(2.0/e2))**(e2/e1)
    return xy+abs(z)**(2.0/e1)-1.0

def ellipsoid_field(p, scales=(1.0,1.0,1.0)):
    if min(scales)<=0: raise ValueError("positive scales required")
    return sum((p[i]/scales[i])**2 for i in range(3))-1.0

def tube_field(p, curve_samples, radius=0.2):
    if radius<0 or not curve_samples: raise ValueError("samples and nonnegative radius required")
    return min(distance(p,q) for q in curve_samples)-radius

def generalized_cylinder(center, e1, e2, u, v):
    return tuple(center[i]+u*e1[i]+v*e2[i] for i in range(len(center)))

def ruled_surface(c0,c1,u,v):
    return lerp(c0(u),c1(u),v)

def helicoid(u,v,pitch=0.2):
    return (v*math.cos(u),v*math.sin(u),pitch*u)

def catenoid(u,v,a=1.0):
    if a<=0: raise ValueError("a must be positive")
    r=a*math.cosh(v/a)
    return (r*math.cos(u),r*math.sin(u),v)

def gyroid_field(p, threshold=0.0):
    x,y,z=p
    return math.sin(x)*math.cos(y)+math.sin(y)*math.cos(z)+math.sin(z)*math.cos(x)-threshold

def schwarz_p_field(p, threshold=0.0):
    x,y,z=p
    return math.cos(x)+math.cos(y)+math.cos(z)-threshold

def metaball_field(p, centers, weights=None, support=1.0, threshold=1.0):
    if support<=0: raise ValueError("support must be positive")
    if weights is None: weights=[1.0]*len(centers)
    if len(weights)!=len(centers): raise ValueError("size mismatch")
    total=0.0
    for c,w in zip(centers,weights):
        q=distance(p,c)/support
        if q<1.0:
            # compact C2-ish polynomial kernel
            total += w*(1-q*q)**3
    return total-threshold

def offset_field(value, delta):
    return value-delta

def constant_speed_arrival(p, source=(0.0,0.0,0.0), speed=1.0):
    if speed<=0: raise ValueError("speed must be positive")
    return distance(p,source)/speed
