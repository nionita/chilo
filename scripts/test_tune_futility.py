from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import tune_futility


def position_record(
    source: str,
    line: int,
    fen: str,
    margins: list[int],
    nodes: int,
    *,
    move: str = "e2e4",
    score: int = 0,
    depth: int = 6,
    terminal: bool = False,
    all_root_scores: bool = False,
    root_scores: object = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "type": "position",
        "source": source,
        "line": line,
        "fen": fen,
        "futility_margins": margins,
        "all_root_scores": all_root_scores,
        "node_limit": nodes,
        "nodes": 0 if terminal else nodes,
        "completed_nodes": 0 if terminal else nodes - 10,
        "completed_depth": 0 if terminal else depth,
        "elapsed_ms": 5,
        "iteration_interrupted": not terminal,
        "terminal": terminal,
        "has_move": not terminal,
        "bestmove": "0000" if terminal else move,
        "score": score,
        "pv": [] if terminal else [move],
        "futility_prunes": [0, 0, 0, 0, 0, 0, 0] if terminal else [1, 2, 3, 0, 0, 0, 0],
        "futility_prunes_in_check": [0, 0, 0, 0, 0, 0, 0] if terminal else [0, 1, 0, 0, 0, 0, 0],
    }
    if all_root_scores and not terminal and depth > 0:
        record["root_scores"] = root_scores if root_scores is not None else {move: score}
    return record


def probe_result(
    records: list[dict[str, object]], margins: list[int], nodes: int, all_root_scores: bool = False
) -> dict[str, object]:
    return {
        "positions": {tune_futility.record_key(record): record for record in records},
        "summary": {
            "type": "summary",
            "positions": len(records),
            "futility_margins": margins,
            "node_limit": nodes,
            "all_root_scores": all_root_scores,
        },
    }


def write_probe_output(
    path: Path, records: list[dict[str, object]], margins: list[int], nodes: int, all_root_scores: bool = False
) -> None:
    summary = {
        "type": "summary",
        "positions": len(records),
        "futility_margins": margins,
        "node_limit": nodes,
        "all_root_scores": all_root_scores,
    }
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records) + json.dumps(summary) + "\n",
        encoding="utf-8",
    )


class ConfigExpansionTest(unittest.TestCase):
    def test_anchor_phase_can_expand_config_without_candidates(self) -> None:
        config = {
            "candidate_nodes": 100,
            "reference_nodes": 200,
            "baseline_margins": [120],
        }
        expanded = tune_futility.expand_config(config, require_candidates=False)
        self.assertEqual(expanded["candidates"], [])
        with self.assertRaisesRegex(tune_futility.TuningError, "produced no"):
            tune_futility.expand_config(config)

    def test_expands_deduplicates_and_discards_invalid_formula_results(self) -> None:
        expanded = tune_futility.expand_config(
            {
                "candidate_nodes": 1000,
                "reference_nodes": 4000,
                "baseline_margins": [120, 320, 550],
                "explicit_candidates": [[100, 300, 500], [100, 300, 500], [120, 320, 550]],
                "families": [
                    {
                        "type": "linear",
                        "depths": [3],
                        "slopes": [100],
                        "intercepts": [0, -150],
                    },
                    {
                        "type": "power",
                        "depths": [3],
                        "scales": [100],
                        "exponents": [1.5],
                    },
                ],
            }
        )

        tuples = [candidate["margins"] for candidate in expanded["candidates"]]
        self.assertEqual(expanded["shortlist_size"], 15)
        self.assertEqual(tuples.count([100, 300, 500]), 1)
        self.assertIn([100, 200, 300], tuples)
        self.assertIn([100, 283, 520], tuples)
        self.assertTrue(any(item["reason"] == "baseline" for item in expanded["discarded"]))
        self.assertTrue(any(">= 0" in item["reason"] for item in expanded["discarded"]))

    def test_rejects_decreasing_explicit_tuple(self) -> None:
        with self.assertRaisesRegex(tune_futility.TuningError, "nondecreasing"):
            tune_futility.expand_config(
                {
                    "candidate_nodes": 100,
                    "reference_nodes": 200,
                    "baseline_margins": [120, 320, 550],
                    "explicit_candidates": [[100, 90]],
                }
            )

    def test_rejects_unknown_fields(self) -> None:
        with self.assertRaisesRegex(tune_futility.TuningError, "unknown config"):
            tune_futility.expand_config(
                {
                    "candidate_nodes": 100,
                    "reference_nodes": 200,
                    "baseline_margins": [120],
                    "explicit_candidates": [[100]],
                    "candidate_node": 10,
                }
            )

    def test_score_scale_and_execution_defaults_are_expanded(self) -> None:
        expanded = tune_futility.expand_config(
            {
                "candidate_nodes": 100,
                "reference_nodes": 200,
                "baseline_margins": [120],
                "explicit_candidates": [[100]],
                "score_scale": 750,
                "probe": "bin/futility_probe",
                "inputs": ["positions.fen"],
                "weights": "net.bin",
            }
        )
        self.assertEqual(expanded["score_scale"], 750.0)
        self.assertEqual(expanded["probe"], "bin/futility_probe")
        self.assertEqual(expanded["inputs"], ["positions.fen"])

    def test_cli_execution_artifacts_override_config_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            expanded = {"probe": "config-probe", "inputs": ["config.fen"], "weights": "config.bin"}
            args = tune_futility.argparse.Namespace(
                probe="cli-probe", input=["cli.fen"], weights="cli.bin", no_weights=False
            )
            probe, inputs, weights = tune_futility.resolve_effective_artifacts(config_path, expanded, args)
            self.assertEqual(probe, Path("cli-probe").resolve())
            self.assertEqual(inputs, [Path("cli.fen").resolve()])
            self.assertEqual(weights, Path("cli.bin").resolve())
            args.no_weights = True
            _, _, weights = tune_futility.resolve_effective_artifacts(config_path, expanded, args)
            self.assertIsNone(weights)


