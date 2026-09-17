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


def fake_rescue(directory: str) -> dict[str, object]:
    return {
        "directory": directory,
        "manifest": {"path": directory + "/rescue_manifest.json", "sha256": "rescue-manifest", "size": 1},
        "results": {"path": directory + "/rescue_results.json", "sha256": "rescue-results", "size": 2},
        "combined_population": {"path": directory + "/combined_population.json", "sha256": "rescue-population", "size": 3},
        "reference": {"path": directory + "/rescue_reference.jsonl", "sha256": "rescue-reference", "size": 4},
        "baseline": {"path": directory + "/rescue_baseline.jsonl", "sha256": "rescue-baseline", "size": 5},
    }


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

    def test_initial_evaluation_is_resolved_from_prior_campaign_and_staged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = root / "store"
            probe, weights = root / "probe", root / "weights"
            probe.write_text("probe", encoding="utf-8")
            weights.write_text("weights", encoding="utf-8")
            development = root / "development"
            development.mkdir()
            current = {
                "store_root": store,
                "run_dir": store / "evals" / "next-run",
                "probe": probe,
                "weights": weights,
                "candidate_nodes": 120000,
                "baseline_margins": (120, 240, 360),
                "score_scale": 600.0,
                "development": {
                    "id": "development", "population": "development", "input": root / "input.csv",
                    "anchor_dir": development, "rescue_dir": development, "population_manifest": None,
                    "context": fake_context("development"),
                },
            }
            current["development"]["input"].write_text("fen\n", encoding="utf-8")
            previous = store / "evals" / "previous-run"
            output = previous / "search" / "probes" / "candidate-0007.jsonl"
            output.parent.mkdir(parents=True)
            output.write_text("synthetic candidate output\n", encoding="utf-8")
            source_manifest = {
                "schema": campaign.MANIFEST_SCHEMA,
                "probe": campaign.file_identity(probe), "weights": campaign.file_identity(weights),
                "candidate_nodes": 120000, "baseline_margins": [120, 240, 360], "score_scale": 600.0,
                "development": campaign.context_identity(current["development"]),
            }
            (previous / "campaign_manifest.json").write_text(json.dumps(source_manifest), encoding="utf-8")
            state = {
                "schema": campaign.optimize_futility_gated.STATE_SCHEMA,
                "evaluations": [{"id": "candidate-0007", "kind": "proposal", "margins": [0, 25, 139], "output": campaign.file_identity(output)}],
            }
            (previous / "search" / "state.json").write_text(json.dumps(state), encoding="utf-8")
            with patch.object(campaign.tune_futility, "parse_probe_output", return_value={}) as parsed:
                seed = campaign.resolve_initial_evaluation(current, {"campaign_run_id": "previous-run", "evaluation_id": "candidate-0007"})
                current["initial_evaluation"] = seed
                campaign.stage_initial_evaluation(current)
            self.assertEqual(seed["margins"], [0, 25, 139])
            self.assertEqual((store / "evals" / "next-run" / "search" / "probes" / "initial.jsonl").read_text(encoding="utf-8"), "synthetic candidate output\n")
            self.assertEqual(parsed.call_count, 2)

    def test_initial_evaluation_rejects_prior_probe_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe, weights = root / "probe", root / "weights"
            probe.write_text("probe", encoding="utf-8")
            weights.write_text("weights", encoding="utf-8")
            development = root / "development"
            development.mkdir()
            input_path = root / "input.csv"
            input_path.write_text("fen\n", encoding="utf-8")
            store = root / "store"
            current = {
                "store_root": store, "run_dir": store / "evals" / "next-run", "probe": probe, "weights": weights,
                "candidate_nodes": 120000, "baseline_margins": (120, 240, 360), "score_scale": 600.0,
                "development": {"id": "development", "population": "development", "input": input_path, "anchor_dir": development, "rescue_dir": development, "population_manifest": None, "context": fake_context("development")},
            }
            previous = store / "evals" / "previous-run"
            (previous / "search").mkdir(parents=True)
            source_manifest = {
                "schema": campaign.MANIFEST_SCHEMA,
                "probe": {"sha256": "wrong", "size": 1}, "weights": campaign.file_identity(weights),
                "candidate_nodes": 120000, "baseline_margins": [120, 240, 360], "score_scale": 600.0,
                "development": campaign.context_identity(current["development"]),
            }
            (previous / "campaign_manifest.json").write_text(json.dumps(source_manifest), encoding="utf-8")
            with self.assertRaisesRegex(campaign.CampaignError, "incompatible probe"):
                campaign.resolve_initial_evaluation(current, {"campaign_run_id": "previous-run", "evaluation_id": "candidate-0007"})

    def test_reuse_contract_accepts_identical_rescue_evidence_at_different_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe, weights = root / "probe", root / "weights"
            probe.write_text("probe", encoding="utf-8")
            weights.write_text("weights", encoding="utf-8")
            input_path = root / "input.csv"
            input_path.write_text("fen\n", encoding="utf-8")
            development = root / "development"
            development.mkdir()
            current_context = fake_context("development")
            current_context.rescue = fake_rescue("/new/store/development/rescue")
            current = {
                "probe": probe, "weights": weights, "candidate_nodes": 120000,
                "baseline_margins": (120, 240, 360), "score_scale": 600.0,
                "development": {"id": "development", "population": "development", "input": input_path,
                                "anchor_dir": development, "rescue_dir": development, "population_manifest": None,
                                "context": current_context},
            }
            source_development = campaign.context_identity(current["development"])
            source_development["rescue"] = fake_rescue("/old/store/development/rescue")
            source = {
                "probe": campaign.file_identity(probe), "weights": campaign.file_identity(weights),
                "candidate_nodes": 120000, "baseline_margins": [120, 240, 360], "score_scale": 600.0,
                "development": source_development,
            }
            campaign.require_reuse_contract(source, current, "previous-run")

    def test_campaign_injects_reused_margins_without_manual_initial_tuple(self) -> None:
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
                "schema": campaign.SCHEMA, "store_root": str(store), "run_id": "next-run",
                "artifacts": {"probe": str(probe), "weights": str(weights)},
                "candidate_nodes": 120000, "baseline_margins": [120, 240, 360], "score_scale": 600, "report_every": 100,
                "development": {"id": "development", "kind": "single", "path": "development"},
                "selection": [{"id": "selection", "kind": "sharded", "path": "selection"}],
                "pareto_search": {
                    "max_proposals": 2, "workers": 1, "seed": 7, "perturbation_c": 40,
                    "perturbation_gamma": 0.101, "max_margin": 1000,
                    "semantic_filters": [{"metric": "winning_mate_missed", "discard_worst_fraction": 0.25}],
                },
                "validation": None,
                "initial_evaluation": {"campaign_run_id": "previous-run", "evaluation_id": "candidate-0007"},
            }
            path = root / "campaign.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            seed = {"campaign_run_id": "previous-run", "evaluation_id": "candidate-0007", "margins": [0, 25, 139], "source_output_path": "/tmp/source.jsonl", "source_output": {"sha256": "x", "size": 1}}
            with patch.object(campaign.optimize_futility, "load_anchor", side_effect=lambda _config, label, *_args: fake_context(label)), \
                 patch.object(campaign, "resolve_initial_evaluation", return_value=seed):
                settings = campaign.load_campaign(path)
            self.assertEqual(settings["pareto_search"]["initial_margins"], [0, 25, 139])
            self.assertEqual(settings["initial_evaluation"], seed)


if __name__ == "__main__":
    unittest.main()
