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

import optimize_futility_gated as pareto
from test_optimize_futility import OptimizerAdapterTest


class ParetoSearchTest(unittest.TestCase):
    def write_anchor(self, root: Path) -> Path:
        anchor = root / "anchor"
        OptimizerAdapterTest().write_per_root_anchor(anchor)
        reference = anchor / "probes" / "reference.jsonl"
        rows = [json.loads(line) for line in reference.read_text(encoding="utf-8").splitlines()]
        rows[0]["root_scores"] = {"e2e4": 30, "d2d4": 0}
        rows[0]["legal_root_moves"] = 2
        rows[0]["completed_root_moves"] = 2
        reference.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return anchor

    def write_config(self, root: Path, anchor: Path, proposals: int = 3, workers: int = 2) -> Path:
        probe, inputs, weights = root / "probe", root / "positions.csv", root / "net.bin"
        probe.write_text("test", encoding="utf-8")
        inputs.write_text("header\nfen\n", encoding="utf-8")
        weights.write_text("test", encoding="utf-8")
        config = {
            "probe": str(probe), "inputs": [str(inputs)], "weights": str(weights),
            "candidate_nodes": 100, "baseline_margins": [120, 240, 360],
            "development": {"reference_dir": str(anchor), "contract": "per_root_v1"},
            "pareto_search": {
                "initial_margins": [120, 240, 360], "max_proposals": proposals, "workers": workers,
                "seed": 7, "perturbation_c": 40, "perturbation_gamma": 0.101, "max_margin": 1000,
                "semantic_filters": [
                    {"metric": "winning_mate_missed", "discard_worst_fraction": 0.25},
                    {"metric": "nonlosing_to_losing", "discard_worst_fraction": 0.25},
                ],
            },
        }
        path = root / "pareto.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    @staticmethod
    def record(identifier: str, values: tuple[float, float, float], mates: int, losses: int) -> dict:
        return {
            "id": identifier, "margins": [1, 2, 3],
            "metrics": {"mean_normalized_regret": values[0]},
            "risk": {"absolute_regret": {"mean_squared": values[1], "tail_mean": {"top_0.01": values[2]}}},
            "semantic": {"winning_mate_missed": mates, "nonlosing_to_losing": losses, "clear_advantage_lost": 0, "clear_advantage_to_nonpositive": 0},
        }

    def test_strict_primary_dominance_updates_archive(self) -> None:
        initial = self.record("initial", (0.2, 0.2, 0.2), 0, 0)
        tradeoff = self.record("tradeoff", (0.1, 0.3, 0.3), 0, 0)
        dominated = self.record("dominated", (0.3, 0.3, 0.3), 0, 0)
        frontier, update = pareto.archive_update([initial], tradeoff)
        self.assertEqual(update["action"], "admitted")
        self.assertEqual([row["id"] for row in frontier], ["initial", "tradeoff"])
        frontier, update = pareto.archive_update(frontier, dominated)
        self.assertEqual(update["action"], "dominated")
        self.assertEqual([row["id"] for row in frontier], ["initial", "tradeoff"])

    def test_semantic_filters_are_sequential_and_keep_cutoff_ties(self) -> None:
        frontier = [
            self.record("a", (0.0, 3.0, 3.0), 0, 0),
            self.record("b", (1.0, 2.0, 2.0), 1, 2),
            self.record("c", (2.0, 1.0, 1.0), 2, 1),
            self.record("d", (3.0, 0.0, 0.0), 3, 1),
        ]
        filters = (pareto.SemanticFilter("winning_mate_missed", 0.25), pareto.SemanticFilter("nonlosing_to_losing", 0.25))
        survivors, history = pareto.decimate_semantic_frontier(frontier, filters)
        self.assertEqual(history[0]["discarded"], ["d"])
        self.assertEqual(history[1]["discarded"], ["b"])
        self.assertEqual([row["id"] for row in survivors], ["a", "c"])

    def test_semantic_cutoff_ties_are_retained(self) -> None:
        frontier = [
            self.record("a", (0.0, 3.0, 3.0), 0, 0),
            self.record("b", (1.0, 2.0, 2.0), 1, 0),
            self.record("c", (2.0, 1.0, 1.0), 2, 0),
            self.record("d", (3.0, 0.0, 0.0), 2, 0),
        ]
        survivors, history = pareto.decimate_semantic_frontier(frontier, (pareto.SemanticFilter("winning_mate_missed", 0.25),))
        self.assertEqual(history[0]["cutoff"], 2)
        self.assertEqual(history[0]["discarded"], [])
        self.assertEqual([row["id"] for row in survivors], ["a", "b", "c", "d"])

    def test_parent_selection_is_deterministic_for_a_frontier_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = pareto.load_settings(self.write_config(root, self.write_anchor(root)))
            frontier = [self.record("a", (0, 1, 2), 0, 0), self.record("b", (1, 0, 2), 0, 0)]
            self.assertEqual(pareto.select_parent(frontier, settings, 9)["id"], pareto.select_parent(frontier, settings, 9)["id"])

    def test_duplicate_tuple_is_dismissed_and_replaced_before_a_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = pareto.load_settings(self.write_config(root, self.write_anchor(root)))
            parent = {"id": "initial", "margins": [120, 240, 360]}
            duplicate = (100, 220, 340)
            replacement = (140, 260, 380)

            def fake_proposal(_parent, _settings, _proposal_index, replacement_attempt=0):
                if replacement_attempt == 0:
                    return duplicate, (-1, -1, -1), 40.0
                return replacement, (1, 1, 1), 40.0

            with patch.object(pareto, "make_proposal", side_effect=fake_proposal):
                actual_parent, margins, direction, size, dismissed = pareto.make_unique_proposal(
                    [parent], settings, 0, {duplicate}
                )
            self.assertEqual(actual_parent, parent)
            self.assertEqual(margins, replacement)
            self.assertEqual(direction, (1, 1, 1))
            self.assertEqual(size, 40.0)
            self.assertEqual(dismissed, 1)

    def test_full_population_batches_reuse_frontier_parents_without_current_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = pareto.load_settings(self.write_config(root, self.write_anchor(root), proposals=3, workers=2))
            run_dir = root / "run"
            pareto.prepare(run_dir, pareto.manifest(settings))
            key = ("positions.csv", 1, "fen")

            def fake_probe(_settings, _run_dir, identifier, _margins):
                move = "e2e4" if identifier == "initial" else "d2d4"
                return {"positions": {key: {"bestmove": move, "score": 30 if move == "e2e4" else 0, "completed_depth": 6, "nodes": 100, "iteration_interrupted": True}}, "summary": {}}

            with patch.object(pareto, "probe_one", side_effect=fake_probe), patch.object(pareto.tune_futility, "file_identity", return_value={"path": "synthetic", "sha256": "0", "size": 0}):
                result = pareto.run(settings, run_dir)
            self.assertEqual(result["proposal_count"], 3)
            self.assertEqual(result["evaluated_count"], 4)
            self.assertEqual([row["id"] for row in result["numeric_pareto_frontier"]], ["initial"])

    def test_bounded_run_commits_only_one_initial_or_proposal_per_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = pareto.load_settings(self.write_config(root, self.write_anchor(root), proposals=3, workers=2))
            run_dir = root / "run"
            pareto.prepare(run_dir, pareto.manifest(settings))
            key = ("positions.csv", 1, "fen")

            def fake_probe(_settings, _run_dir, _identifier, _margins):
                return {"positions": {key: {"bestmove": "e2e4", "score": 30, "completed_depth": 6, "nodes": 100, "iteration_interrupted": True}}, "summary": {}}

            with patch.object(pareto, "probe_one", side_effect=fake_probe), patch.object(pareto.tune_futility, "file_identity", return_value={"path": "synthetic", "sha256": "0", "size": 0}):
                initial = pareto.run(settings, run_dir, max_work_units=1)
                first_proposal = pareto.run(settings, run_dir, max_work_units=1)
            self.assertEqual(initial["status"], "running")
            self.assertEqual(initial["work_units_completed"], 1)
            self.assertEqual(initial["proposal_count"], 0)
            self.assertEqual(first_proposal["work_units_completed"], 1)
            self.assertEqual(first_proposal["proposal_count"], 1)

    def test_v3_state_cannot_resume_under_v4_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = pareto.load_settings(self.write_config(root, self.write_anchor(root)))
            state = root / "state.json"
            state.write_text(json.dumps({"schema": "chilo.futility_relative_risk_hillclimb_state.v3"}), encoding="utf-8")
            with self.assertRaisesRegex(pareto.optimize_futility.OptimizationError, "cannot resume"):
                pareto.load_state(state, settings)


if __name__ == "__main__":
    unittest.main()
