# Allow direct execution from an extracted source tree without installation.
import sys
from pathlib import Path
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import json
import math
import tempfile
import unittest
from pathlib import Path

from ugts_kc3 import io, uncertainty as u
from ugts_kc3.kinematics import JetState
from ugts_kc3.world import CompatibilityRule, RadialAngularSupport, Relation, StateRecord, World


class IntervalTests(unittest.TestCase):
    def test_interval_basic(self):
        x=u.Interval(1,2)
        self.assertEqual(x.width,1)
        self.assertEqual(x.midpoint,1.5)
        self.assertTrue(x.contains(1.2))

    def test_interval_add(self):
        x=u.Interval(1,2)+u.Interval(3,4)
        self.assertLessEqual(x.lo,4)
        self.assertGreaterEqual(x.hi,6)

    def test_interval_mul(self):
        x=u.Interval(-1,2)*u.Interval(3,4)
        self.assertLessEqual(x.lo,-4)
        self.assertGreaterEqual(x.hi,8)

    def test_interval_div(self):
        x=u.Interval(2,4)/u.Interval(2,2)
        self.assertTrue(x.contains(1) and x.contains(2))

    def test_interval_div_zero(self):
        with self.assertRaises(ZeroDivisionError):
            u.Interval(1,2)/u.Interval(-1,1)

    def test_interval_square(self):
        x=u.Interval(-2,1).square()
        self.assertEqual(x.lo,0)
        self.assertGreaterEqual(x.hi,4)

    def test_interval_norm(self):
        x=u.interval_norm_bounds([u.Interval(3,3),u.Interval(4,4)])
        self.assertTrue(x.contains(5))

    def test_affine_interval(self):
        a=u.AffineForm.from_interval(u.Interval(1,3))
        x=a.interval()
        self.assertTrue(x.contains(1) and x.contains(3))

    def test_affine_multiply(self):
        a=u.AffineForm.from_interval(u.Interval(1,2),'a')
        b=u.AffineForm.from_interval(u.Interval(3,4),'b')
        x=a.multiply(b).interval()
        self.assertTrue(x.contains(3) and x.contains(8))

    def test_covariance(self):
        p=u.propagate_covariance([[1,1],[0,1]],[[1,0],[0,1]],[[0,0],[0,0]])
        self.assertEqual(p,[[2,1],[1,1]])

    def test_unscented_linear(self):
        mean,var=u.unscented_transform_scalar(2,3,lambda x:2*x+1)
        self.assertAlmostEqual(mean,5)
        self.assertAlmostEqual(var,12)

    def test_deterministic_samples(self):
        self.assertEqual(u.deterministic_samples(['a',1],5),u.deterministic_samples(['a',1],5))
        self.assertNotEqual(u.deterministic_samples(['a',1],5),u.deterministic_samples(['a',2],5))

    def test_tolerance(self):
        p=u.TolerancePolicy(absolute=0.1,relative=0)
        self.assertTrue(p.close(1,1.05))
        self.assertFalse(p.close(1,1.2))

    def test_pairwise_sum(self):
        self.assertEqual(u.deterministic_pairwise_sum([1,2,3,4]),10)

    def test_canonical_hash_order(self):
        self.assertEqual(u.canonical_json_hash({'a':1,'b':2}),u.canonical_json_hash({'b':2,'a':1}))

    def test_canonical_hash_nonfinite(self):
        with self.assertRaises(ValueError):
            u.canonical_json_hash({'x':float('nan')})

    def test_merkle_chain(self):
        chain=u.merkle_event_chain([{'x':1},{'x':2}])
        self.assertEqual(len(chain),2)
        self.assertNotEqual(chain[0],chain[1])

    def test_checkpoint(self):
        h='0'*64
        c=u.make_checkpoint({'x':1},h,h,2)
        self.assertEqual(c['sequence'],2)
        self.assertEqual(len(c['checkpoint_hash']),64)

    def test_error_budget(self):
        b=u.ErrorBudget(); b.add('a',3); b.add('b',4)
        self.assertEqual(b.worst_case(),7)
        self.assertEqual(b.root_sum_square(),5)
        self.assertTrue(b.within(5,'rss'))


class IOTests(unittest.TestCase):
    def test_capability_manifest(self):
        m=io.capability_manifest(['M001','M360'],fallbacks={'M359':'cpu'})
        self.assertEqual(m['package_version'],'3.0.0')
        self.assertEqual(len(m['manifest_hash']),64)

    def test_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json'
            io.write_json(p,{'b':2,'a':1})
            self.assertEqual(io.load_json(p),{'a':1,'b':2})

    def test_minimal_validation(self):
        world={'schema_version':'3.0.0','metadata':{},'states':[{'id':'x','time':0,'position':[0,0],'velocity':[0,0],'acceleration':[0,0],'jerk':[0,0],'snap':[0,0],'phase':0,'sheet':0,'orientation':1,'lineage':[]}], 'numeric_policy':{}}
        self.assertEqual(io.validate_world_minimal(world),[])

    def test_validation_errors(self):
        self.assertGreater(len(io.validate_world_minimal({})),0)


class WorldTests(unittest.TestCase):
    def make_world(self):
        jet=JetState((-2.0,0.0),(1.0,0.0),(0.0,0.0),(0.0,0.0),(0.0,0.0))
        state=StateRecord('traveler',jet,phase=0,sheet=0,orientation=1,branch='A',tags=('player',))
        other=StateRecord('ghost',JetState((0.0,0.0),(0.0,0.0),(0.0,0.0),(0.0,0.0),(0.0,0.0)),phase=math.pi,sheet=1,orientation=-1)
        support=RadialAngularSupport((0.0,0.0),3.0)
        relation=Relation('x0',lambda s:s.jet.position[0],support,CompatibilityRule((0,),1,0,0.1,('player',)),{'sheet':1,'orientation':-1,'branch':'B'})
        return World([state,other],[relation])

    def test_state_at(self):
        w=self.make_world()
        self.assertEqual(w.state_at('traveler',2).jet.position,(0.0,0.0))

    def test_double_vacuum(self):
        w=self.make_world()
        ok,reasons=w.can_couple('traveler','ghost',2)
        self.assertFalse(ok)
        self.assertIn('sheet_mismatch',reasons)

    def test_next_event(self):
        w=self.make_world()
        result=w.next_event('traveler',0,4)
        self.assertIsNotNone(result)
        relation,interval,reasons=result
        self.assertEqual(relation.id,'x0')
        self.assertTrue(interval.t_lo <= 2 <= interval.t_hi)

    def test_process_event(self):
        w=self.make_world()
        record=w.process_next_event('traveler',0,4)
        self.assertIsNotNone(record)
        self.assertEqual(w.states['traveler'].sheet,1)
        self.assertEqual(w.states['traveler'].branch,'B')
        self.assertEqual(len(w.event_log),1)

    def test_support_cone(self):
        s=RadialAngularSupport((0,0),2,(1,0),0.5)
        self.assertTrue(s.admits((1,0)))
        self.assertFalse(s.admits((-1,0)))

    def test_compatibility_reasons(self):
        state=StateRecord('x',JetState((0,0),(0,0),(0,0),(0,0),(0,0)),phase=1,sheet=2,orientation=-1,tags=())
        ok,reasons=CompatibilityRule((0,),1,0,0.1,('tag',)).check(state)
        self.assertFalse(ok)
        self.assertGreaterEqual(len(reasons),4)


if __name__ == '__main__':
    unittest.main()
