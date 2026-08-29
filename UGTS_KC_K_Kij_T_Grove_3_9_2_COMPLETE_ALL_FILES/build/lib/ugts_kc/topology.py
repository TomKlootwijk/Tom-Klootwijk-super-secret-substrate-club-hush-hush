from __future__ import annotations
import math
from dataclasses import dataclass
from .mathutil import mat_mul

def winding_number(polyline, point):
    if len(polyline)<3: return 0.0
    total=0.0
    px,py=point
    pts=list(polyline)
    if pts[0]!=pts[-1]: pts.append(pts[0])
    for a,b in zip(pts[:-1],pts[1:]):
        ax,ay=a[0]-px,a[1]-py; bx,by=b[0]-px,b[1]-py
        total += math.atan2(ax*by-ay*bx, ax*bx+ay*by)
    return total/(2*math.pi)

def covering_lift(theta, winding=0):
    return theta+2*math.pi*winding

def homotopy_signature(route, obstacles):
    return tuple(int(round(winding_number(route,o))) for o in obstacles)

@dataclass(frozen=True)
class BraidGenerator:
    index: int
    sign: int = 1
    def inverse(self): return BraidGenerator(self.index,-self.sign)

def reduce_braid(word):
    stack=[]
    for g in word:
        if g.index<1 or g.sign not in (-1,1): raise ValueError("invalid braid generator")
        if stack and stack[-1].index==g.index and stack[-1].sign==-g.sign:
            stack.pop()
        else:
            stack.append(g)
    return tuple(stack)

class CellComplex:
    """Small oriented cell complex represented by boundary dictionaries."""
    def __init__(self):
        self.cells={0:{}}
    def add_cell(self, dim, name, boundary=None):
        self.cells.setdefault(dim,{})[name]=dict(boundary or {})
    def boundary(self, dim, chain):
        out={}
        for cell,coef in chain.items():
            for face,inc in self.cells.get(dim,{}).get(cell,{}).items():
                out[face]=out.get(face,0)+coef*inc
        return {k:v for k,v in out.items() if v}
    def boundary_squared_zero(self, max_dim=None):
        if max_dim is None: max_dim=max(self.cells)
        for dim in range(2,max_dim+1):
            for cell in self.cells.get(dim,{}):
                b1=self.boundary(dim,{cell:1})
                b2=self.boundary(dim-1,b1)
                if b2: return False
        return True

def discrete_morse_critical(cells, pairing):
    paired=set(pairing.keys())|set(pairing.values())
    return tuple(c for c in cells if c not in paired)

def mat_close(A,B,tol=1e-9):
    return all(abs(A[i][j]-B[i][j])<=tol for i in range(len(A)) for j in range(len(A[0])))

def cocycle_ok(g_ij,g_jk,g_ik,tol=1e-9):
    return mat_close(mat_mul(g_ij,g_jk),g_ik,tol)
