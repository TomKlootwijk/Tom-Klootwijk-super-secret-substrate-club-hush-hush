import math
import os
import sys
import unittest

HERE=os.path.dirname(__file__)
sys.path.insert(0,os.path.join(HERE,'..','src'))
from ugts_kc import *
from ugts_kc.mathutil import dot, norm, mat_eye

class PatternTests(unittest.TestCase):
    def test_superellipse_axis(self): self.assertAlmostEqual(superellipse(0,2,1,4)[0],2)
    def test_gielis_finite(self): self.assertTrue(all(math.isfinite(x) for x in gielis(0.3)))
    def test_rose_periodicity(self):
        a=rose(0.7,5); b=rose(0.7+2*math.pi,5)
        self.assertAlmostEqual(a[0],b[0],places=10); self.assertAlmostEqual(a[1],b[1],places=10)
    def test_lissajous_bounds(self):
        x,y=lissajous(0.4,ax=2,ay=3); self.assertLessEqual(abs(x),2); self.assertLessEqual(abs(y),3)
    def test_trochoids(self):
        self.assertEqual(cycloid(0),(0.0,0.0)); self.assertTrue(math.isfinite(epitrochoid(1)[0])); self.assertTrue(math.isfinite(hypotrochoid(1)[1]))
    def test_involute_start(self):
        x,y=involute(0,2); self.assertAlmostEqual(x,2); self.assertAlmostEqual(y,0)
    def test_catenary_symmetry(self): self.assertAlmostEqual(catenary(-1,2),catenary(1,2))
    def test_clothoid(self):
        x,y=clothoid(2,2,300); self.assertGreater(x,0); self.assertGreaterEqual(y,0)
    def test_spirals(self):
        self.assertAlmostEqual(norm(fermat_spiral(4,0.5)),1.0,places=8)
        self.assertAlmostEqual(norm(archimedean_spiral(2,1,0.5)),2.0,places=8)
    def test_bezier_endpoints(self):
        p0=(0,0); p1=(1,2); p2=(2,0); p3=(3,1)
        self.assertEqual(rational_quadratic_bezier(p0,p1,p2,0),p0)
        self.assertEqual(cubic_bezier(p0,p1,p2,p3,1),p3)
    def test_bspline_endpoints(self):
        c=[(0,0),(1,2),(2,2),(3,0)]
        self.assertAlmostEqual(bspline(c,0,3)[0],0)
        self.assertAlmostEqual(bspline(c,1,3)[0],3)
    def test_nurbs_quarter_circle(self):
        c=[(1,0),(1,1),(0,1)]; w=[1,math.sqrt(0.5),1]
        p=nurbs(c,w,0.5,2)
        self.assertAlmostEqual(p[0]**2+p[1]**2,1.0,places=8)
    def test_reuleaux_sampler(self): self.assertEqual(len(reuleaux_triangle_points(2,10)),30)
    def test_power_nearest(self): self.assertEqual(power_nearest((0,0),[((0,0),0),((2,0),0)])[0],0)
    def test_medial_midpoints(self): self.assertEqual(medial_midpoints([(0,0)],[(2,0)]),[(1.0,0.0)])

class FieldTests(unittest.TestCase):
    def test_ellipsoid_sign(self):
        self.assertLess(ellipsoid_field((0,0,0)),0); self.assertAlmostEqual(ellipsoid_field((1,0,0)),0)
    def test_superquadric_boundary(self): self.assertAlmostEqual(superquadric_field((1,0,0)),0)
    def test_tube(self): self.assertAlmostEqual(tube_field((0,0,0),[(0,0,0)],0.25),-0.25)
    def test_ruled(self): self.assertEqual(ruled_surface(lambda u:(u,0),lambda u:(u,2),0.5,0.25),(0.5,0.5))
    def test_minimal_fields(self):
        self.assertAlmostEqual(gyroid_field((0,0,0)),0); self.assertAlmostEqual(schwarz_p_field((0,0,0)),3)
    def test_metaball(self): self.assertGreater(metaball_field((0,0,0),[(0,0,0)],threshold=0.5),0)
    def test_offset_arrival(self):
        self.assertEqual(offset_field(2,0.5),1.5); self.assertAlmostEqual(constant_speed_arrival((3,0,0),speed=2),1.5)

class TopologyTests(unittest.TestCase):
    def test_winding(self):
        sq=[(-1,-1),(1,-1),(1,1),(-1,1)]
        self.assertAlmostEqual(abs(winding_number(sq,(0,0))),1,places=8)
        self.assertAlmostEqual(winding_number(sq,(3,0)),0,places=8)
    def test_covering_and_homotopy(self):
        self.assertAlmostEqual(covering_lift(0.2,2),0.2+4*math.pi)
        sq=[(-1,-1),(1,-1),(1,1),(-1,1)]
        self.assertEqual(homotopy_signature(sq,[(0,0)]),(1,))
    def test_braid_reduction(self):
        w=[BraidGenerator(1,1),BraidGenerator(1,-1),BraidGenerator(2,1)]
        self.assertEqual(reduce_braid(w),(BraidGenerator(2,1),))
    def test_boundary_squared(self):
        c=CellComplex()
        for v in 'abc': c.add_cell(0,v)
        c.add_cell(1,'ab',{'b':1,'a':-1}); c.add_cell(1,'bc',{'c':1,'b':-1}); c.add_cell(1,'ca',{'a':1,'c':-1})
        c.add_cell(2,'abc',{'ab':1,'bc':1,'ca':1})
        self.assertTrue(c.boundary_squared_zero())
    def test_discrete_morse(self): self.assertEqual(discrete_morse_critical(['a','b','c'],{'a':'b'}),('c',))
    def test_cocycle(self):
        A=((1,1),(0,1)); B=((1,0),(1,1)); C=((2,1),(1,1))
        self.assertTrue(cocycle_ok(A,B,C))

