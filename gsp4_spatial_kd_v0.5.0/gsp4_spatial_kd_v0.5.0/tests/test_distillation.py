from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from ugts_spatial.builders import build_demo_graph
from ugts_spatial.distill import (
    embed_graph,
    generate_relation_candidates,
    read_relation_candidates,
    write_relation_candidates,
)
from ugts_spatial.edge_teacher import (
    TeacherEdgeSet,
    export_ultra_triples,
    import_scored_triples,
    teacher_edges_from_labels,
)
from ugts_spatial.embeddings import HashEmbedder
from ugts_spatial.teacher import TeacherLabel, read_teacher_labels, write_teacher_labels


class DistillationTests(unittest.TestCase):
    def test_embedding_candidates_labels_and_ultra_adapter(self) -> None:
        graph = build_demo_graph(seed=19, teacher_dimensions=0)
        embedded = embed_graph(graph, HashEmbedder(dimensions=20))
        self.assertEqual(embedded.teacher_dim, 20)
        self.assertEqual(int(embedded.teacher_mask.sum()), embedded.num_nodes)
        candidates = generate_relation_candidates(
            embedded,
            max_distance_m=3000.0,
            concepts_per_source=2,
            spatial_per_source=2,
            max_candidates=100,
        )
        self.assertGreater(len(candidates), 0)
        candidate = candidates[0]
        self.assertGreater(len(candidate.allowed_relations), 0)
        relation = candidate.allowed_relations[0]
        label = TeacherLabel(
            candidate_id=candidate.candidate_id,
            source_id=candidate.source_id,
            target_id=candidate.target_id,
            relation=relation,
            confidence=0.88,
            abstain=False,
            requires_geometric_verification=True,
            evidence_fields=("source_text", "target_text"),
            rationale="deterministic unit-test label",
            teacher_model="unit-test-teacher",
        )
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            candidate_path = directory / "candidates.jsonl"
            label_path = directory / "labels.jsonl"
            teacher_path = directory / "teacher.ugte"
            write_relation_candidates(candidate_path, candidates)
            self.assertEqual(len(read_relation_candidates(candidate_path)), len(candidates))
            write_teacher_labels(label_path, [label])
            labels = read_teacher_labels(label_path)
            self.assertEqual(labels[0].relation, relation)
            teacher = teacher_edges_from_labels(
                embedded, [asdict(labels[0])], teacher_name="unit-test"
            )
            self.assertEqual(teacher.size, 1)
            teacher.save(teacher_path)
            loaded = TeacherEdgeSet.load(teacher_path, graph=embedded)
            self.assertEqual(loaded.size, 1)

            ultra_dir = directory / "ultra"
            manifest = export_ultra_triples(embedded, ultra_dir)
            self.assertGreater(sum(manifest["triples"].values()), 0)
            score_path = directory / "scores.tsv"
            score_path.write_text(
                f"{candidate.source_id}\t{relation}\t{candidate.target_id}\t0.91\t0.75\n",
                encoding="utf-8",
            )
            imported = import_scored_triples(embedded, score_path)
            self.assertEqual(imported.size, 1)
            self.assertAlmostEqual(float(imported.probability[0]), 0.91, places=5)


if __name__ == "__main__":
    unittest.main()
