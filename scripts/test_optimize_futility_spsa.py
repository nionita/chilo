from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import optimize_futility_spsa
from test_optimize_futility import OptimizerAdapterTest


class SpsaAdapterTest(unittest.TestCase):
    def test_loads_explicit_schedules_and_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor"
            OptimizerAdapterTest().write_per_root_anchor(anchor)
            probe, inputs, weights = root / "probe", root / "positions.csv", root / "net.bin"
            for path in (probe, inputs, weights):
                path.write_text("test", encoding="utf-8")
            config = {"probe": str(probe), "inputs": [str(inputs)], "weights": str(weights), "candidate_nodes": 100, "baseline_margins": [120, 240, 360], "development": {"reference_dir": str(anchor), "contract": "per_root_v1"}, "spsa": {"tracks": [{"id": "d3", "margins": [120, 240, 360]}], "iterations": 2, "workers": 2, "subset_fraction": 0.5, "seed": 7, "gain_a": 40, "stability_A": 4, "gain_alpha": 0.602, "perturbation_c": 40, "perturbation_gamma": 0.101, "objective_scale": 1000, "max_margin": 1000}}
            path = root / "spsa.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            settings = optimize_futility_spsa.load_settings(path)
            self.assertEqual(settings.tracks, (("d3", (120, 240, 360)),))
            self.assertEqual(optimize_futility_spsa.sample_keys(settings, "d3", 0), optimize_futility_spsa.sample_keys(settings, "d3", 0))
            self.assertEqual(optimize_futility_spsa.manifest(settings)["spsa"]["workers"], 2)


if __name__ == "__main__":
    unittest.main()
