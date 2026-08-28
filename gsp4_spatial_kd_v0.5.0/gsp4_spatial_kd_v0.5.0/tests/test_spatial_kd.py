from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from ugts_spatial.builders import build_demo_graph, build_geonames_graph
from ugts_spatial.deployment import build_deployment, validate_deployment
from ugts_spatial.distill import embed_graph
from ugts_spatial.edge_teacher import (
    TeacherEdgeSet,
    export_ultra_triples,
    import_scored_triples,
)
from ugts_spatial.embeddings import HashEmbedder
from ugts_spatial.graph import GraphPackage
from ugts_spatial.novelty import NoveltyLog, NoveltyRecord
from ugts_spatial.query import QueryConfig, execute_query
from ugts_spatial.schema import NodeType, NoveltyOp, RelationType
from ugts_spatial.training import TrainConfig, load_model_for_graph, train_model
from ugts_spatial.ugts_bridge import export_ugts_candidates


class SpatialKDTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="ugts-spatial-tests-")
        cls.root = Path(cls.temp.name)
        cls.graph = build_demo_graph(seed=20260710, teacher_dimensions=16)
        cls.graph_path = cls.root / "demo.ugkg"
        cls.graph.save(cls.graph_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_01_variable_length_graph_and_roundtrip(self) -> None:
        observation_counts: Counter[int] = Counter()
        for position in range(self.graph.num_edges):
            if int(self.graph.edge_type[position]) == int(RelationType.MADE_BY_SENSOR):
                target = int(self.graph.edge_index[1, position])
                observation_counts[target] += 1
        self.assertGreaterEqual(len(set(observation_counts.values())), 3)
        self.assertGreater(self.graph.num_edges, self.graph.num_nodes)
        loaded = GraphPackage.load(self.graph_path)
        self.assertEqual(loaded.schema_hash, self.graph.schema_hash)
        np.testing.assert_array_equal(loaded.node_id, self.graph.node_id)
        np.testing.assert_array_equal(loaded.edge_index, self.graph.edge_index)
        self.assertEqual(loaded.metadata["dataset"], "synthetic-flevoland-variable-event-pilot")

    def test_02_hash_linked_novelty(self) -> None:
        path = self.root / "test.ugnl"
        log = NoveltyLog(path, seed=1234)
        log.create(overwrite=True)
        first = log.append(
            NoveltyRecord(
                sequence=0,
                timestamp=1.0,
                op=int(NoveltyOp.OBSERVATION),
                relation=int(RelationType.OBSERVES),
                flags=0,
                source=10,
                target=20,
                value=1.5,
                confidence=0.9,
                lineage_hash=99,
            )
        )
        second = log.append_verified(
            timestamp=2.0,
            relation=int(RelationType.NEAR),
            source_id=10,
            target_id=30,
            value=25.0,
            confidence=0.8,
            lineage_hash=101,
        )
        self.assertEqual(second.prev_hash, first.self_hash)
        self.assertEqual(log.validate()["records"], 2)
        corrupt = self.root / "corrupt.ugnl"
        payload = bytearray(path.read_bytes())
        payload[-8] ^= 0x01
        corrupt.write_bytes(payload)
        with self.assertRaises(ValueError):
            NoveltyLog(corrupt).validate()

    def test_03_hash_teacher_cache(self) -> None:
        embedded = embed_graph(self.graph, HashEmbedder(dimensions=24))
        self.assertEqual(embedded.teacher_dim, 24)
        self.assertEqual(int(embedded.teacher_mask.sum()), embedded.num_nodes)
        norms = np.linalg.norm(embedded.teacher_x, axis=1)
        self.assertTrue(np.allclose(norms[norms > 0], 1.0, atol=1e-5))

    def test_04_train_load_and_query(self) -> None:
        checkpoint = self.root / "student.pt"
        metrics = self.root / "student.metrics.json"
        result = train_model(
            self.graph,
            checkpoint,
            metrics_path=metrics,
            config=TrainConfig(
                hidden_dim=16,
                heads=4,
                layers=1,
                epochs=1,
                max_edges_per_epoch=700,
                max_encoder_edges=1200,
                temporal_edges_per_epoch=96,
                early_stopping_patience=1,
                device="cpu",
                precision="float32",
            ),
        )
        self.assertTrue(checkpoint.exists())
        self.assertEqual(result.final_metrics["epochs_completed"], 1.0)
        model, device, checkpoint_payload = load_model_for_graph(
            self.graph, checkpoint, device="cpu"
        )
        self.assertEqual(str(device), "cpu")
        self.assertEqual(checkpoint_payload["schema_hash"], self.graph.schema_hash)
        source = next(
            i for i, value in enumerate(self.graph.node_type)
            if int(value) == int(NodeType.SENSOR)
        )
        execution = execute_query(
            self.graph,
            QueryConfig(
                source_node_id=int(self.graph.node_id[source]),
                relation=int(RelationType.NEAR),
                radius_m=10_000.0,
                epsilon_m=25.0,
                confidence_min=0.0,
                max_events=16,
                timestamp=float(self.graph.node_time.max()) + 1.0,
            ),
            model=model,
            device=device,
        )
        self.assertGreater(execution.summary["candidates"], 0)
        self.assertGreater(execution.summary["verified"], 0)
        self.assertLessEqual(len(execution.events), 16)

    def test_05_ultra_teacher_adapter(self) -> None:
        directory = self.root / "ultra"
        manifest = export_ultra_triples(self.graph, directory)
        self.assertEqual(sum(manifest["triples"].values()), self.graph.num_edges)
        lines = (directory / "train.txt").read_text(encoding="utf-8").splitlines()[:12]
        scores = self.root / "scores.tsv"
        scores.write_text(
            "".join(f"{line}\t0.90\t1.0\n" for line in lines),
            encoding="utf-8",
        )
        teacher = import_scored_triples(self.graph, scores, teacher_name="test")
        teacher_path = self.root / "teacher.ugte"
        teacher.save(teacher_path)
        loaded = TeacherEdgeSet.load(teacher_path, graph=self.graph)
        self.assertEqual(loaded.size, len(lines))
        self.assertTrue(np.allclose(loaded.probability, 0.9))

    def test_06_g64_g32_bridge_precision_contract(self) -> None:
        source = next(
            i for i, value in enumerate(self.graph.node_type)
            if int(value) == int(NodeType.SENSOR)
        )
        prefix = self.root / "bridge"
        result = export_ugts_candidates(
            self.graph,
            prefix,
            latitude=float(self.graph.latitude[source]),
            longitude=float(self.graph.longitude[source]),
            origin_elevation_m=float(self.graph.elevation[source]),
            source_index=source,
            radius_m=10_000.0,
            guard_epsilon_m=25.0,
            mode_bit=int(RelationType.NEAR),
            maximum_candidates=1000,
        )
        count = int(result["candidate_count"])
        self.assertEqual(result["g64_bytes"], count * 64)
        self.assertEqual(result["g32_bytes"], count * 32)
        self.assertTrue(result["g32_precision_within_guard"])
        self.assertLessEqual(result["g32_max_position_error_m"], 25.0)

    def test_07_deployment_bundle(self) -> None:
        # Reuse the trained model from test_04, or create it if test ordering changes.
        checkpoint = self.root / "student.pt"
        if not checkpoint.exists():
            train_model(
                self.graph,
                checkpoint,
                config=TrainConfig(
                    hidden_dim=16, heads=4, layers=1, epochs=1,
                    max_edges_per_epoch=400, max_encoder_edges=800,
                    temporal_edges_per_epoch=64, device="cpu",
                ),
            )
        novelty_path = self.root / "deploy.ugnl"
        novelty = NoveltyLog(novelty_path)
        novelty.create(overwrite=True)
        novelty.append_verified(
            timestamp=3.0,
            relation=int(RelationType.NEAR),
            source_id=1,
            target_id=2,
            value=3.0,
            confidence=0.7,
            lineage_hash=4,
        )
        bundle = self.root / "demo.ugdeploy"
        build_deployment(
            bundle,
            self.graph_path,
            model_path=checkpoint,
            novelty_path=novelty_path,
        )
        validation = validate_deployment(bundle)
        self.assertTrue(validation["valid"])
        self.assertTrue(validation["model_valid"])
        self.assertEqual(validation["novelty"]["records"], 1)

    def test_08_geonames_plus_irregular_observations(self) -> None:
        geonames = self.root / "NL-test.txt"
        rows = [
            ["1", "Lelystad", "Lelystad", "", "52.5185", "5.4714", "P", "PPLA", "NL", "", "16", "", "", "", "81000", "3", "3", "Europe/Amsterdam", "2026-01-01"],
            ["2", "Almere", "Almere", "", "52.3508", "5.2647", "P", "PPLA2", "NL", "", "16", "", "", "", "220000", "-3", "-3", "Europe/Amsterdam", "2026-01-01"],
            ["3", "Dronten", "Dronten", "", "52.5250", "5.7181", "P", "PPL", "NL", "", "16", "", "", "", "41000", "1", "1", "Europe/Amsterdam", "2026-01-01"],
        ]
        geonames.write_text("\n".join("\t".join(row) for row in rows) + "\n", encoding="utf-8")
        observations = self.root / "observations.csv"
        observations.write_text(
            "sensor_id,latitude,longitude,property,timestamp,value,uncertainty,unit,affected_geoname_id\n"
            "s1,52.51,5.47,traffic flow,2026-01-01T00:00:00Z,1.0,0.05,index,1\n"
            "s1,52.51,5.47,traffic flow,2026-01-01T00:15:00Z,1.2,0.04,index,1\n"
            "s2,52.35,5.26,air temperature,2026-01-01T00:07:00Z,4.5,0.10,C,2\n",
            encoding="utf-8",
        )
        graph = build_geonames_graph(
            geonames,
            observations_csv=observations,
            country_code="NL",
            max_rows=10,
            teacher_dimensions=8,
        )
        counts = Counter(int(value) for value in graph.node_type)
        self.assertEqual(counts[int(NodeType.SPATIAL_ENTITY)], 3)
        self.assertEqual(counts[int(NodeType.SENSOR)], 2)
        self.assertEqual(counts[int(NodeType.OBSERVATION)], 3)
        self.assertGreater(graph.num_edges, 0)


if __name__ == "__main__":
    unittest.main()
