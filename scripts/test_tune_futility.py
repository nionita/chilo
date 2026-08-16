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
) -> dict[str, object]:
    return {
        "type": "position",
        "source": source,
        "line": line,
        "fen": fen,
        "futility_margins": margins,
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


def probe_result(records: list[dict[str, object]], margins: list[int], nodes: int) -> dict[str, object]:
    return {
        "positions": {tune_futility.record_key(record): record for record in records},
        "summary": {
            "type": "summary",
            "positions": len(records),
            "futility_margins": margins,
            "node_limit": nodes,
        },
    }


def write_probe_output(path: Path, records: list[dict[str, object]], margins: list[int], nodes: int) -> None:
    summary = {
        "type": "summary",
        "positions": len(records),
        "futility_margins": margins,
        "node_limit": nodes,
    }
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records) + json.dumps(summary) + "\n",
        encoding="utf-8",
    )


class ConfigExpansionTest(unittest.TestCase):
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
        )
        self.assertEqual(command[1:5], ["--nodes", "1234", "--futility-margins", "100,300"])
        self.assertIn("--overwrite", command)
        self.assertIn("--weights", command)
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
    def test_computes_paired_proxy_metrics(self) -> None:
        reference_margins = [120, 320, 550]
        candidate_margins = [100, 300, 500]
        nodes = 1000
        fens = ["fen-one", "fen-two", "fen-terminal"]
        reference = probe_result(
            [
                position_record("input", 1, fens[0], reference_margins, 4000, move="e2e4", score=20, depth=9),
                position_record("input", 2, fens[1], reference_margins, 4000, move="d2d4", score=29000, depth=8),
                position_record("input", 3, fens[2], reference_margins, 4000, terminal=True),
            ],
            reference_margins,
            4000,
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
                position_record("input", 2, fens[1], candidate_margins, nodes, move="g1f3", score=0, depth=7),
                position_record("input", 3, fens[2], candidate_margins, nodes, terminal=True),
            ],
            candidate_margins,
            nodes,
        )

        metrics = tune_futility.compute_metrics(reference, baseline, candidate, nodes)
        self.assertEqual(metrics["evaluated_positions"], 2)
        self.assertEqual(metrics["move_agreement_rate"], 0.5)
        self.assertEqual(metrics["score_mae"], 10.0)
        self.assertEqual(metrics["mate_class_agreement_rate"], 0.5)
        self.assertEqual(metrics["mean_completed_depth"], 7.0)
        self.assertEqual(metrics["mean_depth_delta_vs_baseline"], 1.0)
        self.assertEqual(metrics["cap_hit_rate"], 1.0)
        self.assertEqual(metrics["futility_prunes"][:3], [2, 4, 6])

    def test_pareto_selection_ranks_all_candidates(self) -> None:
        def candidate(identifier: str, margins: list[int], agreement: float, mae: float, depth: float) -> dict:
            return {
                "id": identifier,
                "margins": margins,
                "origins": [identifier],
                "metrics": {
                    "move_agreement_rate": agreement,
                    "score_mae": mae,
                    "mean_completed_depth": depth,
                },
            }

        candidates = [
            candidate("a", [100], 0.90, 10.0, 6.0),
            candidate("b", [120], 0.85, 8.0, 7.0),
            candidate("c", [140], 0.80, 20.0, 5.0),
            candidate("d", [160], 0.95, 9.0, 5.0),
        ]
        shortlist = tune_futility.rank_and_select(candidates, 2)
        self.assertEqual(len(shortlist), 2)
        self.assertGreater(candidates[2]["pareto_rank"], 1)
        self.assertTrue(all("pareto_rank" in item for item in candidates))
        self.assertEqual(sum(bool(item["selected"]) for item in candidates), 2)


class ResumeTest(unittest.TestCase):
    def test_explicit_resume_requires_identical_manifest(self) -> None:
        manifest = {"schema": tune_futility.SCHEMA, "value": 1}
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            tune_futility.prepare_run_directory(run_dir, manifest, False)
            tune_futility.prepare_run_directory(run_dir, manifest, True)
            with self.assertRaisesRegex(tune_futility.TuningError, "does not match"):
                tune_futility.prepare_run_directory(
                    run_dir,
                    {"schema": tune_futility.SCHEMA, "value": 2},
                    True,
                )

    def test_new_run_rejects_nonempty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "existing").write_text("data", encoding="utf-8")
            with self.assertRaisesRegex(tune_futility.TuningError, "not empty"):
                tune_futility.prepare_run_directory(run_dir, {"schema": tune_futility.SCHEMA}, False)


if __name__ == "__main__":
    unittest.main()
