from __future__ import annotations
import math
from typing import Iterable, Sequence

EPS = 1e-12

def add(a, b): return tuple(x+y for x,y in zip(a,b))
def sub(a, b): return tuple(x-y for x,y in zip(a,b))
def scale(a, s): return tuple(s*x for x in a)
def dot(a, b): return sum(x*y for x,y in zip(a,b))
def norm(a): return math.sqrt(dot(a,a))
def normalize(a, eps=EPS):
    n = norm(a)
    if n <= eps:
        raise ValueError("cannot normalize near-zero vector")
    return scale(a, 1.0/n)
def cross(a,b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def clamp(x, lo, hi): return lo if x < lo else hi if x > hi else x
def lerp(a,b,t): return tuple((1-t)*x+t*y for x,y in zip(a,b))
def distance(a,b): return norm(sub(a,b))
def sign_pow(x, p):
    if x == 0.0: return 0.0
    return math.copysign(abs(x)**p, x)

def mat_eye(n):
    return tuple(tuple(1.0 if i==j else 0.0 for j in range(n)) for i in range(n))
def mat_add(A,B):
    return tuple(tuple(A[i][j]+B[i][j] for j in range(len(A[0]))) for i in range(len(A)))
def mat_scale(A,s):
    return tuple(tuple(s*x for x in row) for row in A)
def mat_mul(A,B):
    return tuple(tuple(sum(A[i][k]*B[k][j] for k in range(len(B))) for j in range(len(B[0]))) for i in range(len(A)))
def mat_vec(A,v):
    return tuple(sum(A[i][j]*v[j] for j in range(len(v))) for i in range(len(A)))
def transpose(A):
    return tuple(tuple(A[i][j] for i in range(len(A))) for j in range(len(A[0])))
def det2(A): return A[0][0]*A[1][1]-A[0][1]*A[1][0]
def inv2(A, eps=EPS):
    d=det2(A)
    if abs(d)<=eps: raise ValueError("singular 2x2 matrix")
    return ((A[1][1]/d,-A[0][1]/d),(-A[1][0]/d,A[0][0]/d))
def skew(w):
    x,y,z=w
    return ((0.0,-z,y),(z,0.0,-x),(-y,x,0.0))
