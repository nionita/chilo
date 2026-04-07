from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from nnue_common import (
    assign_shard_splits,
    build_seeded_weights,
    encode_sample,
    integer_model_eval,
    iter_dataset_records,
    load_contract,
    load_dataset_manifest,
)


class NnuePipelineTest(unittest.TestCase):
    def test_encode_sample_and_eval(self):
        record = encode_sample("4k3/8/8/8/8/8/8/3QK3 w - - 0 1", 901, 1)
        self.assertEqual(int(record["side_to_move"]), 0)
        self.assertEqual(int(record["piece_count"]), 3)

        contract = load_contract()
        seeded = build_seeded_weights(contract)
        pieces = record["pieces"][: int(record["piece_count"])].tolist()
        squares = record["squares"][: int(record["piece_count"])].tolist()
        score = integer_model_eval(seeded, int(record["side_to_move"]), pieces, squares, int(contract["clip_max"]))
        self.assertEqual(score, 901)

    def test_assign_shard_splits(self):
        splits = assign_shard_splits(total_shards=10, validation_fraction=0.2, seed=7)
        self.assertEqual(len(splits), 10)
        self.assertEqual(splits.count("val"), 2)
        self.assertEqual(splits.count("train"), 8)

    def test_prepare_and_export_seeded(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            csv_path = temp_dir / "samples.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["eval_fen", "score", "result"])
                writer.writerow(["4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "901", "1"])
                writer.writerow(["4k3/8/8/8/8/8/8/4K3 w - - 0 1", "0", "0"])
                writer.writerow(["4k3/8/8/8/3N4/8/8/4K3 w - - 0 1", "31", "0"])

            dataset_dir = temp_dir / "dataset"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "prepare_nnue_dataset.py"),
                    "--input",
                    str(csv_path),
                    "--output-dir",
                    str(dataset_dir),
                    "--samples-per-shard",
                    "2",
                    "--validation-fraction",
                    "0.5",
                    "--seed",
                    "7",
                    "--overwrite",
                ],
                check=True,
            )

            manifest_path, manifest = load_dataset_manifest(dataset_dir)
            self.assertEqual(manifest["total_samples"], 3)
            self.assertEqual(manifest["total_shards"], 2)
            self.assertEqual(manifest["split_counts"]["val_shards"], 1)
            records = list(iter_dataset_records(manifest_path, max_records=3))
            self.assertEqual(len(records), 3)
            self.assertEqual(int(records[0]["score"]), 901)

            header_path = temp_dir / "generated_nnue_weights.h"
            export_manifest_path = temp_dir / "generated_nnue_manifest.json"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "export_nnue.py"),
                    "--seeded",
                    "--dataset-dir",
                    str(dataset_dir),
                    "--validation-samples",
                    "3",
                    "--tolerance",
                    "0",
                    "--output-header",
                    str(header_path),
                    "--output-manifest",
                    str(export_manifest_path),
                ],
                check=True,
            )

            header_text = header_path.read_text(encoding="utf-8")
            self.assertIn('kContractId[] = "chilo.tiny_nnue.v1"', header_text)
            export_manifest = json.loads(export_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(export_manifest["validation"]["max_abs_diff"], 0.0)


if __name__ == "__main__":
    unittest.main()
