# Allow direct execution from an extracted source tree without installation.
import sys
from pathlib import Path
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CatalogIntegrityTests(unittest.TestCase):
    def test_catalog_count_and_ids(self):
        with (ROOT / 'catalog/mechanisms_360.csv').open(encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 360)
        self.assertEqual([r['id'] for r in rows], [f'M{i:03d}' for i in range(1, 361)])

    def test_layer_counts(self):
        summary = json.loads((ROOT / 'catalog/catalog_summary.json').read_text())
        self.assertEqual(summary['base_mechanisms'], 197)
        self.assertEqual(summary['kc2_mechanisms'], 60)
        self.assertEqual(summary['kc3_new_mechanisms'], 103)

    def test_v3_count(self):
        with (ROOT / 'catalog/mechanisms_v3_new.csv').open(encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 103)
        self.assertEqual(rows[0]['id'], 'M258')
        self.assertEqual(rows[-1]['id'], 'M360')

    def test_catalog_json_matches(self):
        with (ROOT / 'catalog/mechanisms_360.csv').open(encoding='utf-8') as f:
            csv_rows = list(csv.DictReader(f))
        json_rows = json.loads((ROOT / 'catalog/mechanisms_360.json').read_text())
        self.assertEqual(csv_rows, json_rows)


if __name__ == '__main__':
    unittest.main()
