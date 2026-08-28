import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from ugts_kc import clothoid, quintic_scurve, se3_exp, bisect_root, classify_event

route = [clothoid(6*i/20, A=2.0) for i in range(21)]
print('clothoid_end', route[-1])
print('s_curve_mid', quintic_scurve(0.5, distance=1.0, duration=2.0))
print('twist_T', se3_exp((0,0,0.4),(0.5,0,0),3.0))
t = bisect_root(lambda x: x*x-4.0, 0.0, 3.0)
print('event_time', t, 'class', classify_event(-1,0,1))
