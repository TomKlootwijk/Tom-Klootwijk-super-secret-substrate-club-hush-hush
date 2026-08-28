import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from ugts_kc3 import *
from ugts_kc3.webexport import _safe_script_json


class VectorArt39Tests(unittest.TestCase):
    def test_gradient_validation(self):
        gradient = LinearGradient("g", (0, 0), (10, 0), (GradientStop(0, "#000"), GradientStop(1, "#fff")))
        gradient.validate()
        with self.assertRaises(ValueError):
            LinearGradient("g", (0, 0), (1, 0), (GradientStop(1, "#fff"), GradientStop(0, "#000"))).validate()

    def test_radial_gradient_roundtrip(self):
        gradient = RadialGradient("r", (0, 0), 10, (GradientStop(0, "white"), GradientStop(1, "black")), (1, 2))
        self.assertEqual(RadialGradient.from_dict(gradient.to_dict()), gradient)

    def test_path_builder_and_svg_d(self):
        path = VectorPathBuilder("p").move_to(0, 0).line_to(1, 0).line_to(1, 1).close().build()
        self.assertEqual(path.svg_d(), "M 0 0 L 1 0 L 1 1 Z")

    def test_path_requires_move(self):
        with self.assertRaises(ValueError):
            VectorPath("bad", (PathCommand("L", (1, 2)),)).validate()

    def test_quadratic_flatten(self):
        path = VectorPathBuilder("q").move_to(0, 0).quadratic_to(0.5, 1, 1, 0).build()
        points = path.flatten(0.02)[0]
        self.assertGreater(len(points), 4)
        self.assertEqual(points[0], (0.0, 0.0))
        self.assertEqual(points[-1], (1.0, 0.0))

    def test_cubic_flatten(self):
        path = VectorPathBuilder("c").move_to(0, 0).cubic_to(0, 1, 1, 1, 1, 0).build()
        points = path.flatten(0.01)[0]
        self.assertGreater(len(points), 8)

    def test_multiple_subpaths(self):
        path = VectorPath(
            "multi",
            (
                PathCommand("M", (0, 0)), PathCommand("L", (1, 0)),
                PathCommand("M", (2, 0)), PathCommand("L", (3, 0)),
            ),
        )
        self.assertEqual(len(path.flatten()), 2)

    def test_path_bounds(self):
        path = polygon_path("box", [(-2, -1), (3, -1), (3, 4), (-2, 4)])
        self.assertEqual(path.bounds(), ((-2.0, -1.0), (3.0, 4.0)))

    def test_unknown_gradient_rejected(self):
        asset = VectorAsset2D("a", (10, 10), (0, 0), (polygon_path("p", [(0, 0), (1, 0), (0, 1)], VectorPaint(fill="@missing")),))
        with self.assertRaises(ValueError):
            asset.validate()

    def test_vector_library_roundtrip(self):
        library = VectorLibrary((circle_asset("circle", 5), star_asset("star", 5, 8)))
        clone = VectorLibrary.from_dict(library.to_dict())
        self.assertEqual(tuple(a.id for a in clone), ("circle", "star"))

    def test_rounded_rectangle_asset(self):
        asset = rectangle_asset("rounded", 100, 40, corner_radius=12)
        self.assertEqual(asset.size, (100, 40))
        self.assertTrue(any(command.op == "C" for command in asset.paths[0].commands))

    def test_circle_asset_bounds(self):
        asset = circle_asset("circle", 12)
        minimum, maximum = asset.bounds()
        self.assertAlmostEqual(minimum[0], -12, places=6)
        self.assertAlmostEqual(maximum[1], 12, places=6)

    def test_star_asset_validation(self):
        self.assertEqual(len(star_asset("star", 6, 20).paths[0].commands), 13)
        with self.assertRaises(ValueError):
            star_asset("bad", 2, 10)

    def test_svg_export(self):
        asset = star_asset("star", fill="#ffc400")
        with tempfile.TemporaryDirectory() as tmp:
            path = write_vector_svg(asset, Path(tmp) / "star.svg", "#101020", padding=4)
            text = path.read_text()
            self.assertIn("<svg", text)
            self.assertIn("<path", text)
            self.assertIn("#ffc400", text)
            self.assertIn('viewBox="-28 -28 56 56"', text)


