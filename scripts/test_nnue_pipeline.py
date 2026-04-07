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

from nnue_common import build_seeded_weights, encode_sample, integer_model_eval, load_contract


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

    def test_prepare_and_export_seeded(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            csv_path = temp_dir / "samples.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["eval_fen", "score", "result"])
                writer.writerow(["4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "901", "1"])
                writer.writerow(["4k3/8/8/8/8/8/8/4K3 w - - 0 1", "0", "0"])

            dataset_dir = temp_dir / "dataset"
            subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "prepare_nnue_dataset.py"), "--input", str(csv_path), "--output-dir", str(dataset_dir)],
                check=True,
            )

            manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["sample_count"], 2)
            samples = np.load(dataset_dir / "samples.npy", mmap_mode="r")
            self.assertEqual(int(samples[0]["score"]), 901)

            header_path = temp_dir / "generated_nnue_weights.h"
            export_manifest_path = temp_dir / "generated_nnue_manifest.json"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "export_nnue.py"),
                    "--seeded",
                    "--dataset-dir",
                    str(dataset_dir),
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
