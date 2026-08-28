# UGTS-KC 3.6.1 BEA - Course-Corrected Synthetic Formal Definition

**Version:** 3.6.1  
**Revision status:** course-corrected superseding edition  
**BEA expansion:** Boundary-Equivalence-Alignment  
**Requester-supplied attribution:** Tom Klootwijk, 10-07-1990, NL200678942. These identifiers are recorded as supplied and were not independently verified.

## 1. Scope

This revision replaces the earlier planar-font interpretation of BEA 3.6.1 with a named synthetic profile. The source strings are not treated as ordinary rasterized glyphs. They are literal labels for finite 1-dimensional CW-complexes with profile-supplied cycle annotations, zero-metric whitespace hinge cells, an algebraic four-cycle torus realization, a constrained XOR translation and a semantic quotient metric.

Every result below is exact **inside** profile `bea361:synthetic-cell-complex-v2`. No result is automatically transferable to a font, dialect, historical claim, physical object, Euclidean image SDF or unconstrained byte encoding.

## 2. Literal representations

The shipped pair is:

- source `repr:negentien`: text `negentien`, semantic value 19, intrinsic cycle positions `(1,2,3,7)`;
- target `repr:no-neg-moat`: text `no neg moat`, semantic value 19, intrinsic cycle positions `(1,5,8,9)`.

Positions are zero-based positions in the normalized source strings. They are explicit annotations. They are not inferred from font outlines.

The finite transducer

```text
a -> 4
e -> 3
i -> 1
o -> 0
```

produces:

```text
negentien   -> n3g3nt13n
no neg moat -> n0 n3g m04t
```

Each output cell retains its input index and input symbol as provenance.

## 3. Synthetic cell complex

For a normalized representation `r`, split it into `k` non-empty tokens. Each token of `m` symbols becomes a path with `m` 1-cells and `m+1` vertices. The `k` token paths are initially disjoint.

Each annotated intrinsic cycle position adds one loop 1-cell at the corresponding symbol anchor. Let `h` be the number of such intrinsic loops. The shipped pair fixes `h=4` for both representations.

Each whitespace boundary contributes one additional **space loop**. A space loop is a loop edge `(u,u)` at the terminal vertex of the token to its left. It stores the entry vertex `v` of the next token and has metric weight zero. The edge remains a topological 1-cell even though its weight in the profile pseudometric is zero.

The augmented pre-gluing complex therefore has:

\[
\beta_0 = k,
\qquad
\beta_1 = h+(k-1),
\qquad
\chi=\beta_0-\beta_1=1-h.
\]

Thus the augmented Euler characteristic is independent of token splitting.

## 4. Space-Hole Trading Lemma

### Lemma

Let `X` be a finite graph containing a loop edge `e=(u,u)`. Let `v` be a vertex in a connected component different from the component containing `u`. Form `H_e(X)` by replacing the loop edge with the bridge edge `e'=(u,v)`, leaving every vertex and every other edge unchanged.

Then:

\[
\Delta V=0,
\qquad
\Delta E=0,
\qquad
\Delta\beta_0=-1,
\qquad
\Delta\beta_1=-1,
\qquad
\Delta\chi=0.
\]

### Proof

The replacement does not change the number of vertices or edges, so `V-E` is unchanged. Because `v` lies in another component, the new edge joins exactly two components, hence `beta0` falls by one. For a finite graph,

\[
\beta_1=E-V+\beta_0.
\]

With `E` and `V` fixed and `beta0` reduced by one, `beta1` is also reduced by one. Therefore

\[
\chi'=\beta_0'-\beta_1'
      =(\beta_0-1)-(\beta_1-1)
      =\beta_0-\beta_1=\chi.
\]

### Iteration

Apply the lemma once per whitespace boundary. For `k` tokens and `h` intrinsic loops:

\[
(k,h+k-1)\longmapsto(1,h),
\qquad
\chi=1-h\text{ throughout.}
\]

The traded space loops become zero-metric bridge pathways. This is the course-corrected formal meaning of collapsing spaces into zero-width topology.

### Shipped pair

