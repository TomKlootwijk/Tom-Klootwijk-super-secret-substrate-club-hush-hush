from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from ugts_spatial.builders import build_geonames_graph
from ugts_spatial.ingest_osm import ingest_osm
from ugts_spatial.schema import NodeType, RelationType


def geonames_row(
    geoname_id: int,
    name: str,
    latitude: float,
    longitude: float,
    population: int,
) -> str:
    columns = [
        str(geoname_id), name, name, name, str(latitude), str(longitude),
        "P", "PPL", "NL", "", "16", "", "", "", str(population),
        "2", "2", "Europe/Amsterdam", "2026-01-01",
    ]
    return "\t".join(columns)


class IngestionTests(unittest.TestCase):
    def test_geonames_plus_variable_observations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "NL.txt"
            source.write_text(
                "\n".join(
                    [
                        geonames_row(1001, "Lelystad Test", 52.51, 5.47, 80000),
                        geonames_row(1002, "Almere Test", 52.37, 5.22, 220000),
                        geonames_row(1003, "Outside", 51.0, 4.0, 500000),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            observations = directory / "observations.csv"
            with open(observations, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "sensor_id", "latitude", "longitude", "property", "timestamp",
                        "value", "uncertainty", "unit", "affected_geoname_id",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "sensor_id": "sensor-a", "latitude": 52.51, "longitude": 5.47,
                        "property": "water level", "timestamp": "2026-01-01T00:00:00Z",
                        "value": 1.2, "uncertainty": 0.05, "unit": "m",
                        "affected_geoname_id": 1001,
                    }
                )
                writer.writerow(
                    {
                        "sensor_id": "sensor-a", "latitude": 52.51, "longitude": 5.47,
                        "property": "water level", "timestamp": "2026-01-01T00:15:00Z",
                        "value": 1.3, "uncertainty": 0.04, "unit": "m",
                        "affected_geoname_id": 1001,
                    }
                )
            graph = build_geonames_graph(
                source,
                observations_csv=observations,
                bbox=(52.0, 5.0, 53.0, 6.0),
                max_rows=10,
                teacher_dimensions=8,
            )
            counts = graph.summary()["node_counts"]
            self.assertEqual(counts["spatial_entity"], 2)
            self.assertEqual(counts["sensor"], 1)
            self.assertEqual(counts["observation"], 2)
            self.assertIn(int(RelationType.SUPERSEDES), set(graph.edge_type.tolist()))

    def test_small_osm_xml_adapter(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
<osm version='0.6'>
  <node id='1' lat='52.51' lon='5.47'><tag k='amenity' v='school'/><tag k='name' v='Test School'/></node>
  <node id='2' lat='52.5105' lon='5.471'/><node id='3' lat='52.511' lon='5.472'/>
  <way id='10'><nd ref='2'/><nd ref='3'/><tag k='highway' v='residential'/><tag k='name' v='Test Road'/></way>
</osm>
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tiny.osm"
            path.write_text(xml, encoding="utf-8")
            graph = ingest_osm(path, limit=20, morton_resolution=13, near_per_node=1)
            self.assertGreaterEqual(graph.summary()["node_counts"]["spatial_entity"], 2)
            self.assertIn(int(RelationType.INSTANCE_OF), set(graph.edge_type.tolist()))
            self.assertIn(int(NodeType.SPATIAL_CELL), set(graph.node_type.tolist()))


if __name__ == "__main__":
    unittest.main()