class ProbeContractTest(unittest.TestCase):
    def test_builds_probe_command(self) -> None:
        command = tune_futility.build_probe_command(
            Path("probe"),
            [Path("one.fen"), Path("two.csv")],
            Path("net.bin"),
            1234,
            [100, 300],
            Path("result.jsonl"),
            50,
            all_root_scores=True,
        )
        self.assertEqual(command[1:5], ["--nodes", "1234", "--futility-margins", "100,300"])
        self.assertIn("--overwrite", command)
        self.assertIn("--weights", command)
        self.assertIn("--all-root-scores", command)
        self.assertTrue(command[-1].endswith("two.csv"))

    def test_parses_complete_output_and_rejects_mismatched_position(self) -> None:
        margins = [100, 300]
        nodes = 1000
        record = position_record("input.fen", 1, "fen", margins, nodes)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.jsonl"
            write_probe_output(path, [record], margins, nodes)
            parsed = tune_futility.parse_probe_output(path, nodes, margins)
            self.assertEqual(len(parsed["positions"]), 1)
            record["node_limit"] = 999
            write_probe_output(path, [record], margins, nodes)
            with self.assertRaisesRegex(tune_futility.TuningError, "position does not match"):
                tune_futility.parse_probe_output(path, nodes, margins)

    def test_rejects_incomplete_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.jsonl"
            path.write_text(
                json.dumps(position_record("input.fen", 1, "fen", [100], 100)) + "\n",
                encoding="utf-8",
            )
            self.assertFalse(tune_futility.probe_output_complete(path, 100, [100]))

    def test_reference_requires_root_scores_but_candidates_forbid_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.jsonl"
            reference = position_record(
                "input", 1, "fen", [100], 100, score=10, all_root_scores=True, root_scores={"e2e4": 10}
            )
            write_probe_output(path, [reference], [100], 100, all_root_scores=True)
            tune_futility.parse_probe_output(path, 100, [100], all_root_scores=True)
            reference.pop("root_scores")
            write_probe_output(path, [reference], [100], 100, all_root_scores=True)
            with self.assertRaisesRegex(tune_futility.TuningError, "root_scores"):
                tune_futility.parse_probe_output(path, 100, [100], all_root_scores=True)

            candidate = position_record("input", 1, "fen", [100], 100)
            candidate["root_scores"] = {"e2e4": 10}
            write_probe_output(path, [candidate], [100], 100)
            with self.assertRaisesRegex(tune_futility.TuningError, "must not contain root_scores"):
                tune_futility.parse_probe_output(path, 100, [100])

    @mock.patch("tune_futility.subprocess.run")
    def test_failed_probe_job_is_reported(self, run_mock: mock.Mock) -> None:
        run_mock.return_value.returncode = 7
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "probes").mkdir()
            (run_dir / "logs").mkdir()
            with self.assertRaisesRegex(tune_futility.TuningError, "failed"):
                tune_futility.run_probe_job(
                    {"id": "candidate", "nodes": 100, "margins": [100]},
                    Path("probe"),
                    [Path("input.fen")],
                    None,
                    0,
                    run_dir,
                    False,
                )


