# Allow direct execution from an extracted source tree without installation.
import sys
from pathlib import Path
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import math
import unittest

from ugts_kc3 import kinematics as k
from ugts_kc3 import constraints as c
from ugts_kc3.math3 import mat4_apply, quat_from_axis_angle, quat_rotate


class KinematicsTests(unittest.TestCase):
    def test_jet_taylor(self):
        jet=k.JetState((0.0,), (1.0,), (2.0,), (0.0,), (0.0,))
        out=jet.taylor(2.0)
        self.assertAlmostEqual(out.position[0],6.0)
        self.assertAlmostEqual(out.velocity[0],5.0)

    def test_material_derivative(self):
        f=lambda p,t: p[0]*p[0]+t
        self.assertAlmostEqual(k.material_derivative(f,(2.0,),0.0,(3.0,)),13.0,places=4)

    def test_lie_bracket(self):
        X=lambda p:(1.0,0.0)
        Y=lambda p:(0.0,p[0])
        bracket=k.lie_bracket_2d(X,Y,(2.0,3.0))
        self.assertAlmostEqual(bracket[1],1.0,places=5)

    def test_se2_translation(self):
        m=k.se2_exp((1.0,2.0,0.0),2.0)
        self.assertAlmostEqual(m[0][2],2.0)
        self.assertAlmostEqual(m[1][2],4.0)

    def test_so3_jacobian_zero(self):
        j=k.so3_left_jacobian((0.0,0.0,0.0))
        self.assertEqual(j[0][0],1.0)

    def test_se3_exp_translation(self):
        m=k.se3_exp((0,0,0,1,2,3),2)
        self.assertEqual((m[0][3],m[1][3],m[2][3]),(2.0,4.0,6.0))

    def test_se3_log_roundtrip_small(self):
        xi=(0.1,-0.05,0.02,1.0,0.5,-0.2)
        recovered=k.se3_log(k.se3_exp(xi))
        for a,b in zip(xi,recovered):
            self.assertAlmostEqual(a,b,places=7)

    def test_adjoint_shape(self):
        a=k.se3_adjoint(k.se3_exp((0,0,0,1,2,3)))
        self.assertEqual(len(a),6)
        self.assertEqual(len(a[0]),6)

    def test_quaternion_integration(self):
        q=k.integrate_quaternion((1,0,0,0),(0,0,math.pi),0.5)
        v=quat_rotate(q,(1,0,0))
        self.assertAlmostEqual(v[0],0.0,places=7)
        self.assertAlmostEqual(v[1],1.0,places=7)

    def test_dual_quaternion_translation(self):
        dq=k.DualQuaternion.from_rotation_translation((1,0,0,0),(1,2,3))
        self.assertEqual(tuple(round(x,10) for x in dq.translation()),(1.0,2.0,3.0))

    def test_dual_quaternion_transform(self):
        q=quat_from_axis_angle((0,0,1),math.pi/2)
        dq=k.DualQuaternion.from_rotation_translation(q,(1,0,0))
        p=dq.transform_point((1,0,0))
        self.assertAlmostEqual(p[0],1.0,places=7)
        self.assertAlmostEqual(p[1],1.0,places=7)

    def test_dual_quaternion_blend(self):
        a=k.DualQuaternion.from_rotation_translation((1,0,0,0),(0,0,0))
        b=k.DualQuaternion.from_rotation_translation((1,0,0,0),(2,0,0))
        m=k.blend_dual_quaternions([a,b],[0.5,0.5])
        self.assertAlmostEqual(m.translation()[0],1.0)

    def test_rigid_geodesic(self):
        m=k.rigid_geodesic_interpolate((1,0,0,0),(0,0,0),(1,0,0,0),(2,0,0),0.25)
        self.assertAlmostEqual(m.translation()[0],0.5)

    def test_screw_interpolate(self):
        a=k.se3_exp((0,0,0,0,0,0))
        b=k.se3_exp((0,0,0,2,0,0))
        mid=k.screw_interpolate(a,b,0.5)
        self.assertAlmostEqual(mid[0][3],1.0,places=7)

    def test_curvature_circle(self):
        curv,tors,status=k.curvature_and_torsion((0,1,0),(-1,0,0),(0,-1,0))
        self.assertAlmostEqual(curv,1.0)
        self.assertAlmostEqual(tors,0.0)
        self.assertEqual(status,'ok')

    def test_frenet(self):
        t,n,b,curv,tors,status=k.frenet_frame((0,1,0),(-1,0,0),(0,-1,0))
        self.assertAlmostEqual(curv,1.0)
        self.assertAlmostEqual(sum(x*x for x in t),1.0)

    def test_bishop_transport(self):
        n,b=k.bishop_transport((1,0,0),(0,1,0),(0,1,0))
        self.assertAlmostEqual(sum(x*x for x in n),1.0)
        self.assertAlmostEqual(sum(x*x for x in b),1.0)

    def test_bishop_holonomy_planar(self):
        pts=[(1,0,0),(0,1,0),(-1,0,0),(0,-1,0)]
        angle=k.bishop_holonomy(pts)
        self.assertTrue(math.isfinite(angle))

    def test_arc_length_line(self):
        table=k.arc_length_table(lambda t:(t,0.0),0,2,11)
        self.assertAlmostEqual(table[-1][1],2.0)

    def test_curvature_speed_limit(self):
        self.assertAlmostEqual(k.curvature_speed_limit(2.0,8.0),2.0)

    def test_quintic_endpoints(self):
        self.assertEqual(k.quintic_time_scaling(0.0)[:3],(0.0,0.0,0.0))
        self.assertEqual(k.quintic_time_scaling(1.0)[:3],(1.0,0.0,0.0))

    def test_limit_aware_time(self):
        self.assertGreater(k.limit_aware_time_scale(10,2,3,4),0)

    def test_forward_kinematics(self):
        points=k.forward_kinematics_2d([1,1],[0,math.pi/2])
        self.assertAlmostEqual(points[-1][0],1.0)
        self.assertAlmostEqual(points[-1][1],1.0)

    def test_unicycle_flatness(self):
        heading,speed,omega,status=k.unicycle_from_flat_output((0,0),(1,0),(0,1))
        self.assertEqual(status,'ok')
        self.assertAlmostEqual(heading,0)
        self.assertAlmostEqual(speed,1)
        self.assertAlmostEqual(omega,1)


