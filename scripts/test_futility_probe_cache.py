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

import futility_probe_cache as cache
import optimize_futility_gated as pareto
import run_futility_validation_batch as batch
from test_tune_futility import position_record, write_probe_output


class ProbeCacheTest(unittest.TestCase):
    def make_files(self, root: Path) -> tuple[Path, Path, Path, list[int], int]:
        probe, weights, inputs = root / "probe", root / "net", root / "positions.csv"
        probe.write_text("probe", encoding="utf-8")
        weights.write_text("weights", encoding="utf-8")
        inputs.write_text("fen\n", encoding="utf-8")
        return probe, weights, inputs, [1, 2, 3], 100

    def write_output(self, path: Path, margins: list[int], nodes: int) -> None:
        write_probe_output(path, [position_record("positions.csv", 1, "fen", margins, nodes)], margins, nodes)

    def test_key_is_path_independent_but_binds_search_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe, weights, inputs, margins, nodes = self.make_files(root)
            first = cache.descriptor(probe, weights, [inputs], nodes, margins)
            other_root = root / "other"
            other_root.mkdir()
            copied_probe, copied_weights, copied_inputs = other_root / "probe", other_root / "net", other_root / "positions.csv"
            copied_probe.write_bytes(probe.read_bytes())
            copied_weights.write_bytes(weights.read_bytes())
            copied_inputs.write_bytes(inputs.read_bytes())
            second = cache.descriptor(copied_probe, copied_weights, [copied_inputs], nodes, margins)
            self.assertEqual(cache.key_for(first), cache.key_for(second))
            self.assertNotEqual(cache.key_for(first), cache.key_for(cache.descriptor(probe, weights, [inputs], nodes + 1, margins)))
            self.assertNotEqual(cache.key_for(first), cache.key_for(cache.descriptor(probe, weights, [inputs], nodes, [1, 2, 4])))

    def test_publish_then_restore_is_immutable_and_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe, weights, inputs, margins, nodes = self.make_files(root)
            source, staged = root / "source.jsonl", root / "run" / "candidate.jsonl"
            self.write_output(source, margins, nodes)
            value = cache.descriptor(probe, weights, [inputs], nodes, margins)
            entry = cache.entry_for(root / "cache", value)
            with cache.lock(root / "cache", entry.key):
                cache.publish(entry, source, nodes, margins)
            cache.restore(entry, staged, nodes, margins)
            self.assertEqual(source.read_bytes(), staged.read_bytes())
            staged.write_text("corrupt\n", encoding="utf-8")
            cache.validate(entry, nodes, margins)
            self.assertNotEqual(entry.output.read_bytes(), staged.read_bytes())

    def test_rejects_corrupt_existing_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe, weights, inputs, margins, nodes = self.make_files(root)
            source = root / "source.jsonl"
            self.write_output(source, margins, nodes)
            entry = cache.entry_for(root / "cache", cache.descriptor(probe, weights, [inputs], nodes, margins))
            with cache.lock(root / "cache", entry.key):
                cache.publish(entry, source, nodes, margins)
            entry.output.write_text("corrupt\n", encoding="utf-8")
            with self.assertRaisesRegex(cache.CacheError, "output differs"):
                cache.validate(entry, nodes, margins)

    def test_pareto_probe_promotes_then_reuses_a_completed_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe, weights, inputs, margins, nodes = self.make_files(root)
            run_dir = root / "campaign"
            (run_dir / "probes").mkdir(parents=True)
            (run_dir / "logs").mkdir()
            output = run_dir / "probes" / "candidate-0004.jsonl"
            self.write_output(output, margins, nodes)
            settings = SimpleNamespace(
                probe=probe, weights=weights, inputs=(inputs,), candidate_nodes=nodes,
                probe_report_every=0, probe_cache_dir=root / "cache",
            )
            pareto.probe_one(settings, run_dir, "candidate-0004", tuple(margins))
            receipt = json.loads((run_dir / "logs" / "candidate-0004.cache.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "promoted_existing_output")
            output.unlink()
            with patch.object(pareto.subprocess, "run") as run_probe:
                pareto.probe_one(settings, run_dir, "candidate-0004", tuple(margins))
            run_probe.assert_not_called()
            self.assertTrue(output.is_file())
            receipt = json.loads((run_dir / "logs" / "candidate-0004.cache.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "hit")

    def test_validation_probe_hits_the_same_raw_cache_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe, weights, inputs, margins, nodes = self.make_files(root)
            candidate = {"id": "candidate", "margins": margins}
            shard = {"id": "shard", "input": inputs}
            settings = {
                "run_dir": root / "validation", "probe": probe, "weights": weights,
                "candidate_nodes": nodes, "report_every": 0, "probe_cache_dir": root / "cache",
            }
            source = root / "source.jsonl"
            self.write_output(source, margins, nodes)
            entry = cache.entry_for(settings["probe_cache_dir"], cache.descriptor(probe, weights, [inputs], nodes, margins))
            with cache.lock(settings["probe_cache_dir"], entry.key):
                cache.publish(entry, source, nodes, margins)
            with patch.object(batch.tune_futility, "run_probe_job") as run_probe:
                status = batch.run_candidate_probe(settings, candidate, shard)
            run_probe.assert_not_called()
            self.assertEqual(status, "cache-hit")
            staged = batch.candidate_output_path(settings["run_dir"], candidate["id"], shard["id"])
            self.assertEqual(staged.read_bytes(), source.read_bytes())


if __name__ == "__main__":
    unittest.main()
