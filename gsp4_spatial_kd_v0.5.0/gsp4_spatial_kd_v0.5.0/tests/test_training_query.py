from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import torch

from ugts_spatial.benchmark import BenchmarkConfig, benchmark_student
from ugts_spatial.builders import build_demo_graph
from ugts_spatial.novelty import NoveltyLog
from ugts_spatial.query import QueryConfig, execute_query
from ugts_spatial.schema import NodeType, RelationType
from ugts_spatial.training import TrainConfig, load_model_for_graph, train_model


class TrainingAndQueryTests(unittest.TestCase):
    def test_train_query_commit_and_benchmark(self) -> None:
        torch.set_num_threads(min(4, max(1, torch.get_num_threads())))
        graph = build_demo_graph(seed=17, teacher_dimensions=16)
        source_index = next(
            index
            for index, node_type in enumerate(graph.node_type.tolist())
            if int(node_type) == int(NodeType.SENSOR)
        )
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "student.pt"
            metrics_path = Path(directory) / "metrics.json"
            result = train_model(
                graph,
                model_path,
                metrics_path=metrics_path,
                config=TrainConfig(
                    hidden_dim=32,
                    heads=4,
                    layers=1,
                    epochs=1,
                    max_edges_per_epoch=512,
                    max_encoder_edges=1024,
                    temporal_edges_per_epoch=128,
                    early_stopping_patience=1,
                    device="cpu",
                    precision="float32",
                    seed=17,
                ),
            )
            self.assertTrue(model_path.exists())
            self.assertTrue(metrics_path.exists())
            self.assertEqual(result.final_metrics["epochs_completed"], 1.0)
            model, device, checkpoint = load_model_for_graph(
                graph, model_path, device="cpu"
            )
            self.assertEqual(str(device), "cpu")
            self.assertEqual(checkpoint["schema_hash"], graph.schema_hash)

            novelty_path = Path(directory) / "query.ugnl"
            novelty = NoveltyLog(novelty_path)
            novelty.create()
            query = QueryConfig(
                source_node_id=int(graph.node_id[source_index]),
                relation=int(RelationType.NEAR),
                radius_m=10_000.0,
                epsilon_m=25.0,
                confidence_min=0.0,
                max_events=8,
                timestamp=float(graph.node_time.max()) + 1.0,
            )
            execution = execute_query(
                graph, query, model=model, device=device, novelty_log=novelty
            )
            self.assertGreater(execution.summary["candidates"], 0)
            self.assertGreater(execution.summary["verified"], 0)
            self.assertLessEqual(execution.summary["verified"], 8)
            self.assertEqual(novelty.validate()["records"], execution.summary["verified"])
            for event in execution.events:
                self.assertIn("lineage_hash", event)
                self.assertGreaterEqual(event["confidence"], 0.0)

            benchmark = benchmark_student(
                graph,
                model_path,
                config=BenchmarkConfig(
                    warmup=0,
                    repeats=1,
                    scoring_batch=1024,
                    precision="float32",
                    device="cpu",
                ),
                query_config=query,
            )
            self.assertEqual(benchmark["format"], "UGTS-SPATIAL-BENCHMARK-2")
            self.assertIn("cached_query", benchmark)
            self.assertGreater(benchmark["relation_scoring"]["candidate_scores_per_second_at_p50"], 0.0)


if __name__ == "__main__":
    unittest.main()
