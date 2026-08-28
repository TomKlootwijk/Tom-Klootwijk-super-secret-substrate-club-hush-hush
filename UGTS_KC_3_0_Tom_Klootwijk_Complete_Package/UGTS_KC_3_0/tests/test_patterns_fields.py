# Allow direct execution from an extracted source tree without installation.
import sys
from pathlib import Path
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import math
import unittest

from ugts_kc3 import fields, patterns


class PatternTests(unittest.TestCase):
    def test_superellipse_cardinal(self):
        self.assertAlmostEqual(patterns.superellipse(0.0, 2.0, 3.0, 4.0)[0], 2.0)
        self.assertAlmostEqual(patterns.superellipse(math.pi/2, 2.0, 3.0, 4.0)[1], 3.0)

    def test_superformula_finite(self):
        x, y = patterns.superformula(0.3)
        self.assertTrue(math.isfinite(x) and math.isfinite(y))

    def test_lissajous(self):
        self.assertAlmostEqual(patterns.lissajous(0.0, delta=0.0)[0], 0.0)

    def test_hypotrochoid_start(self):
        x, y = patterns.hypotrochoid(0.0, 5.0, 3.0, 2.0)
        self.assertAlmostEqual(x, 4.0)
        self.assertAlmostEqual(y, 0.0)

    def test_epitrochoid_start(self):
        x, y = patterns.epitrochoid(0.0, 5.0, 3.0, 2.0)
        self.assertAlmostEqual(x, 6.0)
        self.assertAlmostEqual(y, 0.0)

    def test_cycloid_start(self):
        self.assertEqual(patterns.cycloid(0.0), (0.0, 0.0))

    def test_involute_start(self):
        self.assertEqual(patterns.involute(0.0), (1.0, 0.0))

    def test_archimedean_spiral(self):
        self.assertAlmostEqual(patterns.archimedean_spiral(0.0, 2.0, 1.0)[0], 2.0)

    def test_logarithmic_spiral_ratio(self):
        r0 = math.hypot(*patterns.logarithmic_spiral(0.0, 2.0, 0.1))
        r1 = math.hypot(*patterns.logarithmic_spiral(1.0, 2.0, 0.1))
        self.assertAlmostEqual(r1/r0, math.exp(0.1))

    def test_fermat_spiral(self):
        self.assertEqual(patterns.fermat_spiral(0.0), (0.0, 0.0))

    def test_clothoid_origin(self):
        self.assertEqual(patterns.clothoid(0.0), (0.0, 0.0))

    def test_clothoid_small_arc(self):
        x, y = patterns.clothoid(0.1, steps=64)
        self.assertGreater(x, 0.09)
        self.assertGreaterEqual(y, 0.0)

    def test_quadratic_bezier_endpoints(self):
        self.assertEqual(patterns.quadratic_bezier((0,0),(1,2),(2,0),0), (0.0,0.0))
        self.assertEqual(patterns.quadratic_bezier((0,0),(1,2),(2,0),1), (2.0,0.0))

    def test_cubic_bezier_endpoints(self):
        self.assertEqual(patterns.cubic_bezier((0,),(1,),(2,),(3,),0), (0.0,))
        self.assertEqual(patterns.cubic_bezier((0,),(1,),(2,),(3,),1), (3.0,))

    def test_catmull_rom_interpolates(self):
        self.assertAlmostEqual(patterns.catmull_rom((0,),(1,),(2,),(3,),0)[0], 1.0)
        self.assertAlmostEqual(patterns.catmull_rom((0,),(1,),(2,),(3,),1)[0], 2.0)

    def test_uniform_bspline_line(self):
        value = patterns.uniform_cubic_bspline((0.0,), (1.0,), (2.0,), (3.0,), 0.5)[0]
        self.assertAlmostEqual(value, 1.5)

    def test_nurbs_linear(self):
        p = patterns.nurbs_curve([(0.0,0.0),(2.0,0.0)], [1.0,1.0], [0,0,1,1], 1, 0.25)
        self.assertAlmostEqual(p[0], 0.5)

    def test_reuleaux_periodic(self):
        p0 = patterns.reuleaux_triangle_point(0.0)
        p1 = patterns.reuleaux_triangle_point(1.0)
        self.assertAlmostEqual(p0[0], p1[0])
        self.assertAlmostEqual(p0[1], p1[1])

    def test_rose(self):
        self.assertAlmostEqual(patterns.rose(0.0, a=2.0, k=4.0)[0], 2.0)

    def test_viviani_on_sphere(self):
        p = patterns.viviani(0.7, 2.0)
        self.assertAlmostEqual(sum(x*x for x in p), 4.0, places=10)

    def test_loxodrome_on_sphere(self):
        p = patterns.loxodrome(1.2, radius=3.0)
        self.assertAlmostEqual(sum(x*x for x in p), 9.0, places=10)

    def test_helicoid(self):
        self.assertEqual(patterns.helicoid(0.0, 3.0), (0.0, 0.0, 3.0))

    def test_catenoid_radius(self):
        p = patterns.catenoid(0.0, 0.0, 2.0)
        self.assertEqual(p, (2.0, 0.0, 0.0))


