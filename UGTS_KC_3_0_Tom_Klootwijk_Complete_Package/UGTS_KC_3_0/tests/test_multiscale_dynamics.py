# Allow direct execution from an extracted source tree without installation.
import sys
from pathlib import Path
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import math
import unittest

from ugts_kc3 import dynamics as d
from ugts_kc3 import multiscale as m


class MultiscaleTests(unittest.TestCase):
    def test_wallpaper(self):
        pts=m.wallpaper_p4m_transforms((0.2,0.3),1)
        self.assertGreater(len(pts),8)

    def test_frieze(self):
        pts=m.frieze_p11g_transforms((0.2,0.3),1)
        self.assertIn((0.2,0.3),pts)

    def test_penrose_counts(self):
        self.assertEqual(m.penrose_count_substitution(1),(2,1))

    def test_ammann_counts(self):
        self.assertEqual(m.ammann_beenker_counts(1),(1,2))

    def test_cut_and_project(self):
        pts=m.cut_and_project_1d(3,0.5)
        self.assertEqual(pts,sorted(pts))
        self.assertIn(0.0,pts)

    def test_voronoi(self):
        self.assertEqual(m.voronoi_label((0.1,0),[(0,0),(2,0)]),0)

    def test_delaunay_square(self):
        edges=m.delaunay_edges_2d([(0,0),(1,0),(1,1),(0,1)])
        self.assertGreaterEqual(len(edges),4)

    def test_alpha_complex(self):
        c=m.alpha_complex_proxy_2d([(0,0),(1,0),(0,1)],1)
        self.assertIn((0,1,2),c.simplices)

    def test_lloyd(self):
        out=m.lloyd_step_samples([(0,0),(1,0)],[(0,0),(0.2,0),(0.8,0),(1,0)],1)
        self.assertLess(out[0][0],0.2)
        self.assertGreater(out[1][0],0.8)

    def test_poisson_disk(self):
        pts=m.poisson_disk_2d(1,1,0.1,seed=1)
        self.assertGreater(len(pts),10)
        for i,p in enumerate(pts):
            for q in pts[i+1:]:
                self.assertGreaterEqual(math.dist(p,q)+1e-12,0.1)

    def test_blue_noise_diagnostics(self):
        diag=m.blue_noise_diagnostics([(0,0),(1,0),(0,1),(1,1)],1,1)
        self.assertGreater(diag['mean_nearest'],0)

    def test_hilbert_unique(self):
        ids={m.hilbert_index_2d(x,y,2) for x in range(4) for y in range(4)}
        self.assertEqual(len(ids),16)

    def test_morton(self):
        self.assertEqual(m.morton2(1,0,2),1)
        self.assertEqual(m.morton2(0,1,2),2)

    def test_haar_roundtrip(self):
        x=[1,2,3,4,5,6,7,8]
        r=m.haar_inverse(m.haar_forward(x))
        for a,b in zip(x,r): self.assertAlmostEqual(a,b)

    def test_laplacian_pyramid_roundtrip(self):
        x=[1,2,3,4,5,6,7,8]
        residuals,coarse=m.laplacian_pyramid_1d(x,2)
        r=m.reconstruct_laplacian_pyramid_1d(residuals,coarse)
        self.assertEqual(r,x)

    def test_jacobi(self):
        vals,vecs=m.jacobi_eigen_symmetric([[2,1],[1,2]])
        self.assertAlmostEqual(vals[0],1,places=8)
        self.assertAlmostEqual(vals[1],3,places=8)


class DynamicsTests(unittest.TestCase):
    def test_symplectic_euler(self):
        x,v=d.symplectic_euler((0,),(0,),(1,),1)
        self.assertEqual(x,(1.0,))
        self.assertEqual(v,(1.0,))

    def test_velocity_verlet_constant(self):
        x,v=d.velocity_verlet((0,),(0,),lambda x:(1,),2)
        self.assertEqual(x,(2.0,))
        self.assertEqual(v,(2.0,))

    def test_damped_oscillator_initial(self):
        x,v=d.damped_oscillator_exact(1,2,1,0.2,4,0)
        self.assertEqual((x,v),(1.0,2.0))

    def test_graph_diffusion_conserves_sum(self):
        x=d.graph_diffusion_step([1,0],[(0,1,1)],0.1)
        self.assertAlmostEqual(sum(x),1)

    def test_gray_scott_constant(self):
        u,v=d.gray_scott_step_1d([1]*8,[0]*8,0.1)
        self.assertTrue(all(abs(x-1)<1e-12 for x in u))
        self.assertTrue(all(abs(x)<1e-12 for x in v))

    def test_hamiltonian(self):
        q,p=d.hamiltonian_symplectic_euler(1,0,0.1,lambda q,p:q,lambda q,p:p)
        self.assertLess(p,0)

    def test_variational_oscillator(self):
        self.assertAlmostEqual(d.discrete_variational_oscillator(1,1,0.1,1),0.99)

    def test_implicit_midpoint_decay(self):
        y,it,res=d.implicit_midpoint_scalar(1,0.1,lambda y:-y)
        self.assertAlmostEqual(y,(1-0.05)/(1+0.05),places=8)

    def test_stormer_verlet(self):
        q,p=d.stormer_verlet(1,0,0.1,lambda q:-q)
        self.assertLess(q,1)
        self.assertLess(p,0)

    def test_lie_group_step_normalized(self):
        q=d.lie_group_quaternion_step((1,0,0,0),(0,0,1),0.1)
        self.assertAlmostEqual(sum(x*x for x in q),1)

    def test_projected_symplectic_circle(self):
        q,v,res=d.projected_symplectic_circle((1,0),(0,1),(0,0),0.1,1)
        self.assertAlmostEqual(q[0]**2+q[1]**2,1,places=8)
        self.assertAlmostEqual(q[0]*v[0]+q[1]*v[1],0,places=8)

    def test_semi_lagrangian_shift(self):
        x=d.semi_lagrangian_1d([0,1,2,3],1,1,1)
        self.assertEqual(x,[3.0,0.0,1.0,2.0])

    def test_implicit_diffusion(self):
        x=d.implicit_diffusion_1d([0,0,1,0,0],1,0.1)
        self.assertLess(x[2],1)
        self.assertGreater(x[1],0)

    def test_wave_zero(self):
        x=d.wave_leapfrog_1d([0]*5,[0]*5,1,0.5)
        self.assertEqual(x,[0.0]*5)

    def test_gray_scott_split(self):
        u,v=d.gray_scott_split_1d([1]*8,[0]*8,0.1,substeps=2)
        self.assertTrue(all(abs(x-1)<1e-12 for x in u))

    def test_allen_cahn_fixed_points(self):
        x=d.allen_cahn_step_1d([1]*5,0.1)
        self.assertTrue(all(abs(v-1)<1e-12 for v in x))

    def test_cahn_hilliard_mass(self):
        phi=[-1,-0.5,0,0.5,1]
        out=d.cahn_hilliard_step_1d(phi,0.001)
        self.assertAlmostEqual(sum(out),sum(phi),places=10)

    def test_eikonal(self):
        t=d.fast_sweeping_eikonal([[1]*5 for _ in range(5)],[(2,2)],sweeps=4)
        self.assertEqual(t[2][2],0)
        self.assertAlmostEqual(t[2][3],1,places=8)
        self.assertGreater(t[0][0],2)


if __name__ == '__main__':
    unittest.main()
