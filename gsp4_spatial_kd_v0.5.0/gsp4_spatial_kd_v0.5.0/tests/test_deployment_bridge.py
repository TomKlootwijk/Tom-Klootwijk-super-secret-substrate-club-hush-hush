from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import torch

from ugts_spatial.builders import build_demo_graph
from ugts_spatial.deployment import build_deployment, validate_deployment
from ugts_spatial.model import ModelConfig, UGTSSpatialModel
from ugts_spatial.novelty import NoveltyLog
from ugts_spatial.schema import NodeType, RelationType
from ugts_spatial.ugts_bridge import export_ugts_candidates


class DeploymentAndBridgeTests(unittest.TestCase):
    def test_deployment_hashes_and_g64_g32_bridge(self) -> None:
        graph = build_demo_graph(seed=23, teacher_dimensions=8)
        source_index = next(
            index
            for index, value in enumerate(graph.node_type.tolist())
            if int(value) == int(NodeType.SENSOR)
        )
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            graph_path = directory / "graph.ugkg"
            model_path = directory / "model.pt"
            novelty_path = directory / "novelty.ugnl"
            bundle_path = directory / "bundle.ugdeploy"
            graph.save(graph_path)
            model = UGTSSpatialModel(
                ModelConfig(
                    input_dim=graph.input_dim,
                    teacher_dim=graph.teacher_dim,
                    edge_dim=graph.edge_dim,
                    hidden_dim=32,
                    num_heads=4,
                    num_layers=1,
                )
            )
            torch.save(model.checkpoint(schema_hash=graph.schema_hash), model_path)
            novelty = NoveltyLog(novelty_path)
            novelty.create()
            novelty.append_verified(
                timestamp=1.0,
                relation=int(RelationType.CROSSED_GUARD),
                source_id=int(graph.node_id[source_index]),
                target_id=int(graph.node_id[source_index]),
                value=0.0,
                confidence=1.0,
                lineage_hash=123,
            )
            summary = build_deployment(
                bundle_path,
                graph_path,
                model_path=model_path,
                novelty_path=novelty_path,
            )
            self.assertGreater(summary.bytes, 0)
            validation = validate_deployment(bundle_path)
            self.assertTrue(validation["valid"])
            self.assertTrue(validation["model_valid"])

            bridge = export_ugts_candidates(
                graph,
                directory / "candidate_stream",
                latitude=float(graph.latitude[source_index]),
                longitude=float(graph.longitude[source_index]),
                origin_elevation_m=float(graph.elevation[source_index]),
                radius_m=5000.0,
                guard_epsilon_m=50.0,
                mode_bit=int(RelationType.NEAR),
                maximum_candidates=256,
                source_index=source_index,
            )
            self.assertEqual(bridge["g64_bytes"], bridge["candidate_count"] * 64)
            self.assertEqual(bridge["g32_bytes"], bridge["candidate_count"] * 32)
            self.assertTrue(bridge["g32_precision_within_guard"])


if __name__ == "__main__":
    unittest.main()
