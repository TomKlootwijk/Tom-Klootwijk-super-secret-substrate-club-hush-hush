from __future__ import annotations
import math
from .mathutil import (EPS, add, clamp, cross, distance, dot, inv2, lerp, mat_add, mat_eye,
                       mat_mul, mat_scale, mat_vec, norm, normalize, scale, skew, sub, transpose)

def se2_exp(vx,vy,omega,t=1.0):
    th=omega*t
    if abs(omega)<1e-12:
        R=((1.0,0.0),(0.0,1.0)); p=(vx*t,vy*t)
    else:
        c=math.cos(th); s=math.sin(th)
        R=((c,-s),(s,c))
        p=((s*vx-(1-c)*vy)/omega, ((1-c)*vx+s*vy)/omega)
    return ((R[0][0],R[0][1],p[0]),(R[1][0],R[1][1],p[1]),(0.0,0.0,1.0))

def rodrigues(omega,t=1.0):
    th=norm(omega)*t
    if th<1e-12: return mat_eye(3)
    k=scale(omega,1.0/norm(omega)); K=skew(k); K2=mat_mul(K,K)
    return mat_add(mat_add(mat_eye(3),mat_scale(K,math.sin(th))),mat_scale(K2,1-math.cos(th)))

def se3_exp(omega,v,t=1.0):
    wnorm=norm(omega)
    if wnorm<1e-12:
        R=mat_eye(3); p=scale(v,t)
    else:
        W=skew(omega); W2=mat_mul(W,W); th=wnorm*t
        R=mat_add(mat_add(mat_eye(3),mat_scale(W,math.sin(th)/wnorm)),
                  mat_scale(W2,(1-math.cos(th))/(wnorm*wnorm)))
        V=mat_add(mat_add(mat_scale(mat_eye(3),t),
                          mat_scale(W,(1-math.cos(th))/(wnorm*wnorm))),
                  mat_scale(W2,(th-math.sin(th))/(wnorm**3)))
        p=mat_vec(V,v)
    return ((R[0][0],R[0][1],R[0][2],p[0]),
            (R[1][0],R[1][1],R[1][2],p[1]),
            (R[2][0],R[2][1],R[2][2],p[2]),
            (0.0,0.0,0.0,1.0))

def transform_inverse(T):
    R=tuple(tuple(T[i][j] for j in range(3)) for i in range(3)); Rt=transpose(R)
    p=(T[0][3],T[1][3],T[2][3]); pinv=scale(mat_vec(Rt,p),-1.0)
    return ((Rt[0][0],Rt[0][1],Rt[0][2],pinv[0]),
            (Rt[1][0],Rt[1][1],Rt[1][2],pinv[1]),
            (Rt[2][0],Rt[2][1],Rt[2][2],pinv[2]),
            (0.0,0.0,0.0,1.0))

def transform_mul(A,B): return mat_mul(A,B)

def so3_log(R):
    tr=R[0][0]+R[1][1]+R[2][2]
    c=clamp((tr-1.0)/2.0,-1.0,1.0); th=math.acos(c)
    if th<1e-10: return (0.0,0.0,0.0)
    factor=th/(2*math.sin(th))
    return (factor*(R[2][1]-R[1][2]),factor*(R[0][2]-R[2][0]),factor*(R[1][0]-R[0][1]))

def se3_log(T):
    R=tuple(tuple(T[i][j] for j in range(3)) for i in range(3)); p=(T[0][3],T[1][3],T[2][3])
    omega=so3_log(R); th=norm(omega)
    if th<1e-10: return omega,p
    W=skew(omega); W2=mat_mul(W,W)
    # inverse left Jacobian for rotation vector omega
    a=1.0/(th*th)-(1+math.cos(th))/(2*th*math.sin(th))
    Vinv=mat_add(mat_add(mat_eye(3),mat_scale(W,-0.5)),mat_scale(W2,a))
    v=mat_vec(Vinv,p)
    return omega,v

def se3_interpolate(T0,T1,t):
    t=clamp(t,0.0,1.0)
    rel=transform_mul(transform_inverse(T0),T1)
    omega,v=se3_log(rel)
    return transform_mul(T0,se3_exp(omega,v,t))

def quat_normalize(q):
    n=math.sqrt(sum(x*x for x in q))
    if n<1e-15: raise ValueError("zero quaternion")
    return tuple(x/n for x in q)

def quat_slerp(q0,q1,t):
    t=clamp(t,0.0,1.0); q0=quat_normalize(q0); q1=quat_normalize(q1)
    d=sum(a*b for a,b in zip(q0,q1))
    if d<0: q1=tuple(-x for x in q1); d=-d
    d=clamp(d,-1.0,1.0)
    if d>0.9995: return quat_normalize(tuple((1-t)*a+t*b for a,b in zip(q0,q1)))
    th=math.acos(d); s=math.sin(th)
    a=math.sin((1-t)*th)/s; b=math.sin(t*th)/s
    return tuple(a*x+b*y for x,y in zip(q0,q1))

