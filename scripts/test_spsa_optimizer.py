from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import spsa_optimizer


class SpsaOptimizerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schedule = spsa_optimizer.Schedule(10.0, 5.0, 0.602, 30.0, 0.101, 1000.0, 500)

    def test_projection_preserves_order_and_bounds(self) -> None:
        self.assertEqual(spsa_optimizer.project((-2.0, 12.6, 600.0), 100), (0, 13, 100))
        self.assertEqual(spsa_optimizer.to_vector((75, 212, 390)), (75.0, 137.0, 178.0))

    def test_step_is_deterministic_and_noncollapsed(self) -> None:
        first = spsa_optimizer.make_step((120.0, 120.0, 120.0), self.schedule, 0, random.Random("x"))
        second = spsa_optimizer.make_step((120.0, 120.0, 120.0), self.schedule, 0, random.Random("x"))
        self.assertEqual(first, second)
        self.assertNotEqual(first.plus, first.minus)

    def test_update_moves_against_higher_plus_objective(self) -> None:
        step = spsa_optimizer.Step(0, 1.0, 1.0, (1, -1), (1, 1), (1, 1))
        updated = spsa_optimizer.update((10.0, 10.0), step, 0.02, 0.01, 1000.0)
        self.assertLess(updated[0], 10.0)
        self.assertGreater(updated[1], 10.0)


if __name__ == "__main__":
    unittest.main()