class KinematicsTests(unittest.TestCase):
    def test_se2_translation(self):
        T=se2_exp(2,3,0,0.5); self.assertAlmostEqual(T[0][2],1); self.assertAlmostEqual(T[1][2],1.5)
    def test_se3_translation(self):
        T=se3_exp((0,0,0),(1,2,3),2); self.assertEqual((T[0][3],T[1][3],T[2][3]),(2,4,6))
    def test_slerp_endpoints(self):
        q0=(1,0,0,0); q1=(0,0,0,1)
        self.assertEqual(quat_slerp(q0,q1,0),q0); self.assertEqual(quat_slerp(q0,q1,1),q1)
    def test_se3_interpolate_endpoints(self):
        A=mat_eye(4); B=se3_exp((0,0,1),(1,0,0),0.5)
        C=se3_interpolate(A,B,1.0)
        self.assertAlmostEqual(C[0][3],B[0][3],places=8)
    def test_frenet(self):
        T,N,B,k=frenet_frame((1,0,1),(0,1,0))
        self.assertAlmostEqual(dot(T,N),0,places=8); self.assertGreater(k,0)
    def test_bishop(self):
        pts=[(0,0,0),(1,0,0),(2,0.1,0),(3,0.3,0.1)]
        frames=bishop_frames(pts)
        self.assertEqual(len(frames),len(pts)); self.assertAlmostEqual(dot(frames[1][0],frames[1][1]),0,places=8)
    def test_arc_length(self):
        L=arc_length_table([(0,0),(1,0),(2,0)]); self.assertEqual(L,[0.0,1.0,2.0]); self.assertAlmostEqual(parameter_at_length(L,1),0.5)
    def test_curvature_limit(self):
        v,w=curvature_limited_speed(2,4,10); self.assertAlmostEqual(v,math.sqrt(2)); self.assertAlmostEqual(w,2*math.sqrt(2))
    def test_scurve_endpoints(self):
        p0=quintic_scurve(0,2,3); p1=quintic_scurve(1,2,3)
        self.assertEqual(p0[0],0); self.assertAlmostEqual(p1[0],2); self.assertAlmostEqual(p0[1],0); self.assertAlmostEqual(p1[2],0)
    def test_duration(self): self.assertGreater(limit_aware_duration(2,1,1,1,500),0)
    def test_forward_kinematics(self):
        p=planar_forward_kinematics([1,1],[0,0])[-1]; self.assertAlmostEqual(p[0],2); self.assertAlmostEqual(p[1],0)
    def test_dls_ik(self):
        q,p=dls_ik([1,1],[0.2,0.2],(1,1),iterations=200)
        self.assertLess(math.dist(p,(1,1)),1e-5)

class DynamicsEventTests(unittest.TestCase):
    def test_symplectic(self):
        x,v=symplectic_euler(1,0,lambda x,v:-x,0.1); self.assertAlmostEqual(v,-0.1); self.assertAlmostEqual(x,0.99)
    def test_damped_energy_decreases(self):
        x=v=1.0; e0=0.5*x*x+0.5*v*v
        for _ in range(100): x,v=damped_oscillator_step(x,v,1,1,0.2,0,0.01)
        e1=0.5*x*x+0.5*v*v; self.assertLess(e1,e0)
    def test_graph_diffusion_mass(self):
        x=(1.0,0.0); y=graph_diffusion_step(x,[(0,1,1.0)],1.0,0.1)
        self.assertAlmostEqual(sum(x),sum(y))
    def test_gray_scott_shape(self):
        U=[[1.0]*4 for _ in range(4)]; V=[[0.0]*4 for _ in range(4)]; V[2][2]=1.0
        Un,Vn=gray_scott_step(U,V); self.assertEqual(len(Un),4); self.assertEqual(len(Vn[0]),4)
    def test_hybrid(self):
        modes=[HybridMode('A',lambda x,v,dt:(x+dt,v)),HybridMode('B',lambda x,v,dt:(x,v))]
        trs=[HybridTransition('A','B',lambda x,v,t:x>=1,lambda x,v,t:(x,0),priority=1)]
        h=HybridAutomaton(modes,trs,'A'); x=0
        for i in range(2): x,v,m=h.step(x,0,i,0.6)
        self.assertEqual(m,'B')
    def test_root_and_classification(self):
        r=bisect_root(lambda x:x*x-2,0,2); self.assertAlmostEqual(r,math.sqrt(2),places=8)
        self.assertEqual(classify_event(-1,0,1),'crossing')
        self.assertEqual(classify_event(1,0,1,0),'tangency')
    def test_patch_resolution(self):
        out,conf=resolve_patches([Patch(2,{'sheet':1},'hi'),Patch(1,{'sheet':0,'branch':'B'},'lo')])
        self.assertEqual(out['sheet'],1); self.assertEqual(out['branch'],'B'); self.assertEqual(len(conf),1)

if __name__=='__main__': unittest.main(verbosity=2)
