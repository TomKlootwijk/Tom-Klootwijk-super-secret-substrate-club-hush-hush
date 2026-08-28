# Allow direct execution from an extracted source tree without installation.
import sys
from pathlib import Path
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import math
import unittest

from ugts_kc3 import events as e
from ugts_kc3 import topology as t
from ugts_kc3.uncertainty import Interval


class EventTests(unittest.TestCase):
    def test_event_interval(self):
        x=e.EventInterval(1,2)
        self.assertEqual(x.midpoint,1.5)
        self.assertEqual(x.width,1)

    def test_crossing_direction(self):
        self.assertEqual(e.crossing_direction(-1,1),'rising')
        self.assertEqual(e.crossing_direction(1,-1),'falling')
        self.assertEqual(e.crossing_direction(1,2),'none')

    def test_tangency(self):
        self.assertEqual(e.classify_tangency(0,1,0),'crossing')
        self.assertEqual(e.classify_tangency(0,0,1),'touch')

    def test_grazing(self):
        self.assertTrue(e.grazing_marker(0,0,1))

    def test_group_simultaneous(self):
        groups=e.group_simultaneous_events([{'id':'b','time':1+1e-10},{'id':'a','time':1},{'id':'c','time':2}],1e-8)
        self.assertEqual(len(groups),2)
        self.assertEqual([x['id'] for x in groups[0]],['a','b'])

    def test_topological_order(self):
        order=e.topological_event_order(['a','b','c'],[('a','c'),('b','c')])
        self.assertEqual(order[-1],'c')

    def test_topological_order_cycle(self):
        with self.assertRaises(ValueError):
            e.topological_event_order(['a','b'],[('a','b'),('b','a')])

    def test_tie_break(self):
        k=e.event_tie_break_key({'time':1.0,'priority':2,'relation_id':'r','lineage_hash':'h'},0.1)
        self.assertEqual(k,(10,2,'r','h'))

    def test_zeno(self):
        times=[0,1,1.5,1.75,1.875,1.9375]
        found,h=e.detect_zeno(times,ratio_threshold=0.6,min_intervals=4)
        self.assertTrue(found)
        self.assertAlmostEqual(h,2.0,places=3)

    def test_no_zeno(self):
        self.assertFalse(e.detect_zeno([0,1,2,3,4],0.8,3)[0])

    def test_dwell_hysteresis(self):
        h=e.DwellHysteresis(1.0,0.5,0.2)
        self.assertFalse(h.update(1.1,0.0))
        self.assertTrue(h.update(1.1,0.3))
        self.assertFalse(h.update(0.4,0.4))

    def test_lipschitz(self):
        self.assertTrue(e.lipschitz_excludes_root(2.0,0.5,1.0))
        self.assertFalse(e.lipschitz_excludes_root(0.2,0.5,1.0))

    def test_interval_newton(self):
        root,status,it=e.interval_newton(lambda x:x*x-2,lambda I:Interval(2*I.lo,2*I.hi),Interval(1,2))
        self.assertEqual(status,'unique_root')
        self.assertTrue(root.contains(math.sqrt(2)))

    def test_interval_newton_no_root(self):
        root,status,it=e.interval_newton(lambda x:x*x+1,lambda I:Interval(2*I.lo,2*I.hi),Interval(1,2))
        self.assertEqual(status,'no_root')
        self.assertIsNone(root)

    def test_sturm_count(self):
        # (x-1)(x+1)(x-2)
        coeff=[1,-2,-1,2]
        self.assertEqual(e.sturm_root_count(coeff,-3,3),3)
        self.assertEqual(e.sturm_root_count(coeff,0,1.5),1)

    def test_atomic_commit(self):
        state={'x':1,'sheet':0}
        out,record=e.apply_atomic_transition_batch(state,[{'id':'b','time':1,'priority':1,'patch':{'x':2}},{'id':'a','time':1,'priority':0,'patch':{'sheet':1}}],lambda s:s['x']>0)
        self.assertTrue(record['committed'])
        self.assertEqual(out,{'x':2,'sheet':1})

    def test_atomic_rollback(self):
        state={'x':1}
        out,record=e.apply_atomic_transition_batch(state,[{'id':'a','time':1,'patch':{'x':-1}}],lambda s:s['x']>0)
        self.assertFalse(record['committed'])
        self.assertEqual(out,state)

    def test_hybrid_automaton(self):
        tr=e.HybridTransition('go','idle','run',lambda s:s['x']>0,lambda s:{**s,'x':0})
        a=e.HybridAutomaton(['idle','run'],[tr])
        mode,state,tid=a.step('idle',{'x':1})
        self.assertEqual((mode,state['x'],tid),('run',0,'go'))


