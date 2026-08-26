from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import discrete_optimizer


class DiscreteOptimizerTest(unittest.TestCase):
    def test_increment_representation_and_legal_neighbours(self) -> None:
        margins = (75, 212, 390)
        self.assertEqual(discrete_optimizer.to_increments(margins), (75, 137, 178))
        self.assertEqual(discrete_optimizer.from_increments((75, 137, 178)), margins)
        neighbours = discrete_optimizer.neighbours(margins, 20, 500)
        self.assertIn((55, 192, 370), neighbours)
        self.assertIn((75, 192, 370), neighbours)
        self.assertTrue(all(left <= right for item in neighbours for left, right in zip(item, item[1:])))

    def test_search_uses_cache_then_stops_at_new_probe_budget(self) -> None:
        config = discrete_optimizer.SearchConfig((1,), (10,), 100, 1)
        cached = {(50,): (50.0, 0.0, 0.0, (50,))}
        calls: list[tuple[int, ...]] = []

        def lookup(margins: tuple[int, ...]):
            return cached.get(margins)

        def evaluate(margins: tuple[int, ...]):
            calls.append(margins)
            return (float(margins[0]), 0.0, 0.0, margins)

        result = discrete_optimizer.optimize(config, [(50,)], lookup, evaluate)
        self.assertEqual(calls, [(40,)])
        self.assertEqual(result.new_evaluations, 1)
        self.assertTrue(result.stopped_by_budget)
        self.assertIn((50,), result.evaluations)
        self.assertIn((40,), result.evaluations)

    def test_requires_explicit_seed_for_each_enabled_depth(self) -> None:
        config = discrete_optimizer.SearchConfig((3, 4), (10,), 1000, 1)
        with self.assertRaisesRegex(discrete_optimizer.OptimizationError, "missing seed"):
            discrete_optimizer.optimize(
                config,
                [(100, 200, 300)],
                lambda _: (0.0, 0.0, 0.0, (100, 200, 300)),
                lambda _: (0.0, 0.0, 0.0, (100, 200, 300)),
            )

    def test_ranked_uses_metric_order_then_margin_tuple(self) -> None:
        evaluations = {
            (120,): (0.1, 0.2, 0.2, (120,)),
            (100,): (0.1, 0.2, 0.2, (100,)),
            (140,): (0.1, 0.1, 0.9, (140,)),
        }
        self.assertEqual([item[0] for item in discrete_optimizer.ranked(evaluations)], [(140,), (100,), (120,)])


if __name__ == "__main__":
    unittest.main()
