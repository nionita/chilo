from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_pareto_selection_evaluation as selection


class ParetoSelectionEvaluationTest(unittest.TestCase):
    @staticmethod
    def frontier() -> dict:
        first = {"id": "candidate-0001", "margins": [4, 62, 175]}
        second = {"id": "candidate-0009", "margins": [0, 25, 139]}
        return {
            "numeric_pareto_frontier": [first, second],
            "selection_shortlist": [first],
        }

    def test_default_uses_mechanical_shortlist(self) -> None:
        self.assertEqual(selection.selected_ids(self.frontier(), []), ["candidate-0001"])

    def test_manual_candidate_must_be_on_numeric_frontier(self) -> None:
        self.assertEqual(selection.selected_ids(self.frontier(), ["candidate-0009"]), ["candidate-0009"])
        with self.assertRaisesRegex(RuntimeError, "not on the final numeric Pareto frontier"):
            selection.selected_ids(self.frontier(), ["candidate-0002"])

    def test_duplicate_manual_candidate_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "duplicate --candidate-id"):
            selection.selected_ids(self.frontier(), ["candidate-0009", "candidate-0009"])

    def test_fresh_package_can_omit_completed_frontier_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "run").mkdir()
            (root / "run" / "pareto_frontier.json").write_text("{}\n", encoding="utf-8")
            (root / "bin").mkdir()
            (root / "bin" / "probe.exe").write_text("probe\n", encoding="utf-8")
            (root / "weights").mkdir()
            (root / "weights" / "net.bin").write_text("weights\n", encoding="utf-8")
            (root / "selection" / "anchor" / "probes").mkdir(parents=True)
            (root / "selection" / "rescue").mkdir(parents=True)
            (root / "selection" / "positions.csv").write_text("fen\n", encoding="utf-8")
            for relative in ("selection/anchor/probes/reference.jsonl", "selection/anchor/probes/baseline.jsonl",
                             "selection/rescue/rescue_reference.jsonl", "selection/rescue/rescue_baseline.jsonl",
                             "selection/rescue/rescue_manifest.json", "selection/rescue/combined_population.json"):
                (root / relative).write_text("{}\n", encoding="utf-8")
            config = {
                "schema": selection.SCHEMA,
                "source_run_dir": "run",
                "probe": "bin/probe.exe",
                "weights": "weights/net.bin",
                "candidate_nodes": 1,
                "baseline_margins": [1, 2, 3],
                "score_scale": 100,
                "report_every": 1,
                "worker_limit": 1,
                "selection": {"id": "sr3", "input": "selection/positions.csv", "anchor_dir": "selection/anchor", "rescue_dir": "selection/rescue"},
                "required_existing_artifacts": {
                    "probe_sha256": selection.file_identity(root / "bin" / "probe.exe")["sha256"],
                    "weights_sha256": selection.file_identity(root / "weights" / "net.bin")["sha256"],
                },
            }
            paths = selection.required_config(root, config)
            self.assertEqual(paths["source_run"], root / "run")


if __name__ == "__main__":
    unittest.main()
