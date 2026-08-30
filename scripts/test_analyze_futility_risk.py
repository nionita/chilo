from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import analyze_futility_risk


class RiskAnalysisTest(unittest.TestCase):
    def test_tail_and_semantic_regressions_are_calculated_from_root_scores(self) -> None:
        first = ("positions.csv", 1, "fen-one")
        second = ("positions.csv", 2, "fen-two")
        reference = {"positions": {
            first: {"root_scores": {"a1a2": 300, "b1b2": -200}},
            second: {"root_scores": {"a1a2": 29000, "b1b2": 0}},
        }}
        control = {"positions": {
            first: {"bestmove": "a1a2"},
            second: {"bestmove": "a1a2"},
        }}
        candidate = {"positions": {
            first: {"bestmove": "b1b2"},
            second: {"bestmove": "b1b2"},
        }}
        metrics = analyze_futility_risk.compute_risk_metrics(
            reference, control, candidate, [first, second], 600.0,
            [0.5], [0.1, 0.5], 150, -150,
        )
        self.assertEqual(metrics["position_count"], 2)
        self.assertGreater(metrics["absolute_regret"]["tail_mean"]["top_0.5"], 0.0)
        self.assertGreater(metrics["excess_vs_control"]["mean_positive"], 0.0)
        self.assertEqual(metrics["semantic_regressions_vs_control"]["winning_mate_missed"], 1)
        self.assertEqual(metrics["semantic_regressions_vs_control"]["clear_advantage_lost"], 1)
        self.assertEqual(metrics["semantic_regressions_vs_control"]["clear_advantage_to_nonpositive"], 1)
        self.assertEqual(metrics["semantic_regressions_vs_control"]["nonlosing_to_losing"], 1)


if __name__ == "__main__":
    unittest.main()
