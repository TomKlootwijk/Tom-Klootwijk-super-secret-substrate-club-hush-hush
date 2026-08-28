"""Minimal UGTS-KC 3.0 query-first portal example."""
from ugts_kc3.kinematics import JetState
from ugts_kc3.world import CompatibilityRule, RadialAngularSupport, Relation, StateRecord, World

jet = JetState((-2.0, 0.0), (1.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0))
traveler = StateRecord("traveler", jet, sheet=0, orientation=1, tags=("player",), lineage=("seed:traveler",))
relation = Relation(
    "x_zero_portal",
    lambda state: state.jet.position[0],
    RadialAngularSupport((0.0, 0.0), 3.0),
    CompatibilityRule((0,), 1, 0.0, 0.2, ("player",)),
    {"sheet": 1, "orientation": -1, "branch": "B"},
)
world = World([traveler], [relation])
print("state_at_1.25", world.state_at("traveler", 1.25).jet.position)
print("next_event", world.next_event("traveler", 0.0, 4.0))
print("processed", world.process_next_event("traveler", 0.0, 4.0))
print("post_state", world.states["traveler"])