def frenet_frame(r1,r2):
    T=normalize(r1); B=normalize(cross(r1,r2)); N=cross(B,T)
    kappa=norm(cross(r1,r2))/(norm(r1)**3)
    return T,N,B,kappa

def bishop_frames(points, initial_normal=(0.0,0.0,1.0)):
    if len(points)<2: raise ValueError("at least two points required")
    tangents=[]
    for i in range(len(points)-1): tangents.append(normalize(sub(points[i+1],points[i])))
    tangents.append(tangents[-1])
    n0=sub(initial_normal,scale(tangents[0],dot(initial_normal,tangents[0])))
    if norm(n0)<1e-9:
        trial=(1.0,0.0,0.0) if abs(tangents[0][0])<0.8 else (0.0,1.0,0.0)
        n0=sub(trial,scale(tangents[0],dot(trial,tangents[0])))
    n=normalize(n0); frames=[]
    for T in tangents:
        n=sub(n,scale(T,dot(n,T)))
        if norm(n)<1e-9:
            trial=(1.0,0.0,0.0) if abs(T[0])<0.8 else (0.0,1.0,0.0)
            n=sub(trial,scale(T,dot(trial,T)))
        n=normalize(n); b=normalize(cross(T,n)); frames.append((T,n,b))
    return frames

def arc_length_table(points):
    if not points: return []
    out=[0.0]
    for a,b in zip(points[:-1],points[1:]): out.append(out[-1]+distance(a,b))
    return out

def parameter_at_length(lengths,s):
    if not lengths: raise ValueError("length table required")
    s=clamp(s,0.0,lengths[-1])
    lo=0
    while lo+1<len(lengths) and lengths[lo+1]<s: lo+=1
    if lo+1==len(lengths): return 1.0
    den=lengths[lo+1]-lengths[lo]
    f=0.0 if den<=0 else (s-lengths[lo])/den
    return (lo+f)/(len(lengths)-1)

def curvature_limited_speed(kappa,a_lat_max,v_nominal,eps=1e-12):
    if a_lat_max<=0 or v_nominal<0: raise ValueError("invalid limits")
    if abs(kappa)<=eps: return v_nominal,0.0
    v=min(v_nominal,math.sqrt(a_lat_max/abs(kappa)))
    return v,v*kappa

def quintic_scurve(u,distance=1.0,duration=1.0):
    if duration<=0: raise ValueError("duration must be positive")
    u=clamp(u,0.0,1.0)
    s=10*u**3-15*u**4+6*u**5
    ds=30*u**2-60*u**3+30*u**4
    d2=60*u-180*u**2+120*u**3
    d3=60-360*u+360*u**2
    return (distance*s, distance*ds/duration, distance*d2/duration**2, distance*d3/duration**3)

def limit_aware_duration(distance_value,v_max,a_max,j_max,samples=4000):
    if min(v_max,a_max,j_max)<=0 or distance_value<0: raise ValueError("invalid limits")
    peak_v=peak_a=peak_j=0.0
    for i in range(samples+1):
        _,v,a,j=quintic_scurve(i/samples,1.0,1.0)
        peak_v=max(peak_v,abs(v)); peak_a=max(peak_a,abs(a)); peak_j=max(peak_j,abs(j))
    D=distance_value
    return max(D*peak_v/v_max, math.sqrt(D*peak_a/a_max) if D else 0.0,
               (D*peak_j/j_max)**(1/3) if D else 0.0)

def planar_forward_kinematics(lengths,angles):
    if len(lengths)!=len(angles): raise ValueError("size mismatch")
    x=y=th=0.0; points=[(0.0,0.0)]
    for L,q in zip(lengths,angles):
        th+=q; x+=L*math.cos(th); y+=L*math.sin(th); points.append((x,y))
    return points

def planar_jacobian(lengths,angles):
    n=len(lengths); th=[]; acc=0.0
    for q in angles: acc+=q; th.append(acc)
    J=[[0.0]*n for _ in range(2)]
    for j in range(n):
        for i in range(j,n):
            J[0][j]+=-lengths[i]*math.sin(th[i])
            J[1][j]+= lengths[i]*math.cos(th[i])
    return tuple(tuple(row) for row in J)

def dls_ik(lengths,initial,target,damping=1e-2,iterations=100,tol=1e-8):
    q=list(initial)
    for _ in range(iterations):
        end=planar_forward_kinematics(lengths,q)[-1]; e=(target[0]-end[0],target[1]-end[1])
        if norm(e)<=tol: break
        J=planar_jacobian(lengths,q)
        JJt=((dot(J[0],J[0])+damping*damping,dot(J[0],J[1])),
             (dot(J[1],J[0]),dot(J[1],J[1])+damping*damping))
        y=mat_vec(inv2(JJt),e)
        dq=tuple(J[0][i]*y[0]+J[1][i]*y[1] for i in range(len(q)))
        q=[q[i]+dq[i] for i in range(len(q))]
    return tuple(q),planar_forward_kinematics(lengths,q)[-1]
