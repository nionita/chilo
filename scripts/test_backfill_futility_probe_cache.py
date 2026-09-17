from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import backfill_futility_probe_cache as backfill
import futility_probe_cache as cache
import tune_futility
from test_tune_futility import position_record, write_probe_output


class BackfillProbeCacheTest(unittest.TestCase):
    def write_artifacts(self, root: Path) -> tuple[Path, Path, Path]:
        probe, weights, inputs = root / "probe", root / "weights", root / "input.csv"
        probe.write_text("probe", encoding="utf-8")
        weights.write_text("weights", encoding="utf-8")
        inputs.write_text("fen\n", encoding="utf-8")
        return probe, weights, inputs

    def write_output(self, path: Path, margins: list[int], nodes: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_probe_output(path, [position_record("input.csv", 1, "fen", margins, nodes)], margins, nodes)

    def invoke(self, arguments: list[str]) -> dict[str, object]:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(backfill.main(arguments), 0)
        return json.loads(stream.getvalue())

    def test_backfill_imports_campaign_and_batch_outputs_from_canonical_evals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary) / "store"
            evals = store / "evals"
            probe, weights, inputs = self.write_artifacts(Path(temporary))
            nodes, margins = 100, [1, 2, 3]

            campaign_run = evals / "campaign"
            campaign_output = campaign_run / "search" / "probes" / "candidate-0004.jsonl"
            self.write_output(campaign_output, margins, nodes)
            (campaign_run / "campaign_manifest.json").write_text(json.dumps({
                "schema": backfill.CAMPAIGN_SCHEMA, "probe": tune_futility.file_identity(probe),
                "weights": tune_futility.file_identity(weights), "candidate_nodes": nodes,
                "development": {"input": tune_futility.file_identity(inputs)},
            }), encoding="utf-8")
            (campaign_run / "search" / "state.json").write_text(json.dumps({
                "schema": "chilo.futility_pareto_search_state.v4",
                "evaluations": [{"id": "candidate-0004", "margins": margins}],
            }), encoding="utf-8")

            batch_run = evals / "batch"
            batch_output = batch_run / "candidates" / "candidate" / "shard" / "probes" / "candidate.jsonl"
            batch_margins = [2, 3, 4]
            self.write_output(batch_output, batch_margins, nodes)
            (batch_run / "batch_manifest.json").write_text(json.dumps({
                "schema": backfill.BATCH_SCHEMA, "probe": tune_futility.file_identity(probe),
                "weights": tune_futility.file_identity(weights), "candidate_nodes": nodes,
                "candidates": [{"id": "candidate", "margins": batch_margins}],
                "shards": [{"id": "shard", "input": tune_futility.file_identity(inputs)}],
            }), encoding="utf-8")

            dry = self.invoke(["--store-root", str(store), "--dry-run"])
            self.assertEqual(dry["summary"], {"would_import": 2})
            self.assertFalse((store / "candidate-probe-cache").exists())

            report_path = store / "reports" / "backfill.json"
            imported = self.invoke(["--store-root", str(store), "--report", str(report_path)])
            self.assertEqual(imported["summary"], {"imported": 2})
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["summary"], {"imported": 2})
            for tuple_margins in (margins, batch_margins):
                entry = cache.entry_for(
                    store / "candidate-probe-cache",
                    cache.descriptor(probe, weights, [inputs], nodes, tuple_margins),
                )
                cache.validate(entry, nodes, tuple_margins)

            repeated = self.invoke(["--store-root", str(store)])
            self.assertEqual(repeated["summary"], {"existing": 2})


if __name__ == "__main__":
    unittest.main()
