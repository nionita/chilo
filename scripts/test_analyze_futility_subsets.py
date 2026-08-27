from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import analyze_futility_subsets
from test_optimize_futility import OptimizerAdapterTest
from test_tune_futility import position_record, write_probe_output


class SubsetAnalysisTest(unittest.TestCase):
    def test_reuses_existing_outputs_without_a_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor"
            OptimizerAdapterTest().write_per_root_anchor(anchor)
            candidate = root / "candidate.jsonl"
            margins = [40, 160, 280]
            record = position_record("positions.csv", 1, "fen", margins, 100, move="e2e4", score=20, depth=6)
            write_probe_output(candidate, [record], margins, 100)
            config = {"candidate_nodes": 100, "baseline_margins": [120, 240, 360], "development": {"reference_dir": str(anchor), "contract": "per_root_v1"}, "variants": [{"id": "f01", "margins": [120, 240, 360], "output": str(anchor / "probes" / "baseline.jsonl")}, {"id": "other", "margins": margins, "output": str(candidate)}], "sampling": {"seed": 7, "fractions": [1.0], "replicates": 2}}
            config_path = root / "subsets.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = analyze_futility_subsets.run(config_path, root / "out")
            self.assertEqual(len(result["samples"]), 2)
            self.assertTrue((root / "out" / "report.md").is_file())


if __name__ == "__main__":
    unittest.main()
