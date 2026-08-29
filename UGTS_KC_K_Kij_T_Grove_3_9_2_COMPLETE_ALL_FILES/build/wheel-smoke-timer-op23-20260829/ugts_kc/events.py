from __future__ import annotations
from dataclasses import dataclass

def bisect_root(f,a,b,tol=1e-10,max_iter=100):
    fa=f(a); fb=f(b)
    if fa==0: return a
    if fb==0: return b
    if fa*fb>0: raise ValueError("root not bracketed")
    for _ in range(max_iter):
        m=(a+b)/2; fm=f(m)
        if abs(fm)<=tol or (b-a)/2<=tol: return m
        if fa*fm<=0: b=m; fb=fm
        else: a=m; fa=fm
    return (a+b)/2

def classify_event(g_before,g_at,g_after,derivative=None,tol=1e-8):
    if max(abs(g_before),abs(g_at),abs(g_after))<=tol: return 'coincident'
    if g_before*g_after<0: return 'crossing'
    if abs(g_at)<=tol:
        if derivative is not None and abs(derivative)<=tol: return 'tangency'
        return 'touch'
    return 'none'

@dataclass(frozen=True)
class Patch:
    priority: int
    updates: dict
    label: str = ''

def resolve_patches(patches):
    ordered=sorted(patches,key=lambda p:(-p.priority,p.label))
    result={}; owners={}
    conflicts=[]
    for p in ordered:
        for k,v in p.updates.items():
            if k in result and result[k]!=v:
                conflicts.append((k,owners[k],p.label,result[k],v))
                continue
            result[k]=v; owners[k]=p.label
    return result,tuple(conflicts)