class Collision39Tests(unittest.TestCase):
    def test_aabb_properties(self):
        box = AABB2.from_center((2, 3), (1, 2))
        self.assertEqual(box.minimum, (1.0, 1.0))
        self.assertEqual(box.maximum, (3.0, 5.0))
        self.assertEqual(box.area, 8.0)

    def test_aabb_exclusive_touch(self):
        a = AABB2((0, 0), (1, 1))
        b = AABB2((1, 0), (2, 1))
        self.assertTrue(a.intersects(b))
        self.assertFalse(a.intersects(b, inclusive=False))

    def test_circle_circle_collision(self):
        hit = collide(Circle2((0, 0), 2), Circle2((3, 0), 2))
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.penetration, 1.0)
        self.assertEqual(hit.normal, (1.0, 0.0))

    def test_circle_circle_miss(self):
        self.assertIsNone(collide(Circle2((0, 0), 1), Circle2((3, 0), 1)))

    def test_aabb_circle_collision(self):
        hit = collide(AABB2((-1, -1), (1, 1)), Circle2((1.5, 0), 1))
        self.assertIsNotNone(hit)
        self.assertEqual(hit.normal, (1.0, 0.0))

    def test_circle_inside_aabb(self):
        hit = collide(AABB2((-2, -2), (2, 2)), Circle2((0, 0), 0.5))
        self.assertIsNotNone(hit)
        self.assertGreater(hit.penetration, 2)

    def test_polygon_polygon(self):
        a = ConvexPolygon2(((-1, -1), (1, -1), (1, 1), (-1, 1)))
        b = a.moved((1.5, 0))
        hit = collide(a, b)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.penetration, 0.5)

    def test_nonconvex_polygon_rejected(self):
        with self.assertRaises(ValueError):
            ConvexPolygon2(((0, 0), (2, 0), (1, 0.5), (2, 2), (0, 2)))

    def test_polygon_circle(self):
        polygon = ConvexPolygon2(((-1, -1), (1, -1), (1, 1), (-1, 1)))
        self.assertIsNotNone(collide(polygon, Circle2((1.4, 0), 0.5)))

    def test_collision_filter(self):
        a = CollisionFilter(layer=1, mask=2)
        b = CollisionFilter(layer=2, mask=1)
        c = CollisionFilter(layer=4, mask=1)
        self.assertTrue(a.allows(b))
        self.assertFalse(a.allows(c))

    def test_shape_roundtrip(self):
        for shape in (AABB2((-1, -2), (3, 4)), Circle2((2, 3), 5), ConvexPolygon2(((0, 0), (1, 0), (0, 1)))):
            self.assertEqual(shape_from_dict(shape.to_dict()), shape)

    def test_spatial_hash_query(self):
        spatial = SpatialHash2D(10)
        spatial.insert("a", AABB2((0, 0), (2, 2)))
        spatial.insert("b", AABB2((20, 0), (22, 2)))
        self.assertEqual(spatial.query(AABB2((-1, -1), (3, 3))), ("a",))

    def test_spatial_hash_pairs(self):
        spatial = SpatialHash2D(10)
        spatial.insert("a", AABB2((0, 0), (5, 5)))
        spatial.insert("b", AABB2((4, 4), (7, 7)))
        spatial.insert("c", AABB2((20, 20), (21, 21)))
        self.assertEqual(spatial.potential_pairs(), (("a", "b"),))

    def test_spatial_update_remove(self):
        spatial = SpatialHash2D(10)
        spatial.insert("a", AABB2((0, 0), (1, 1)))
        spatial.update("a", AABB2((20, 20), (21, 21)))
        self.assertEqual(spatial.query(AABB2((0, 0), (2, 2))), ())
        spatial.remove("a")
        self.assertEqual(len(spatial), 0)

    def test_sweep_aabb_hit(self):
        hit = sweep_aabb(AABB2((0, 0), (1, 1)), (10, 0), AABB2((5, 0), (6, 1)))
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.time, 0.4)
        self.assertEqual(hit.normal, (-1.0, 0.0))

    def test_sweep_aabb_miss(self):
        self.assertIsNone(sweep_aabb(AABB2((0, 0), (1, 1)), (0, 10), AABB2((5, 0), (6, 1))))

    def test_resolve_velocity(self):
        velocity = resolve_velocity((10, 4), (-1, 0), restitution=0.5, friction=0.25)
        self.assertAlmostEqual(velocity[0], -5)
        self.assertAlmostEqual(velocity[1], 3)


