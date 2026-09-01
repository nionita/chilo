from __future__ import annotations

import sys
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


if __name__ == "__main__":
    unittest.main()