class TopologyTests(unittest.TestCase):
    def test_winding(self):
        square=[(-1,-1),(1,-1),(1,1),(-1,1)]
        self.assertEqual(t.winding_number(square,(0,0)),1)
        self.assertEqual(t.winding_number(square,(2,0)),0)

    def test_lift_periodic(self):
        wrapped,sheet=t.lift_periodic(7.5,3)
        self.assertAlmostEqual(wrapped,1.5)
        self.assertEqual(sheet,2)

    def test_reduce_word(self):
        self.assertEqual(t.reduce_word(['a','A','b']),('b',))

    def test_oriented_boundary(self):
        b=t.oriented_boundary((0,1,2))
        self.assertEqual(len(b),3)
        self.assertEqual(b[0],(1,(1,2)))

    def test_complex_closure(self):
        c=t.SimplicialComplex([(0,1,2)])
        self.assertIn((0,1),c.simplices)
        self.assertIn((0,),c.simplices)

    def test_boundary_matrix(self):
        c=t.SimplicialComplex([(0,1,2)])
        b=t.boundary_matrix(c,2)
        self.assertEqual(len(b),3)
        self.assertEqual(len(b[0]),1)

    def test_boundary_squared_zero(self):
        c=t.SimplicialComplex([(0,1,2,3)])
        self.assertTrue(t.boundary_squared_zero(c))

    def test_rank_mod2(self):
        self.assertEqual(t.rank_mod2([[1,0],[0,1]]),2)
        self.assertEqual(t.rank_mod2([[1,1],[1,1]]),1)

    def test_betti_triangle_boundary(self):
        c=t.SimplicialComplex([(0,1),(1,2),(0,2)])
        self.assertEqual(t.betti_numbers(c)[:2],(1,1))

    def test_betti_filled_triangle(self):
        c=t.SimplicialComplex([(0,1,2)])
        self.assertEqual(t.betti_numbers(c)[:2],(1,0))

    def test_euler(self):
        c=t.SimplicialComplex([(0,1,2)])
        self.assertEqual(t.euler_characteristic(c),1)

    def test_union_find(self):
        u=t.UnionFind([1,2,3])
        u.union(1,2)
        self.assertEqual(u.find(1),u.find(2))

    def test_persistence_h0(self):
        intervals=t.persistence_h0({0:0,1:0,2:0},[(0,1,1),(1,2,2)])
        finite=[x for x in intervals if x.death is not None]
        infinite=[x for x in intervals if x.death is None]
        self.assertEqual(len(finite),2)
        self.assertEqual(len(infinite),1)

    def test_greedy_diagram_distance(self):
        a=[t.PersistenceInterval(0,1)]
        b=[t.PersistenceInterval(0,1.5)]
        self.assertAlmostEqual(t.greedy_diagram_distance(a,b),0.5)

    def test_rips(self):
        c=t.vietoris_rips_complex([(0,0),(1,0),(0,1)],1.5)
        self.assertIn((0,1,2),c.simplices)

    def test_cubical_order(self):
        cells=t.cubical_lower_star_order([[0,1],[2,3]])
        self.assertEqual(cells[0]['dimension'],0)
        self.assertEqual(cells[-1]['dimension'],2)

    def test_hodge_laplacian(self):
        l=t.hodge_laplacian_0(3,[(0,1),(1,2)])
        self.assertEqual(l[1][1],2)
        self.assertEqual(sum(l[1]),0)

    def test_linking_finite(self):
        a=[(math.cos(x),math.sin(x),0) for x in [0,math.pi/2,math.pi,3*math.pi/2]]
        b=[(1.5,0.5*math.cos(x),0.5*math.sin(x)) for x in [0,math.pi/2,math.pi,3*math.pi/2]]
        value=t.gauss_linking_number(a,b)
        self.assertTrue(math.isfinite(value))

    def test_group_presentation(self):
        g=t.GroupPresentation(('a','b'),(('a','a'),))
        self.assertEqual(g.reduce(['a','a','b']),('b',))

    def test_monodromy(self):
        self.assertEqual(t.apply_monodromy(0,['a'],{'a':[1,0]}),1)
        self.assertEqual(t.apply_monodromy(1,['A'],{'a':[1,0]}),0)

    def test_persistence_events(self):
        intervals=[t.PersistenceInterval(0,2,0,'x'),t.PersistenceInterval(0,0.5,0,'y')]
        events=t.persistence_threshold_events(intervals,1)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['representative'],'x')


if __name__ == '__main__':
    unittest.main()