class Input39Tests(unittest.TestCase):
    def make_map(self):
        return InputMap((
            ActionDefinition("x", (InputBinding("key", "KeyA", -1), InputBinding("key", "KeyD", 1)), deadzone=0),
            ActionDefinition("jump", (InputBinding("key", "Space"),), deadzone=0),
            ActionDefinition("axis", (InputBinding("gamepad_axis", "0"),), deadzone=0.2),
        ))

    def test_keyboard_axis(self):
        mapping = self.make_map()
        frame = mapping.evaluate(RawInputState(keys=frozenset({"KeyD"})))
        self.assertEqual(frame.value("x"), 1)

    def test_opposed_keys_cancel(self):
        frame = self.make_map().evaluate(RawInputState(keys=frozenset({"KeyA", "KeyD"})))
        self.assertEqual(frame.value("x"), 0)

    def test_deadzone(self):
        frame = self.make_map().evaluate(RawInputState(gamepad_axes={"0": 0.1}))
        self.assertEqual(frame.value("axis"), 0)

    def test_pressed_and_released(self):
        mapping = self.make_map()
        first = mapping.evaluate(RawInputState(keys=frozenset({"Space"})))
        second = mapping.evaluate(RawInputState(), first)
        self.assertTrue(first.pressed("jump"))
        self.assertTrue(second.released("jump"))

    def test_vector_normalization(self):
        frame = InputFrame({"x": 1, "y": 1}, {}, {"x": 0.5, "y": 0.5})
        x, y = frame.vector("x", "y")
        self.assertAlmostEqual(math.hypot(x, y), 1)

    def test_gamepad_device_key(self):
        mapping = InputMap((ActionDefinition("fire", (InputBinding("gamepad_button", "2", device=1),), deadzone=0),))
        frame = mapping.evaluate(RawInputState(gamepad_buttons={"1:2": 0.8}))
        self.assertGreater(frame.value("fire"), 0.7)

    def test_input_map_roundtrip(self):
        mapping = self.make_map()
        clone = InputMap.from_dict(mapping.to_dict())
        self.assertEqual(set(clone.actions), set(mapping.actions))

    def test_input_recorder_roundtrip(self):
        recorder = InputRecorder()
        recorder.append(InputFrame({"x": 1}, frame_index=0))
        recorder.append(InputFrame({"x": 0}, {"x": 1}, frame_index=1))
        clone = InputRecorder.from_dict(recorder.to_dict())
        self.assertEqual(clone.frame(1).previous_values["x"], 1)


