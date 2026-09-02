from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_futility_matrix_evaluation as matrix


class FutilityMatrixEvaluationTest(unittest.TestCase):
    def test_two_candidates_two_corpora_validate_as_four_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ("bin/probe.exe", "weights/net.bin", "input/a.csv", "input/b.csv"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x\n", encoding="utf-8")
            for corpus in ("a", "b"):
                for relative in (
                    f"anchor/{corpus}/probes/reference.jsonl", f"anchor/{corpus}/probes/baseline.jsonl",
                    f"rescue/{corpus}/rescue_reference.jsonl", f"rescue/{corpus}/rescue_baseline.jsonl",
                    f"rescue/{corpus}/rescue_manifest.json", f"rescue/{corpus}/rescue_results.json",
                    f"rescue/{corpus}/combined_population.json", f"controls/{corpus}/d3.jsonl",
                ):
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("{}\n", encoding="utf-8")
            config = {
                "schema": matrix.SCHEMA,
                "probe": "bin/probe.exe",
                "weights": "weights/net.bin",
                "candidate_nodes": 1,
                "worker_limit": 4,
                "score_scale": 600,
                "baseline_margins": [1, 2, 3],
                "report_every": 1,
                "corpora": [
                    {"id": "a", "input": "input/a.csv", "anchor_dir": "anchor/a", "rescue_dir": "rescue/a"},
                    {"id": "b", "input": "input/b.csv", "anchor_dir": "anchor/b", "rescue_dir": "rescue/b"},
                ],
                "candidates": [{"id": "f21", "margins": [1, 2, 3, 4, 5]}, {"id": "spsa150b", "margins": [0, 1, 2, 3, 4]}],
                "controls": [{"id": "d3-0009", "margins": [0, 1, 2], "outputs": {"a": "controls/a/d3.jsonl", "b": "controls/b/d3.jsonl"}}],
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            settings = matrix.load_config(root, config_path)
            self.assertEqual(len(settings["candidates"]) * len(settings["corpora"]), 4)
            self.assertEqual(settings["controls"][0]["outputs"]["b"], root / "controls/b/d3.jsonl")


if __name__ == "__main__":
    unittest.main()
