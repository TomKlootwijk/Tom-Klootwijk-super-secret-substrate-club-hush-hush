import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from ugts_kc import superellipse, gielis, rose, epitrochoid

families = {
    'superellipse': lambda t: superellipse(t,1.5,1.0,4),
    'gielis': lambda t: gielis(t,m=7,n1=0.4,n2=1.7,n3=1.7),
    'rose': lambda t: rose(t,5,1),
    'epitrochoid': lambda t: epitrochoid(t,5,3,5),
}
for name, fn in families.items():
    pts=[fn(2*math.pi*i/16) for i in range(16)]
    print(name, pts[:3], '...')
