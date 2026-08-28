"""Small CPU reference benchmark.  Results are environment-specific and nonportable."""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from time import perf_counter

from ugts_kc3.events import interval_newton
from ugts_kc3.kinematics import se3_exp
from ugts_kc3.patterns import superformula
from ugts_kc3.topology import persistence_h0
from ugts_kc3.uncertainty import Interval


def bench(name, iterations, func):
    start=perf_counter()
    acc=0.0
    for i in range(iterations):
        value=func(i)
        if isinstance(value,(int,float)):
            acc += float(value)
        elif isinstance(value,tuple):
            acc += float(value[0])
    elapsed=perf_counter()-start
    return {"name":name,"iterations":iterations,"seconds":elapsed,"operations_per_second":iterations/elapsed,"checksum":acc}


def main():
    results=[]
    results.append(bench('superformula',200_000,lambda i:superformula(i*1e-4)[0]))
    results.append(bench('se3_exp',50_000,lambda i:se3_exp((0.01,0.02,0.03,1.0,0.5,-0.2))[0][0]))
    results.append(bench('interval_newton_sqrt2',20_000,lambda i:interval_newton(lambda x:x*x-2,lambda I:Interval(2*I.lo,2*I.hi),Interval(1,2))[0].midpoint))
    births={i:0.0 for i in range(128)}
    edges=[(i,i+1,(i+1)/128) for i in range(127)]
    results.append(bench('persistence_h0_128',2_000,lambda i:len(persistence_h0(births,edges))))
    payload={
        "boundary":"Reference Python CPU benchmark only; not a GPU, hardware or universal performance claim.",
        "python":sys.version,
        "platform":platform.platform(),
        "processor":platform.processor(),
        "results":results,
    }
    out=Path(__file__).resolve().parent/'reference_benchmark_results.json'
    out.write_text(json.dumps(payload,indent=2))
    print(json.dumps(payload,indent=2))

if __name__=='__main__':
    main()
