from __future__ import annotations

import sys
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_futility_loop as loop
import test_optimize_futility_gated as pareto_fixtures
import test_optimize_futility as optimizer_fixtures
from test_tune_futility import position_record, write_probe_output


def record(identifier, margins, values=(0.1, 0.1, 0.1)):
    value = pareto_fixtures.ParetoSearchTest.record(identifier, values, 0, 0)
    value["margins"] = margins
    return value


def validation_results(state):
    rows = []
    for key in state["active"]["candidates"]:
        item = record(key, state["candidates"][key]["margins"])
        item["risk"]["semantic_regressions_vs_reference"] = item["semantic"]
        rows.append({"id": key, "pooled_metrics": item["metrics"], "pooled_risk": item["risk"], "shards": []})
    return rows


class LoopTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "loop.json"
        self.raw = {
            "schema": loop.SCHEMA, "loop_id": "test", "store_root": str(self.root),
            "initialization": {"base": {"margins": [10, 20, 30], "alias": "best"}},
            "search": {"max_proposals": 2},
            "dev_selector": {"semantic_filters": []},
            "validation_selector": {"semantic_filters": []},
        }
        self.config = self.configured()
        self.contract = {"probe": "abc", "selection": "xyz"}
        self.state = loop.initialize(self.config, self.contract)

    def configured(self):
        loop.write(self.path, self.raw)
        return loop.load_config(self.path)

    def control(self):
        return loop.read(self.config["root"] / "control.json")

    def validation_import_fixture(self):
        directory = self.root / 'external-validation'
        directory.mkdir()
        probe, net = self.root / 'probe', self.root / 'net'
        probe.write_text('probe')
        net.write_text('net')
        shard = {'id': 'selection'}
        rows = [{'id': 'nominee', 'margins': [12,22,32]}]
        output = loop.batch.candidate_output_path(directory, 'nominee', 'selection')
        output.parent.mkdir(parents=True)
        output.write_text('raw output')
        r = record('nominee', [12,22,32])
        r['risk']['semantic_regressions_vs_reference'] = r['semantic']
        results = {'trusted_position_count': 3, 'candidates': [{
            'id':'nominee', 'margins':[12,22,32], 'pooled_metrics':r['metrics'],
            'pooled_risk':r['risk'], 'shards':[{'id':'selection', 'output':loop.tune.file_identity(output)}]}]}
        env = dict(probe=probe, weights=net, candidate_nodes=120000,
                   baseline_margins=[10,20,30], score_scale=600, selection=[shard])
        manifest = {**env, 'schema':loop.batch.MANIFEST_SCHEMA, 'shards':[shard], 'candidates':rows}
        manifest.pop('selection')
        manifest.update(probe=loop.tune.file_identity(probe), weights=loop.tune.file_identity(net))
        loop.write(directory / 'batch_manifest.json', manifest)
        loop.write(directory / 'results.json', results)
        loop.write(directory / 'complete.json', dict(schema=loop.batch.SCHEMA, trusted_position_count=3,
            batch_manifest=loop.tune.file_identity(directory/'batch_manifest.json'),
            results=loop.tune.file_identity(directory/'results.json')))
        self.state.update(stopped=True, active=None)
        return directory, env, results

    def test_validation_import_is_idempotent_and_preserves_control(self):
        directory, env, results = self.validation_import_fixture()
        control = self.control()
        with patch.object(loop.batch,'load_contexts',return_value=env['selection']), \
             patch.object(loop.batch,'execution_manifest',return_value={'shards':[{'id':'selection'}]}), \
             patch.object(loop.batch,'calculate_results',return_value=results) as score:
            loop.import_validation(self.config,env,self.state,directory)
            first = copy.deepcopy(self.state)
            loop.import_validation(self.config,env,self.state,directory)
        self.assertEqual(self.state,first)
        self.assertEqual(self.control(),control)
        self.assertEqual(score.call_count,2)
        key = loop.tuple_id(self.state,[12,22,32])
        self.assertIn(key,self.state['archive'])
        loop.enqueue(self.state,key)
        self.assertNotIn(key,self.state['pending'])

    def test_validation_import_refuses_active_partial_or_corrupt_evidence(self):
        directory,env,results = self.validation_import_fixture()
        original = copy.deepcopy(self.state)
        with patch.object(loop.batch,'load_contexts',return_value=env['selection']), \
             patch.object(loop.batch,'execution_manifest',return_value={'shards':[{'id':'selection'}]}), \
             patch.object(loop.batch,'calculate_results',return_value=results):
            self.state['stopped'] = False
            with self.assertRaisesRegex(loop.LoopError,'phase-boundary'):
                loop.import_validation(self.config,env,self.state,directory)
            self.state.update(original)
            path = loop.batch.candidate_output_path(directory,'nominee','selection')
            path.write_text('corrupt')
            with self.assertRaisesRegex(loop.LoopError,'raw output'):
                loop.import_validation(self.config,env,self.state,directory)
            self.assertEqual(self.state,original)
            path.write_text('raw output')
            with patch.object(loop.batch,'execution_manifest',return_value={'shards':[]}):
                with self.assertRaisesRegex(loop.LoopError,'populations differ'):
                    loop.import_validation(self.config,env,self.state,directory)
            changed = copy.deepcopy(results)
            changed['candidates'][0]['pooled_metrics']['mean_normalized_regret'] += 1
            with patch.object(loop.batch,'calculate_results',return_value=changed):
                with self.assertRaisesRegex(loop.LoopError,'metrics differ'):
                    loop.import_validation(self.config,env,self.state,directory)
            self.assertEqual(self.state,original)

    def test_validation_import_with_real_campaign_shards_and_batch_loader(self):
        fixture = optimizer_fixtures.OptimizerAdapterTest()
        anchor = self.root / 'anchor'
        fixture.write_per_root_anchor_with_rejection(anchor)
        rescue = fixture.write_rescue_run(self.root, anchor)
        inputs = self.root / 'positions.csv'
        inputs.write_text('fen\nfen-complete\nfen-rescue\n')
        probe, weights = self.root / 'probe', self.root / 'weights'
        probe.write_text('probe')
        weights.write_text('weights')
        loop.write(anchor / 'anchor_manifest.json', {'inputs': [loop.tune.file_identity(inputs)]})
        context = loop.campaign.optimize_futility.load_anchor(
            self.path, 'tiny', {'reference_dir': str(anchor), 'contract': 'per_root_v1',
                                'rescue_dir': str(rescue)}, 100, (120,240,360))
        shard = dict(id='tiny', population='tiny', input=inputs, anchor_dir=anchor,
                     rescue_dir=rescue, context=context)
        self.assertNotIn('anchor_manifest', shard)
        self.assertNotIn('rescue_completion', shard)
        directory = self.root / 'external-batch'
        rows = [{'id': 'nominee', 'margins': [12,22,32]}]
        env = dict(config_path=self.path, config_sha256='fixture', probe=probe, weights=weights,
                   candidate_nodes=100, baseline_margins=(120,240,360), score_scale=600,
                   selection=[shard], probe_cache_dir=None)
        settings = dict(env, shards=[shard], candidates=rows, run_dir=directory,
                        tail_fractions=[0.01,0.05], regret_thresholds=[0.1,0.25],
                        advantage_cp=150, loss_cp=-150)
        output = loop.batch.candidate_output_path(directory, 'nominee', 'tiny')
        output.parent.mkdir(parents=True)
        write_probe_output(output, [position_record('positions.csv',i,fen,[12,22,32],100,
                           move='e2e4',score=30,depth=6)
                           for i,fen in enumerate(('fen-complete','fen-rescue'),1)], [12,22,32], 100)
        contexts = loop.batch.load_contexts(settings)
        manifest = loop.batch.execution_manifest(settings, contexts)
        results = loop.batch.calculate_results(settings, contexts)
        loop.write(directory / 'batch_manifest.json', manifest)
        loop.write(directory / 'results.json', results)
        loop.write(directory / 'complete.json', dict(schema=loop.batch.SCHEMA, trusted_position_count=2,
                   batch_manifest=loop.tune.file_identity(directory/'batch_manifest.json'),
                   results=loop.tune.file_identity(directory/'results.json')))
        self.state.update(stopped=True, active=None)
        with patch.object(loop.pareto.subprocess, 'run', side_effect=AssertionError('must not launch probes')):
            loop.import_validation(self.config,env,self.state,directory)
            snapshot = copy.deepcopy(self.state)
            loop.import_validation(self.config,env,self.state,directory)
        self.assertEqual(self.state,snapshot)
        self.assertEqual(len(self.state['archive']),1)
        # Actual receipt changes remain fail-closed, not masked by optional keys.
        loop.write(anchor/'anchor_manifest.json',{'inputs':[loop.tune.file_identity(inputs)],'changed':True})
        with self.assertRaisesRegex(loop.LoopError,'populations differ'):
            loop.import_validation(self.config,env,self.state,directory)
        self.assertEqual(self.state,snapshot)

    def run_phases(self, count, dev=None, validation=None):
        if dev is None:
            dev = lambda *_: [record("proposal", [12, 22, 32])]
        if validation is None:
            validation = lambda _config, _env, state: validation_results(state)
        with patch.object(loop, "execute_dev", side_effect=dev) as d, \
             patch.object(loop, "execute_validation", side_effect=validation) as v:
            loop.run_loop(self.config, {}, self.state, count)
        return d.call_count, v.call_count

    def test_cycles_deduplicate_validation_and_queue(self):
        self.assertEqual(self.run_phases(4), (3, 1))
        self.assertEqual(len(self.state["archive"]), 2)
        self.assertEqual(len(self.state["sprt_queue"]), 1)
        self.assertEqual(self.state["pending"], [])
        self.assertEqual(self.state["cycle"], 3)
        self.assertEqual(self.state["next_phase"], "dev")

    def request_validation(self, margins='13,23,33', alias='valbo', note='offline-validation-bo'):
        return loop.main(['enqueue','--config',str(self.path),'--margins',margins,
                          '--alias',alias,'--note',note])

    def test_enqueue_during_dev_is_control_only_and_bypasses_dev_selection(self):
        def dev(_config, _env, state):
            saved = loop.read(self.config['root']/'loop_state.json')
            active = copy.deepcopy(state['active'])
            with loop.locked(self.config['root']/'loop.lock') as acquired, \
                 patch.object(loop,'environment',side_effect=AssertionError('no probe or context loading')):
                self.assertTrue(acquired)
                self.request_validation()
                first = self.control()
                self.request_validation()
                self.assertEqual(self.control(),first)
            self.assertEqual(loop.read(self.config['root']/'loop_state.json'),saved)
            self.assertEqual(state['active'],active)
            return [record('initial',[10,20,30])]  # external tuple was not a dev proposal
        self.assertEqual(self.run_phases(2,dev=dev),(1,1))
        key = loop.tuple_id(self.state,[13,23,33])
        self.assertIn(key,self.state['archive'])
        self.assertEqual(self.state['candidates'][key]['provenance'],['offline-validation-bo'])
        self.assertEqual(self.state['applied_validation_requests'][key],1)
        self.assertEqual(self.state['base_id'],loop.tuple_id(self.state,[10,20,30]))
        # Replaying a consumed/validated tuple adds no probe work or pending entry.
        snapshot = copy.deepcopy(self.state)
        loop.apply_validation_requests(self.state,self.control())
        self.assertEqual(self.state,snapshot)

    def test_enqueue_during_validation_does_not_change_frozen_batch(self):
        self.run_phases(1)
        batches = []
        def validate(_config,_env,state):
            frozen = list(state['active']['candidates'])
            batches.append(frozen)
            if len(batches)==1:
                self.request_validation()
                self.assertEqual(state['active']['candidates'],frozen)
                with self.assertRaisesRegex(loop.LoopError,'phase boundary'):
                    loop.apply_validation_requests(state,self.control())
            return validation_results(state)
        self.assertEqual(self.run_phases(2,validation=validate),(0,2))
        key = loop.tuple_id(self.state,[13,23,33])
        self.assertNotIn(key,batches[0])
        self.assertIn(key,batches[1])
        self.assertIn(key,self.state['archive'])

    def test_enqueue_validation_and_old_state_compatibility(self):
        before = self.control()
        for margins in ('1,2','1,2,1300','30,20,10','1,-2,3','x,2,3'):
            with self.assertRaises((loop.LoopError,ValueError,loop.tune.TuningError)):
                self.request_validation(margins)
            self.assertEqual(self.control(),before)
        self.state.update(stopped=True)
        loop.save(self.config['root'],self.state)
        self.request_validation()
        self.assertTrue(loop.read(self.config['root']/'loop_state.json')['stopped'])
        loop.apply_validation_requests(self.state,self.control())
        self.assertEqual(self.state['next_phase'],'validation')
        self.assertTrue(self.state['stopped'])
        loop.save(self.config['root'],self.state)
        restored = loop.initialize(self.config,self.contract)
        loop.apply_validation_requests(restored,self.control())
        self.assertEqual(restored,self.state)
        bo_options = copy.deepcopy(self.state['options'])
        bo_options['search'].update(backend='bo',bo={'bounds':[[0,12],[0,30],[0,40]]})
        with self.assertRaisesRegex(loop.LoopError,'outside BO bounds'):
            loop.validation_candidate({'margins':[13,23,33]},self.state['initialization'],bo_options)

    def test_initial_pool_validates_before_first_search(self):
        self.raw["loop_id"] = "with-pool"
        self.raw["initialization"]["validation_pool"] = [{"margins": [11, 21, 31]}]
        config = self.configured()
        state = loop.initialize(config, self.contract)
        loop.begin_phase(state, loop.read(config["root"] / "control.json"))
        self.assertEqual(state["active"]["phase"], "validation")
        self.assertEqual(len(state["active"]["candidates"]), 2)
        self.assertEqual(state["cycle"], 0)

    def test_stop_during_dev_is_sticky_for_cron_and_resume_is_explicit(self):
        def dev(*_):
            loop.main(["stop", "--config", str(self.path)])
            return [record("proposal", [12, 22, 32])]
        self.assertEqual(self.run_phases(9, dev=dev), (1, 0))
        self.assertTrue(self.state["stopped"])
        self.assertIsNone(self.state["active"])
        self.assertEqual(self.run_phases(9), (0, 0))
        with patch.object(loop, "environment", return_value=({}, self.contract)), \
             patch.object(loop, "execute_validation", side_effect=lambda c, e, s: validation_results(s)):
            loop.main(["resume", "--config", str(self.path), "--max-phases", "1"])
        resumed = loop.read(self.config["root"] / "loop_state.json")
        self.assertFalse(resumed["stopped"])
        self.assertEqual(resumed["phase_number"], 2)

    def test_stop_during_validation_finishes_the_whole_batch(self):
        self.run_phases(1)
        def validate(_c, _e, state):
            loop.main(["stop", "--config", str(self.path)])
            return validation_results(state)
        self.assertEqual(self.run_phases(8, validation=validate), (0, 1))
        self.assertTrue(self.state["stopped"])
        self.assertEqual(len(self.state["archive"]), 2)
        self.assertEqual(self.state["next_phase"], "dev")

    def test_interruption_resumes_same_phase_seed_and_tuple(self):
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.run_phases(1, dev=lambda *_: (_ for _ in ()).throw(RuntimeError("interrupted")))
        checkpoint = loop.read(self.config["root"] / "loop_state.json")
        self.assertEqual(checkpoint["active"]["cycle"], 1)
        self.state = loop.initialize(self.config, self.contract)
        self.run_phases(1)
        self.assertEqual(self.state["cycle"], 1)
        self.assertEqual(self.state["phase_number"], 1)

    def test_base_update_is_frozen_until_next_dev_and_seed_advances(self):
        loop.begin_phase(self.state, self.control())
        old_base = self.state["active"]["base_id"]
        old_seed = self.state["active"]["seed"]
        loop.main(["set-base", "--config", str(self.path), "--margins", "20,30,40"])
        self.assertEqual(self.state["active"]["base_id"], old_base)
        loop.finish_phase(self.state, [record("proposal", [12, 22, 32])])
        loop.begin_phase(self.state, self.control())
        self.assertEqual(self.state["active"]["base_id"], old_base)
        loop.finish_phase(self.state, validation_results(self.state))
        loop.begin_phase(self.state, self.control())
        self.assertNotEqual(self.state["active"]["base_id"], old_base)
        self.assertEqual(self.state["active"]["seed"], old_seed + 1)

    def test_queue_supersedes_requalifies_and_preserves_tested_candidates(self):
        self.run_phases(2)
        first = next(iter(self.state["sprt_queue"]))
        second = loop.register(self.state, loop.candidate({"margins": [14, 24, 34]}))
        self.state["archive"][second] = record(second, [14, 24, 34], (0.01, 0.01, 0.01))
        loop.rebuild(self.state)
        self.assertEqual(self.state["sprt_queue"][first]["status"], "superseded")
        self.assertEqual(self.state["sprt_queue"][second]["status"], "pending")
        self.state["archive"][first]["metrics"]["mean_normalized_regret"] = 0.001
        loop.rebuild(self.state)
        self.assertEqual(self.state["sprt_queue"][first]["status"], "pending")
        control = self.control()
        control["sprt"][first] = {"revision": 1, "status": "accepted", "note": "manual test"}
        base = self.state["base_id"]
        loop.apply_test_updates(self.state, control)
        self.state["archive"][first]["metrics"]["mean_normalized_regret"] = 0.1
        loop.rebuild(self.state)
        self.assertEqual(self.state["sprt_queue"][first]["status"], "accepted")
        self.assertEqual(self.state["base_id"], base)

    def test_reconfigure_and_contract_checks(self):
        self.raw["search"]["max_proposals"] = 7
        updated = self.configured()
        with self.assertRaisesRegex(loop.LoopError, "phase-boundary stop"):
            loop.reconfigure(updated, self.state)
        with self.assertRaisesRegex(loop.LoopError, "contract changed"):
            loop.initialize(updated, {"probe": "different"})
        self.state["stopped"] = True
        loop.reconfigure(updated, self.state)
        self.assertEqual(self.state["revision"], 2)
        self.assertEqual(self.state["options"]["search"]["max_proposals"], 7)

    def test_missing_authoritative_state_cannot_reset_existing_run(self):
        (self.config["root"] / "loop_state.json").unlink()
        with self.assertRaisesRegex(loop.LoopError, "nonempty without loop_state"):
            loop.initialize(self.config, self.contract)

    def test_config_edits_are_rejected_until_explicit_reconfigure(self):
        self.raw["search"]["max_proposals"] = 7
        self.configured()
        with patch.object(loop, "environment", return_value=({}, self.contract)):
            with self.assertRaisesRegex(loop.LoopError, "parameters changed"):
                loop.main(["run", "--config", str(self.path), "--max-phases", "1"])

    def test_selectors_are_independent_and_ties_preserved(self):
        a = record("a", [1, 2, 3], (0.1, 0.3, 0.3))
        b = record("b", [2, 3, 4], (0.2, 0.2, 0.2))
        policy = loop.selector({"objectives": ["mean_regret"], "semantic_filters": []})
        self.assertEqual([r["id"] for r in loop.select([a, b], policy)[1]], ["a"])
        self.assertEqual(len(loop.select([a, b], loop.selector({}))[1]), 2)
        for invalid in ([], ["missing"], ["cvar1", "cvar1"]):
            with self.assertRaises(loop.pareto.optimize_futility.OptimizationError):
                loop.selector({"objectives": invalid})

    def test_lock_is_process_owned_not_file_existence(self):
        lock = self.config["root"] / "loop.lock"
        with loop.locked(lock) as first:
            self.assertTrue(first)
            with loop.locked(lock) as second:
                self.assertFalse(second)
        self.assertTrue(lock.exists())
        with loop.locked(lock) as recovered:
            self.assertTrue(recovered)

    def test_portable_contract_ignores_paths_not_content(self):
        old = {"input": {"path": "/old", "sha256": "x", "size": 1}}
        new = {"input": {"path": "/new", "sha256": "x", "size": 1}}
        self.assertEqual(loop.portable(old), loop.portable(new))
        new["input"]["sha256"] = "y"
        self.assertNotEqual(loop.portable(old), loop.portable(new))

    def test_batch_import_reuses_partial_coverage_and_checks_output_identity(self):
        previous = self.root / "previous"
        probe, weights, inputs = self.root / "probe", self.root / "net", self.root / "positions.csv"
        for path in (probe, weights, inputs):
            path.write_text(path.name)
        margins = [12, 22, 32]
        output = previous / "candidates" / "old-alias" / "one" / "probes" / "candidate.jsonl"
        output.parent.mkdir(parents=True)
        write_probe_output(output, [position_record("positions.csv", 1, "fen", margins, 100)], margins, 100)
        loop.write(previous / "batch_manifest.json", {
            "schema": loop.backfill.BATCH_SCHEMA, "probe": loop.tune.file_identity(probe),
            "weights": loop.tune.file_identity(weights), "candidate_nodes": 100,
            "candidates": [{"id": "old-alias", "margins": margins}],
            "shards": [{"id": "one", "input": loop.tune.file_identity(inputs)}]})
        loop.write(previous / "results.json", {"candidates": [{"id": "old-alias", "shards": [
            {"id": "one", "output": loop.tune.file_identity(output)}]}]})
        other = self.root / "other.csv"
        other.write_text("other")
        env = {"probe": probe, "weights": weights, "candidate_nodes": 100,
               "selection": [{"input": inputs}, {"input": other}], "probe_cache_dir": self.root / "cache"}
        self.state["initialization"]["imports"] = [str(previous)]
        loop.import_sources(self.config, env, self.state)
        key = loop.tuple_id(self.state, margins)
        self.assertIn(key, self.state["pending"])
        self.assertNotIn(key, self.state["archive"])  # partial coverage is not a full validation
        entry = loop.cache.entry_for(env["probe_cache_dir"], loop.cache.descriptor(probe, weights, [inputs], 100, margins))
        loop.cache.validate(entry, 100, margins)
        loop.import_sources(self.config, env, self.state)
        self.assertEqual(self.state["pending"].count(key), 1)
        output.write_text(output.read_text() + "\n")
        with self.assertRaisesRegex(loop.LoopError, "output differs"):
            loop.import_sources(self.config, env, self.state)
        env["candidate_nodes"] = 200
        with self.assertRaisesRegex(loop.LoopError, "incompatible nodes"):
            loop.import_sources(self.config, env, self.state)

    def test_environment_loads_real_campaign_config_and_detects_dev_leakage(self):
        from test_run_futility_campaign import CampaignPopulationTest, fake_context
        fixture = CampaignPopulationTest()
        fixture.write_single(self.root / "development")
        fixture.write_sharded(self.root / "selection")
        probe, weights = self.root / "probe", self.root / "weights"
        probe.write_text("probe")
        weights.write_text("weights")
        self.raw.update(artifacts={"probe": str(probe), "weights": str(weights)}, candidate_nodes=120000,
                        baseline_margins=[120, 240, 360], score_scale=600,
                        development={"id": "development", "kind": "single", "path": "development"},
                        selection=[{"id": "selection", "kind": "sharded", "path": "selection"}])
        config = self.configured()
        def context(_config, label, *_args):
            value = fake_context(label)
            value.trusted_keys = [(label, 1, "fen-" + label)]
            return value
        with patch.object(loop.campaign.optimize_futility, "load_anchor", side_effect=context):
            env, contract = loop.environment(config)
        self.assertEqual(len(env["selection"]), 2)
        self.assertEqual(contract["candidate_nodes"], 120000)
        env["selection"][0]["context"].trusted_keys = env["development"]["context"].trusted_keys
        with patch.object(loop.campaign, "load_campaign", return_value=env):
            with self.assertRaisesRegex(loop.LoopError, "FENs overlap"):
                loop.environment(config)

    def test_real_search_and_batch_adapters_reuse_cache_after_checkpoint_crash(self):
        # Tiny valid per-root+rescue data. Only the expensive subprocess is fake.
        fixture = optimizer_fixtures.OptimizerAdapterTest()
        anchor = self.root / "anchor"
        fixture.write_per_root_anchor_with_rejection(anchor)
        rescue = fixture.write_rescue_run(self.root, anchor)
        inputs = self.root / "positions.csv"
        inputs.write_text("fen\nfen-complete\nfen-rescue\n")
        probe, weights = self.root / "probe", self.root / "weights"
        probe.write_text("test-probe")
        weights.write_text("test-weights")
        population = {"id": "tiny", "input": inputs, "anchor_dir": anchor, "rescue_dir": rescue}
        env = {"probe": probe, "weights": weights, "candidate_nodes": 100,
               "baseline_margins": (120, 240, 360), "score_scale": 600,
               "development": population, "selection": [population],
               "probe_cache_dir": self.root / "candidate-probe-cache"}
        from types import SimpleNamespace
        calls = []
        def fake_subprocess(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            margins = [int(v) for v in command[command.index("--futility-margins") + 1].split(",")]
            output.parent.mkdir(parents=True, exist_ok=True)
            rows = [position_record("positions.csv", i, fen, margins, 100, move="e2e4", score=30, depth=6)
                    for i, fen in enumerate(("fen-complete", "fen-rescue"), 1)]
            write_probe_output(output, rows, margins, 100)
            calls.append(tuple(margins))
            return SimpleNamespace(returncode=0)
        with patch.object(loop.pareto.subprocess, "run", side_effect=fake_subprocess):
            loop.run_loop(self.config, env, self.state, max_phases=1)
            self.assertEqual(len(calls), 3)  # initial + two proposals
            # Complete batch, but crash before the controller commits its phase.
            loop.begin_phase(self.state, self.control())
            loop.save(self.config["root"], self.state)
            loop.execute_validation(self.config, env, self.state)
            self.state = loop.initialize(self.config, self.contract)
            loop.run_loop(self.config, env, self.state, max_phases=1)
            self.assertEqual(len(calls), 3)  # cache and completed outputs reused
        self.assertEqual(self.state["phase_number"], 2)
        self.assertEqual(len(self.state["archive"]), 3)
        self.assertTrue(all(r["shards"][0]["position_count"] == 2 for r in self.state["archive"].values()))


if __name__ == "__main__":
    unittest.main()
