from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_futility_validation_batch as batch


class FutilityValidationBatchTest(unittest.TestCase):
    def test_config_requires_immutable_shard_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ("bin/probe", "weights/net.bin", "inputs/sr3v-01.csv", "anchors/sr3v-01", "rescues/sr3v-01"):
                path = root / relative
                if path.suffix or relative == "bin/probe":
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("x\n", encoding="utf-8")
                else:
                    path.mkdir(parents=True, exist_ok=True)
            config = {
                "schema": batch.SCHEMA, "run_dir": "run", "probe": "bin/probe", "weights": "weights/net.bin",
                "candidate_nodes": 120000, "baseline_margins": [120, 240, 360], "score_scale": 600,
                "report_every": 250, "tail_fractions": [0.05, 0.01], "regret_thresholds": [0.1, 0.25],
                "semantic_thresholds": {"advantage_cp": 150, "loss_cp": -150},
                "shards": [{"id": "sr3v-01", "input": "inputs/sr3v-01.csv", "anchor_dir": "anchors/sr3v-01", "rescue_dir": "rescues/sr3v-01"}],
                "candidates": [{"id": "f21", "margins": [75, 212, 390, 600, 839]}],
            }
            path = root / "batch.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            settings = batch.load_settings(path)
            self.assertEqual(settings["candidates"][0]["id"], "f21")
            self.assertEqual(settings["shards"][0]["input"], root / "inputs/sr3v-01.csv")

    def test_manifest_rejects_changed_artifact_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            expected = {"schema": batch.MANIFEST_SCHEMA, "probe": {"sha256": "a"}}
            batch.verify_or_write_manifest(run_dir, expected)
            batch.verify_or_write_manifest(run_dir, expected)
            with self.assertRaises(batch.BatchError):
                batch.verify_or_write_manifest(run_dir, {"schema": batch.MANIFEST_SCHEMA, "probe": {"sha256": "b"}})


if __name__ == "__main__":
    unittest.main()