class Animation39Tests(unittest.TestCase):
    def test_easing_endpoints(self):
        for name in ("linear", "ease_in", "ease_out", "ease_in_out", "smoothstep", "smootherstep", "back_out", "elastic_out"):
            self.assertAlmostEqual(easing(name, 0), 0)
            self.assertAlmostEqual(easing(name, 1), 1)

    def test_vector_interpolation(self):
        self.assertEqual(interpolate((0.0, 2.0), (2.0, 4.0), 0.5), (1.0, 3.0))

    def test_track_sampling(self):
        track = AnimationTrack("transform.x", (Keyframe(0, 0), Keyframe(1, 10)))
        self.assertEqual(track.sample(0.25), 2.5)

    def test_track_step_easing(self):
        track = AnimationTrack("x", (Keyframe(0, 0), Keyframe(1, 10, "step")))
        self.assertEqual(track.sample(0.9), 0)

    def test_clip_loop(self):
        clip = AnimationClip("loop", (AnimationTrack("x", (Keyframe(0, 0), Keyframe(1, 10))),), loop_mode="loop")
        self.assertAlmostEqual(clip.sample(1.25)["x"], 2.5)

    def test_clip_pingpong(self):
        clip = AnimationClip("ping", (AnimationTrack("x", (Keyframe(0, 0), Keyframe(1, 10))),), loop_mode="pingpong")
        self.assertAlmostEqual(clip.sample(1.25)["x"], 7.5)

    def test_player_finishes_once(self):
        clip = AnimationClip("once", (AnimationTrack("x", (Keyframe(0, 0), Keyframe(1, 1))),))
        player = AnimationPlayer((clip,))
        player.play("once")
        player.update(2)
        self.assertTrue(player.finished)
        self.assertFalse(player.playing)

    def test_crossfade(self):
        a = AnimationClip("a", (AnimationTrack("x", (Keyframe(0, 0), Keyframe(1, 0))),), loop_mode="loop")
        b = AnimationClip("b", (AnimationTrack("x", (Keyframe(0, 10), Keyframe(1, 10))),), loop_mode="loop")
        player = AnimationPlayer((a, b))
        player.play("a")
        player.play("b", fade=1)
        value = player.update(0.5)["x"]
        self.assertGreater(value, 0)
        self.assertLess(value, 10)

    def test_state_machine(self):
        idle = AnimationClip("idle", (AnimationTrack("x", (Keyframe(0, 0), Keyframe(1, 0))),), loop_mode="loop")
        run = AnimationClip("run", (AnimationTrack("x", (Keyframe(0, 1), Keyframe(1, 1))),), loop_mode="loop")
        machine = AnimationStateMachine(AnimationPlayer((idle, run)), "idle", (AnimationTransition("idle", "run", "speed", ">", 0.1, 0),))
        machine.set("speed", 1)
        self.assertEqual(machine.update(0.1)["x"], 1)
        self.assertEqual(machine.state, "run")

    def test_apply_sample(self):
        target = {}
        apply_animation_sample(target, {"transform.position": (1, 2), "opacity": 0.5})
        self.assertEqual(target["transform"]["position"], [1, 2])
        self.assertEqual(target["opacity"], 0.5)

    def test_duplicate_key_time_rejected(self):
        with self.assertRaises(ValueError):
            AnimationTrack("x", (Keyframe(0, 0), Keyframe(0, 1))).validate()

    def test_clip_roundtrip(self):
        clip = AnimationClip("clip", (AnimationTrack("x", (Keyframe(0, 0), Keyframe(1, 1))),), loop_mode="loop")
        self.assertEqual(AnimationClip.from_dict(clip.to_dict()), clip)


