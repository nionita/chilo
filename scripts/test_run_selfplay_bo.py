"""Small game-outcome BO checks. Requires NumPy, tinibo v4 and the match binary."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import random
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import run_selfplay_bo as bo
import prepare_selfplay_bo_followup as followup
import prepare_selfplay_bo as preparation
from test_selfplay_match import BIN, ROOT, START, zero_net

TINIBO_ROOT = Path(os.environ.get("CHILO_TINIBO_ROOT", ROOT.parent / "tinibo")).resolve()


class Coordinates(unittest.TestCase):
    def test_repeat_budget_and_streak_exclude_bootstrap(self):
        c = {"measurements": 50, "repeat_policy": {"max_repeat_fraction": .14,
                                                 "max_consecutive_repeats": 1}}
        state = {"completed": 0, "observations": [{"margins": [1]}, {"margins": [1]}]}
        self.assertEqual(bo.repeat_status(c, state)["budget"], 7)  # exact decimal floor
        self.assertEqual(bo.repeat_status(c, state)["completed_repeats"], 0)
        state["observations"].append({"margins": [1]})
        state["completed"] = 1
        self.assertEqual(bo.repeat_status(c, state)["blocked_by"], ["consecutive_repeat_limit"])
        pool, status = bo.eligible_pool(c, state, [[1], [2]])
        self.assertEqual(pool, [[2]])
        self.assertEqual(status["excluded_measured_tuples"], 1)
        state["observations"].append({"margins": [2]})
        state["completed"] += 1
        self.assertTrue(bo.repeat_status(c, state)["repeats_allowed"])
        c["repeat_policy"]["max_repeat_fraction"] = 0
        self.assertEqual(bo.eligible_pool(c, state, [[1], [2], [3]])[0], [[3]])
        with self.assertRaisesRegex(bo.BOError, "no eligible new tuples"):
            bo.eligible_pool(c, state, [[1], [2]])

    def test_round_trip_and_depths(self):
        for n in range(1, 8):
            values = list(range(0, n*20, 20))
            self.assertEqual(bo.decode(bo.encode(values)), values)
        for values in ([20, 20], [20, 10], [-1, 5], [1.5, 4], [], [1]*8):
            with self.assertRaises(bo.BOError):
                bo.encode(values)
        with self.assertRaises(bo.BOError):
            bo.decode([1, 0.5])

    def test_cpp_checksum_float_format_and_strings(self):
        v = {"alpha": 0.00001, "large": 1e15, "name": "keep-1e-05", "zero": -0.0}
        expected = '{"alpha":1e-05,"large":1e+15,"name":"keep-1e-05","zero":-0.0}'
        self.assertEqual(bo.cpp_digest(v), bo.hashlib.sha256(expected.encode()).hexdigest())

    def test_actual_region_not_delta_rectangle(self):
        bounds = [[0, 20], [40, 80], [100, 180]]
        self.assertEqual(bo.delta_bounds(bounds), [[0, 20], [20, 80], [20, 140]])
        self.assertFalse(bo.in_region(bo.decode([20, 80, 140]), bounds))
        bo.check_bounds(bounds)
        with self.assertRaises(bo.BOError):
            bo.check_bounds([[4, 4], [0, 4]])

    def test_mixed_pool_replay_and_repeats(self):
        c = {"proposal_margin_bounds": [[0, 20], [30, 60], [90, 160]],
             "base": {"futility_margins": [10, 40, 120]},
             "pool": {"size": 100, "local_fraction": .8, "radius_fraction": .1}}
        observations = [{"margins": [10, 40, 120]}, {"margins": [0, 35, 100]}]
        one = bo.proposal_pool(c, random.Random(42), observations, [10, 40, 120])
        self.assertEqual(one, bo.proposal_pool(c, random.Random(42), observations, [10, 40, 120]))
        self.assertEqual(one[:2], [[10, 40, 120], [0, 35, 100]])
        self.assertEqual(len(one), 100)
        self.assertEqual(len(one), len(set(map(tuple, one))))
        self.assertTrue(all(bo.in_region(p, c["proposal_margin_bounds"]) for p in one))
        self.assertTrue(any(p[2] > 140 for p in one))  # broad component

    def test_finite_pool_and_fixed_proposal(self):
        c = {"proposal_margin_bounds": [[1, 1], [2, 2]],
             "base": {"futility_margins": [1, 2]},
             "pool": {"size": 10, "local_fraction": .8, "radius_fraction": .1}}
        self.assertEqual(bo.proposal_pool(c, random.Random(3), [], None), [[1, 2]])

    def test_opening_normalization(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "book.fen"
            path.write_text(START.replace("8/8/8/8", "11111111/8/8/8").replace("KQkq", "qkQK").replace("0 1", "0 0") + "\n")
            self.assertEqual(bo.opening_fens(path), [START])
            path.write_text(START + ' ; id "start"; hmvc 3; fmvn 0;\n')
            # Six-field FEN counters take precedence over following operations.
            self.assertEqual(bo.opening_fens(path), [START])
            path.write_text(" ".join(START.split()[:4]) + ' id "start"; hmvc 3; fmvn 0;\n')
            self.assertEqual(bo.opening_fens(path), [START.replace("0 1", "3 1")])


@unittest.skipUnless(BIN.exists(), "build selfplay_collect first")
@unittest.skipUnless((TINIBO_ROOT / "tinibo/__init__.py").exists() and
                     importlib.util.find_spec("numpy") is not None,
                     "game BO integration requires NumPy and sibling tinibo (or CHILO_TINIBO_ROOT)")
class Runner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        zero_net(self.root / "net.bin")
        (self.root / "book.fen").write_text(START + "\n7k/8/5K2/8/8/8/P7/8 b - - 0 1\n")
        self.raw = {
            "schema": bo.SCHEMA, "executable": str(BIN), "weights": "net.bin", "openings": "book.fen",
            "tinibo_path": str(TINIBO_ROOT),
            "base": {"name": "base", "futility_margins": [10, 20, 30]},
            "nodes": 300, "max_pairs": 2, "measurements": 2, "seed": 32,
            "model_margin_bounds": [[0, 40], [1, 80], [2, 120]],
            "proposal_margin_bounds": [[10, 10], [20, 20], [30, 30]],
            "pool": {"size": 12}, "model": {"gp_n_restarts": 1, "gp_max_iter": 3},
            "adjudication": {"maxmoves": 2, "resign": {"movecount": 0}, "draw": {"movecount": 0}}}
        self.cfg_path = self.root / "bo.json"
        self.save()
        c = bo.load_config(self.cfg_path)
        cfg = bo.match_config(c, [10, 20, 30], 11, "bootstrap")
        bo.atomic_json(self.root / "bootstrap.json", cfg)
        self.source = self.root / "bootstrap"
        subprocess.run([str(BIN), "--match-config", str(self.root / "bootstrap.json"),
                        "--run-dir", str(self.source)], check=True, capture_output=True, timeout=30)
        self.raw["bootstrap"] = [str(self.source)]
        self.save()
        self.run = self.root / "bo-run"

    def save(self):
        bo.atomic_json(self.cfg_path, self.raw)

    def config(self):
        return bo.load_config(self.cfg_path)

    def state(self):
        return bo.read_json(self.run / "state.json")

    def execute(self, **kwargs):
        bo.execute(self.cfg_path, self.run, **kwargs)

    def cli(self, command, extra=()):
        return [sys.executable, str(ROOT / "scripts/run_selfplay_bo.py"), command,
                "--run-dir", str(self.run)] + ([] if command in {"stop", "status"} else
                ["--config", str(self.cfg_path)]) + list(extra)

    def test_import_statistics_and_degenerate(self):
        o = bo.import_match(self.source, self.config())
        self.assertEqual(o["margins"], [10, 20, 30])
        self.assertTrue(o["degenerate"])
        self.assertEqual(o["noise_variance"], 0)
        self.assertEqual(o["result"]["score"], .5)
        self.assertEqual(o["y"], 0)

    def test_repeat_policy_validation_and_default(self):
        self.assertEqual(self.config()["repeat_policy"], bo.REPEAT_POLICY)
        for policy in ({"max_repeat_fraction": True}, {"max_repeat_fraction": -1},
                       {"max_repeat_fraction": 1.1}, {"max_repeat_fraction": float("inf")},
                       {"max_consecutive_repeats": True}, {"max_consecutive_repeats": -1},
                       {"unknown": 1}):
            self.raw["repeat_policy"] = policy
            with self.assertRaises((bo.BOError, ValueError)):
                self.save()
                self.config()

    def test_quota_and_streak_force_new_matches_after_repeat(self):
        self.raw.update(measurements=4, proposal_margin_bounds=[[10, 11], [20, 21], [30, 31]],
                        repeat_policy={"max_repeat_fraction": .25, "max_consecutive_repeats": 1})
        self.save()
        # Prefer a measured point if the driver permits one, independent of GP fit.
        from types import SimpleNamespace
        _, tinibo = bo.libraries(self.config())
        def ask(opt, candidates, return_info):
            seen = {tuple(x) for x in opt.get_state()["observations"]["x"]}
            point = next((p for p in candidates if tuple(p) in seen), candidates[0])
            return SimpleNamespace(x=point, mean=0, std=1, acquisition_value=-.5,
                                   diagnostics={"fit": {"length_scale": .005}})
        with patch.object(tinibo.BayesianOptimizer, "ask", ask):
            self.execute(max_evaluations=1)
            self.execute(resume=True)
        proposals = [bo.read_json(self.run / f"measurements/gamebo-{i:04d}/proposal.json") for i in range(4)]
        self.assertEqual([p["repeat"] for p in proposals], [True, False, False, False])
        self.assertIn("repeat_budget_exhausted", proposals[1]["repeat_status"]["blocked_by"])
        self.assertIn("consecutive_repeat_limit", proposals[1]["repeat_status"]["blocked_by"])
        self.assertEqual(bo.read_json(self.run / "report.json")["repeat_status"]["completed_repeats"], 1)
        self.assertEqual(len({o["seed"] for o in self.state()["observations"]}), 5)
        self.raw["repeat_policy"]["max_repeat_fraction"] = .5
        self.save()
        with self.assertRaisesRegex(bo.BOError, "fingerprint mismatch"):
            self.execute(resume=True)

    def test_no_repeat_finite_region_exhaustion_before_engine(self):
        self.raw["repeat_policy"] = {"max_repeat_fraction": 0}
        self.save()
        with patch.object(bo.subprocess, "Popen", side_effect=AssertionError("must not launch")):
            with self.assertRaisesRegex(bo.BOError, "no eligible new tuples"):
                self.execute()
        self.assertIsNone(self.state()["pending"])
        self.assertEqual(self.state()["completed"], 0)

    def test_streak_limit_recovers_after_new_match_and_pending_is_not_counted(self):
        self.raw.update(measurements=4, proposal_margin_bounds=[[10, 11], [20, 21], [30, 31]],
                        repeat_policy={"max_repeat_fraction": 1, "max_consecutive_repeats": 1})
        self.save()
        from types import SimpleNamespace
        _, tinibo = bo.libraries(self.config())
        def ask(opt, candidates, return_info):
            seen = {tuple(x) for x in opt.get_state()["observations"]["x"]}
            point = next((p for p in candidates if tuple(p) in seen), candidates[0])
            return SimpleNamespace(x=point, mean=0, std=1, acquisition_value=-.5,
                                   diagnostics={"fit": {"length_scale": .005}})
        with patch.object(tinibo.BayesianOptimizer, "ask", ask):
            with patch.object(bo.subprocess, "Popen", side_effect=OSError("crash")):
                with self.assertRaises(OSError):
                    self.execute()
            self.assertTrue(self.state()["pending"]["repeat"])
            self.assertEqual(bo.repeat_status(self.config(), self.state())["completed_repeats"], 0)
            self.execute(resume=True)
        proposals = [bo.read_json(self.run / f"measurements/gamebo-{i:04d}/proposal.json") for i in range(4)]
        self.assertEqual([p["repeat"] for p in proposals], [True, False, True, False])

    def prepare_followup(self, **kwargs):
        return followup.prepare(self.cfg_path, self.run, self.root / "followup.json",
                                self.root / "new-run", seed=45, **kwargs)

    def test_followup_keeps_replicates_and_remaining_budget(self):
        self.execute(max_evaluations=1)
        # Model an older source config whose manifest did not expand repeat_policy.
        manifest = bo.read_json(self.run / "manifest.json")
        manifest["config"].pop("repeat_policy")
        bo.atomic_json(self.run / "manifest.json", manifest)
        state = self.state()
        state["fingerprint"] = bo.digest(manifest)
        bo.atomic_json(self.run / "state.json", state)
        receipt = self.prepare_followup()
        cfg = bo.load_config(self.root / "followup.json")
        self.assertEqual(cfg["measurements"], 1)
        self.assertEqual(len(cfg["bootstrap"]), 2)
        self.assertEqual(receipt["repeat_budget"], 0)
        self.assertEqual(self.prepare_followup(), receipt)  # idempotent
        bo.execute(self.root / "followup.json", self.root / "new-run", dry_run=True)
        self.assertFalse((self.root / "new-run").exists())
        with self.assertRaisesRegex(bo.BOError, "refusing to overwrite"):
            self.prepare_followup(measurements=10)
        evidence = self.source / "games.jsonl"
        evidence.write_bytes(evidence.read_bytes()[:-1])
        with self.assertRaisesRegex(bo.BOError, "torn"):
            self.prepare_followup()

    def test_followup_rejects_active_or_pending_source(self):
        with patch.object(bo.subprocess, "Popen", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                self.execute()
        with bo.run_lock(self.run / "run.lock"):
            with self.assertRaisesRegex(bo.BOError, "locked"):
                self.prepare_followup()
        with self.assertRaisesRegex(bo.BOError, "pending match"):
            self.prepare_followup()
        self.assertFalse((self.root / "followup.json").exists())

    def test_followup_model_overrides_preserve_source_and_observations(self):
        self.execute(max_evaluations=1)
        original_state = (self.run / "state.json").read_bytes()
        original_manifest = (self.run / "manifest.json").read_bytes()
        with self.assertRaises((bo.BOError, ValueError)):
            self.prepare_followup(gp_length_scale_bounds=[.05, .01])
        self.assertFalse((self.root / "followup.json").exists())
        receipt = self.prepare_followup(gp_ard=True, gp_length_scale_bounds=[.05, 10])
        cfg = bo.load_config(self.root / "followup.json")
        self.assertTrue(cfg["model"]["gp_ard"])
        self.assertEqual(cfg["model"]["gp_length_scale_bounds"], [.05, 10])
        self.assertFalse(receipt["source_model"]["gp_ard"])
        self.assertEqual(receipt["model"], cfg["model"])
        self.assertEqual(receipt["config_sha256"], bo.digest(cfg))
        self.assertEqual(cfg["bootstrap"], [o["path"] for o in self.state()["observations"]])
        self.assertEqual((self.run / "state.json").read_bytes(), original_state)
        self.assertEqual((self.run / "manifest.json").read_bytes(), original_manifest)
        bo.execute(self.root / "followup.json", self.root / "new-run", dry_run=True)
        self.assertFalse((self.root / "new-run").exists())

    def extra_match(self, seed, values=(10, 20, 30)):
        path = self.root / f"extra-{seed}"
        cfg = path.with_suffix(".json")
        bo.atomic_json(cfg, bo.match_config(self.config(), list(values), seed, path.name))
        subprocess.run([str(BIN), "--match-config", str(cfg), "--run-dir", str(path)],
                       check=True, capture_output=True, timeout=30)
        return path

    def test_evidence_additive_collection_portability_and_new_pair_cap(self):
        self.execute(max_evaluations=1)
        store = self.root / "cloud-evidence"
        first = preparation.collect(self.config(), store, [self.run])
        self.assertEqual((first["added"], first["total"]), (2, 2))
        self.assertEqual(preparation.collect(self.config(), store, [self.run])["added"], 0)
        local = self.root / "local-evidence"
        shutil.copytree(store, local)
        self.source.rename(self.root / "removed-source")
        # Copied evidence must not depend on its former absolute source paths.
        self.assertEqual(preparation.collect(self.config(), local, [store])["total"], 2)
        third = self.extra_match(22)
        self.assertEqual(preparation.collect(self.config(), local, [third])["total"], 3)
        original = self.cfg_path.read_bytes()
        output = self.root / "configs/new.json"
        receipt = preparation.prepare(self.config(), local, output, seed=45, measurements=15,
                                      max_pairs=1500, gp_ard=True, gp_length_scale_bounds=[.05, 10])
        cfg = bo.load_config(output)
        self.assertEqual(len(cfg["bootstrap"]), 3)  # independent repeats retained
        self.assertEqual((cfg["measurements"], cfg["max_pairs"], cfg["seed"]), (15, 1500, 45))
        self.assertTrue(cfg["model"]["gp_ard"])
        self.assertEqual(cfg["model"]["gp_length_scale_bounds"], [.05, 10])
        self.assertEqual(receipt["config_sha256"], bo.digest(cfg))
        self.assertEqual(self.cfg_path.read_bytes(), original)
        self.assertFalse(Path(receipt["run_dir"]).exists())
        bo.execute(output, Path(receipt["run_dir"]), dry_run=True)

    def test_compact_bootstrap_without_journals_and_resume(self):
        store = self.root / "evidence"
        preparation.collect(self.config(), store)
        summary = self.root / "bootstrap-summary.json"
        spec = preparation.export_summary(self.config(), store, summary)
        output = self.root / "compact-config.json"
        receipt = preparation.prepare(self.config(), store, output, measurements=2,
                                      max_pairs=2, bootstrap_summary=summary)
        shutil.rmtree(store)
        shutil.rmtree(self.source)
        self.assertEqual(len(receipt["measurement_ids"]), 1)
        self.assertEqual(bo.load_config(output)["bootstrap"], [])
        root = self.root / "compact-run"
        bo.execute(output, root, max_evaluations=1)
        bo.execute(output, root, resume=True)
        self.assertEqual(bo.read_json(root / "state.json")["completed"], 2)
        # Collection retains new full journals; old compact bootstrap is not duplicated.
        collected = preparation.collect(bo.load_config(output), self.root / "new-store", [root])
        self.assertEqual(collected["total"], 2)
        summary.write_text(summary.read_text() + " ")
        with self.assertRaisesRegex(bo.BOError, "checksum"):
            bo.summary_observations(spec, self.config(), bo.match_contract(self.config()))

    def test_compact_bootstrap_contract_seed_and_statistics_checks(self):
        store = self.root / "evidence"
        preparation.collect(self.config(), store)
        path = self.root / "summary.json"
        preparation.export_summary(self.config(), store, path)
        original = bo.read_json(path)
        for change, message in ((lambda d: d["contract"].update(base=[1,2,3]), "contract"),
                                (lambda d: d["observations"].append(d["observations"][0]), "measurement ID"),
                                (lambda d: d["observations"][0].update(noise_variance=1), "variance")):
            data = copy.deepcopy(original); change(data); bo.atomic_json(path, data)
            with self.assertRaisesRegex(bo.BOError, message):
                bo.summary_observations({"path": str(path), "sha256": bo.identity(path)["sha256"]},
                                        self.config(), bo.match_contract(self.config()))

    def test_evidence_duplicate_seeds_rejected_before_index_changes(self):
        store = self.root / "evidence"
        preparation.collect(self.config(), store)
        original = (store / "index.json").read_bytes()
        another = self.extra_match(11, values=(11, 21, 31))
        with self.assertRaisesRegex(bo.BOError, "share an opening seed"):
            preparation.collect(self.config(), store, [self.extra_match(22), another])
        self.assertEqual((store / "index.json").read_bytes(), original)
        self.assertEqual(len(list((store / "measurements").iterdir())), 1)

    def test_evidence_tampering_and_contract_mismatch_rejected(self):
        store = self.root / "evidence"
        preparation.collect(self.config(), store)
        c = self.config()
        c["nodes"] += 1
        with self.assertRaisesRegex(bo.BOError, "incompatible evidence"):
            preparation.collect(c, store, [])
        folder = next((store / "measurements").iterdir())
        (folder / "games.jsonl").write_bytes(b"corrupt\n")
        with self.assertRaisesRegex(bo.BOError, "stored evidence changed"):
            preparation.prepare(self.config(), store, self.root / "new.json")
        self.assertFalse((self.root / "new.json").exists())

    def test_evidence_collects_only_committed_points_with_pending_match(self):
        self.execute(max_evaluations=1)
        with patch.object(bo.subprocess, "Popen", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                self.execute(resume=True)
        self.assertIsNotNone(self.state()["pending"])
        result = preparation.collect(self.config(), self.root / "evidence", [self.run])
        self.assertEqual(result["total"], 2)

    def test_evidence_relocated_bo_paths(self):
        self.execute(max_evaluations=1)
        state = self.state()
        for observed in state["observations"]:
            observed["path"] = observed["path"].replace(str(self.root), "/cloud/experiment", 1)
        bo.atomic_json(self.run / "state.json", state)
        store = self.root / "evidence"
        with self.assertRaisesRegex(bo.BOError, "use --path-map"):
            preparation.collect(self.config(), store, [self.run])
        result = preparation.collect(self.config(), store, [self.run],
                                     mappings=[(Path("/cloud/experiment"), self.root)])
        self.assertEqual(result["total"], 2)

    def test_evidence_orphan_recovery_and_relative_paths(self):
        store = self.root / "evidence"
        preparation.collect(self.config(), store)
        index = bo.read_json(store / "index.json")
        mid = next(iter(index["measurements"]))
        index["measurements"].pop(mid)
        bo.atomic_json(store / "index.json", index)  # emulate interrupted index commit
        self.assertEqual(preparation.collect(self.config(), store)["total"], 1)
        index = bo.read_json(store / "index.json")
        index["measurements"][mid]["path"] = "../bootstrap"
        bo.atomic_json(store / "index.json", index)
        with self.assertRaisesRegex(bo.BOError, "invalid evidence path"):
            preparation.collect(self.config(), self.root / "other", [store])

    def test_evidence_preparation_defaults_and_output_guards(self):
        store = self.root / "evidence"
        preparation.collect(self.config(), store)
        with self.assertRaises((bo.BOError, ValueError)):
            preparation.prepare(self.config(), store, self.root / "bad.json", gp_length_scale_bounds=[10, .05])
        self.assertFalse((self.root / "bad.json").exists())
        output = self.root / "configs/prepared.json"
        receipt = preparation.prepare(self.config(), store, output)
        self.assertIsInstance(receipt["seed"], int)
        self.assertEqual(receipt["run_dir"], str(self.root / "runs/prepared"))
        self.assertEqual(bo.load_config(output)["measurements"], 2)
        with self.assertRaisesRegex(bo.BOError, "refusing to overwrite"):
            preparation.prepare(self.config(), store, output)
        with self.assertRaisesRegex(bo.BOError, "not empty"):
            preparation.prepare(self.config(), store, self.root / "other.json", run_dir=self.source)

    def test_evidence_cli_machine_overrides_and_collect_without_numpy(self):
        raw = dict(self.raw)
        for key in ("executable", "weights", "openings", "tinibo_path"):
            raw[key] = "/other-machine/missing"
        remote = self.root / "remote.json"
        bo.atomic_json(remote, raw)
        store = self.root / "evidence"
        common = ["--config", str(remote), "--store", str(store),
                  "--executable", str(BIN), "--weights", str(self.root / "net.bin"),
                  "--openings", str(self.root / "book.fen"), "--tinibo-path", str(TINIBO_ROOT)]
        # -S disables site packages: collection needs only standard-library code.
        result = subprocess.run([sys.executable, "-S", str(ROOT / "scripts/prepare_selfplay_bo.py"),
                                 "collect", *common, "--source", str(self.source)],
                                check=True, capture_output=True, text=True, timeout=30)
        self.assertIn("total=1", result.stdout)
        output = self.root / "fresh.json"
        subprocess.run([sys.executable, str(ROOT / "scripts/prepare_selfplay_bo.py"),
                        "prepare", *common, "--output-config", str(output), "--seed", "91"],
                       check=True, capture_output=True, timeout=30)
        self.assertEqual(bo.load_config(output)["seed"], 91)

    def test_cpp_scientific_manifest_import(self):
        c = self.config()
        c["sprt"]["alpha"] = 1e-5
        cfg = bo.match_config(c, [10, 20, 30], 12, "name-1e-05")
        bo.atomic_json(self.root / "scientific.json", cfg)
        source = self.root / "scientific"
        subprocess.run([str(BIN), "--match-config", str(self.root / "scientific.json"),
                        "--run-dir", str(source)], check=True, capture_output=True, timeout=30)
        self.assertEqual(bo.import_match(source, c)["seed"], 12)

    def test_summary_and_journal_corruption(self):
        result_path = self.source / "results.json"
        original = bo.read_json(result_path)
        for key in ("score", "score_mean_variance", "wins", "elo", "llr", "pentanomial", "status"):
            changed = copy.deepcopy(original)
            changed[key] = "bad"
            bo.atomic_json(result_path, changed)
            bo.atomic_json(self.source / "status.json", changed)
            with self.assertRaises((bo.BOError, TypeError)):
                bo.import_match(self.source, self.config())
        bo.atomic_json(result_path, original)
        bo.atomic_json(self.source / "status.json", original)
        journal_path = self.source / "games.jsonl"
        original = journal_path.read_bytes()
        records = original.splitlines(keepends=True)
        g = json.loads(records[0])
        g["game"]["a_score"] = 0
        records[0] = (json.dumps(g) + "\n").encode()
        journal_path.write_bytes(b"".join(records))
        with self.assertRaisesRegex(bo.BOError, "checksum"):
            bo.import_match(self.source, self.config())
        journal_path.write_bytes(original[:-1])
        with self.assertRaisesRegex(bo.BOError, "torn"):
            bo.import_match(self.source, self.config())

    def test_import_contract_rejections(self):
        for key, value in (("nodes", 5000), ("base", {"name": "base", "futility_margins": [1]})):
            c = self.config()
            c[key] = value
            with self.assertRaisesRegex(bo.BOError, "incompatible"):
                bo.import_match(self.source, c)
        c = self.config()
        (self.root / "wrong-net.bin").write_bytes(b"wrong")
        c["weights"] = str(self.root / "wrong-net.bin")
        with self.assertRaisesRegex(bo.BOError, "weights"):
            bo.import_match(self.source, c)
        # Paths, names and pair caps are not the compatible-observation identity.
        c = self.config()
        c["base"]["name"] = "renamed"
        c["max_pairs"] = 1500
        self.assertEqual(bo.import_match(self.source, c)["result"]["pairs"], 2)

    def test_dry_run_dedup_and_no_execution(self):
        self.raw["bootstrap"] *= 2
        self.save()
        with patch.object(bo.subprocess, "Popen", side_effect=AssertionError("must not launch")):
            self.execute(dry_run=True)
        self.assertFalse(self.run.exists())

    def test_base_can_disable_futility_or_have_other_depth(self):
        for values in ([], [0], [30, 0, 10, 20, 0, 5, 0]):
            self.raw["base"]["futility_margins"] = values
            self.save()
            self.assertEqual(self.config()["base"]["futility_margins"], values)

    def test_duplicate_seed_bootstraps_rejected(self):
        c = self.config()
        cfg = bo.match_config(c, [11, 21, 31], 11, "second")
        bo.atomic_json(self.root / "second.json", cfg)
        source = self.root / "second"
        subprocess.run([str(BIN), "--match-config", str(self.root / "second.json"),
                        "--run-dir", str(source)], check=True, capture_output=True, timeout=30)
        self.raw["bootstrap"].append(str(source))
        self.save()
        with self.assertRaisesRegex(bo.BOError, "share a seed"):
            self.execute(dry_run=True)

    def test_recover_uncommitted_initial_engine_manifest(self):
        with patch.object(bo.subprocess, "Popen", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                self.execute()
        match = self.run / "measurements/gamebo-0000/match"
        match.mkdir()
        (match / "manifest.json.tmp").write_text('{"contract":')
        self.execute(resume=True, max_evaluations=1)
        self.assertEqual(self.state()["completed"], 1)

    def test_real_repeat_resume_and_new_seeds(self):
        self.execute(max_evaluations=1)
        one = self.state()
        self.assertEqual(one["completed"], 1)
        self.assertEqual(len(one["observations"]), 2)
        pending_config = bo.read_json(self.run / "measurements/gamebo-0000/match.json")
        proposal = bo.read_json(self.run / "measurements/gamebo-0000/proposal.json")
        self.assertTrue(proposal["repeat"])
        self.assertEqual(proposal["seed"], one["observations"][-1]["seed"])
        self.assertEqual(len(proposal["pool_sha256"]), 64)
        self.execute(resume=True)
        state = self.state()
        self.assertEqual(state["completed"], 2)
        self.assertEqual(len(state["observations"]), 3)
        self.assertEqual(len(set(o["seed"] for o in state["observations"])), 3)
        self.assertEqual(state["observations"][1]["margins"], state["observations"][2]["margins"])
        self.assertNotEqual(bo.read_json(self.run / "measurements/gamebo-0001/match.json")["openings"]["seed"],
                            pending_config["openings"]["seed"])
        self.execute(resume=True)
        self.assertEqual(state, self.state())
        self.assertEqual(bo.read_json(self.run / "report.json")["recommendation"]["margins"], [10, 20, 30])

    def test_crash_before_launch_and_after_result(self):
        with patch.object(bo.subprocess, "Popen", side_effect=OSError("injected crash before launch")):
            with self.assertRaisesRegex(OSError, "injected"):
                self.execute()
        reserved = self.state()["pending"]
        self.assertEqual(self.state()["completed"], 0)
        original = bo.import_match

        def crash_after(path, c, contract=None):
            o = original(path, c, contract)
            if Path(path) != self.source:
                raise bo.BOError("injected crash after result")
            return o

        with patch.object(bo, "import_match", side_effect=crash_after):
            with self.assertRaisesRegex(bo.BOError, "injected crash after"):
                self.execute(resume=True)
        self.assertEqual(self.state()["pending"], reserved)
        journal = (self.run / "measurements/gamebo-0000/match/games.jsonl").read_bytes()
        self.execute(resume=True, max_evaluations=1)
        self.assertEqual(len(self.state()["observations"]), 2)
        self.assertEqual(self.state()["observations"][-1]["seed"], reserved["seed"])
        self.assertEqual(journal, (self.run / "measurements/gamebo-0000/match/games.jsonl").read_bytes())

    def test_atomic_tell_recovery(self):
        original = bo.atomic_json

        def crash_save(path, value):
            if Path(path).name == "state.json" and value.get("completed") == 1:
                raise OSError("injected crash after tell before checkpoint")
            original(path, value)

        with patch.object(bo, "atomic_json", side_effect=crash_save):
            with self.assertRaisesRegex(OSError, "injected"):
                self.execute()
        self.assertEqual(self.state()["completed"], 0)
        self.execute(resume=True, max_evaluations=1)
        self.assertEqual(len(self.state()["observations"]), 2)

    def test_fingerprint_and_checkpoint_rejection(self):
        self.execute(max_evaluations=1)
        original = copy.deepcopy(self.raw)
        for key, value in (("max_pairs", 1500), ("proposal_margin_bounds", [[10, 11], [20, 21], [30, 31]])):
            self.raw = {**original, key: value}
            self.save()
            with self.assertRaisesRegex(bo.BOError, "fingerprint"):
                self.execute(resume=True)
        self.raw = original
        self.save()
        state = self.state()
        state["observations"][-1]["y"] = .1
        bo.atomic_json(self.run / "state.json", state)
        with self.assertRaisesRegex(bo.BOError, "history mismatch"):
            self.execute(resume=True)

    def test_stop_cron_and_explicit_resume(self):
        self.execute(max_evaluations=1)
        self.assertEqual(bo.main(["stop", "--run-dir", str(self.run)]), 0)
        self.execute(resume=True)
        self.assertEqual(self.state()["completed"], 1)
        self.assertTrue((self.run / "STOP").exists())
        self.assertEqual(bo.main(["resume", "--config", str(self.cfg_path), "--run-dir", str(self.run)]), 0)
        self.assertEqual(self.state()["completed"], 2)
        self.assertFalse((self.run / "STOP").exists())

    def test_lock(self):
        self.run.mkdir()
        with bo.run_lock(self.run / "run.lock"):
            with self.assertRaisesRegex(bo.BOError, "locked"):
                self.execute()

    def test_soft_stop_finishes_current_measurement(self):
        original = bo.subprocess.Popen

        def request_stop(*args, **kwargs):
            bo.atomic_json(self.run / "STOP", {"request": "test"})
            return original(*args, **kwargs)

        with patch.object(bo.subprocess, "Popen", side_effect=request_stop):
            self.execute()
        self.assertEqual(self.state()["completed"], 1)
        self.assertIsNone(self.state()["pending"])

    def test_new_precision_import_keeps_out_of_proposal_observations(self):
        self.raw["max_pairs"] = 1500
        self.raw["proposal_margin_bounds"] = [[11, 11], [21, 21], [31, 31]]
        self.save()
        self.execute(max_evaluations=1)
        self.assertEqual(self.state()["observations"][0]["margins"], [10, 20, 30])
        self.assertEqual(self.state()["observations"][1]["margins"], [11, 21, 31])
        self.assertEqual(self.state()["observations"][1]["result"]["status"], "openings_exhausted")

    def test_no_bootstrap_initial_match(self):
        self.raw["bootstrap"] = []
        self.save()
        self.execute(max_evaluations=1)
        self.assertEqual(len(self.state()["observations"]), 1)

    def test_exact_next_proposal_replay(self):
        self.raw["proposal_margin_bounds"] = self.raw["model_margin_bounds"]
        self.save()
        self.execute(max_evaluations=1)
        state = self.state()
        c = self.config()

        def next_proposal():
            opt = bo.optimizer(c, state["optimizer"])
            rng = random.Random()
            rng.setstate(bo.tuple_tree(state["pool_rng"]))
            pool = bo.proposal_pool(c, rng, state["observations"], bo.decode(opt.recommend_observed()[0]))
            suggestion = opt.ask(candidates=[bo.encode(p) for p in pool], return_info=True)
            return bo.decode(suggestion.x), bo.digest(pool), opt.get_state()

        self.assertEqual(next_proposal(), next_proposal())

    def test_sigterm_pair_boundary_and_resume(self):
        self.raw.update(nodes=3000, max_pairs=2, measurements=1, bootstrap=[])
        self.raw["adjudication"]["maxmoves"] = 50
        self.save()
        process = subprocess.Popen(self.cli("run"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            log = self.run / "measurements/gamebo-0000/engine.log"
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if log.exists() and "match game=1" in log.read_text():
                    break
                if process.poll() is not None:
                    self.fail("driver exited before signal: " + str(process.communicate()))
                time.sleep(.01)
            else:
                self.fail("engine did not start")
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stdout + stderr)
            self.assertEqual(self.state()["completed"], 0)
            self.assertIsNotNone(self.state()["pending"])
            status = bo.read_json(self.run / "measurements/gamebo-0000/match/status.json")
            self.assertEqual(status["status"], "stopped")
            self.assertEqual(status["games"] % 2, 0)
            self.execute(resume=True)
            self.assertEqual(self.state()["completed"], 1)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                process.communicate(timeout=30)


if __name__ == "__main__":
    unittest.main()
