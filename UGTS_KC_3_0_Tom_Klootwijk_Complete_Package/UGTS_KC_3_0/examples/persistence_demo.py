"""Connected-component persistence over an edge filtration."""
from ugts_kc3.topology import persistence_h0, persistence_threshold_events

births = {0: 0.0, 1: 0.0, 2: 0.1, 3: 0.2}
edges = [(0, 1, 0.3), (1, 2, 0.5), (2, 3, 0.9)]
intervals = persistence_h0(births, edges)
for interval in intervals:
    print(interval)
print("events", persistence_threshold_events(intervals, min_lifetime=0.35))