class Tilemap39Tests(unittest.TestCase):
    def make_map(self):
        definitions = (TileDefinition("floor"), TileDefinition("wall", solid=True))
        return TileMap.from_ascii("map", (".....", ".###.", "....."), {".": "floor", "#": "wall"}, definitions, tile_size=10)

    def test_ascii_import(self):
        tilemap = self.make_map()
        self.assertEqual(tilemap.width, 5)
        self.assertEqual(tilemap.tile_id("main", (1, 1)), "wall")

    def test_ascii_unknown_character(self):
        with self.assertRaises(KeyError):
            TileMap.from_ascii("bad", ("x",), {".": None}, ())

    def test_coordinate_conversion(self):
        tilemap = self.make_map()
        self.assertEqual(tilemap.world_to_cell((15, 25)), (1, 2))
        self.assertEqual(tilemap.cell_to_world((1, 2)), (15.0, 25.0))

    def test_solid_out_of_bounds(self):
        tilemap = self.make_map()
        self.assertTrue(tilemap.is_solid((-1, 0)))
        self.assertTrue(tilemap.is_solid((2, 1)))

    def test_pathfinding(self):
        tilemap = self.make_map()
        path = tilemap.find_path((0, 1), (4, 1))
        self.assertEqual(path[0], (0, 1))
        self.assertEqual(path[-1], (4, 1))
        self.assertGreater(len(path), 5)

    def test_blocked_endpoint(self):
        self.assertEqual(self.make_map().find_path((0, 0), (2, 1)), ())

    def test_diagonal_path(self):
        tilemap = TileMap.from_ascii("open", ("...", "...", "..."), {".": "floor"}, (TileDefinition("floor"),))
        self.assertEqual(tilemap.find_path((0, 0), (2, 2), diagonal=True), ((0, 0), (1, 1), (2, 2)))

    def test_flood_fill(self):
        cells = self.make_map().flood_fill((0, 0), limit=4)
        self.assertEqual(len(cells), 4)

    def test_collision_box_merge(self):
        boxes = self.make_map().collision_boxes()
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0], AABB2((10, 10), (40, 20)))

    def test_tilemap_roundtrip(self):
        tilemap = self.make_map()
        clone = TileMap.from_dict(tilemap.to_dict())
        self.assertEqual(clone.to_dict(), tilemap.to_dict())


class Audio39Tests(unittest.TestCase):
    def test_a4_frequency(self):
        self.assertAlmostEqual(note_frequency("A4"), 440)

    def test_c4_frequency(self):
        self.assertAlmostEqual(note_frequency("C4"), 261.625565, places=5)

    def test_invalid_note(self):
        with self.assertRaises(ValueError):
            note_frequency("H4")

    def test_cue_roundtrip(self):
        cue = SoundCue.from_note("coin", "E6", waveform="triangle", duration=0.1)
        self.assertEqual(SoundCue.from_dict(cue.to_dict()), cue)

    def test_invalid_waveform(self):
        with self.assertRaises(ValueError):
            SoundCue("bad", waveform="noise").validate()

    def test_sequence_validation(self):
        cue = SoundCue("tone")
        sequence = MusicSequence("seq", 120, 4, (SequenceNote(0, "tone"), SequenceNote(2, "tone", 2, 0.5)))
        AudioBank((cue,), (sequence,)).validate()

    def test_sequence_unknown_cue(self):
        with self.assertRaises(KeyError):
            AudioBank().add_sequence(MusicSequence("bad", 120, 4, (SequenceNote(0, "missing"),)))

    def test_audio_bank_roundtrip(self):
        bank = AudioBank((SoundCue("tone"),), (MusicSequence("seq", 120, 2, (SequenceNote(0, "tone"),)),))
        self.assertEqual(AudioBank.from_dict(bank.to_dict()).to_dict(), bank.to_dict())


