# UGTS-KC 3.6.2 SCLP - Formal Definition

**Version:** 3.6.2  
**SCLP:** Swept-Cone Log-Polar Packing  
**Requester-supplied attribution:** Tom Klootwijk, 10-07-1990, NL200678942 (not independently verified).

## 1. Scope and authoritative object

Version 3.6.2 is a referential delta over the course-corrected 3.6.1 BEA substrate. The attached source is treated as a source of geometric, topological, kinematic, grammar and packing operators. Rasterization, ray marching and display are outside the authoritative core.

The SCLP state is typed:

\[
q=(x,t,\rho,\theta,\phi,\dot\phi,\ddot\phi,o,s,b,\omega_L,K,a,\mathcal L,u),
\]

where `x` is position, `t` is linear time, `(rho,theta)` is a local log-polar chart, `phi` is a periodic hinge angle, `o` is orientation, `s` a sheet, `b` a branch bit, `omega_L` a bounded grammar-state word, `K` a 64-bit key, `a` a generative address, `L` lineage and `u` uncertainty.

## 2. Finite cone relation

Let `T>0` be slant length and `alpha in (0,pi/2)` the half-angle. Define

\[
h=T\cos\alpha,\qquad R=T\sin\alpha.
\]

For apex `c` and unit axis `a`, write

\[
z=a\cdot(x-c),\qquad q=\|(x-c)-za\|.
\]

The exact Euclidean signed distance is the signed distance from `(q,z)` to the filled meridian triangle with vertices `(-R,h),(R,h),(0,0)`. Interior is `0<=z<=h` and `q<=z tan(alpha)`.

A sphere relation is `f_S(x)=||x-c_S||-R_S`. Two sphere relations may form a union/intersection support certificate.

## 3. Swept relation with a certified bound

For a fixed-orientation translation `s(u)`, `u in [0,1]`, define the sweep relation

\[
F_{\rm sweep}(x)=\inf_{u\in[0,1]} d_C(x-s(u)).
\]

For a linear segment of length `L`, `n>=2` uniform samples and sample minimum `m_n`, the signed-distance translation law gives

\[
m_n-\frac{L}{2(n-1)}\le F_{\rm sweep}(x)\le m_n.
\]

This interval is the reference certificate. It does not claim that every sweep envelope is itself an exact SDF.

## 4. Log-polar metric and change-of-change

With `r=r0 exp(rho)`:

\[
x=r\cos\theta,\qquad y=r\sin\theta,
\]

\[
ds^2=r^2(d\rho^2+d\theta^2),\qquad
J=r\begin{bmatrix}\cos\theta&-\sin\theta\\\sin\theta&\cos\theta\end{bmatrix}.
\]

An exact log-radius increment is

\[
\Delta r=r(e^{\Delta\rho}-1).
\]

Velocity and acceleration are

\[
v=r(\dot\rho e_r+\dot\theta e_\theta),
\]

\[
a=r[(\ddot\rho+\dot\rho^2-\dot\theta^2)e_r+(\ddot\theta+2\dot\rho\dot\theta)e_\theta].
\]

The Cartesian gradient is `(f_rho e_r+f_theta e_theta)/r`. A physical force law remains separately typed.

## 5. One-bit jitter contract

A deterministic bit `b=H(seed,K,X) mod 2` yields `sigma=2b-1`. The optional perturbation is

\[
f_j=f+\epsilon_j\sigma.
\]

The authoritative residual is enclosed by `[f-epsilon_j,f+epsilon_j]`. The profile is valid only when `epsilon_j` lies below the declared guard margin and cannot change verified event ordering.

## 6. Time, winding and topological wrapping

Linear time is not replaced. A declared reference tick `X0` and period `P` define

\[
u=(X-X_0)/P,\qquad w=\lfloor u\rfloor,\qquad \psi=u-w\in[0,1).
\]

The source half-turn bundle twist on odd radial wraps is

\[
(\rho,\theta,\phi,o)\mapsto(\rho',\theta+\pi,-\phi,-o).
\]

It is retained as an internal state-bundle map. The orientation-reversing Klein profile uses

\[
(\rho,\theta,\phi,o)\mapsto(\rho',\pi-\theta,-\phi,-o)
\]

on odd wraps, with angular periodicity on the other boundary. Winding count and wrap count are lineage.

## 7. Hinge and missing-shackle calculus

The hinge state is `(phi,omega,alpha)`. Torque is only defined after a mechanical model is selected, for example

\[
\tau=I\alpha+c\omega+k\phi.
\]

Let a holonomic velocity constraint be `A(q) qdot=0`. Removing the declared shackle row gives `A'`. The freedom gain is

\[
\Delta d=\operatorname{nullity}(A')-\operatorname{nullity}(A).
\]

No chaos follows from this rank change alone.

For a regular zero surface with normal `n`, a proposed velocity can be projected into the tangent space by `P_T=I-nn^T`.

## 8. Binary branch and finite grammar

A guard produces a branch bit `b in {0,1}` and selects a declared transition or grammar production. Binary branching is not automatically chaotic.

The reference grammar expands each `F(T)` into two `F(T/2)` branches with a signed turn, stack delimiters and a metric-aware jitter token. Expansion is rejected when depth, symbol or stack budgets are exceeded. A topological chirality flip acts by the automorphism `+ <-> -` on turn commands.

## 9. 64-bit keys

The field widths are

| field | bits | states |
|---|---:|---:|
| rho | 20 | 1,048,576 |
| theta | 18 | 262,144 |
| X | 14 | 16,384 |
| phi | 12 | 4,096 |

Two layouts are explicit:

1. **Contiguous:** `[63:44]=rho`, `[43:26]=theta`, `[25:12]=X`, `[11:0]=phi`.
2. **Morton:** MSB round-robin `rho19,theta17,X13,phi11,...` until all field bits are consumed.

A radix-trie shift appends one key-prefix bit. It refines the corresponding scheduled field interval. It does not directly divide the physical coordinate.

The finite key space contains exactly `2^64` combinations.

## 10. Memory and metric discipline

Pointerless does not mean metadata-free. A sparse trie needs topology/presence bits plus navigation support. Eight raw 64-bit keys fit in a 64-byte cache line, but no execution-width or one-cycle claim follows.

The source widths `192/64=3`, `32/1=32` and `512/12=42.666...` are nominal ratios only. They become valid compression metrics only when both records preserve the same semantics under a declared reconstruction/error contract.

## 11. Referential handoff

The 3.6.2 delta produces typed support, relation, topology, branch, grammar, key and uncertainty records. Authority then returns to

\[
\text{support}\to\text{compatibility}\to\text{guard}\to\text{verified event}\to\text{transition}\to\text{lineage}.
\]
