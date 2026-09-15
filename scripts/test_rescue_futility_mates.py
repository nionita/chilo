from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import rescue_futility_mates as rescue


class MateRescueFormatTest(unittest.TestCase):
    def test_parses_certified_rescue_and_adapts_it_for_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rescue.jsonl"
            record = {
                "type": "position", "reference_mode": rescue.RESCUE_MODE, "reference_status": "rescued",
                "source": "positions.csv", "line": 2, "fen": "fen", "futility_margins": [120, 240, 360],
                "all_root_scores": True, "node_limit": 400, "baseline_node_limit": 100,
                "score": 28990, "bestmove": "e2e4", "root_scores": {"e2e4": 28990, "d2d4": 0},
                "root_score_depths": {"e2e4": 7, "d2d4": 6}, "mate_score": 28990,
                "completed_depth": 6, "legal_root_moves": 2, "baseline_completed_depth": 4,
            }
            summary = {"type": "summary", "reference_mode": rescue.RESCUE_MODE, "positions": 1,
                       "node_limit": 400, "baseline_node_limit": 100, "reference_depth_gap": 2}
            path.write_text(json.dumps(record) + "\n" + json.dumps(summary) + "\n", encoding="utf-8")
            parsed = rescue.parse_rescue(path, 400, (120, 240, 360), 100, 2)
            key = next(iter(parsed["positions"]))
            adapted = rescue.rescue_as_reference(parsed["positions"][key])
            self.assertEqual(adapted["reference_mode"], "per_root_v1")
            self.assertEqual(adapted["reference_status"], "complete")
            self.assertEqual(adapted["target_depth"], 6)

    def test_rejects_uncertified_mate_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rescue.jsonl"
            record = {"type": "position", "reference_mode": rescue.RESCUE_MODE, "reference_status": "rescued",
                      "source": "positions.csv", "line": 2, "fen": "fen", "futility_margins": [120],
                      "all_root_scores": True, "node_limit": 400, "baseline_node_limit": 100,
                      "score": 20, "bestmove": "e2e4", "root_scores": {"e2e4": 20},
                      "root_score_depths": {"e2e4": 6}, "mate_score": 20}
            summary = {"type": "summary", "reference_mode": rescue.RESCUE_MODE, "positions": 1,
                       "node_limit": 400, "baseline_node_limit": 100, "reference_depth_gap": 2}
            path.write_text(json.dumps(record) + "\n" + json.dumps(summary) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(rescue.RescueError, "winning mate"):
                rescue.parse_rescue(path, 400, (120,), 100, 2)

    def test_normalizes_legacy_baseline_score_from_complete_root_map_in_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rescue.jsonl"
            record = {
                "type": "position", "reference_mode": rescue.RESCUE_MODE, "reference_status": "rescued",
                "source": "positions.csv", "line": 3622, "fen": "fen", "futility_margins": [120],
                "all_root_scores": True, "node_limit": 400, "baseline_node_limit": 100,
                "score": 28993, "bestmove": "e2e4", "root_scores": {"e2e4": 28989, "d2d4": 1414},
                "root_score_depths": {"e2e4": 15, "d2d4": 15}, "mate_score": 28989,
            }
            summary = {"type": "summary", "reference_mode": rescue.RESCUE_MODE, "positions": 1,
                       "node_limit": 400, "baseline_node_limit": 100, "reference_depth_gap": 2}
            original = json.dumps(record) + "\n" + json.dumps(summary) + "\n"
            path.write_text(original, encoding="utf-8")

            parsed = rescue.parse_rescue(path, 400, (120,), 100, 2)
            key = next(iter(parsed["positions"]))
            self.assertEqual(parsed["positions"][key]["score"], 28989)
            self.assertEqual(parsed["positions"][key]["bestmove"], "e2e4")
            self.assertEqual(parsed["rescued_root_map_normalizations"], [{
                "jsonl_line": 1,
                "original_score": 28993,
                "normalized_score": 28989,
                "original_bestmove": "e2e4",
                "normalized_bestmove": "e2e4",
                "reason": "rescued_complete_root_map_overrides_legacy_baseline_result",
                "position_key": list(key),
            }])
            self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
