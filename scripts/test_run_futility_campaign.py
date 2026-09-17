from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_futility_campaign as campaign


def fake_context(label: str) -> SimpleNamespace:
    return SimpleNamespace(
        reference_identity={"path": f"{label}/reference.jsonl", "sha256": "reference-" + label, "size": 1},
        baseline_identity={"path": f"{label}/baseline.jsonl", "sha256": "baseline-" + label, "size": 1},
        rescue=None,
        trusted_set={"trusted_position_count": 1, "position_keys_sha256": "keys-" + label},
    )


class CampaignPopulationTest(unittest.TestCase):
    def write_single(self, root: Path) -> None:
        (root / "inputs").mkdir(parents=True)
        (root / "inputs" / "positions.csv").write_text("fen\n", encoding="utf-8")
        (root / "probes").mkdir()
        (root / "probes" / "reference.jsonl").write_text("{}\n", encoding="utf-8")
        (root / "rescue").mkdir()

    def write_sharded(self, root: Path) -> None:
        (root / "inputs").mkdir(parents=True)
        for shard in ("one", "two"):
            (root / "inputs" / f"{shard}.csv").write_text("fen\n", encoding="utf-8")
            (root / "shards" / shard / "anchor").mkdir(parents=True)
            (root / "shards" / shard / "rescue").mkdir(parents=True)
        (root / "complete.json").write_text(json.dumps({"schema": "chilo.futility_validation_shards_complete.v1", "shards": ["one", "two"]}), encoding="utf-8")

    def test_config_resolves_single_and_completed_sharded_populations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = root / "store"
            development = store / "development"
            selection = store / "selection"
            self.write_single(development)
            self.write_sharded(selection)
            probe, weights = root / "probe", root / "weights"
            probe.write_text("probe", encoding="utf-8")
            weights.write_text("weights", encoding="utf-8")
            config = {
                "schema": campaign.SCHEMA, "store_root": str(store), "run_id": "test-run",
                "artifacts": {"probe": str(probe), "weights": str(weights)},
                "candidate_nodes": 120000, "baseline_margins": [120, 240, 360], "score_scale": 600, "report_every": 100,
                "development": {"id": "development", "kind": "single", "path": "development"},
                "selection": [{"id": "selection", "kind": "sharded", "path": "selection"}],
                "pareto_search": None, "validation": None,
            }
            path = root / "campaign.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch.object(campaign.optimize_futility, "load_anchor", side_effect=lambda _config, label, *_args: fake_context(label)):
                settings = campaign.load_campaign(path)
            self.assertEqual(settings["development"]["input"], development / "inputs" / "positions.csv")
            self.assertEqual([item["id"] for item in settings["selection"]], ["one", "two"])
            self.assertEqual(settings["run_dir"], store / "evals" / "test-run")

    def test_all_phase_defers_validation_after_bounded_search_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = {
                "run_dir": root, "pareto_search": {}, "validation": {},
            }
            search_result = {"status": "running", "work_units_completed": 1}
            with patch.object(campaign.optimize_futility_gated, "load_settings", return_value=object()), \
                 patch.object(campaign.optimize_futility_gated, "manifest", return_value={}), \
                 patch.object(campaign.optimize_futility_gated, "prepare"), \
                 patch.object(campaign.optimize_futility_gated, "run", return_value=search_result), \
                 patch.object(campaign.validation_batch, "load_settings") as validation_load:
                campaign.run_campaign(settings, "all", 1)
            validation_load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
