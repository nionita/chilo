from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import optimize_futility_gated as gated
from test_optimize_futility import OptimizerAdapterTest


class GatedHillClimbTest(unittest.TestCase):
    def write_config(self, root: Path, anchor: Path, max_attempts: int = 3, stalled: int = 2) -> Path:
        probe, inputs, weights = root / "probe", root / "positions.csv", root / "net.bin"
        probe.write_text("test", encoding="utf-8")
        inputs.write_text("header\nfen\n", encoding="utf-8")
        weights.write_text("test", encoding="utf-8")
        config = {
            "probe": str(probe),
            "inputs": [str(inputs)],
            "weights": str(weights),
            "candidate_nodes": 100,
            "baseline_margins": [120, 240, 360],
            "development": {"reference_dir": str(anchor), "contract": "per_root_v1"},
            "gated_hillclimb": {
                "tracks": [{
                    "id": "trial",
                    "margins": [120, 240, 360],
                    "gate": {
                        "mode": "both",
                        "max_squared_positive_excess": 1.0,
                        "max_cvar1_excess": 1.0,
                        "min_mean_improvement": 0.001,
                        "max_stalled_attempts": stalled,
                    },
                }],
                "max_attempts": max_attempts,
                "workers": 2,
                "subset_fraction": 1.0,
                "seed": 7,
                "perturbation_c": 40,
                "perturbation_gamma": 0.101,
                "max_margin": 1000,
            },
        }
        path = root / "gated.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def write_anchor(self, root: Path) -> Path:
        helper = OptimizerAdapterTest()
        anchor = root / "anchor"
        helper.write_per_root_anchor(anchor)
        reference_path = anchor / "probes" / "reference.jsonl"
        rows = [json.loads(line) for line in reference_path.read_text(encoding="utf-8").splitlines()]
        rows[0]["root_scores"] = {"e2e4": 30, "d2d4": 0}
        rows[0]["legal_root_moves"] = 2
        rows[0]["completed_root_moves"] = 2
        reference_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return anchor

    @staticmethod
    def risk(downside: float, cvar1: float) -> dict:
        return {"excess_vs_control": {"mean_squared_positive": downside, "tail_mean": {"top_0.01": cvar1}}}

    def test_gate_modes_enforce_only_their_selected_limits(self) -> None:
        downside = gated.Gate("downside", 0.1, 0.1, 0.0, 1)
        cvar1 = gated.Gate("cvar1", 0.1, 0.1, 0.0, 1)
        both = gated.Gate("both", 0.1, 0.1, 0.0, 1)
        metrics = self.risk(0.2, 0.05)
        self.assertFalse(gated.evaluate_gate(metrics, downside)["passed"])
        self.assertTrue(gated.evaluate_gate(metrics, cvar1)["passed"])
        self.assertFalse(gated.evaluate_gate(metrics, both)["passed"])

    def test_proposal_is_deterministic_and_changes_tuple(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = gated.load_settings(self.write_config(root, self.write_anchor(root)))
            first = gated.make_proposal((120, 240, 360), settings, "trial", 0)
            second = gated.make_proposal((120, 240, 360), settings, "trial", 0)
            self.assertEqual(first, second)
            self.assertNotEqual(first[0], (120, 240, 360))

    def test_acceptance_resets_stall_then_later_failure_stops_track(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = gated.load_settings(self.write_config(root, self.write_anchor(root), max_attempts=3, stalled=1))
            run_dir = root / "run"
            gated.prepare(run_dir, gated.manifest(settings))
            key = ("positions.csv", 1, "fen")

            def fake_probe(_settings, _run_dir, _track, attempt, role, _margins, _masked):
                move = "d2d4" if attempt == 0 and role == "current" else "e2e4"
                return {"positions": {key: {
                    "bestmove": move,
                    "score": 0 if move == "d2d4" else 30,
                    "completed_depth": 6,
                    "nodes": 100,
                    "iteration_interrupted": True,
                }}, "summary": {}}

            with patch.object(gated, "probe_one", side_effect=fake_probe), patch.object(
                gated, "record_output", return_value={"path": "synthetic", "sha256": "0", "size": 0}
            ):
                result = gated.run(settings, run_dir)
            finalist = result["finalists"][0]
            self.assertEqual(finalist["status"], "stalled")
            self.assertEqual(finalist["accepted_improvements"], 1)
            self.assertEqual(finalist["attempted_count"], 2)

    def test_missing_per_track_gate_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write_config(root, self.write_anchor(root))
            raw = json.loads(path.read_text(encoding="utf-8"))
            del raw["gated_hillclimb"]["tracks"][0]["gate"]["max_cvar1_excess"]
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(gated.optimize_futility.OptimizationError, "missing required"):
                gated.load_settings(path)

    def test_initial_gate_failure_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write_config(root, self.write_anchor(root))
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["gated_hillclimb"]["tracks"][0]["gate"]["max_squared_positive_excess"] = 0.0
            raw["gated_hillclimb"]["tracks"][0]["gate"]["max_cvar1_excess"] = 0.0
            path.write_text(json.dumps(raw), encoding="utf-8")
            settings = gated.load_settings(path)
            run_dir = root / "run"
            gated.prepare(run_dir, gated.manifest(settings))
            key = ("positions.csv", 1, "fen")

            def fake_probe(_settings, _run_dir, _track, _attempt, _role, _margins, _masked):
                return {"positions": {key: {"bestmove": "d2d4", "score": 0, "completed_depth": 6, "nodes": 100, "iteration_interrupted": True}}, "summary": {}}

            with patch.object(gated, "probe_one", side_effect=fake_probe), patch.object(
                gated, "record_output", return_value={"path": "synthetic", "sha256": "0", "size": 0}
            ):
                result = gated.run(settings, run_dir)
            finalist = result["finalists"][0]
            self.assertEqual(finalist["status"], "initial_gate_failed")
            self.assertEqual(finalist["attempted_count"], 1)


if __name__ == "__main__":
    unittest.main()
