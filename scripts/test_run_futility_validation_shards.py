from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_futility_validation_shards as shards


FENS = [
    "4k3/8/8/8/8/8/8/4K3 w - - 0 1",
    "4k3/8/8/8/8/8/3K4/8 w - - 0 1",
    "4k3/8/8/8/8/8/2K5/8 w - - 0 1",
    "4k3/8/8/8/8/8/1K6/8 w - - 0 1",
    "4k3/8/8/8/8/8/K7/8 w - - 0 1",
    "8/4k3/8/8/8/8/8/4K3 w - - 0 1",
    "8/8/4k3/8/8/8/8/4K3 w - - 0 1",
    "8/8/8/4k3/8/8/8/4K3 w - - 0 1",
]


def write_csv(path: Path, fens: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["eval_fen", "score", "result"])
        for index, fen in enumerate(fens):
            writer.writerow([fen, str(index), "0"])


class ValidationShardInputTest(unittest.TestCase):
    def test_generated_shards_are_disjoint_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            exclude = root / "existing.csv"
            probe = root / "probe"
            weights = root / "weights.bin"
            write_csv(source, FENS)
            write_csv(exclude, [FENS[0]])
            probe.write_text("probe", encoding="utf-8")
            weights.write_bytes(b"weights")
            config = {
                "schema": shards.SCHEMA,
                "run_dir": "run",
                "source": "source.csv",
                "exclude_inputs": ["existing.csv"],
                "shards": [
                    {"id": "test-a", "seed": 7, "count": 3},
                    {"id": "test-b", "seed": 8, "count": 3},
                ],
                "anchor": {
                    "probe": "probe", "weights": "weights.bin", "candidate_nodes": 100,
                    "reference_nodes_per_root": 200, "reference_depth_gap": 2,
                    "baseline_margins": [120], "report_every": 1,
                },
                "rescue": {"report_every": 1},
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            settings = shards.parse_config(config_path)
            first = shards.ensure_inputs(settings)
            self.assertEqual([item["id"] for item in first["inputs"]], ["test-a", "test-b"])
            first_fens = shards.read_fens(root / "run" / "inputs" / "test-a.csv")
            second_fens = shards.read_fens(root / "run" / "inputs" / "test-b.csv")
            self.assertEqual(len(first_fens), 3)
            self.assertEqual(len(second_fens), 3)
            self.assertFalse(first_fens & second_fens)
            self.assertNotIn(FENS[0], first_fens | second_fens)
            self.assertEqual(first, shards.ensure_inputs(settings))


if __name__ == "__main__":
    unittest.main()
