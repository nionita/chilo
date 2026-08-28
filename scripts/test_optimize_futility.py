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
import rescue_futility_mates as rescue
import tune_futility
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

    def write_per_root_anchor_with_rejection(self, directory: Path) -> None:
        probes = directory / "probes"
        probes.mkdir(parents=True)
        margins = [120, 240, 360]
        complete = position_record("positions.csv", 1, "fen-complete", margins, 400, move="e2e4", score=30, depth=8, all_root_scores=True, root_scores={"e2e4": 30})
        complete.update({"reference_mode": "per_root_v1", "reference_status": "complete", "node_limit_per_root": 400, "baseline_node_limit": 100, "baseline_completed_depth": 6, "target_depth": 8, "legal_root_moves": 1, "completed_root_moves": 1, "baseline_nodes": 100, "total_nodes": 500})
        rejected = position_record("positions.csv", 2, "fen-rescue", margins, 400, depth=0, all_root_scores=True)
        rejected.update({"reference_mode": "per_root_v1", "reference_status": "rejected", "node_limit_per_root": 400, "baseline_node_limit": 100, "baseline_completed_depth": 6, "target_depth": 8, "legal_root_moves": 1, "completed_root_moves": 0, "baseline_nodes": 100, "total_nodes": 500, "rejection_reason": "root_node_limit"})
        summary = {"type": "summary", "reference_mode": "per_root_v1", "futility_margins": margins, "all_root_scores": True, "node_limit": 400, "node_limit_per_root": 400, "baseline_node_limit": 100, "reference_depth_gap": 2, "positions": 2}
        (probes / "reference.jsonl").write_text("\n".join(json.dumps(value) for value in (complete, rejected, summary)) + "\n", encoding="utf-8")
        baseline = [
            position_record("positions.csv", 1, "fen-complete", margins, 100, move="e2e4", score=20, depth=6),
            position_record("positions.csv", 2, "fen-rescue", margins, 100, move="d2d4", score=10, depth=6),
        ]
        write_probe_output(probes / "baseline.jsonl", baseline, margins, 100)

    def write_rescue_run(self, root: Path, anchor: Path) -> Path:
        run = root / "rescue-run"
        run.mkdir()
        margins = [120, 240, 360]
        rescue_reference = position_record("positions.csv", 2, "fen-rescue", margins, 400, move="e2e4", score=28990, depth=5, all_root_scores=True, root_scores={"e2e4": 28990})
        rescue_reference.update({"reference_mode": rescue.RESCUE_MODE, "reference_status": "rescued", "node_limit_per_root": 400, "baseline_node_limit": 100, "baseline_completed_depth": 6, "normal_target_depth": 8, "rescue_target_depth": 5, "mate_found_depth": 3, "legal_root_moves": 1, "normal_completed_root_moves": 0, "rescue_completed_root_moves": 1, "baseline_nodes": 100, "total_nodes": 500, "root_score_depths": {"e2e4": 5}, "mate_score": 28990})
        rescue_summary = {"type": "summary", "reference_mode": rescue.RESCUE_MODE, "futility_margins": margins, "all_root_scores": True, "node_limit": 400, "node_limit_per_root": 400, "baseline_node_limit": 100, "reference_depth_gap": 2, "positions": 1}
        rescue_reference_path = run / "rescue_reference.jsonl"
        rescue_reference_path.write_text("\n".join(json.dumps(value) for value in (rescue_reference, rescue_summary)) + "\n", encoding="utf-8")
        rescue_baseline_path = run / "rescue_baseline.jsonl"
        write_probe_output(rescue_baseline_path, [position_record("positions.csv", 2, "fen-rescue", margins, 100, move="d2d4", score=10, depth=6)], margins, 100)
        reference_path = anchor / "probes" / "reference.jsonl"
        baseline_path = anchor / "probes" / "baseline.jsonl"
        reference = tune_futility.parse_probe_output(reference_path, 400, margins, True, True, 100, 2)
        baseline = tune_futility.parse_probe_output(baseline_path, 100, margins)
        ordinary, ordinary_keys = tune_futility.trusted_position_set(reference, baseline, 2)
        rescue_key = tune_futility.record_key(rescue_reference)
        combined_keys = sorted([*ordinary_keys, rescue_key])
        manifest = {"schema": rescue.SCHEMA, "anchor": {"reference": tune_futility.file_identity(reference_path), "baseline": tune_futility.file_identity(baseline_path)}, "candidate_nodes": 100, "reference_nodes_per_root": 400, "reference_depth_gap": 2, "baseline_margins": margins}
        results = {"schema": rescue.SCHEMA, "ordinary_trusted_set": ordinary, "rescued_position_count": 1, "combined_position_count": 2, "rescued_position_keys": [list(rescue_key)], "rescue_reference": tune_futility.file_identity(rescue_reference_path), "rescue_baseline": tune_futility.file_identity(rescue_baseline_path), "candidates": []}
        population = {"schema": rescue.SCHEMA, "ordinary_trusted_set": ordinary, "rescued_position_count": 1, "combined_position_count": 2, "position_keys": [list(key) for key in combined_keys]}
        (run / "rescue_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (run / "rescue_results.json").write_text(json.dumps(results), encoding="utf-8")
        (run / "combined_population.json").write_text(json.dumps(population), encoding="utf-8")
        return run

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

    def test_rescue_population_is_merged_and_fingerprinted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor"
            self.write_per_root_anchor_with_rejection(anchor)
            rescue_run = self.write_rescue_run(root, anchor)
            config_path = self.write_config(root, anchor)
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            raw["development"] = {"reference_dir": str(anchor), "contract": "per_root_v1", "rescue_dir": str(rescue_run)}
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            settings = optimize_futility.load_settings(config_path, require_validation=False)
            context = settings.development
            self.assertEqual(context.trusted_set["trusted_position_count"], 2)
            self.assertEqual(context.trusted_set["rescued_position_count"], 1)
            self.assertIsNotNone(context.rescue)
            rescued = context.reference["positions"][("positions.csv", 2, "fen-rescue")]
            self.assertEqual(rescued["reference_status"], "complete")
            self.assertEqual(context.baseline["positions"][("positions.csv", 2, "fen-rescue")]["bestmove"], "d2d4")
            manifest = optimize_futility.settings_manifest(settings)
            self.assertIn("rescue", manifest["development"])

    def test_rescue_population_rejects_inconsistent_declared_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor"
            self.write_per_root_anchor_with_rejection(anchor)
            rescue_run = self.write_rescue_run(root, anchor)
            population_path = rescue_run / "combined_population.json"
            population = json.loads(population_path.read_text(encoding="utf-8"))
            population["position_keys"] = []
            population_path.write_text(json.dumps(population), encoding="utf-8")
            config_path = self.write_config(root, anchor)
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            raw["development"] = {"reference_dir": str(anchor), "contract": "per_root_v1", "rescue_dir": str(rescue_run)}
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(optimize_futility.OptimizationError, "combined population keys"):
                optimize_futility.load_settings(config_path, require_validation=False)

    def test_rescue_population_rejects_a_different_base_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor"
            self.write_per_root_anchor_with_rejection(anchor)
            rescue_run = self.write_rescue_run(root, anchor)
            manifest_path = rescue_run / "rescue_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["anchor"]["reference"]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            config_path = self.write_config(root, anchor)
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            raw["development"] = {"reference_dir": str(anchor), "contract": "per_root_v1", "rescue_dir": str(rescue_run)}
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(optimize_futility.OptimizationError, "artifact sha256"):
                optimize_futility.load_settings(config_path, require_validation=False)

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
