from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
if importlib.util.find_spec('tinibo') is None:
    raise unittest.SkipTest('BO integration tests require tinibo on PYTHONPATH')

import numpy as np
import run_futility_bo as bo
from test_tune_futility import position_record, write_probe_output


class PilotTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'evals' / 'old-loop'
        self.source.mkdir(parents=True)
        (self.source / 'loop.lock').touch()
        self.base = [0, 40, 158, 488, 754]
        self.path = self.root / 'config.json'
        self.raw = {'schema': bo.SCHEMA, 'run_id': 'pilot', 'source_loop': 'old-loop',
                    'store_root': str(self.root), 'base': {'margins': self.base, 'alias': 'best'},
                    'bo': {'max_proposals': 2, 'pool_size': 40,
                           'model': {'gp_n_restarts': 1, 'gp_max_iter': 5}}}
        bo.write(self.path, self.raw)
        self.config = bo.load_config(self.path)
        self.probe, self.weights, self.inputs = self.root/'probe', self.root/'net', self.root/'positions.csv'
        for p in (self.probe, self.weights, self.inputs):
            p.write_text('fixture')
        key = ('positions.csv', 1, 'fen')
        baseline = position_record(*key, [120, 240, 360], 100, move='d2d4')
        reference = position_record(*key, [120, 240, 360], 200, score=35, depth=8,
                                    all_root_scores=True, root_scores={'e2e4': 35, 'd2d4': 0})
        context = SimpleNamespace(reference={'positions': {key: reference}},
                                  baseline={'positions': {key: baseline}}, trusted_keys=[key],
                                  trusted_set={'trusted_position_count': 1}, rescue=None,
                                  reference_identity={'sha256': 'ref', 'size': 1},
                                  baseline_identity={'sha256': 'base', 'size': 1})
        development = dict(id='dev', population='dev', input=self.inputs, context=context,
                           anchor_dir=self.root/'anchor', rescue_dir=self.root/'rescue', population_manifest=None)
        self.env = dict(probe=self.probe, weights=self.weights, candidate_nodes=100, score_scale=600,
                        report_every=0, baseline_margins=(120,240,360), development=development,
                        selection=[dict(id='sel',context=context)], probe_cache_dir=self.root/'cache')
        self.contract = {'fixture': 'fixed'}
        self.state = dict(schema=bo.loop.SCHEMA, stopped=True, active=None, archive={},
                          contract=self.contract, contract_sha256=bo.digest(self.contract))
        bo.write(self.source/'loop_state.json', self.state)
        bo.write(self.source/'control.json', {'base': {'margins': self.base}})
        self.add_cycle(1)
        self.probe_calls = 0

    def add_cycle(self, cycle, target=None):
        root = self.source/'cycles'/f'{cycle:06d}'/'search'
        (root/'probes').mkdir(parents=True)
        out = root/'probes'/'initial.jsonl'
        write_probe_output(out, [position_record('positions.csv',1,'fen',self.base,100,move='d2d4')], self.base,100)
        (root/'logs').mkdir()
        record = bo.probes.evaluate(bo.probe_settings(self.config,self.env),root,'initial',self.base,
                                   bo.tune.parse_probe_output(out,100,self.base))
        if target is not None:
            record['metrics']['mean_normalized_regret'] = target
        bo.write(root/'state.json', {'schema': bo.probes.STATE_SCHEMA, 'status':'max_proposals',
                                    'evaluations':[record]})
        bo.write(root/'optimizer_manifest.json', {
            'schema': bo.probes.SCHEMA,
            'probe':bo.tune.file_identity(self.probe),'weights':bo.tune.file_identity(self.weights),
            'inputs':[bo.tune.file_identity(self.inputs)],'candidate_nodes':100,
            'baseline_margins':[120,240,360],'score_scale':600,
            'development':bo.campaign.context_identity(self.env['development'])})

    def initialize(self, config=None):
        config = config or self.config
        config['root'].mkdir(parents=True,exist_ok=True)
        return bo.initialize(config,self.env,self.contract,self.state)

    def fake_command(self, command, _log):
        self.probe_calls += 1
        margins = [int(x) for x in command[command.index('--futility-margins')+1].split(',')]
        out = Path(command[command.index('--output')+1])
        write_probe_output(out,[position_record('positions.csv',1,'fen',margins,100)],margins,100)
        return SimpleNamespace(returncode=0)

    def run_pilot(self, config=None, limit=0):
        config = config or self.config
        observations,state = self.initialize(config)
        with patch.object(bo,'run_command',side_effect=self.fake_command):
            return bo.run(config,self.env,self.contract,observations,state,limit)

    def continuation(self):
        self.run_pilot()
        (self.config['root']/'bo.lock').touch()
        raw=copy.deepcopy(self.raw)
        raw.update(run_id='next-pilot', import_bo_runs=['pilot'])
        path=self.root/'next.json'
        bo.write(path,raw)
        return bo.load_config(path)

    def test_previous_bo_points_are_added_without_reprobing(self):
        config=self.continuation()
        calls=self.probe_calls
        observations,state=self.initialize(config)
        self.assertEqual(self.probe_calls,calls)
        self.assertEqual(len(observations['development']),3)
        self.assertEqual(len(state['optimizer']['observations']['x']),3)
        self.assertEqual(state['completed'],[])
        self.assertEqual(observations['development'][-1]['sources'][0]['bo_run'],'pilot')
        self.assertEqual(self.initialize(config)[1],state)
        pool=bo.candidate_pool(config['options'],observations['development'],np.random.default_rng(1),self.base)
        self.assertFalse({tuple(r['margins']) for r in observations['development']} & {tuple(x) for x in pool})

    def test_import_is_measurement_reuse_not_old_optimizer_restore(self):
        config=self.continuation()
        path=self.config['root']/'state.json'
        state=bo.read(path)
        state['optimizer']['environment']={'python':'another runtime','numpy':'another version'}
        bo.write(path,state)
        config['options']['model']['gp_n_restarts']=2
        observations,_=self.initialize(config)
        self.assertEqual(len(observations['development']),3)

    def test_resume_uses_frozen_imports_if_producer_is_unavailable(self):
        config=self.continuation()
        expected=self.initialize(config)
        self.config['root'].rename(self.root/'old-evidence-unavailable')
        self.assertEqual(self.initialize(config),expected)

    def test_prior_bo_run_must_be_complete_and_contract_matching(self):
        config=self.continuation()
        path=self.config['root']/'state.json'
        state=bo.read(path);state['status']='running';bo.write(path,state)
        with self.assertRaisesRegex(bo.BOError,'must be complete'):
            self.initialize(config)
        state['status']='complete';bo.write(path,state)
        path=self.config['root']/'manifest.json'
        manifest=bo.read(path);manifest['contract']={'changed':True};bo.write(path,manifest)
        with self.assertRaisesRegex(bo.BOError,'contract is incompatible'):
            self.initialize(config)

    def test_prior_bo_raw_history_and_frozen_observations_are_checked(self):
        config=self.continuation()
        prior=self.config['root']
        state=bo.read(prior/'state.json')
        changed=copy.deepcopy(state)
        changed['optimizer']['observations']['y'][0]=999
        bo.write(prior/'state.json',changed)
        with self.assertRaisesRegex(bo.BOError,'history differs'):
            self.initialize(config)
        bo.write(prior/'state.json',state)
        path=prior/'observations.json';original=path.read_text();path.write_text('corrupt')
        with self.assertRaisesRegex(bo.BOError,'observations differ'):
            self.initialize(config)
        path.write_text(original)
        (prior/'probes/bo-0000.jsonl').write_text('corrupt')
        with self.assertRaisesRegex(bo.BOError,'raw probe differs'):
            self.initialize(config)

    def test_prior_bo_lock_prevents_active_import(self):
        config=self.continuation()
        with bo.loop.locked(self.config['root']/'bo.lock'):
            with self.assertRaisesRegex(bo.BOError,'still running'):
                self.initialize(config)

    def test_cross_run_duplicate_tuples_are_deduplicated(self):
        config=self.continuation()
        other=self.root/'evals/duplicate-pilot'
        shutil.copytree(self.config['root'],other)
        manifest=bo.read(other/'manifest.json');manifest['config']['run_id']='duplicate-pilot'
        bo.write(other/'manifest.json',manifest)
        config['raw']['import_bo_runs'].append('duplicate-pilot')
        observations,_=self.initialize(config)
        self.assertEqual(len(observations['development']),3)
        self.assertEqual(len(observations['development'][-1]['sources']),2)

    def test_invalid_import_lists_fail_before_work(self):
        for imports in ('pilot', ['pilot'], ['old-loop'], ['other','other'], ['../other']):
            bo.write(self.path,{**self.raw,'import_bo_runs':imports})
            with self.assertRaises((bo.BOError,bo.campaign.CampaignError)):
                bo.load_config(self.path)

    def test_import_deduplicates_compatible_observations(self):
        self.add_cycle(2)
        observations,_=self.initialize()
        self.assertEqual(len(observations['development']),1)
        self.assertEqual(len(observations['development'][0]['sources']),2)

    def test_import_rejects_conflicting_targets_and_bad_raw_output(self):
        self.add_cycle(2,target=0.7)
        with self.assertRaisesRegex(bo.BOError,'conflicting'):
            self.initialize()
        (self.source/'cycles/000002/search/probes/initial.jsonl').write_text('corrupt')
        with self.assertRaisesRegex(bo.BOError,'raw probe differs'):
            self.initialize()

    def test_import_rejects_changed_contract_or_probe(self):
        self.state['contract']={'different':True}
        with self.assertRaisesRegex(bo.BOError,'incompatible'):
            self.initialize()
        self.state['contract']=self.contract
        path=self.source/'cycles/000001/search/optimizer_manifest.json'
        value=bo.read(path);value['probe']['sha256']='changed';bo.write(path,value)
        with self.assertRaisesRegex(bo.campaign.CampaignError,'incompatible probe'):
            self.initialize()

    def test_pending_resume_replays_same_proposals_and_outputs(self):
        # One uninterrupted control, then interruption before a probe in the pilot.
        control=copy.deepcopy(self.config);control['root']=self.root/'control-run'
        expected=self.run_pilot(control)
        observations,state=self.initialize()
        with patch.object(bo,'evaluate_pending',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                bo.run(self.config,self.env,self.contract,observations,state)
        pending=bo.read(self.config['root']/'state.json')['pending']
        self.assertIsNotNone(pending)
        actual=self.run_pilot()
        self.assertEqual([r['margins'] for r in expected['evaluations']],
                         [r['margins'] for r in actual['evaluations']])
        self.assertEqual([r['pool_sha256'] for r in expected['evaluations']],
                         [r['pool_sha256'] for r in actual['evaluations']])

    def test_resume_after_output_reuses_probe_without_double_count(self):
        observations,state=self.initialize()
        real=bo.evaluate_pending
        def after_output(*args):
            real(*args)
            raise KeyboardInterrupt
        with patch.object(bo,'run_command',side_effect=self.fake_command), \
             patch.object(bo,'evaluate_pending',side_effect=after_output):
            with self.assertRaises(KeyboardInterrupt):
                bo.run(self.config,self.env,self.contract,observations,state)
        self.assertEqual(self.probe_calls,1)
        result=self.run_pilot()
        self.assertEqual(result['completed_count'],2)
        self.assertEqual(self.probe_calls,2)
        self.assertEqual(result['evaluations'][0]['cache']['status'],'hit')

    def test_resume_after_checkpoint_write_failure_reuses_output(self):
        observations,state=self.initialize()
        actual_write=bo.write
        def fail_commit(path,value):
            if path.name=='state.json' and value.get('completed'):
                raise OSError('simulated commit failure')
            actual_write(path,value)
        with patch.object(bo,'run_command',side_effect=self.fake_command),patch.object(bo,'write',side_effect=fail_commit):
            with self.assertRaisesRegex(OSError,'commit failure'):
                bo.run(self.config,self.env,self.contract,observations,state)
        result=self.run_pilot()
        self.assertEqual(result['completed_count'],2)
        self.assertEqual(self.probe_calls,2)

    def test_limit_completion_and_manifest_mismatch(self):
        self.assertEqual(self.run_pilot(limit=1)['completed_count'],1)
        self.assertEqual(self.run_pilot()['status'],'complete')
        count=self.probe_calls
        self.assertEqual(self.run_pilot()['status'],'complete')
        self.assertEqual(count,self.probe_calls)
        changed=copy.deepcopy(self.config);changed['raw']['bo']['seed']=99
        with self.assertRaisesRegex(bo.BOError,'manifest mismatch'):
            self.initialize(changed)

    def test_nominee_excludes_already_validated_and_no_improvement(self):
        result=self.run_pilot()
        self.assertIsNotNone(result['nominee'])
        observations=bo.read(self.config['root']/'observations.json');state=bo.read(self.config['root']/'state.json')
        observations['validated']=state['completed']
        self.assertIsNone(bo.report(self.config,self.contract,observations,state)['nominee'])
        observations['validated']=[]
        for record in state['completed']:
            record['metrics']['mean_normalized_regret']=1
        self.assertIsNone(bo.report(self.config,self.contract,observations,state)['nominee'])

    def test_candidate_pool_is_feasible_unique_and_reproducible(self):
        observations,_=self.initialize()
        options=copy.deepcopy(self.config['options']);options['pool_size']=200
        a=bo.candidate_pool(options,observations['development'],np.random.default_rng(7),self.base)
        b=bo.candidate_pool(options,observations['development'],np.random.default_rng(7),self.base)
        np.testing.assert_array_equal(a,b)
        self.assertEqual(len({tuple(x) for x in a}),200)
        self.assertTrue(np.all(np.diff(a,axis=1)>=0))
        self.assertTrue(np.all((a>=0)&(a<=1200)))
        self.assertNotIn(tuple(self.base),{tuple(x) for x in a})

    def test_stopped_source_is_required_and_locked(self):
        with bo.stopped_source(self.config):
            with self.assertRaisesRegex(bo.BOError,'still running'):
                with bo.stopped_source(self.config):pass
        self.state['stopped']=False;bo.write(self.source/'loop_state.json',self.state)
        with self.assertRaisesRegex(bo.BOError,'phase boundary'):
            with bo.stopped_source(self.config):pass

    def test_overlapping_runner_is_noop_and_dry_run_does_not_create_run(self):
        with patch.object(bo,'environment',return_value=(self.env,self.contract)):
            self.assertEqual(bo.main(['--config',str(self.path),'--dry-run']),0)
            self.assertFalse(self.config['root'].exists())
            with bo.loop.locked(self.config['root']/'bo.lock'):
                self.assertEqual(bo.main(['--config',str(self.path),'--resume']),0)

    def test_validation_labels_never_enter_optimizer(self):
        self.state['archive']={'tuple': {'margins':[1,2,3,4,5],
            'metrics':{'evaluated_positions':1,'mean_normalized_regret':-999},'shards':[{'id':'sel'}]}}
        observations,state=self.initialize()
        self.assertEqual(len(observations['validated']),1)
        self.assertNotIn(-999,state['optimizer']['observations']['y'])

    def test_corrupt_checkpoint_history_is_rejected(self):
        self.initialize()
        path=self.config['root']/'state.json';state=bo.read(path)
        state['optimizer']['observations']['y'][0]=99;bo.write(path,state)
        with self.assertRaisesRegex(bo.BOError,'history differs'):
            self.initialize()

    def test_child_is_terminated_and_reaped_on_interrupt(self):
        process = unittest.mock.Mock(pid=12345)
        process.wait.side_effect = [KeyboardInterrupt(), None]
        process.poll.return_value = None
        with patch.object(bo.subprocess, 'Popen', return_value=process), \
             patch.object(bo.os, 'killpg') as kill:
            with self.assertRaises(KeyboardInterrupt):
                bo.run_command(['fixture-probe'], None)
        kill.assert_called_once_with(12345, bo.signal.SIGTERM)
        self.assertEqual(process.wait.call_count, 2)


if __name__=='__main__':
    unittest.main()
