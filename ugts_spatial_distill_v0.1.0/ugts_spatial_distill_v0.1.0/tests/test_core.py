from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
import torch

from ugts_spatial.demo_data import DemoConfig, build_demo_graph
from ugts_spatial.features import hashed_text_embedding
from ugts_spatial.geonames import GeoNamesConfig, build_geonames_graph
from ugts_spatial.graph import SparseTemporalGraph
from ugts_spatial.ids import lineage_update, stable_u64
from ugts_spatial.losses import LossWeights, binary_distillation_loss
from ugts_spatial.metrics import binary_metrics
from ugts_spatial.model import ModelConfig, UGTSSpatialStudent, segment_softmax
from ugts_spatial.ontology import Ontology
from ugts_spatial.spatial import LocalFrame, SpatialIndexer, cone_sphere_support, haversine_m
from ugts_spatial.substrate import SpatialQuery, run_spatial_query
from ugts_spatial.teacher_client import export_relation_tasks, import_relation_labels
from ugts_spatial.tensor_data import graph_to_tensors
from ugts_spatial.training import TrainConfig, load_checkpoint, train_model
from ugts_spatial.ugts_bridge import export_candidate_abi

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology" / "ugts_geo_ontology.json"
CATALOG = ROOT / "vendor" / "ugts_gn_1_1" / "knowledge_catalog.json"
REFERENCE = ROOT / "vendor" / "ugts_gn_1_1" / "ugts_reference.py"


class TestCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ontology = Ontology.load(ONTOLOGY)
        cls.graph = build_demo_graph(ONTOLOGY, CATALOG, DemoConfig(sensors_per_area=3, entities_per_area=6, observation_nodes_per_area=2, min_events_per_sensor=2, max_events_per_sensor=4))

    def test_identity_does_not_use_coordinates(self):
        a = stable_u64("source", "42")
        b = stable_u64("source", "42")
        c = stable_u64("source", "43")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(lineage_update(1, a, 1, 2, {"x": 1}), lineage_update(1, a, 2, 2, {"x": 1}))

    def test_feature_hash_is_deterministic(self):
        a = hashed_text_embedding("sensor observes water level", 32)
        b = hashed_text_embedding("sensor observes water level", 32)
        self.assertTrue(np.array_equal(a, b))
        self.assertAlmostEqual(float(np.linalg.norm(a)), 1.0, places=5)

    def test_ontology_constraints(self):
        observes = self.ontology.rel_by_name["observes"]
        self.assertTrue(self.ontology.compatible(observes.id, self.ontology.node_by_name["sensor"].id, self.ontology.node_by_name["property"].id))
        self.assertFalse(self.ontology.compatible(observes.id, self.ontology.node_by_name["property"].id, self.ontology.node_by_name["sensor"].id))

    def test_spatial_support_and_index(self):
        frame = LocalFrame(52.5, 5.5, 0.0)
        p = frame.to_enu(52.51, 5.5, 0.0)
        result = cone_sphere_support(p, (0, 1, 0), 2000.0, 0.5, 1.0, "inside")
        self.assertTrue(result.in_support)
        self.assertTrue(result.guard_pass)
        self.assertGreater(haversine_m(52.5, 5.5, 52.51, 5.5), 1000.0)
        index = SpatialIndexer(prefer_h3=False, fallback_cell_deg=0.01)
        coords = np.asarray([[52.5, 5.5], [52.501, 5.501], [53.0, 6.0]])
        cells, buckets = index.build_buckets(coords)
        candidates = index.candidates(52.5, 5.5, 500.0, cells, buckets)
        self.assertIn(0, candidates)
        self.assertIn(1, candidates)
        self.assertNotIn(2, candidates)

    def test_graph_roundtrip_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            self.graph.save(td)
            loaded = SparseTemporalGraph.load(td, mmap=True, verify_hashes=True)
            self.assertEqual(loaded.num_nodes, self.graph.num_nodes)
            self.assertEqual(loaded.num_events, self.graph.num_events)
            self.assertEqual(loaded.metadata["no_frame_padding"], True)

    def test_segment_softmax(self):
        logits = torch.tensor([[0.0, 1.0], [1.0, 0.0], [2.0, 2.0]])
        dst = torch.tensor([0, 0, 1])
        out = segment_softmax(logits, dst, 2)
        self.assertTrue(torch.allclose(out[:2].sum(0), torch.ones(2), atol=1e-6))
        self.assertTrue(torch.allclose(out[2], torch.ones(2), atol=1e-6))

    def test_model_forward_and_loss(self):
        batch = graph_to_tensors(self.graph)
        cfg = ModelConfig(self.graph.feature_dim, self.ontology.num_node_types, self.ontology.num_relations, 8, hidden_dim=32, heads=4, layers=1, memory_dim=16, teacher_dim=self.graph.teacher_embeddings.shape[1])
        model = UGTSSpatialStudent(cfg)
        out = model(batch, 168.0)
        self.assertEqual(out["link_logits"].shape, (self.graph.num_examples,))
        loss, parts = binary_distillation_loss(out, batch["ex_label"], batch["ex_teacher_prob"], batch["ex_split"] == 0, batch["teacher_embeddings"], batch["teacher_mask"], LossWeights())
        self.assertTrue(torch.isfinite(loss))
        self.assertGreater(parts["loss"], 0.0)
        metrics = binary_metrics(out["link_logits"], batch["ex_label"])
        self.assertEqual(metrics["count"], self.graph.num_examples)

    def test_training_query_and_bridge(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            graph_dir = self.graph.save(td / "graph")
            report = train_model(graph_dir, ONTOLOGY, td / "run", TrainConfig(hidden_dim=16, heads=4, layers=1, memory_dim=8, epochs=2, patience=2, device="cpu", num_threads=1))
            self.assertTrue((td / "run" / "checkpoint.pt").exists())
            self.assertIn("validation", report["metrics"])
            model, _ = load_checkpoint(td / "run" / "checkpoint.pt")
            source = next(i for i, t in enumerate(self.graph.node_types) if int(t) == self.ontology.node_by_name["sensor"].id)
            query = SpatialQuery(source, self.ontology.rel_by_name["near"].id, radius_m=20_000.0, semantic_threshold=0.0, query_time=168.0, max_results=8)
            events = run_spatial_query(self.graph, self.ontology, model, query)
            self.assertTrue(events)
            self.assertTrue(any(x.verified for x in events))
            manifest = export_candidate_abi(graph_dir, ONTOLOGY, REFERENCE, td / "abi", source_index=source, relation_id=self.ontology.rel_by_name["near"].id, candidate_indices=[events[0].target_index], radius_m=events[0].distance_m, guard_epsilon_m=100.0)
            self.assertEqual(manifest["candidate_count"], 1)
            self.assertEqual((td / "abi" / "states_g64.bin").stat().st_size, 64)
            self.assertEqual((td / "abi" / "events_e16.bin").stat().st_size, 16)

    def test_teacher_task_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            graph_dir = self.graph.save(td / "graph")
            count = export_relation_tasks(graph_dir, ONTOLOGY, td / "tasks.jsonl", max_records=2)
            self.assertEqual(count, 2)
            rows = [json.loads(x) for x in (td / "tasks.jsonl").read_text().splitlines()]
            with (td / "labels.jsonl").open("w") as f:
                for row in rows:
                    f.write(json.dumps({"example_index": row["example_index"], "probability": 0.77}) + "\n")
            output = import_relation_labels(graph_dir, td / "labels.jsonl", td / "updated")
            updated = SparseTemporalGraph.load(output, verify_hashes=True)
            for row in rows:
                self.assertAlmostEqual(float(updated.ex_teacher_prob[row["example_index"]]), 0.77, places=5)

    def test_geonames_zip_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            rows = [
                "1\tAlpha\tAlpha\t\t52.5\t5.5\tP\tPPL\tNL\t\t16\t\t\t\t1000\t2\t2\tEurope/Amsterdam\t2026-01-01",
                "2\tBeta\tBeta\t\t52.51\t5.51\tP\tPPL\tNL\t\t16\t\t\t\t500\t1\t1\tEurope/Amsterdam\t2026-01-01",
                "3\tGamma\tGamma\t\t52.8\t5.8\tP\tPPL\tNL\t\t16\t\t\t\t300\t0\t0\tEurope/Amsterdam\t2026-01-01",
            ]
            with zipfile.ZipFile(td / "NL.zip", "w") as z:
                z.writestr("NL.txt", "\n".join(rows) + "\n")
            graph = build_geonames_graph(td / "NL.zip", ONTOLOGY, GeoNamesConfig(max_records=3, near_radius_m=3000, negative_radius_m=10000))
            self.assertGreaterEqual(graph.num_nodes, 3)
            self.assertEqual(graph.metadata["record_count"], 3)


if __name__ == "__main__":
    unittest.main()
