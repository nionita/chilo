from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_futility_margin_analysis as runner


class MarginAnalysisRunnerTest(unittest.TestCase):
    def write_fixture(self, directory: Path) -> tuple[Path, Path]:
        analyzer = directory / "analyzer"
        weights = directory / "net.bin"
        sites = directory / "sites.fen"
        analyzer.write_bytes(b"analyzer")
        weights.write_bytes(b"weights")
        sites.write_text("fen one\nfen two\nfen three\n", encoding="utf-8")
        digest = hashlib.sha256(sites.read_bytes()).hexdigest()
        Path(str(sites) + ".manifest.json").write_text(
            json.dumps({"output": {"sha256": digest}}), encoding="utf-8"
        )
        config = directory / "config.json"
        config.write_text(json.dumps({
            "analyzer": str(analyzer), "input": str(sites), "weights": str(weights),
            "target_depth": 2, "previous_margins": [75], "max_fens": 2,
            "sample_seed": 9, "report_every": 1,
        }), encoding="utf-8")
        return config, directory / "run"

    def test_new_freezes_reservoir_and_resume_reuses_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config, run = self.write_fixture(Path(temporary))
            process = mock.Mock(returncode=0)
            with mock.patch.object(runner.subprocess, "run", return_value=process) as call:
                self.assertEqual(runner.main(["--config", str(config), "--run-dir", str(run), "--new"]), 0)
                selected = (run / "selected.fens").read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(selected), 2)
                manifest = json.loads((run / "analysis_manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["selected_count"], 2)
                self.assertEqual(manifest["target_depth"], 2)
                self.assertIn("--previous-margins", call.call_args.args[0])
                self.assertEqual(runner.main(["--config", str(config), "--run-dir", str(run), "--resume"]), 0)
                self.assertEqual((run / "selected.fens").read_text(encoding="utf-8").splitlines(), selected)

    def test_rejects_collector_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config, _ = self.write_fixture(Path(temporary))
            sites = Path(temporary) / "sites.fen"
            sites.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "SHA-256"):
                runner.load_settings(config)


if __name__ == "__main__":
    unittest.main()
