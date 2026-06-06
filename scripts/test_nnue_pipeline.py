from __future__ import annotations

import csv
import importlib.util
import json
import math
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
from nnue_torch import make_tiny_nnue_model
from train_nnue import learning_rate_for_epoch

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None
TENSORBOARD_AVAILABLE = importlib.util.find_spec("tensorboard") is not None


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
        self.assertEqual(seeded["input_weights"].shape, (13, 64, 64))
        self.assertEqual(seeded["hidden2_weights"].shape, (32, 128))
        self.assertEqual(seeded["hidden2_bias"].shape, (32,))
        self.assertEqual(seeded["output_weights"].shape, (32,))
        self.assertEqual(score, 0)

    def test_assign_shard_splits(self):
        splits = assign_shard_splits(total_shards=10, validation_fraction=0.2, seed=7)
        self.assertEqual(len(splits), 10)
        self.assertEqual(splits.count("val"), 2)
        self.assertEqual(splits.count("train"), 8)

    def test_learning_rate_schedules(self):
        constant = [learning_rate_for_epoch("constant", 0.01, 0.001, epoch, 5, 2, 0.5) for epoch in range(1, 6)]
        step = [learning_rate_for_epoch("step", 0.01, 0.001, epoch, 5, 2, 0.5) for epoch in range(1, 6)]
        cosine = [learning_rate_for_epoch("cosine", 0.01, 0.001, epoch, 5, 2, 0.5) for epoch in range(1, 6)]
        one_epoch = learning_rate_for_epoch("cosine", 0.01, 0.001, 1, 1, 2, 0.5)

        self.assertEqual(constant, [0.01] * 5)
        self.assertEqual(step, [0.01, 0.01, 0.005, 0.005, 0.0025])
        self.assertAlmostEqual(cosine[0], 0.01)
        self.assertAlmostEqual(cosine[-1], 0.001)
        self.assertGreater(cosine[1], cosine[2])
        self.assertGreater(cosine[2], cosine[3])
        self.assertEqual(one_epoch, 0.01)

    @unittest.skipUnless(TORCH_AVAILABLE, "PyTorch not installed in this environment")
    def test_random_initialization_is_fan_in_aware_and_deterministic(self):
        import torch

        contract = load_contract()
        TinyNnueModel = make_tiny_nnue_model(torch, torch.nn)

        torch.manual_seed(17)
        model_a = TinyNnueModel(contract, 64, 32, "random")
        torch.manual_seed(17)
        model_b = TinyNnueModel(contract, 64, 32, "random")

        for name, value in model_a.state_dict().items():
            self.assertTrue(torch.equal(value, model_b.state_dict()[name]), name)

        self.assertTrue(torch.allclose(model_a.hidden2_weights.mean(dim=1), torch.zeros(32), atol=1e-6))
        self.assertAlmostEqual(float(model_a.output_weights.mean().item()), 0.0, places=6)
        self.assertAlmostEqual(float(model_a.hidden_bias.mean().item()), 1.0, places=6)
        self.assertAlmostEqual(float(model_a.hidden2_bias.mean().item()), 1.0, places=6)
        self.assertAlmostEqual(float(model_a.input_weights.std(unbiased=False).item()), 1.0 / math.sqrt(16.0), delta=0.01)
        self.assertAlmostEqual(
            float(model_a.hidden2_weights.std(unbiased=False).item()),
            math.sqrt(2.0 / 128.0),
            delta=0.01,
        )
        self.assertAlmostEqual(
            float(model_a.output_weights.std(unbiased=False).item()),
            64.0 / math.sqrt(32.0),
            delta=3.0,
        )

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
            export_bin_path = temp_dir / "weights.bin"
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
                    "--output-bin",
                    str(export_bin_path),
                ],
                check=True,
            )

            header_text = header_path.read_text(encoding="utf-8")
            self.assertIn('kContractId[] = "chilo.tiny_nnue.v4"', header_text)
            self.assertIn("inline constexpr int kHiddenSize = 64;", header_text)
            self.assertIn("inline constexpr int kHidden2Size = 32;", header_text)
            self.assertIn("inline constexpr int kInputScale = 64;", header_text)
            self.assertIn("inline constexpr int kHiddenScale = 8;", header_text)
            self.assertIn("inline constexpr int kOutputScale = 1;", header_text)
            self.assertIn("inline constexpr int kActivationScale = 127;", header_text)
            self.assertIn("inline constexpr int kOutputSize = 32;", header_text)
            self.assertIn("int8_t hidden2Weights", header_text)
            self.assertIn("int8_t outputWeights", header_text)
            export_manifest = json.loads(export_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(export_manifest["format"], "chilo.nnue_export.v8")
            self.assertEqual(export_manifest["hidden_size"], 64)
            self.assertEqual(export_manifest["hidden2_size"], 32)
            self.assertEqual(export_manifest["output_size"], 32)
            self.assertEqual(export_manifest["quantization"], "byte_dense_shift_v1")
            self.assertEqual(export_manifest["input_scale"], 64)
            self.assertEqual(export_manifest["hidden_scale"], 8)
            self.assertEqual(export_manifest["output_scale"], 1)
            self.assertEqual(export_manifest["activation_scale"], 127)
            self.assertEqual(export_manifest["validation"]["max_abs_diff"], 0.0)
            self.assertTrue(export_bin_path.exists())

    def test_prepare_headerless_input(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            csv_path = temp_dir / "samples-headerless.csv"
            csv_path.write_text(
                "4k3/8/8/8/8/8/8/3QK3 w - - 0 1,901,1\n"
                "4k3/8/8/8/8/8/8/4K3 w - - 0 1,0,0\n",
                encoding="utf-8",
            )

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
                    "--overwrite",
                ],
                check=True,
            )

            _, manifest = load_dataset_manifest(dataset_dir)
            self.assertEqual(manifest["total_samples"], 2)

    def test_dedup_training_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            csv_a = temp_dir / "a.csv"
            csv_b = temp_dir / "b.csv"
            output_csv = temp_dir / "dedup.csv"

            for path, rows in (
                (
                    csv_a,
                    [
                        ["4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "901", "1"],
                        ["4k3/8/8/8/8/8/8/4K3 w - - 0 1", "0", "0"],
                    ],
                ),
                (
                    csv_b,
                    [
                        ["4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "901", "1"],
                        ["4k3/8/8/8/3N4/8/8/4K3 w - - 0 1", "31", "0"],
                    ],
                ),
            ):
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["eval_fen", "score", "result"])
                    writer.writerows(rows)

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "dedup_training_csv.py"),
                    "--input",
                    str(csv_a),
                    str(csv_b),
                    "--output",
                    str(output_csv),
                    "--report-every",
                    "1",
                    "--overwrite",
                ],
                check=True,
            )

            with output_csv.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0], ["eval_fen", "score", "result"])
            self.assertEqual(len(rows) - 1, 3)

    @unittest.skipUnless(TORCH_AVAILABLE and TENSORBOARD_AVAILABLE, "PyTorch/TensorBoard not installed in this environment")
    def test_tensorboard_hidden2_tags_and_resume_schedule_restart(self):
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            csv_path = temp_dir / "samples.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["eval_fen", "score", "result"])
                writer.writerow(["4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "901", "1"])
                writer.writerow(["4k3/8/8/8/8/8/8/4K3 w - - 0 1", "0", "0"])
                writer.writerow(["4k3/8/8/8/3N4/8/8/4K3 w - - 0 1", "31", "0"])
                writer.writerow(["4k3/8/8/8/8/3n4/8/4K3 b - - 0 1", "-31", "0"])

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

            diagnostic = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "diagnose_nnue_init.py"),
                    "--dataset",
                    str(dataset_dir),
                    "--max-samples",
                    "4",
                    "--percentile-samples",
                    "4",
                    "--batch-size",
                    "2",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("accumulator_activation:", diagnostic.stdout)
            self.assertIn("hidden2_activation:", diagnostic.stdout)

            first_training_dir = temp_dir / "training-first"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "train_nnue.py"),
                    "--dataset",
                    str(dataset_dir),
                    "--output-dir",
                    str(first_training_dir),
                    "--epochs",
                    "1",
                    "--batch-size",
                    "2",
                    "--no-shuffle",
                    "--seed",
                    "11",
                ],
                check=True,
            )

            resumed_training_dir = temp_dir / "training-resumed"
            tensorboard_dir = resumed_training_dir / "tb"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "train_nnue.py"),
                    "--dataset",
                    str(dataset_dir),
                    "--output-dir",
                    str(resumed_training_dir),
                    "--epochs",
                    "2",
                    "--batch-size",
                    "2",
                    "--learning-rate",
                    "0.01",
                    "--lr-schedule",
                    "cosine",
                    "--min-learning-rate",
                    "0.001",
                    "--resume-checkpoint",
                    str(first_training_dir / "best.pt"),
                    "--tensorboard-dir",
                    str(tensorboard_dir),
                    "--no-shuffle",
                    "--seed",
                    "13",
                ],
                check=True,
            )

            manifest = json.loads((resumed_training_dir / "training_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["lr_schedule"], "cosine")
            self.assertEqual([entry["epoch"] for entry in manifest["history"]], [2, 3])
            self.assertEqual([entry["learning_rate"] for entry in manifest["history"]], [0.01, 0.001])

            event_files = list(tensorboard_dir.glob("events.out.tfevents.*"))
            self.assertEqual(len(event_files), 1)
            events = EventAccumulator(str(event_files[0]))
            events.Reload()
            scalar_tags = set(events.Tags()["scalars"])
            histogram_tags = set(events.Tags()["histograms"])
            self.assertIn("activation/hidden2_val_clip_frac", scalar_tags)
            self.assertIn("activation/hidden2_val_dead_unit_count", scalar_tags)
            self.assertIn("activation/accumulator_val_zero_frac", scalar_tags)
            self.assertIn("hist/hidden2_pre_activation_val", histogram_tags)
            self.assertIn("hist/hidden2_zero_frac_val", histogram_tags)

    @unittest.skipUnless(TORCH_AVAILABLE, "PyTorch not installed in this environment")
    def test_train_seeded_noise_wakes_dormant_output_units(self):
        import torch

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
                    "3",
                    "--validation-fraction",
                    "0",
                    "--seed",
                    "7",
                    "--overwrite",
                ],
                check=True,
            )

            training_dir = temp_dir / "training"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "train_nnue.py"),
                    "--dataset",
                    str(dataset_dir),
                    "--output-dir",
                    str(training_dir),
                    "--epochs",
                    "1",
                    "--hidden-size",
                    "32",
                    "--batch-size",
                    "3",
                    "--shuffle-buffer-size",
                    "4",
                    "--report-batches",
                    "1",
                    "--seed",
                    "11",
                    "--init",
                    "seeded-noise",
                ],
                check=True,
            )

            training_manifest = json.loads((training_dir / "training_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(training_manifest["init"], "seeded-noise")
            self.assertTrue((training_dir / "best.pt").exists())

            checkpoint = torch.load(training_dir / "best.pt", map_location="cpu")
            output_weights = checkpoint["state_dict"]["output_weights"].detach().cpu().numpy()
            seeded = build_seeded_weights(load_contract(), hidden_size=32)
            dormant_mask = np.asarray(seeded["output_weights"]) == 0
            self.assertTrue(np.any(np.abs(output_weights[dormant_mask]) > 1e-8))

    @unittest.skipUnless(TORCH_AVAILABLE, "PyTorch not installed in this environment")
    def test_run_nnue_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            csv_path = temp_dir / "samples.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["eval_fen", "score", "result"])
                writer.writerow(["4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "901", "1"])
                writer.writerow(["4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "901", "1"])
                writer.writerow(["4k3/8/8/8/8/8/8/4K3 w - - 0 1", "0", "0"])
                writer.writerow(["4k3/8/8/8/3N4/8/8/4K3 w - - 0 1", "31", "0"])

            output_root = temp_dir / "workflow"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "run_nnue_workflow.py"),
                    "--input",
                    str(csv_path),
                    "--output-root",
                    str(output_root),
                    "--dedup-mode",
                    "exact-row",
                    "--samples-per-shard",
                    "2",
                    "--validation-fraction",
                    "0.5",
                    "--epochs",
                    "1",
                    "--hidden-size",
                    "16",
                    "--batch-size",
                    "2",
                    "--shuffle-buffer-size",
                    "4",
                    "--report-batches",
                    "1",
                    "--validation-samples",
                    "3",
                    "--tolerance",
                    "256",
                ],
                check=True,
            )

            summary = json.loads((output_root / "run_summary.json").read_text(encoding="utf-8"))
            self.assertIn("dedup_output", summary)
            self.assertTrue((output_root / "dataset" / "manifest.json").exists())
            self.assertTrue((output_root / "training" / "best.pt").exists())
            self.assertTrue((output_root / "export" / "generated_nnue_weights.h").exists())
            self.assertTrue((output_root / "export" / "generated_nnue_manifest.json").exists())
            self.assertTrue((output_root / "export" / "weights.bin").exists())

            _, manifest = load_dataset_manifest(output_root / "dataset")
            self.assertEqual(manifest["total_samples"], 3)


if __name__ == "__main__":
    unittest.main()
