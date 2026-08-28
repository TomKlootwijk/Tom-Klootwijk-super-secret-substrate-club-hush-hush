from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from ugts_spatial.builders import build_demo_graph
from ugts_spatial.graph import GraphPackage
from ugts_spatial.schema import NodeType, RelationType


class GraphPackageTests(unittest.TestCase):
    def test_demo_is_sparse_variable_length_and_roundtrips(self) -> None:
        graph = build_demo_graph(seed=7, teacher_dimensions=24)
        self.assertEqual(graph.FORMAT, "UGKG2")
        self.assertGreater(graph.num_nodes, 300)
        self.assertGreater(graph.num_edges, graph.num_nodes)
        self.assertEqual(graph.teacher_dim, 24)
        self.assertEqual(graph.edge_dim, 4)
        self.assertTrue(np.any(graph.edge_attr[:, 0] > 0.0))
        node_counts = graph.summary()["node_counts"]
        self.assertGreater(node_counts["observation"], node_counts["sensor"])
        self.assertGreater(node_counts["event"], 0)
        self.assertTrue(np.all(graph.compatibility_mask != 0))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.ugkg"
            graph.save(path)
            loaded = GraphPackage.load(path)
            self.assertEqual(loaded.schema_hash, graph.schema_hash)
            np.testing.assert_array_equal(loaded.node_id, graph.node_id)
            np.testing.assert_allclose(loaded.edge_attr, graph.edge_attr)
            self.assertEqual(loaded.keys, graph.keys)
            self.assertEqual(loaded.texts, graph.texts)

    def test_subgraph_preserves_valid_edges(self) -> None:
        graph = build_demo_graph(seed=11, teacher_dimensions=8)
        indices = np.arange(64, dtype=np.int64)
        subgraph = graph.subgraph(indices)
        self.assertEqual(subgraph.num_nodes, 64)
        self.assertTrue(np.all(subgraph.edge_index >= 0))
        self.assertTrue(np.all(subgraph.edge_index < 64))
        self.assertEqual(subgraph.metadata["parent_schema_hash"], graph.schema_hash)

    def test_type_and_relation_vocabulary_present(self) -> None:
        graph = build_demo_graph(seed=13, teacher_dimensions=0)
        self.assertIn(int(NodeType.SENSOR), set(graph.node_type.tolist()))
        self.assertIn(int(RelationType.NEAR), set(graph.edge_type.tolist()))
        self.assertIn(int(RelationType.DESCENDS_FROM), set(graph.edge_type.tolist()))


if __name__ == "__main__":
    unittest.main()