| Representation | Stage | beta0 | beta1 | chi |
|---|---:|---:|---:|---:|
| `negentien` | augmented | 1 | 4 | -3 |
| `negentien` | canonical | 1 | 4 | -3 |
| `no neg moat` | augmented | 3 | 6 | -3 |
| `no neg moat` | canonical after 2 trades | 1 | 4 | -3 |

The target's two auxiliary space loops are consumed by the two gluing operations. The four intrinsic cycles remain.

## 5. Abstract 4-Torus Immersing

Let `X` be either canonical complex. It is connected and has `beta1=4`. Choose a spanning tree `T` containing the symbol backbones and zero-metric bridges. Collapsing `T` gives

\[
X/T \cong S^1\vee S^1\vee S^1\vee S^1.
\]

Let

\[
\mathbb T^4_{\mathrm{syn}}=(\mathbb R/\mathbb Z)^4.
\]

Order the four intrinsic cycle generators as `c1,...,c4`. Define the cellular immersion

\[
\iota(c_j(t))=(0,\ldots,0,t,0,\ldots,0)\pmod 1,
\]

with `t` in the `j`th coordinate. The wedge point maps to `(0,0,0,0)`. The induced homology map is

\[
H_1(\iota)=I_4:\mathbb Z^4\to\mathbb Z^4.
\]

Its rank is four. The exact claim is an immersion of the four-cycle quotient into the four coordinate circles of the synthetic torus. The image is not the full torus, and neither text complex is asserted to be homeomorphic to `T^4`.

## 6. Bitwise Parity/Entropy Constraint

Encode the two transduced strings in 8-bit ASCII, left-align them, and append NUL bytes to the shorter string. The aligned width is 11 bytes. Let

\[
X,Y\in\mathbb F_2^{11\times8},
\qquad
\Delta=X\oplus Y.
\]

The shipped delta is:

```text
00 03 47 5d 5d 13 11 5e 5e 34 74
```

and has Hamming weight 38.

Define the even-weight subspace

\[
\mathcal E_n=\ker p,
\qquad
p(\Delta)=\sum_{i=0}^{n-1}\sum_{j=0}^{7}\Delta_{ij}\pmod 2.
\]

For `n>0`, `dim(E_n)=8n-1`. Here `dim(E_11)=87`.

The shipped symmetric subspace also imposes:

\[
\Delta_3=\Delta_4=\texttt{0x5d},
\qquad
\Delta_7=\Delta_8=\texttt{0x5e}.
\]

For disjoint pair constraints `(3,4)` and `(7,8)`, the resulting linear subspace has dimension

\[
88-16-1=71.
\]

Let global parity be

\[
\pi(X)=\sum_{i,j}X_{ij}\pmod 2.
\]

Because `Y=X+Delta`,

\[
\pi(Y)=\pi(X)+p(\Delta).
\]

If `Delta` lies in `E_n`, global parity is preserved. In the shipped witness:

```text
source Hamming weight = 39
 target Hamming weight = 37
  delta Hamming weight = 38
source parity          = 1
 target parity          = 1
```

Hamming weight is not conserved.

The narrow entropy statement is exact: translation by a fixed delta is a bijection of the fixed-width code space. Therefore, for any random variable `Z` on that space,

\[
H(Z\oplus\Delta)=H(Z).
\]

Even delta weight adds the parity-coset constraint. This is Shannon entropy invariance under a bijective relabeling. It is not a statement about physical entropy, heat, energy or the empirical number of one-bits in one fixed codeword.

## 7. Semantic-Boundary SDF Integration

Let `R_P` be the set of representations admitted by the profile and let

\[
\nu:R_P\to\mathbb R
\]

be the declared semantic evaluator. Define

\[
r\sim r'\iff \nu(r)=\nu(r').
\]

The quotient `Q=R_P/~` is identified with `im(nu)` and carries the metric