class FieldTests(unittest.TestCase):
    def test_sphere_sdf(self):
        self.assertAlmostEqual(fields.sphere_sdf((2,0,0), radius=1), 1.0)
        self.assertAlmostEqual(fields.sphere_sdf((0,0,0), radius=1), -1.0)

    def test_box_sdf(self):
        self.assertLess(fields.box_sdf((0,0,0),(1,1,1)), 0.0)
        self.assertAlmostEqual(fields.box_sdf((2,0,0),(1,1,1)), 1.0)

    def test_capsule_sdf(self):
        self.assertAlmostEqual(fields.capsule_sdf((0.5,1,0),(0,0,0),(1,0,0),0.5), 0.5)

    def test_torus_sdf(self):
        self.assertAlmostEqual(fields.torus_sdf((2.5,0,0),2.0,0.5), 0.0)

    def test_superquadric_sign(self):
        self.assertLess(fields.superquadric_field((0,0,0)), 0.0)
        self.assertAlmostEqual(fields.superquadric_field((1,0,0)), 0.0)

    def test_gyroid_origin(self):
        self.assertAlmostEqual(fields.gyroid_field((0,0,0)), 0.0)

    def test_schwarz_p_origin(self):
        self.assertAlmostEqual(fields.schwarz_p_field((0,0,0)), 3.0)

    def test_metaball(self):
        near = fields.metaball_field((0,0,0),[(0,0,0)],[1.0])
        far = fields.metaball_field((10,0,0),[(0,0,0)],[1.0])
        self.assertLess(near, far)

    def test_offset(self):
        f = fields.offset_field(lambda p: fields.sphere_sdf(p, radius=1.0), 0.5)
        self.assertAlmostEqual(f((1.5,0,0)), 0.0)

    def test_csg(self):
        a=lambda p: fields.sphere_sdf(p,(-0.5,0,0),1)
        b=lambda p: fields.sphere_sdf(p,(0.5,0,0),1)
        self.assertLess(fields.union_field(a,b)((0,0,0)),0)
        self.assertLess(fields.intersection_field(a,b)((0,0,0)),0)

    def test_smooth_union_value(self):
        self.assertLessEqual(fields.smooth_union_value(-1,1,0.5), -1+1e-12)

    def test_gradient_sphere(self):
        g=fields.gradient_central(lambda p: fields.sphere_sdf(p,radius=1), (2,0,0))
        self.assertAlmostEqual(g[0],1.0,places=5)
        self.assertAlmostEqual(g[1],0.0,places=5)

    def test_point_segment_distance(self):
        self.assertAlmostEqual(fields.point_segment_distance((0.5,1),(0,0),(1,0)),1.0)

    def test_polyline_tube(self):
        self.assertAlmostEqual(fields.polyline_tube_sdf((0.5,1),[(0,0),(1,0)],0.25),0.75)


if __name__ == '__main__':
    unittest.main()
