from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

def symplectic_euler(x,v,acceleration,dt):
    a=acceleration(x,v)
    v1=v+a*dt
    x1=x+v1*dt
    return x1,v1

def damped_oscillator_step(x,v,mass,stiffness,damping,force,dt):
    if mass<=0 or dt<=0: raise ValueError("mass and dt must be positive")
    return symplectic_euler(x,v,lambda xx,vv:(force-damping*vv-stiffness*xx)/mass,dt)

def graph_diffusion_step(values,edges,alpha,dt):
    if alpha<0 or dt<0: raise ValueError("alpha/dt must be nonnegative")
    out=list(values); delta=[0.0]*len(values)
    for i,j,w in edges:
        flow=alpha*w*(values[j]-values[i])
        delta[i]+=flow; delta[j]-=flow
    return tuple(values[i]+dt*delta[i] for i in range(len(values)))

def _lap_periodic(A,i,j):
    h=len(A); w=len(A[0])
    return (A[(i-1)%h][j]+A[(i+1)%h][j]+A[i][(j-1)%w]+A[i][(j+1)%w]-4*A[i][j])

def gray_scott_step(U,V,du=0.16,dv=0.08,feed=0.060,kill=0.062,dt=1.0):
    h=len(U); w=len(U[0])
    if h!=len(V) or any(len(r)!=w for r in U+V): raise ValueError("grid mismatch")
    Un=[[0.0]*w for _ in range(h)]; Vn=[[0.0]*w for _ in range(h)]
    for i in range(h):
        for j in range(w):
            u=U[i][j]; v=V[i][j]; uvv=u*v*v
            Un[i][j]=u+dt*(du*_lap_periodic(U,i,j)-uvv+feed*(1-u))
            Vn[i][j]=v+dt*(dv*_lap_periodic(V,i,j)+uvv-(feed+kill)*v)
    return Un,Vn

@dataclass
class HybridMode:
    name: str
    flow: Callable[[float,float,float], tuple[float,float]]

@dataclass
class HybridTransition:
    source: str
    target: str
    guard: Callable[[float,float,float], bool]
    reset: Callable[[float,float,float], tuple[float,float]]
    priority: int = 0

class HybridAutomaton:
    def __init__(self,modes,transitions,initial_mode):
        self.modes={m.name:m for m in modes}; self.transitions=list(transitions); self.mode=initial_mode
    def step(self,x,v,t,dt):
        x1,v1=self.modes[self.mode].flow(x,v,dt)
        eligible=[tr for tr in self.transitions if tr.source==self.mode and tr.guard(x1,v1,t+dt)]
        if eligible:
            tr=sorted(eligible,key=lambda z:(-z.priority,z.target))[0]
            x1,v1=tr.reset(x1,v1,t+dt); self.mode=tr.target
        return x1,v1,self.mode