\[
d_\nu([r],[r'])=|\nu(r)-\nu(r')|.
\]

Let `Omega` be the disjoint union of the spatial cell-complex domains and let `lambda:Omega->R_P` label every point by its representation. Pull the quotient metric back to a pseudometric:

\[
\widehat d_\nu(p,q)=|\nu(\lambda(p))-\nu(\lambda(q))|.
\]

Define the signed residual field

\[
F_{19}(p)=\nu(\lambda(p))-19
\]

and its zero set

\[
Z_{19}=F_{19}^{-1}(0).
\]

If `Z_19` is non-empty, then

\[
|F_{19}(p)|
=\inf_{z\in Z_{19}}\widehat d_\nu(p,z).
\]

Therefore `F_19` is an exact signed-distance field in the evaluator-induced quotient/pullback metric. It is not the Euclidean distance to a visible font outline. Distinct spatial points in the same semantic fiber can have pseudodistance zero.

For both shipped representations, `nu=19`, so the field is identically zero on both spatial components.

A finite guard band is

\[
g_\varepsilon(r)=|\nu(r)-19|-\varepsilon.
\]

The ordinary UGTS event pipeline may accept the semantic guard only after support and compatibility also hold.

## 8. Integrated BEA certificate

A course-corrected certificate stores:

\[
C_{BEA}^{syn}=(P,r_s,r_t,X_s^+,X_t^+,H_s,H_t,X_s^c,X_t^c,
\iota_s,\iota_t,\Delta,\mathcal E_n,\nu,F_{19},N),
\]

where:

- `P` is the profile identity;
- `X+` are augmented complexes;
- `H` are ordered Space-Hole trade records;
- `Xc` are canonical complexes;
- `iota` are torus immersion certificates;
- `Delta` is the exact XOR witness;
- `E_n` is the even-weight constraint;
- `nu` and `F19` are the semantic evaluator and signed residual;
- `N` is the list of explicit non-claims.

The shipped certificate is valid when:

1. all definition references resolve and content hashes verify;
2. source and target canonical signatures both equal `(beta0,beta1,chi)=(1,4,-3)`;
3. each Space-Hole trade preserves `chi` and reduces both Betti numbers by one;
4. both `H1` immersion matrices equal `I4`;
5. `X xor Delta = Y` and `Y xor Delta = X`;
6. `wt(Delta)=38` is even and parity is preserved;
7. both semantic residuals to 19 equal zero;
8. every claim remains scoped to the named profile.

The claim level is:

```text
profile-exact-synthetic-topology-equivalence
```

## 9. Referential substrate order

The literal definition graph executes in this order:

1. resolve profile;
2. normalize representations;
3. transduce with provenance;
4. build augmented cell complexes;
5. perform Space-Hole trades;
6. evaluate Betti signatures;
7. collapse spanning tree and construct torus immersions;
8. align bytes and build XOR delta matrix;
9. verify even parity and the bounded entropy statement;
10. build semantic quotient and `F19`;
11. issue the integrated BEA certificate;
12. hand off to the ordinary UGTS sequence:

```text
support -> compatibility -> guard -> verified event -> transition -> lineage
```

## 10. Reference implementation bounds

The reference implementation is intentionally finite and auditable.

- Python standard library only for the BEA algorithms; JSON Schema validation is a test dependency already used by the baseline package.
- Text is normalized to NFC, lowercase and single ASCII spaces.
- Cycle annotations are explicit zero-based positions and must not point to whitespace.
- The graph builder supports finite ordered token strings. It is not a general CW-complex parser.
- The Space-Hole lemma requires a loop edge whose target lies in a distinct component.
- Zero-metric edges make the spatial metric a pseudometric; code must not assume strict positive edge lengths.
- The torus operator accepts only connected canonical complexes with exactly four intrinsic cycles.
- The torus certificate is symbolic and exact; it does not numerically embed a four-dimensional surface.
- The shipped binary witness is ASCII, 11 bytes, left aligned and NUL padded.
- The entropy statement applies to a fixed-width random variable transformed by a fixed XOR translation.
- The semantic evaluator returns finite real values. The semantic zero set must be non-empty.
- The semantic SDF is exact only in the evaluator-induced metric.
- This revision does not add a physical hardware benchmark or performance claim.

## 11. Validation targets

The package validates:

- exact source/target transduction;
- augmented and canonical Betti signatures;
- per-space Euler preservation;
- generic `k`-token Space-Hole iteration;
- four-cycle homology rank and coordinate-circle closure;
- exact XOR bytes, repeated masks, weights and parity;
- even-subspace and symmetric-subspace dimensions;
- bijectivity of fixed XOR translation;
- semantic quotient metric and SDF identity;
- JSON Schema, content hashes, reference resolution and dependency order;
- end-to-end certificate validity.
