#!/usr/bin/env python3
"""Bounded, resumable scalar BO using a stopped futility loop's observations."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import platform
import signal
import subprocess
import sys
from pathlib import Path

import optimize_futility_gated as probes
import run_futility_campaign as campaign
import run_futility_loop as loop
import tune_futility as tune
from futility_bo_core import (SCHEMA, OPTIMIZER_SCHEMA, PRESET, DEFAULTS, BOError,
    script_closure, code_identity, validate_tuple, restore_optimizer, candidate_pool,
    probe_settings, run_command, evaluate_pending as shared_evaluate_pending,
    import_observations, normalize_options)

try:
    import numpy as np
    import tinibo
    from tinibo import BayesianOptimizer
except ImportError as exc:
    raise ImportError('BO requires NumPy and tinibo on PYTHONPATH; see futility-tuning.md') from exc

write = campaign.atomic_json
read = loop.read
digest = loop.digest


def load_config(path):
    raw = read(path)
    allowed = loop.CONTRACT_FIELDS | {'schema', 'run_id', 'source_loop', 'base',
                                     'report_every', 'bo', 'expected_contract_sha256', 'import_bo_runs'}
    if raw.get('schema') != SCHEMA or set(raw) - allowed:
        raise BOError('invalid BO schema or unknown config fields')
    run_id = campaign.require_identifier(raw.get('run_id'), 'run_id')
    source = campaign.require_identifier(raw.get('source_loop'), 'source_loop')
    if source == run_id:
        raise BOError('source_loop must differ from run_id')
    imports = raw.get('import_bo_runs', [])
    if not isinstance(imports, list):
        raise BOError('import_bo_runs must be a list of completed BO run IDs')
    imports = [campaign.require_identifier(value, 'import_bo_runs') for value in imports]
    if len(set(imports)) != len(imports) or run_id in imports or source in imports:
        raise BOError('import_bo_runs must be distinct and exclude this run and source loop')
    store = campaign.resolve(path, raw.get('store_root'), 'store_root')
    base = loop.candidate(raw.get('base'))
    options = normalize_options(raw.get('bo', {}), base['margins'])
    return dict(path=path, raw=raw, store=store, root=store / 'evals' / run_id,
                source=store / 'evals' / source, options=options, base=base)


def environment(config):
    synthetic = {'path': config['path'], 'raw': {**config['raw'], 'loop_id': config['raw']['run_id']},
                 'options': {'report_every': config['raw'].get('report_every', 1000)}}
    env, contract = loop.environment(synthetic)
    expected = config['raw'].get('expected_contract_sha256')
    if expected is not None and expected != digest(contract):
        raise BOError('effective artifacts/populations differ from expected contract')
    return env, contract


@contextlib.contextmanager
def stopped_source(config):
    """Hold the old loop's existing process lock without editing its state."""
    with (config['source'] / 'loop.lock').open('r') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BOError('source loop is still running; wait for its graceful stop') from exc
        try:
            state = read(config['source'] / 'loop_state.json')
            control = read(config['source'] / 'control.json')
            if not state.get('stopped') or state.get('active') is not None:
                raise BOError('source loop must be stopped at a phase boundary')
            if control['base']['margins'] != config['base']['margins']:
                raise BOError('configured SPRT base differs from source control')
            yield state
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def manifest(config, contract):
    return {'schema': SCHEMA, 'config': config['raw'], 'contract': contract,
            'optimizer_schema': OPTIMIZER_SCHEMA,
            'contract_sha256': digest(contract), 'code': code_identity(),
            'environment': {'python': platform.python_version(), 'numpy': np.__version__,
                            'blas_threads': {k: os.environ.get(k) for k in
                                            ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')}}}


def initialize(config, env, contract, source):
    root = config['root']
    expected = manifest(config, contract)
    path = root / 'manifest.json'
    if path.exists():
        existing = read(path)
        if {k: existing[k] for k in expected} != expected:
            raise BOError('BO manifest mismatch; use the original config/code/environment or a new run ID')
        if existing['observations'] != tune.file_identity(root / 'observations.json'):
            raise BOError('frozen imported observations differ')
        observations = read(root / 'observations.json')
    else:
        allowed = {'bo.lock', 'observations.json', 'observations.json.tmp', 'manifest.json.tmp'}
        if any(p.name not in allowed for p in root.iterdir()):
            raise BOError('nonempty run directory without BO manifest')
        observations = import_observations(config, env, contract, source)
        write(root / 'observations.json', observations)
        write(path, {**expected, 'observations': tune.file_identity(root / 'observations.json')})
    state_path = root / 'state.json'
    if state_path.exists():
        state = read(state_path)
        if state.get('schema') != SCHEMA or state.get('status') not in {'running', 'complete'}:
            raise BOError('invalid BO state')
        validate_state(config, observations, state)
        return observations, state
    optimizer = BayesianOptimizer(objective=None, bounds=config['options']['bounds'],
                                  seed=config['options']['seed'], **config['options']['model'])
    for record in observations['development']:
        optimizer.tell(record['margins'], record['metrics']['mean_normalized_regret'])
    state = {'schema': SCHEMA, 'status': 'running', 'completed': [], 'pending': None,
             'optimizer': optimizer.get_state(),
             'pool_rng': np.random.default_rng(config['options']['seed']).bit_generator.state}
    write(state_path, state)
    return observations, state


def validate_state(config, observations, state):
    completed = state.get('completed')
    if not isinstance(completed, list) or len(completed) > config['options']['max_proposals'] or \
       (state['status'] == 'complete') != (len(completed) == config['options']['max_proposals']):
        raise BOError('checkpoint evaluation count/status differs')
    optimizer = restore_optimizer(state.get('optimizer'))
    fresh = BayesianOptimizer(objective=None, bounds=config['options']['bounds'],
                              seed=config['options']['seed'], **config['options']['model'])
    if optimizer.get_state()['settings'] != fresh.get_state()['settings']:
        raise BOError('checkpoint optimizer settings differ from manifest')
    expected = observations['development'] + completed
    if optimizer.get_state()['observations'] != {
        'x': [[float(v) for v in r['margins']] for r in expected],
        'y': [float(r['metrics']['mean_normalized_regret']) for r in expected],
    }:
        raise BOError('checkpoint optimizer history differs from committed evaluations')
    seen = {tuple(r['margins']) for r in observations['development']}
    for index, record in enumerate(completed):
        margins = validate_tuple(record['margins'], config['options']['bounds'])
        if margins in seen or record['id'] != f'bo-{index:04d}':
            raise BOError('duplicate or misnumbered committed evaluation')
        seen.add(margins)
        output = config['root'] / 'probes' / f"{record['id']}.jsonl"
        if not campaign.same_identity(record['output'], tune.file_identity(output)):
            raise BOError('committed probe output differs')
    pending = state.get('pending')
    if pending is not None:
        margins = validate_tuple(pending['margins'], config['options']['bounds'])
        if state['status'] == 'complete' or margins in seen or pending['alias'] != f'bo-{len(completed):04d}':
            raise BOError('invalid pending proposal')
    rng = np.random.default_rng()
    rng.bit_generator.state = state['pool_rng']


def evaluate_pending(config, env, pending):
    return shared_evaluate_pending(config, env, pending, runner=run_command)


def report(config, contract, observations, state):
    base = next(r for r in observations['development'] if r['margins'] == config['base']['margins'])
    validated = {tuple(r['margins']) for r in observations['validated']}
    eligible = [r for r in state['completed'] if tuple(r['margins']) not in validated and
                r['metrics']['mean_normalized_regret'] < base['metrics']['mean_normalized_regret']]
    eligible.sort(key=lambda r: (r['metrics']['mean_normalized_regret'], r['margins']))
    nominee = eligible[0] if eligible and state['status'] == 'complete' else None
    results = {'schema': SCHEMA, 'status': state['status'], 'imported_count': len(observations['development']),
               'completed_count': len(state['completed']), 'base': base, 'evaluations': state['completed'],
               'nominee': nominee, 'contract_sha256': digest(contract)}
    write(config['root'] / 'results.json', results)
    write(config['root'] / 'nominee.json', {'schema': SCHEMA, 'candidate': nominee,
          'reason': 'new unvalidated tuple improving base dev mean regret' if nominee else
                    'no nominee yet' if state['status'] != 'complete' else 'no eligible improvement'})
    lines = ['# Futility BO pilot', '', f"Status: {state['status']}; imported: {len(observations['development'])}; "
             f"completed: {len(state['completed'])}/{config['options']['max_proposals']}", '',
             'Development only; validation and SPRT require separate operator decisions.', '',
             '| Candidate | Margins | Mean regret | Squared regret | CVaR-1% | Cache |',
             '|---|---|---:|---:|---:|---|']
    for r in [dict(base, id='SPRT base'), *state['completed']]:
        risk = r['risk']['absolute_regret']
        lines.append(f"| {r['id']} | {','.join(map(str,r['margins']))} | {r['metrics']['mean_normalized_regret']:.9f} | "
                     f"{risk['mean_squared']:.9f} | {risk['tail_mean']['top_0.01']:.9f} | {r.get('cache',{}).get('status','imported')} |")
    (config['root'] / 'report.md').write_text('\n'.join(lines) + '\n')
    return results


def run(config, env, contract, observations, state, limit=0):
    root = config['root']
    for directory in ('probes', 'logs'):
        (root / directory).mkdir(exist_ok=True)
    optimizer = restore_optimizer(state['optimizer'])
    rng = np.random.default_rng()
    rng.bit_generator.state = state['pool_rng']
    done = 0
    while len(state['completed']) < config['options']['max_proposals'] and (not limit or done < limit):
        if state['pending'] is None:
            pool = candidate_pool(config['options'], observations['development'] + state['completed'], rng, config['base']['margins'])
            info = optimizer.ask(candidates=pool, return_info=True)
            margins = [int(v) for v in info.x]
            state['pending'] = {'alias': f"bo-{len(state['completed']):04d}", 'margins': margins,
                'tuple_id': loop.tuple_id({'contract_sha256': digest(contract)}, margins),
                'pool_sha256': digest(pool.tolist()), 'proposal': {'mean': info.mean, 'std': info.std,
                'acquisition_value': info.acquisition_value, 'effective_xi': info.effective_xi,
                'diagnostics': info.diagnostics}}
            state['pool_rng'] = rng.bit_generator.state
            state['optimizer'] = optimizer.get_state()
            write(root / 'state.json', state)
        pending = state['pending']
        print(f"BO probe {len(state['completed'])+1}/{config['options']['max_proposals']} "
              f"{pending['alias']} margins={','.join(map(str,pending['margins']))}", flush=True)
        result = evaluate_pending(config, env, pending)
        result.update(tuple_id=pending['tuple_id'], proposal=pending['proposal'], pool_sha256=pending['pool_sha256'])
        optimizer.tell(result['margins'], result['metrics']['mean_normalized_regret'])
        state['completed'].append(result)
        state['pending'] = None
        state['optimizer'] = optimizer.get_state()
        state['status'] = 'complete' if len(state['completed']) == config['options']['max_proposals'] else 'running'
        write(root / 'state.json', state)
        report(config, contract, observations, state)
        done += 1
    return report(config, contract, observations, state)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max-evaluations', type=int, default=0)
    args = parser.parse_args(argv)
    if args.max_evaluations < 0:
        raise BOError('max-evaluations must be nonnegative')
    config = load_config(Path(args.config).expanduser().resolve())
    guard = contextlib.nullcontext(True) if args.dry_run else loop.locked(config['root'] / 'bo.lock')
    with guard as acquired:
        if not acquired:
            print('BO pilot already running', flush=True)
            return 0
        env, contract = environment(config)
        with stopped_source(config) as source:
            if source.get('contract') != contract:
                raise BOError('source contract differs from effective pilot contract')
            if args.dry_run:
                if (config['root'] / 'manifest.json').exists():
                    existing = read(config['root'] / 'manifest.json')
                    if any(existing.get(k) != v for k, v in manifest(config, contract).items()):
                        raise BOError('existing pilot manifest differs')
                print(json.dumps({'status': 'ok', 'contract_sha256': digest(contract), 'base': config['base'],
                      'run_dir': str(config['root']), 'bo': config['options']}, indent=2))
                return 0
            if (config['root'] / 'state.json').exists() and not args.resume:
                raise BOError('pilot exists; use --resume')
            observations, state = initialize(config, env, contract, source)
            print(f"BO imported={len(observations['development'])} validated={len(observations['validated'])}", flush=True)
            result = run(config, env, contract, observations, state, args.max_evaluations)
            print(f"BO {result['status']} completed={result['completed_count']} nominee="
                  f"{result['nominee']['tuple_id'] if result['nominee'] else 'none'}", flush=True)
    return 0


if __name__ == '__main__':
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('BO interrupted; pending tuple is retained for --resume', file=sys.stderr)
        raise SystemExit(130)
    except (BOError, loop.LoopError, campaign.CampaignError, OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f'fatal: {exc}', file=sys.stderr)
        raise SystemExit(1)
