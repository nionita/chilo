from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import optimize_futility
from test_tune_futility import position_record, write_probe_output


class OptimizerAdapterTest(unittest.TestCase):
    def write_shared_anchor(self, directory: Path) -> None:
        probes = directory / "probes"
        probes.mkdir(parents=True)
        margins = [120, 240, 360]
        reference = position_record(
            "positions.csv", 1, "fen", margins, 1000, move="e2e4", score=30, depth=8,
            all_root_scores=True, root_scores={"e2e4": 30, "d2d4": 0},
        )
        baseline = position_record("positions.csv", 1, "fen", margins, 100, move="e2e4", score=20, depth=6)
        write_probe_output(probes / "reference.jsonl", [reference], margins, 1000, all_root_scores=True)
        write_probe_output(probes / "baseline.jsonl", [baseline], margins, 100)

    def write_config(self, directory: Path, anchor: Path) -> Path:
        probe = directory / "probe"
        inputs = directory / "positions.csv"
        weights = directory / "net.bin"
        for path in (probe, inputs, weights):
            path.write_text("test", encoding="utf-8")
        config = {
            "probe": str(probe),
            "inputs": [str(inputs)],
            "weights": str(weights),
            "candidate_nodes": 100,
            "baseline_margins": [120, 240, 360],
            "score_scale": 600,
            "development": {"reference_dir": str(anchor), "contract": "shared_budget_v1"},
            "optimizer": {
                "depths": [3],
                "seeds": [[120, 240, 360]],
                "steps": [20, 10],
                "max_margin": 1000,
                "max_new_evaluations": 0,
                "validation_top": 1,
            },
        }
        path = directory / "optimizer.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def write_per_root_anchor(self, directory: Path) -> None:
        probes = directory / "probes"
        probes.mkdir(parents=True)
        margins = [120, 240, 360]
        reference = position_record(
            "positions.csv", 1, "fen", margins, 400, move="e2e4", score=30, depth=8,
            all_root_scores=True, root_scores={"e2e4": 30},
        )
        reference.update({
            "reference_mode": "per_root_v1",
            "reference_status": "complete",
            "node_limit_per_root": 400,
            "baseline_node_limit": 100,
            "baseline_completed_depth": 6,
            "target_depth": 8,
            "legal_root_moves": 1,
            "completed_root_moves": 1,
            "baseline_nodes": 100,
            "total_nodes": 500,
        })
        baseline = position_record("positions.csv", 1, "fen", margins, 100, move="e2e4", score=20, depth=6)
        summary = {
            "type": "summary",
            "reference_mode": "per_root_v1",
            "futility_margins": margins,
            "all_root_scores": True,
            "node_limit": 400,
            "node_limit_per_root": 400,
            "baseline_node_limit": 100,
            "reference_depth_gap": 2,
            "positions": 1,
        }
        (probes / "reference.jsonl").write_text(
            json.dumps(reference) + "\n" + json.dumps(summary) + "\n", encoding="utf-8"
        )
        write_probe_output(probes / "baseline.jsonl", [baseline], margins, 100)

    def test_finished_shared_anchor_can_score_existing_f01_without_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor"
            self.write_shared_anchor(anchor)
            config_path = self.write_config(root, anchor)
            settings = optimize_futility.load_settings(config_path, require_validation=False)
            run_dir = root / "run"
            optimize_futility.prepare_run_directory(run_dir, optimize_futility.settings_manifest(settings))
            results = optimize_futility.run_optimize(settings, run_dir)
            self.assertEqual(results["new_evaluations"], 0)
            self.assertTrue(results["stopped_by_budget"])
            self.assertEqual(len(results["ranked"]), 1)
            self.assertTrue(results["ranked"][0]["baseline"])
            self.assertTrue((run_dir / "development" / "report.md").is_file())

    def test_anchor_contract_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor"
            self.write_shared_anchor(anchor)
            config_path = self.write_config(root, anchor)
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            raw["development"]["contract"] = "per_root_v1"
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(optimize_futility.OptimizationError, "per-root"):
                optimize_futility.load_settings(config_path, require_validation=False)

    def test_per_root_anchor_is_scored_through_the_same_adapter_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor"
            self.write_per_root_anchor(anchor)
            config_path = self.write_config(root, anchor)
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            raw["development"]["contract"] = "per_root_v1"
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            settings = optimize_futility.load_settings(config_path, require_validation=False)
            self.assertEqual(settings.development.contract, "per_root_v1")
            self.assertEqual(settings.development.trusted_set["trusted_position_count"], 1)

    def test_validation_promotes_top_nonbaseline_candidates_only(self) -> None:
        development = {
            "schema": optimize_futility.SCHEMA,
            "ranked": [
                {"margins": [120, 240, 360]},
                {"margins": [100, 220, 360]},
                {"margins": [90, 210, 350]},
                {"margins": [80, 200, 340]},
            ],
        }
        promoted = optimize_futility.select_promoted(development, (120, 240, 360), 3)
        self.assertEqual(promoted, [(100, 220, 360), (90, 210, 350), (80, 200, 340)])
        with self.assertRaisesRegex(optimize_futility.OptimizationError, "enough"):
            optimize_futility.select_promoted(development, (120, 240, 360), 4)


if __name__ == "__main__":
    unittest.main()
