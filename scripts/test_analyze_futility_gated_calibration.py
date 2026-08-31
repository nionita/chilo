from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import analyze_futility_gated_calibration as calibration
import tune_futility
from test_optimize_futility import OptimizerAdapterTest
from test_tune_futility import position_record, write_probe_output


class GatedCalibrationTest(unittest.TestCase):
    @staticmethod
    def add_second_reference_move(anchor: Path) -> None:
        path = anchor / "probes" / "reference.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["root_scores"] = {"e2e4": 30, "d2d4": 0}
        rows[0]["legal_root_moves"] = 2
        rows[0]["completed_root_moves"] = 2
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    def write_run(self, root: Path, anchor: Path, version: str = "v1") -> Path:
        run = root / "historical"
        probes = run / "tracks" / "both" / "probes"
        probes.mkdir(parents=True)
        margins = [120, 240, 360]
        current = position_record("positions.csv", 1, "fen", margins, 100, move="d2d4", score=0, depth=6)
        proposal = position_record("positions.csv", 1, "fen", margins, 100, move="e2e4", score=30, depth=6)
        current_path = probes / "attempt-0000-current.jsonl"
        proposal_path = probes / "attempt-0000-proposal.jsonl"
        write_probe_output(current_path, [current], margins, 100)
        write_probe_output(proposal_path, [proposal], margins, 100)
        manifest = {
            "schema": f"chilo.futility_gated_hillclimb.{version}",
            "candidate_nodes": 100,
            "baseline_margins": margins,
            "score_scale": 600,
        }
        state = {
            "schema": f"chilo.futility_gated_hillclimb_state.{version}",
            "tracks": {"both": {"current_margins": margins, "completed_attempts": [{
                "attempt": 0,
                "current_margins": margins,
                "proposal_margins": margins,
                "accepted": True,
                "decision": "accepted",
                "current": {"output": tune_futility.file_identity(current_path)},
                "proposal": {"output": tune_futility.file_identity(proposal_path)},
            }]}},
        }
        (run / "optimizer_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
        return run

    def test_reads_raw_paired_v1_probes_and_mapped_full_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor"
            OptimizerAdapterTest().write_per_root_anchor(anchor)
            self.add_second_reference_move(anchor)
            run = self.write_run(root, anchor)
            endpoint = run / "tracks" / "both" / "probes" / "attempt-0000-proposal.jsonl"
            config = {
                "attempt_runs": [{"id": "v1", "run_dir": str(run), "anchor": {"reference_dir": str(anchor), "contract": "per_root_v1"}}],
                "full_evaluations": [{
                    "id": "v1-endpoint", "attempt_run": "v1", "track": "both", "margins": [120, 240, 360],
                    "populations": [{
                        "id": "development", "candidate_nodes": 100, "baseline_margins": [120, 240, 360], "score_scale": 600,
                        "anchor": {"reference_dir": str(anchor), "contract": "per_root_v1"}, "output": str(endpoint),
                    }],
                }],
            }
            config_path = root / "calibration.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = calibration.run(config_path, root / "report")
            self.assertEqual(result["paired_delta_summary"]["mean_normalized_regret"]["count"], 1)
            self.assertLess(result["attempts"][0]["deltas"]["mean_normalized_regret"], 0)
            self.assertLess(result["attempts"][0]["deltas"]["mean_squared_regret"], 0)
            self.assertTrue((root / "report" / "report.md").is_file())

    def test_rejects_missing_retained_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor"
            OptimizerAdapterTest().write_per_root_anchor(anchor)
            self.add_second_reference_move(anchor)
            run = self.write_run(root, anchor)
            missing = run / "tracks" / "both" / "probes" / "attempt-0000-current.jsonl"
            missing.unlink()
            config = {"attempt_runs": [{"id": "v1", "run_dir": str(run), "anchor": {"reference_dir": str(anchor), "contract": "per_root_v1"}}], "full_evaluations": [{"id": "endpoint", "attempt_run": "v1", "track": "both", "margins": [120, 240, 360], "populations": [{"id": "development", "candidate_nodes": 100, "baseline_margins": [120, 240, 360], "score_scale": 600, "anchor": {"reference_dir": str(anchor), "contract": "per_root_v1"}, "output": str(run / "tracks" / "both" / "probes" / "attempt-0000-proposal.jsonl")}]}]}
            config_path = root / "calibration.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(calibration.optimize_futility.OptimizationError, "missing retained probe"):
                calibration.run(config_path, root / "report")

    def test_reads_corrected_v2_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor"
            OptimizerAdapterTest().write_per_root_anchor(anchor)
            self.add_second_reference_move(anchor)
            run = self.write_run(root, anchor, "v2")
            endpoint = run / "tracks" / "both" / "probes" / "attempt-0000-proposal.jsonl"
            config = {"attempt_runs": [{"id": "v2", "run_dir": str(run), "anchor": {"reference_dir": str(anchor), "contract": "per_root_v1"}}], "full_evaluations": [{"id": "endpoint", "attempt_run": "v2", "track": "both", "margins": [120, 240, 360], "populations": [{"id": "development", "candidate_nodes": 100, "baseline_margins": [120, 240, 360], "score_scale": 600, "anchor": {"reference_dir": str(anchor), "contract": "per_root_v1"}, "output": str(endpoint)}]}]}
            config_path = root / "calibration.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            self.assertEqual(calibration.run(config_path, root / "report")["attempt_runs"][0]["state_schema"], "chilo.futility_gated_hillclimb_state.v2")


if __name__ == "__main__":
    unittest.main()