class MetricsAndRankingTest(unittest.TestCase):
    def test_normalized_score_maps_mates_and_scales_centipawns(self) -> None:
        self.assertEqual(tune_futility.normalized_score(29000, 600), 1.0)
        self.assertEqual(tune_futility.normalized_score(-29000, 600), -1.0)
        self.assertEqual(tune_futility.normalized_score(0, 600), 0.0)
        self.assertGreater(tune_futility.normalized_score(100, 600), 0.0)
    def test_computes_score_regret_metrics_and_mate_diagnostics(self) -> None:
        reference_margins = [120, 320, 550]
        candidate_margins = [100, 300, 500]
        nodes = 1000
        fens = ["fen-one", "fen-two", "fen-terminal"]
        reference = probe_result(
            [
                position_record(
                    "input", 1, fens[0], reference_margins, 4000, move="e2e4", score=20, depth=9,
                    all_root_scores=True, root_scores={"e2e4": 20, "d2d4": 10},
                ),
                position_record(
                    "input", 2, fens[1], reference_margins, 4000, move="d2d4", score=29000, depth=8,
                    all_root_scores=True, root_scores={"d2d4": 29000, "g1f3": 0},
                ),
                position_record("input", 3, fens[2], reference_margins, 4000, terminal=True),
            ],
            reference_margins,
            4000,
            all_root_scores=True,
        )
        baseline = probe_result(
            [
                position_record("input", 1, fens[0], reference_margins, nodes, move="e2e4", score=25, depth=6),
                position_record("input", 2, fens[1], reference_margins, nodes, move="d2d4", score=28999, depth=6),
                position_record("input", 3, fens[2], reference_margins, nodes, terminal=True),
            ],
            reference_margins,
            nodes,
        )
        candidate = probe_result(
            [
                position_record("input", 1, fens[0], candidate_margins, nodes, move="e2e4", score=30, depth=7),
                position_record("input", 2, fens[1], candidate_margins, nodes, move="g1f3", score=29000, depth=7),
                position_record("input", 3, fens[2], candidate_margins, nodes, terminal=True),
            ],
            candidate_margins,
            nodes,
        )

        metrics = tune_futility.compute_metrics(reference, baseline, candidate, nodes)
        self.assertEqual(metrics["evaluated_positions"], 2)
        self.assertEqual(metrics["move_agreement_rate"], 0.5)
        self.assertEqual(metrics["score_mae"], 10.0)
        self.assertEqual(metrics["missed_reference_winning_mate_rate"], 1.0)
        self.assertEqual(metrics["candidate_mate_claim_categories"]["non_mate"], 1)
        self.assertEqual(metrics["candidate_mate_claim_categories"]["winning_unconfirmed"], 1)
        self.assertGreater(metrics["mean_normalized_regret"], 0.49)
        self.assertEqual(metrics["mean_completed_depth"], 7.0)
        self.assertEqual(metrics["mean_depth_delta_vs_baseline"], 1.0)
        self.assertEqual(metrics["cap_hit_rate"], 1.0)
        self.assertEqual(metrics["futility_prunes"][:3], [2, 4, 6])

    def test_scalar_regret_selection_uses_documented_tie_breakers(self) -> None:
        def candidate(identifier: str, margins: list[int], mean: float, p90: float, median: float) -> dict:
            return {
                "id": identifier,
                "margins": margins,
                "origins": [identifier],
                "metrics": {
                    "mean_normalized_regret": mean,
                    "p90_normalized_regret": p90,
                    "median_normalized_regret": median,
                },
            }

        candidates = [
            candidate("a", [100], 0.10, 0.20, 0.10),
            candidate("b", [120], 0.10, 0.10, 0.20),
            candidate("c", [140], 0.20, 0.01, 0.01),
            candidate("d", [160], 0.10, 0.10, 0.20),
        ]
        shortlist = tune_futility.rank_and_select(candidates, 2)
        self.assertEqual(len(shortlist), 2)
        self.assertEqual(shortlist[0]["id"], "b")
        self.assertEqual(shortlist[1]["id"], "d")
        self.assertTrue(all("regret_rank" in item for item in candidates))
        self.assertEqual(sum(bool(item["selected"]) for item in candidates), 2)


class PhaseManifestTest(unittest.TestCase):
    def test_anchor_manifest_is_stable_when_candidate_families_change(self) -> None:
        anchor = {"schema": tune_futility.ANCHOR_SCHEMA, "probe": {"sha256": "one"}}
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            tune_futility.prepare_run_directory(run_dir)
            tune_futility.ensure_anchor_manifest(run_dir, anchor)
            tune_futility.require_anchor_manifest(run_dir, anchor)
            tune_futility.ensure_anchor_manifest(run_dir, anchor)
            with self.assertRaisesRegex(tune_futility.TuningError, "does not match"):
                tune_futility.require_anchor_manifest(
                    run_dir, {"schema": tune_futility.ANCHOR_SCHEMA, "probe": {"sha256": "two"}}
                )

    def test_candidates_manifest_records_reference_score_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            tune_futility.prepare_run_directory(run_dir)
            anchor_path = run_dir / "anchor_manifest.json"
            reference_path = run_dir / "probes" / "reference.jsonl"
            baseline_path = run_dir / "probes" / "baseline.jsonl"
            anchor_path.write_text("{}", encoding="utf-8")
            reference_path.write_text("reference root scores", encoding="utf-8")
            baseline_path.write_text("baseline", encoding="utf-8")
            expanded = {
                "score_scale": 600.0,
                "shortlist_size": 1,
                "candidates": [{"id": "candidate", "margins": [100], "origins": ["test"]}],
                "discarded": [],
            }
            manifest = tune_futility.build_candidates_manifest(run_dir, expanded)
            self.assertEqual(manifest["schema"], tune_futility.CANDIDATES_SCHEMA)
            self.assertEqual(manifest["reference_root_scores"]["path"], str(reference_path.resolve()))
            self.assertIn("sha256", manifest["reference_root_scores"])

    def test_legacy_single_manifest_layout_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(tune_futility.TuningError, "older single-manifest"):
                tune_futility.prepare_run_directory(run_dir)


if __name__ == "__main__":
    unittest.main()
