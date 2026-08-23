from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("sample_futility_positions.py")


def write_collector_csv(path: Path, rows: list[tuple[str, int, int]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["eval_fen", "score", "result"])
        writer.writerows(rows)


class SampleFutilityPositionsTest(unittest.TestCase):
    def test_creates_unique_fen_disjoint_sample_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            exclude = root / "exclude.csv"
            output = root / "output.csv"
            metadata = root / "output.json"
            write_collector_csv(
                source,
                [
                    ("fen-a", 1, 1),
                    ("fen-b", 2, 1),
                    ("fen-b", 3, 0),
                    ("fen-c", 4, 1),
                    ("fen-d", 5, 0),
                    ("fen-e", 6, 1),
                ],
            )
            write_collector_csv(exclude, [("fen-a", 9, 1)])

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    str(source),
                    "--exclude",
                    str(exclude),
                    "--output",
                    str(output),
                    "--metadata",
                    str(metadata),
                    "--seed",
                    "17",
                    "--count",
                    "4",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            with output.open(newline="") as handle:
                output_rows = list(csv.DictReader(handle))
            self.assertEqual(len(output_rows), 4)
            output_fens = [row["eval_fen"] for row in output_rows]
            self.assertEqual(len(output_fens), len(set(output_fens)))
            self.assertNotIn("fen-a", output_fens)

            manifest = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(manifest["sample_rows"], 4)
            self.assertEqual(manifest["duplicate_fens"], 0)
            self.assertEqual(manifest["overlap_fens"], 0)
            self.assertIn('"seed": 17', completed.stdout)

            repeat = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    str(source),
                    "--exclude",
                    str(exclude),
                    "--output",
                    str(output),
                    "--metadata",
                    str(metadata),
                    "--seed",
                    "17",
                    "--count",
                    "4",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(repeat.returncode, 0)
            self.assertIn("output already exists", repeat.stderr)

