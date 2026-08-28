"""Run a deterministic smoke simulation of Elizabeth's Vector Garden."""
from pathlib import Path
from ugts_kc3 import GameProject

project = GameProject.load(Path(__file__).with_name("project.json"))
world = project.instantiate_world()
previous = None
for tick in range(240):
    values = {"move_x": 1.0, "move_y": -0.15, "dash": 1.0 if tick == 30 else 0.0}
    frame = project.input_map.frame_from_actions(values, previous)
    world.step(frame)
    previous = frame
print({"tick": world.tick, "state": world.state, "entities": len(world.entities), "hash": world.state_hash()})