class GameWorld39Tests(unittest.TestCase):
    def make_world(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("a", components=(Transform2D((0, 0)), Body2D(gravity_scale=0), Collider2D(Circle2((0, 0), 1))))
        return world

    def test_spawn_and_query(self):
        world = self.make_world()
        self.assertEqual(world.query(Transform2D)[0].id, "a")
        self.assertIsInstance(world.require("a", Body2D), Body2D)

    def test_duplicate_entity_rejected(self):
        world = self.make_world()
        with self.assertRaises(ValueError):
            world.spawn("a")

    def test_query_tags(self):
        world = GameWorld()
        world.spawn("p", tags=("player",), components=(Transform2D(),))
        world.spawn("n", tags=("npc",), components=(Transform2D(),))
        self.assertEqual(tuple(e.id for e in world.query(Transform2D, tags=("player",))), ("p",))

    def test_physics_motion(self):
        world = self.make_world()
        world.require("a", Body2D).velocity = (10, 0)
        world.step()
        self.assertAlmostEqual(world.require("a", Transform2D).position[0], 1)

    def test_force_application(self):
        world = self.make_world()
        world.apply_force("a", (10, 0))
        world.step()
        self.assertAlmostEqual(world.require("a", Body2D).velocity[0], 1)

    def test_max_speed(self):
        world = self.make_world()
        body = world.require("a", Body2D)
        body.velocity = (100, 0)
        body.max_speed = 5
        world.step()
        self.assertAlmostEqual(length2(body.velocity), 5)

    def test_collision_enter_and_resolution(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("moving", components=(Transform2D((0, 0)), Body2D(velocity=(10, 0), gravity_scale=0), Collider2D(Circle2((0, 0), 1))))
        world.spawn("wall", components=(Transform2D((1.5, 0)), Body2D(body_type="static"), Collider2D(Circle2((0, 0), 1))))
        events = world.step()
        self.assertTrue(any(event.kind == "collision_enter" for event in events))
        self.assertLess(world.require("moving", Transform2D).position[0], 1)

    def test_sensor_does_not_resolve(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("a", components=(Transform2D((0, 0)), Body2D(velocity=(1, 0), gravity_scale=0), Collider2D(Circle2((0, 0), 1), CollisionFilter(sensor=True))))
        world.spawn("b", components=(Transform2D((0.5, 0)), Body2D(body_type="static"), Collider2D(Circle2((0, 0), 1))))
        world.step()
        self.assertAlmostEqual(world.require("a", Transform2D).position[0], 0.1)

    def test_collision_exit(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("a", components=(Transform2D((0, 0)), Body2D(gravity_scale=0), Collider2D(Circle2((0, 0), 1))))
        world.spawn("b", components=(Transform2D((1, 0)), Body2D(body_type="static"), Collider2D(Circle2((0, 0), 1))))
        world.step()
        world.require("a", Transform2D).position = (-10, 0)
        events = world.step()
        self.assertTrue(any(event.kind == "collision_exit" for event in events))

    def test_filter_prevents_collision(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("a", components=(Transform2D(), Collider2D(Circle2((0, 0), 1), CollisionFilter(1, 2))))
        world.spawn("b", components=(Transform2D(), Collider2D(Circle2((0, 0), 1), CollisionFilter(4, 1))))
        self.assertFalse(any(event.kind.startswith("collision") for event in world.step()))

    def test_bounds_clamp(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("a", components=(Transform2D((20, -3)), BoundsConstraint2D(AABB2((0, 0), (10, 10)), "clamp")))
        world.step()
        self.assertEqual(world.require("a", Transform2D).position, (10, 0))

    def test_bounds_bounce(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("a", components=(Transform2D((9.5, 5)), Body2D(velocity=(10, 0), restitution=1, gravity_scale=0), BoundsConstraint2D(AABB2((0, 0), (10, 10)), "bounce")))
        world.step()
        self.assertLess(world.require("a", Body2D).velocity[0], 0)

    def test_bounds_wrap(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("a", components=(Transform2D((11, 5)), BoundsConstraint2D(AABB2((0, 0), (10, 10)), "wrap")))
        world.step()
        self.assertEqual(world.require("a", Transform2D).position[0], 0)

    def test_player_controller(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("p", components=(Transform2D(), Body2D(gravity_scale=0), PlayerController2D(speed=10, dash_action=None)))
        frame = InputFrame({"move_x": 1, "move_y": 0}, {}, {"move_x": 0.5, "move_y": 0.5})
        world.step(frame)
        self.assertAlmostEqual(world.require("p", Transform2D).position[0], 1)

    def test_dash_event(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("p", components=(Transform2D(), Body2D(gravity_scale=0), PlayerController2D(speed=10, dash_speed=50)))
        frame = InputFrame({"move_x": 1, "move_y": 0, "dash": 1}, {}, {"move_x": 0.5, "move_y": 0.5, "dash": 0.5})
        events = world.step(frame)
        self.assertTrue(any(event.kind == "dash" for event in events))
        self.assertGreater(world.require("p", Transform2D).position[0], 4)

    def test_collectible(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("p", tags=("player",), components=(Transform2D(), Collider2D(Circle2((0, 0), 1))))
        world.spawn("c", components=(Transform2D((0.5, 0)), Collider2D(Circle2((0, 0), 1), CollisionFilter(sensor=True)), Collectible2D(points=3)))
        events = world.step()
        self.assertEqual(world.state["score"], 3)
        self.assertNotIn("c", world.entities)
        self.assertTrue(any(event.kind == "collected" for event in events))

    def test_hazard_damage_and_cooldown(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("p", tags=("player",), components=(Transform2D(), Body2D(gravity_scale=0), Collider2D(Circle2((0, 0), 1)), Health2D(3, 3)))
        world.spawn("h", components=(Transform2D((0.5, 0)), Collider2D(Circle2((0, 0), 1), CollisionFilter(sensor=True)), Hazard2D(damage=1, cooldown=1)))
        world.step()
        self.assertEqual(world.require("p", Health2D).current, 2)
        world.step()
        self.assertEqual(world.require("p", Health2D).current, 2)

    def test_lifetime_despawn(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("short", components=(Transform2D(), Lifetime2D(0.05)))
        world.step()
        self.assertNotIn("short", world.entities)

    def test_camera_conversion(self):
        camera = Camera2D(position=(100, 50), viewport=(200, 100), zoom=2)
        screen = camera.world_to_screen((110, 50))
        self.assertEqual(screen, (120.0, 50.0))
        self.assertEqual(camera.screen_to_world(screen), (110.0, 50.0))

    def test_camera_follow(self):
        world = GameWorld(fixed_dt=0.1)
        world.spawn("p", components=(Transform2D((100, 0)),))
        world.spawn("cam", components=(Camera2D(position=(0, 0), follow_entity="p", follow_smoothing=0),))
        world.step()
        self.assertEqual(world.require("cam", Camera2D).position, (100.0, 0.0))

    def test_world_shape_rotation(self):
        world = GameWorld()
        world.spawn("box", components=(Transform2D(rotation=math.pi / 4), Collider2D(AABB2((-1, -1), (1, 1)))))
        self.assertIsInstance(world.world_shape("box"), ConvexPolygon2)

    def test_snapshot_roundtrip(self):
        world = self.make_world()
        world.step()
        clone = GameWorld.from_snapshot(world.snapshot())
        self.assertEqual(clone.state_hash(), world.state_hash())

    def test_save_load(self):
        world = self.make_world()
        with tempfile.TemporaryDirectory() as tmp:
            path = world.save(Path(tmp) / "save.json")
            clone = GameWorld.load(path)
            self.assertEqual(clone.state_hash(), world.state_hash())

    def test_deterministic_hash(self):
        a = self.make_world()
        b = self.make_world()
        a.step(); b.step()
        self.assertEqual(a.state_hash(), b.state_hash())

    def test_system_order(self):
        world = GameWorld()
        order = []
        world.add_system(lambda *_: order.append("b"), phase="update", priority=2, name="b")
        world.add_system(lambda *_: order.append("a"), phase="update", priority=1, name="a")
        world.step()
        self.assertEqual(order, ["a", "b"])


class ProjectAndWeb39Tests(unittest.TestCase):
    def test_elizabeth_project_validation(self):
        project = elizabeth_vector_quest_project()
        report = project.validate()
        self.assertTrue(report.passed)
        self.assertGreaterEqual(report.metrics["entity_count"], 20)

    def test_blank_project_validation(self):
        project = blank_vector_game_project("Test Game", "Tester")
        self.assertTrue(project.validate().passed)

    def test_project_roundtrip(self):
        project = blank_vector_game_project("Roundtrip Game")
        clone = GameProject.from_dict(project.to_dict())
        self.assertEqual(clone.content_hash(), project.content_hash())

    def test_project_hash_stable(self):
        self.assertEqual(elizabeth_vector_quest_project().content_hash(), elizabeth_vector_quest_project().content_hash())

    def test_project_instantiate_world(self):
        project = elizabeth_vector_quest_project()
        world = project.instantiate_world()
        self.assertIn("player", world.entities)
        self.assertIsInstance(world.require("player", PlayerController2D), PlayerController2D)

    def test_unknown_asset_reported(self):
        project = blank_vector_game_project()
        scene = project.scenes[project.start_scene]
        bad_entity = EntitySpec("bad", {"transform": {"position": [0, 0]}, "vector_renderer": {"asset_id": "missing"}})
        project.scenes[scene.id] = GameSceneSpec(scene.id, scene.entities + (bad_entity,), scene.world_size, scene.background, scene.tilemaps, scene.initial_state, scene.rules, scene.ui)
        report = project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        self.assertTrue(any(issue.code == "asset.unknown" for issue in report.issues))

    def test_project_file_write_load(self):
        project = blank_vector_game_project("File Game")
        with tempfile.TemporaryDirectory() as tmp:
            path = project.write(Path(tmp) / "project.json")
            self.assertEqual(GameProject.load(path).content_hash(), project.content_hash())

    def test_web_single_file_build(self):
        project = blank_vector_game_project("Web Game")
        with tempfile.TemporaryDirectory() as tmp:
            result = build_html5(project, Path(tmp) / "dist")
            self.assertTrue(result.entrypoint.exists())
            text = result.entrypoint.read_text()
            self.assertIn("window.KCGame", text)
            self.assertIn(project.metadata.title, text)
            self.assertTrue(result.single_file)

    def test_web_bundle_build(self):
        project = blank_vector_game_project("Bundle Game")
        with tempfile.TemporaryDirectory() as tmp:
            result = build_html5(project, Path(tmp) / "dist", single_file=False)
            self.assertTrue((result.output_dir / "kc-runtime.js").exists())
            self.assertIn('src="kc-runtime.js"', result.entrypoint.read_text())

    def test_build_report_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_html5(blank_vector_game_project(), Path(tmp) / "dist")
            report = json.loads((result.output_dir / "build-report.json").read_text())
            self.assertEqual(report["project_hash"], result.project_hash)
            self.assertTrue(all(len(item["sha256"]) == 64 for item in report["files"]))

    def test_safe_script_json(self):
        encoded = _safe_script_json({"x": "</script><script>alert(1)</script>"})
        self.assertNotIn("</script>", encoded)
        self.assertIn("\\u003c", encoded)

    def test_cli_info(self):
        env = dict(os.environ, PYTHONPATH=str(HERE.parent / "src"))
        result = subprocess.run([sys.executable, "-m", "ugts_kc3", "info"], cwd=HERE.parent, env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("3.9.1", result.stdout)

    def test_cli_new_validate_build(self):
        env = dict(os.environ, PYTHONPATH=str(HERE.parent / "src"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            new = subprocess.run([sys.executable, "-m", "ugts_kc3", "new", str(root), "--title", "CLI Game"], cwd=HERE.parent, env=env, text=True, capture_output=True)
            self.assertEqual(new.returncode, 0, new.stderr)
            validate = subprocess.run([sys.executable, "-m", "ugts_kc3", "validate", str(root / "project.json")], cwd=HERE.parent, env=env, text=True, capture_output=True)
            self.assertEqual(validate.returncode, 0, validate.stderr)
            build = subprocess.run([sys.executable, "-m", "ugts_kc3", "build-web", str(root / "project.json"), str(root / "dist")], cwd=HERE.parent, env=env, text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            self.assertTrue((root / "dist" / "index.html").exists())

    def test_headless_template_progress(self):
        project = elizabeth_vector_quest_project()
        world = project.instantiate_world()
        previous = None
        for index in range(120):
            frame = project.input_map.frame_from_actions({"move_x": 1, "move_y": 0, "dash": 1 if index == 5 else 0}, previous)
            world.step(frame)
            previous = frame
        self.assertEqual(world.tick, 120)
        self.assertGreater(world.require("player", Transform2D).position[0], 500)
        self.assertGreaterEqual(world.state["score"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