class ConstraintTests(unittest.TestCase):
    def test_holonomic(self):
        h=c.HolonomicConstraint('circle',lambda q,t:q[0]*q[0]+q[1]*q[1]-1)
        self.assertTrue(h.satisfied((1,0)))

    def test_numeric_jacobian(self):
        j=c.numeric_jacobian(lambda q:q[0]**2+3*q[1],(2.0,1.0))
        self.assertAlmostEqual(j[0],4.0,places=5)
        self.assertAlmostEqual(j[1],3.0,places=5)

    def test_baumgarte(self):
        self.assertAlmostEqual(c.baumgarte_term(1,0,2,1),-4)

    def test_shake_circle(self):
        q,it,res=c.shake_project_circle((2,0),1)
        self.assertAlmostEqual(q[0],1.0,places=8)
        self.assertLess(res,1e-10)

    def test_rattle_tangent(self):
        v=c.rattle_project_velocity_circle((1,0),(1,2))
        self.assertAlmostEqual(v[0],0)
        self.assertAlmostEqual(v[1],2)

    def test_multiplier(self):
        lam,status=c.solve_single_multiplier((2,0),(0.5,1),4)
        self.assertEqual(status,'ok')
        self.assertAlmostEqual(lam,2)

    def test_nullspace(self):
        p=c.project_to_nullspace_single((1,2),(1,0))
        self.assertAlmostEqual(p[0],0)
        self.assertAlmostEqual(p[1],2)

    def test_gap_plane(self):
        self.assertAlmostEqual(c.gap_plane((0,2,0),(0,0,0),(0,1,0)),2)

    def test_complementarity(self):
        self.assertEqual(c.complementarity_residual(2,0),(0.0,0.0,0))

    def test_restitution(self):
        self.assertAlmostEqual(c.restitution_target_velocity(-2,0.5),1)

    def test_normal_impulse(self):
        self.assertAlmostEqual(c.normal_impact_impulse(-2,2,restitution=0.5),1.5)

    def test_friction_cone(self):
        j=c.clamp_friction_cone_2d((3,4),0.5,2)
        self.assertAlmostEqual(math.hypot(*j),1)

    def test_friction_pyramid(self):
        self.assertEqual(c.clamp_friction_pyramid_2d((3,-4),0.5,2),(1.0,-1.0))

    def test_reduce_contacts(self):
        contacts=[{'depth':-i,'point':(i,0,0),'id':i} for i in range(6)]
        out=c.reduce_contacts(contacts,4)
        self.assertEqual(len(out),4)

    def test_warm_start(self):
        out=c.apply_warm_start((0,0),0.5,[(2,0),(0,2)])
        self.assertEqual(out,(1.0,1.0))


if __name__ == '__main__':
    unittest.main()
