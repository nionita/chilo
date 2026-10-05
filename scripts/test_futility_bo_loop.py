from __future__ import annotations
import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_futility_loop as loop


class LazyDependencyTest(unittest.TestCase):
    def test_pareto_import_needs_no_numerical_dependencies(self):
        code = "import run_futility_loop; import sys; assert 'numpy' not in sys.modules; assert 'tinibo' not in sys.modules"
        subprocess.run([sys.executable, '-S', '-c', code], cwd=Path(__file__).parent, check=True)


@unittest.skipUnless(importlib.util.find_spec('tinibo'), 'requires tinibo on PYTHONPATH')
class BOLoopTest(unittest.TestCase):
    def setUp(self):
        import futility_bo_backend as backend
        from test_run_futility_bo import PilotTest
        self.backend = backend
        self.core = backend.core
        self.fixture = PilotTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.env = self.fixture.env
        self.path = self.fixture.root / 'loop-config.json'
        self.raw = dict(schema=loop.SCHEMA, loop_id='new-loop', store_root=str(self.fixture.root),
            initialization={'base': {'margins': self.fixture.base, 'alias': 'best'}},
            search={'backend': 'bo', 'max_proposals': 2, 'bo': {'pool_size': 25,
                'model': {'gp_n_restarts': 1, 'gp_max_iter': 3}}},
            dev_selector={'semantic_filters': []}, validation_selector={'semantic_filters': []})
        self.config = self.configure()
        self.state = loop.initialize(self.config, self.fixture.contract)
        shutil.copytree(self.fixture.source / 'cycles', self.config['root'] / 'cycles')
        self.state['cycle'] = 1
        self.state['dev_results'] = [{'cycle': 1, 'base_id': self.state['base_id']}]
        self.state['imports_done'] = True
        loop.save(self.config['root'], self.state)
        self.calls = []

    def configure(self):
        loop.write(self.path, self.raw)
        return loop.load_config(self.path)

    def start(self):
        loop.begin_phase(self.state, loop.read(self.config['root'] / 'control.json'))
        loop.save(self.config['root'], self.state)
        return self.backend.phase_config(self.config, self.state)

    def runner(self, command, handle):
        self.calls.append(tuple(command[command.index('--futility-margins') + 1].split(',')))
        return self.fixture.fake_command(command, handle)

    def run_phase(self, config, limit=0):
        with patch.object(self.core, 'run_command', side_effect=self.runner):
            return self.backend.run(config, self.env, self.state, limit)

    def test_defaults_bad_configuration_and_fixed_depth(self):
        options = self.config['options']['search']['bo']
        self.assertTrue(options['model']['gp_ard'])
        self.assertEqual(options['model']['kappa'], .5)
        self.assertEqual(options['model']['acquisition'], 'ucb')
        self.assertEqual(options['local_fraction'], 1)
        original = copy.deepcopy(self.raw)
        for change in ({'workers': 2}, {'backend': 'unknown'}, {'bo': {'max_proposals': 3}},
                       {'bo': {'import_bo_runs': ['new-loop']}},
                       {'bo': {'bounds': [[0,1200]]*3}}, {'bo': {'model': {'kappa': -1}}}):
            self.raw = copy.deepcopy(original)
            self.raw['search'].update(change)
            with self.assertRaises((loop.LoopError, self.core.BOError, ValueError)):
                self.configure()
        control = loop.read(self.config['root'] / 'control.json')
        control['base']['margins'] = [10, 20, 30]
        with self.assertRaisesRegex(loop.LoopError, 'depth changed'):
            loop.begin_phase(self.state, control)

    def test_frozen_options_and_settings_runtime_guards(self):
        config = self.start()
        self.backend.prepare(config, self.env, self.state)
        self.state['options']['search']['bo']['model']['kappa'] = 0
        self.assertEqual(config['options']['model']['kappa'], .5)
        changed = copy.deepcopy(config)
        changed['options']['model']['kappa'] = 0
        with self.assertRaisesRegex(self.core.BOError, 'code/config/runtime changed'):
            self.backend.prepare(changed, self.env, self.state)
        with patch.object(self.backend.platform, 'python_version', return_value='different'):
            with self.assertRaisesRegex(self.core.BOError, 'runtime changed'):
                self.backend.prepare(config, self.env, self.state)

    def test_crash_before_probe_replays_same_proposal(self):
        config = self.start()
        with patch.object(self.core, 'evaluate_pending', side_effect=RuntimeError('interrupt')):
            with self.assertRaisesRegex(RuntimeError, 'interrupt'):
                self.backend.run(config, self.env, self.state)
        checkpoint = loop.read(config['root'] / 'state.json')
        pending = checkpoint['pending']
        result, records = self.run_phase(config, 1)
        self.assertEqual(result['completed'][0]['margins'], pending['margins'])
        self.assertEqual(result['completed'][0]['pool_sha256'], pending['pool_sha256'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(result['optimizer']['observations']['y']), 2)
        self.assertEqual(records[0]['id'], 'initial')

    def test_crash_after_raw_and_commit_failure_do_not_repeat_probe_or_tell(self):
        config = self.start()
        real_write = self.core.write
        def fail_commit(path, value):
            if path.name == 'state.json' and value.get('completed'):
                raise OSError('commit interrupted')
            real_write(path, value)
        with patch.object(self.core, 'write', side_effect=fail_commit):
            with self.assertRaisesRegex(OSError, 'commit interrupted'):
                self.run_phase(config, 1)
        state, _ = self.run_phase(config, 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(state['completed']), 1)
        self.assertEqual(len(state['optimizer']['observations']['y']), 2)
        # Finish and repeat after controller crash: no second phase or tell.
        state, records = self.run_phase(config)
        calls = len(self.calls)
        replay, repeated = self.run_phase(config)
        self.assertEqual(state, replay)
        self.assertEqual(records, repeated)
        self.assertEqual(len(self.calls), calls)

    def test_history_across_cycles_and_pareto_reconfiguration(self):
        config = self.start()
        completed, records = self.run_phase(config)
        loop.finish_phase(self.state, records)
        loop.save(self.config['root'], self.state)
        first = completed['optimizer']['observations']
        # Cloud absolute paths are informational; stable provenance relocates.
        frozen_path = config['root'] / 'observations.json'
        frozen = loop.read(frozen_path)
        frozen['development'][0]['sources'][0]['output']['path'] = '/missing-cloud/initial.jsonl'
        loop.write(frozen_path, frozen)
        receipt = loop.read(config['root'] / 'manifest.json')
        receipt['observations'] = self.core.tune.file_identity(frozen_path)
        loop.write(config['root'] / 'manifest.json', receipt)
        # Raw evidence of every new tuple enters warm history, including losers.
        self.state.update(next_phase='dev', pending=[])
        next_config = self.start()
        observations, state = self.backend.prepare(next_config, self.env, self.state)
        self.assertEqual(len(observations['development']), 3)
        self.assertEqual(state['optimizer']['observations'], first)
        seen = {tuple(r['margins']) for r in observations['development']}
        pool = self.core.candidate_pool(next_config['options'], observations['development'],
            self.core.np.random.default_rng(5), self.fixture.base)
        self.assertFalse(seen.intersection(map(tuple, pool)))
        # Re-select mixed historical backends without deleting queue/archive.
        self.state.update(active=None, stopped=True)
        self.raw['search'] = {'max_proposals': 3}
        updated = self.configure()
        self.state['archive']['fixture'] = {'id': 'fixture', 'margins': [1,2,3,4,5],
            **{k: records[0][k] for k in ('metrics','risk','semantic')}}
        self.state['sprt_queue']['fixture'] = {'status':'running', 'history': []}
        self.state['candidates']['fixture'] = {'id':'fixture', 'margins':[1,2,3,4,5],
                                              'aliases':[], 'provenance':[]}
        loop.reconfigure(updated, self.state)
        self.assertEqual(self.state['options']['search']['backend'], 'pareto')
        self.assertEqual(self.state['sprt_queue']['fixture']['status'], 'running')
        self.assertIn('fixture', self.state['archive'])

    def test_reference_scoring_and_raw_tampering_rejected(self):
        config = self.start()
        observations, state = self.backend.prepare(config, self.env, self.state)
        self.assertEqual(len(observations['development']), 1)
        self.assertEqual(observations['validated'], [])
        self.run_phase(config, 1)
        out = config['root'] / 'probes' / 'bo-0000.jsonl'
        out.write_text(out.read_text() + '\n')
        with self.assertRaisesRegex(self.core.BOError, 'raw output differs'):
            self.backend.prepare(config, self.env, self.state)

    def test_explicit_completed_pilot_import_and_conflicting_labels(self):
        # Standalone producer uses its own lock; importer does not lock itself.
        self.fixture.run_pilot()
        (self.fixture.config['root'] / 'bo.lock').touch()
        self.raw['search']['bo']['import_bo_runs'] = ['pilot']
        self.config = self.configure()
        self.state['options'] = self.config['options']
        config = self.start()
        observations, _ = self.backend.prepare(config, self.env, self.state)
        self.assertEqual(len(observations['development']), 3)
        self.assertEqual(len({tuple(r['margins']) for r in observations['development']}), 3)
        broken = self.config['root'] / 'cycles' / '000001' / 'search' / 'state.json'
        value = loop.read(broken)
        value['evaluations'][0]['metrics']['mean_normalized_regret'] += .01
        loop.write(broken, value)
        with self.assertRaisesRegex(self.core.BOError, 'scored metrics differ'):
            self.core.import_observations(config, self.env, self.state['contract'], self.state)

    def test_legacy_pareto_state_migrates_without_changing_queue(self):
        self.state['options']['search'].pop('backend')
        self.state['revisions'][0]['options']['search'].pop('backend', None)
        loop.save(self.config['root'], self.state)
        state = loop.initialize(self.config, self.fixture.contract)
        self.assertEqual(state['options']['search']['backend'], 'pareto')

    def test_switching_requires_boundary_and_controller_stop_is_sticky(self):
        self.start()
        with self.assertRaisesRegex(loop.LoopError, 'phase-boundary stop'):
            loop.reconfigure(self.config, self.state)
        original = loop.execute_dev
        # Complete the actual BO adapter; only engine subprocesses are fake.
        with patch.object(self.core, 'run_command', side_effect=self.runner):
            records = original(self.config, self.env, self.state)
        loop.main(['stop', '--config', str(self.path)])
        loop.finish_phase(self.state, records)
        loop.save(self.config['root'], self.state)
        loop.run_loop(self.config, self.env, self.state, 2)
        self.assertTrue(self.state['stopped'])
        phase = self.state['phase_number']
        loop.run_loop(self.config, self.env, self.state, 2)
        self.assertEqual(self.state['phase_number'], phase)
        # Switching modes doesn't reset pending validation or the cycle count.
        pending = list(self.state['pending'])
        self.raw['search'] = {'max_proposals': 2}
        updated = self.configure()
        loop.reconfigure(updated, self.state)
        self.assertEqual(self.state['pending'], pending)
        self.assertEqual(self.state['cycle'], 2)

    def test_updated_sprt_base_does_not_follow_dev_incumbent(self):
        config = self.start()
        completed, records = self.run_phase(config)
        original_base = self.state['base_id']
        loop.finish_phase(self.state, records)
        self.assertEqual(self.state['base_id'], original_base)
        new = completed['completed'][0]['margins']
        loop.main(['set-base', '--config', str(self.path), '--margins', ','.join(map(str,new))])
        self.state.update(next_phase='dev',pending=[])
        next_config = self.start()
        self.assertEqual(next_config['base']['margins'], new)
        self.assertNotEqual(self.state['base_id'], original_base)
        observations, _ = self.backend.prepare(next_config, self.env, self.state)
        self.assertEqual(len(observations['development']), 3)


@unittest.skipUnless(importlib.util.find_spec('tinibo'), 'requires tinibo on PYTHONPATH')
class ComparisonTest(unittest.TestCase):
    def test_matched_offline_comparison_and_replay(self):
        import compare_futility_bo_lcb as comparison
        rows = [dict(margins=[i,i+10,i+30],target=(i-4)**2/1000) for i in range(8)]
        kwargs = dict(seeds=[1],warm_sizes=[3],steps=2,kappas=[0,.2,.5],
                      model={'gp_n_restarts':1,'gp_max_iter':3})
        a, b = comparison.compare(rows, **kwargs), comparison.compare(rows, **kwargs)
        self.assertEqual(a,b)
        self.assertEqual(len(a['results']),3)
        for result in a['results']:
            self.assertEqual(len(result['reveals']),2)
            self.assertEqual(len({tuple(r['margins']) for r in result['reveals']}),2)
        with self.assertRaisesRegex(comparison.core.BOError,'exceeds measured pool'):
            comparison.compare(rows)


if __name__ == '__main__':
    unittest.main()
