from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _bootstrap import ROOT
from ugts5.canonical import load_json
from ugts5.packing import PackedNode32, PackedNodeFields
from ugts5.stream import StreamError, read_stream, write_stream


class StreamTests(unittest.TestCase):
    def setUp(self):
        atlas = load_json(ROOT / "spec" / "operator_atlas.json")
        codebook = load_json(ROOT / "spec" / "hot_codebook_set_core_16.json")
        self.header = {
            "schema_id": "ugts.packed-set-field-node-stream@5.0.0",
            "codebook_id": codebook["codebook_id"],
            "codebook_hash": codebook["codebook_hash"],
            "atlas_hash": atlas["atlas_hash"],
            "chart": {"rho_origin": -5.0, "theta_origin_code": 0, "theta_bins": 256, "wrap_profile": "reflective-klein-converse-v1"},
            "quantization": {"delta_rho_scale": 0.03125, "theta_bin_degrees": 1.40625},
            "error_contract": {"event_margin_rule": "numeric_error <= event_margin"},
        }
        self.words = [
            PackedNode32.pack(PackedNodeFields(0, 0, -3, 4, 5)),
            PackedNode32.pack(PackedNodeFields(3, 1, 6, 7, 8, 1, False)),
        ]

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.ug5n"
            write_stream(path, self.header, self.words)
            header, words = read_stream(path)
            self.assertEqual(header, self.header)
            self.assertEqual(words, self.words)

    def test_bad_crc_rejects(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.ug5n"
            write_stream(path, self.header, self.words)
            data = bytearray(path.read_bytes())
            data[-1] ^= 1
            path.write_bytes(data)
            with self.assertRaises(StreamError):
                read_stream(path)

    def test_invalid_node_rejects_on_write(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.ug5n"
            with self.assertRaises(StreamError):
                write_stream(path, self.header, [self.words[0] ^ 1])

    def test_bad_magic_rejects_even_with_recomputed_crc(self):
        import zlib, struct
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.ug5n"
            write_stream(path, self.header, self.words)
            data = bytearray(path.read_bytes())
            data[0:4] = b"BAD!"
            body = bytes(data[:-4])
            data[-4:] = struct.pack("<I", zlib.crc32(body) & 0xffffffff)
            path.write_bytes(data)
            with self.assertRaises(StreamError):
                read_stream(path)

    def test_sample_stream_exists_after_demo_generation(self):
        # The release build runs the demo before packaging.
        self.assertTrue((ROOT / "examples" / "sample_nodes.ug5n").exists())


if __name__ == "__main__":
    unittest.main()
