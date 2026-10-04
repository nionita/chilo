#!/usr/bin/env python3
"""Bounded, resumable scalar BO using a stopped futility loop's observations."""
from __future__ import annotations

import argparse
import ast
import contextlib
import copy
import fcntl
import hashlib
import json
import math
import os
import platform
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import optimize_futility_gated as probes
import run_futility_campaign as campaign
import run_futility_loop as loop
import tune_futility as tune

try:
    import numpy as np
    import tinibo
    from tinibo import BayesianOptimizer
except ImportError as exc:
    raise ImportError('BO requires NumPy and tinibo on PYTHONPATH; see futility-tuning.md') from exc

SCHEMA = 'chilo.futility_bo.v1'
OPTIMIZER_SCHEMA = 'tinibo.optimizer.v3'
PRESET = dict(kernel='matern52', acquisition='ei', xi=0.0, xi_mode='raw',
              kappa=2.0, ei_incumbent='observed', gp_ard=False,
              noise_mode='learned', gp_fit_mode='scaled', gp_length_scale_bounds=[0.005, 1000],
              gp_n_restarts=8, gp_max_iter=100, gp_restart_strategy='coverage',
              duplicate_policy='ignore', n_restarts=0)
DEFAULTS = dict(max_proposals=5, seed=20261003, pool_size=10000,
                local_fraction=0.8, local_radius=80, local_centers=10,
                bounds=[[0, 1200]] * 5, model=PRESET)
write = campaign.atomic_json
read = loop.read
digest = loop.digest


class BOError(RuntimeError):
    pass


def script_closure(entry: Path):
    """Local import closure, also used to fingerprint and package the adapter."""
    found, todo = {}, [entry]
    while todo:
        path = todo.pop().resolve()
        if path.name in found:
            continue
        found[path.name] = path
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for name in names:
                candidate = entry.parent / (name.split('.')[0] + '.py')
                if candidate.is_file() and candidate.name not in found:
                    todo.append(candidate)
    return [found[k] for k in sorted(found)]


def code_identity():
    files = {f'scripts/{p.name}': tune.sha256_file(p) for p in script_closure(Path(__file__))}
    files.update({f'tinibo/{p.name}': tune.sha256_file(p)
                  for p in sorted(Path(tinibo.__file__).parent.glob('*.py'))})
    return files


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
    if not isinstance(raw.get('bo', {}), dict):
        raise BOError('bo must be an object')
    options = {**copy.deepcopy(DEFAULTS), **raw.get('bo', {})}
    if set(options) != set(DEFAULTS):
        raise BOError('unknown BO option')
    for name in ('max_proposals', 'pool_size', 'local_radius', 'local_centers'):
        campaign.require_int(options[name], name)
    campaign.require_int(options['seed'], 'seed', 0)
    fraction = options['local_fraction']
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 <= fraction <= 1:
        raise BOError('local_fraction must be between zero and one')
    bounds = options['bounds']
    if not isinstance(bounds, list) or not 3 <= len(bounds) <= 7 or any(
        not isinstance(b, list) or len(b) != 2 or
        any(type(v) is not int or v < 0 for v in b) or b[0] >= b[1] for b in bounds
    ):
        raise BOError('bounds require 3–7 nonnegative integer [low,high] pairs')
    base = loop.candidate(raw.get('base'))
    validate_tuple(base['margins'], bounds)
    if not isinstance(options['model'], dict) or set(options['model']) - set(PRESET):
        raise BOError('unknown model option')
    options['model'] = {**PRESET, **options['model']}
    if type(options['model']['gp_ard']) is not bool:
        raise BOError('model gp_ard must be boolean')
    if options['model']['kernel'] not in ('matern52', 'matern32', 'rbf'):
        raise BOError('model kernel must be matern52, matern32 or rbf')
    kappa = options['model']['kappa']
    if isinstance(kappa, bool) or not isinstance(kappa, (int, float)) or not math.isfinite(kappa) or kappa < 0:
        raise BOError('model kappa must be finite and nonnegative')
    if options['model']['ei_incumbent'] not in ('observed', 'posterior_mean'):
        raise BOError('model ei_incumbent must be observed or posterior_mean')
    # Validate the public optimizer settings before reading any engine data.
    BayesianOptimizer(objective=None, bounds=bounds, seed=options['seed'], **options['model'])
    return dict(path=path, raw=raw, store=store, root=store / 'evals' / run_id,
                source=store / 'evals' / source, options=options, base=base)


def validate_tuple(margins, bounds):
    values = tune.validate_margins(margins, 'BO margins')
    if len(values) != len(bounds) or any(not lo <= v <= hi for v, (lo, hi) in zip(values, bounds)):
        raise BOError('tuple dimension or bounds mismatch')
    return tuple(values)


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


def import_observations(config, env, contract, source):
    if source.get('schema') != loop.SCHEMA or source['contract'] != contract or source['contract_sha256'] != digest(contract):
        raise BOError('source loop contract is incompatible')
    records, identities = {}, []

    def add_record(record, output, provenance):
        margins = validate_tuple(record['margins'], config['options']['bounds'])
        if not campaign.same_identity(record.get('output'), tune.file_identity(output)):
            raise BOError(f'source raw probe differs: {output}')
        candidate = tune.parse_probe_output(output, env['candidate_nodes'], margins)
        if set(candidate['positions']) != set(env['development']['context'].baseline['positions']):
            raise BOError(f'source probe position coverage differs: {output}')
        target = record['metrics']['mean_normalized_regret']
        if isinstance(target, bool) or not isinstance(target, (int, float)) or not math.isfinite(target):
            raise BOError('nonfinite source target')
        if record['metrics']['evaluated_positions'] != env['development']['context'].trusted_set['trusted_position_count']:
            raise BOError('source scored population differs')
        if margins in records and records[margins]['metrics']['mean_normalized_regret'] != target:
            raise BOError('conflicting targets for an imported tuple')
        if margins not in records:
            records[margins] = {k: record[k] for k in ('margins', 'metrics', 'risk', 'semantic')}
            records[margins]['sources'] = []
        records[margins]['sources'].append({**provenance, 'output': tune.file_identity(output)})

    for state_path in sorted(config['source'].glob('cycles/*/search/state.json')):
        state = read(state_path)
        if state.get('status') != 'max_proposals':
            continue
        if state.get('schema') != probes.STATE_SCHEMA:
            raise BOError(f'unsupported source optimizer state: {state_path}')
        manifest_path = state_path.parent / 'optimizer_manifest.json'
        manifest = read(manifest_path)
        if manifest.get('schema') != probes.SCHEMA:
            raise BOError(f'unsupported source optimizer manifest: {manifest_path}')
        campaign.require_reuse_contract(manifest, env, str(state_path))
        if len(manifest.get('inputs', [])) != 1 or not campaign.same_identity(
            manifest['inputs'][0], tune.file_identity(env['development']['input'])
        ):
            raise BOError('source development input differs')
        identities.append({'state': tune.file_identity(state_path), 'manifest': tune.file_identity(manifest_path)})
        for record in state['evaluations']:
            alias = campaign.require_identifier(record['id'], 'source evaluation id')
            output = state_path.parent / 'probes' / f'{alias}.jsonl'
            add_record(record, output, {'cycle': state_path.parents[1].name, 'alias': alias})
        print(f'BO import cycle={state_path.parents[1].name} unique={len(records)}', flush=True)
    for identifier in config['raw'].get('import_bo_runs', []):
        root = config['store'] / 'evals' / identifier
        # Read under the existing producer lock. Evidence reuse is independent
        # of the producer's Python/NumPy/model settings; do not restore its GP.
        with (root / 'bo.lock').open('r') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BOError(f'imported BO run is still running: {identifier}') from exc
            manifest_path, state_path = root/'manifest.json', root/'state.json'
            prior_manifest, prior_state = read(manifest_path), read(state_path)
            if prior_manifest.get('schema') != SCHEMA or prior_manifest.get('contract') != contract or \
               prior_manifest.get('contract_sha256') != digest(contract) or \
               prior_manifest.get('config', {}).get('run_id') != identifier:
                raise BOError(f'imported BO run contract is incompatible: {identifier}')
            completed = prior_state.get('completed')
            expected = prior_manifest['config'].get('bo', {}).get('max_proposals', DEFAULTS['max_proposals'])
            if prior_state.get('schema') != SCHEMA or prior_state.get('status') != 'complete' or \
               prior_state.get('pending') is not None or not isinstance(completed, list) or len(completed) != expected:
                raise BOError(f'imported BO run must be complete: {identifier}')
            observations_path = root/'observations.json'
            if not campaign.same_identity(prior_manifest.get('observations'), tune.file_identity(observations_path)):
                raise BOError(f'imported BO observations differ: {identifier}')
            frozen = read(observations_path)
            history = frozen['development'] + completed
            if prior_state.get('optimizer', {}).get('observations') != {
                'x': [[float(v) for v in r['margins']] for r in history],
                'y': [float(r['metrics']['mean_normalized_regret']) for r in history],
            }:
                raise BOError(f'imported BO history differs: {identifier}')
            identities.append({'bo_run': identifier, 'state': tune.file_identity(state_path),
                               'manifest': tune.file_identity(manifest_path),
                               'observations': tune.file_identity(observations_path)})
            before = len(records)
            for index, record in enumerate(completed):
                if record['id'] != f'bo-{index:04d}':
                    raise BOError(f'imported BO evaluation is misnumbered: {identifier}')
                add_record(record, root/'probes'/f"{record['id']}.jsonl",
                           {'bo_run': identifier, 'alias': record['id']})
            print(f'BO import run={identifier} added={len(records)-before} unique={len(records)}', flush=True)
    if tuple(config['base']['margins']) not in records:
        raise BOError('SPRT base has no completed compatible development evaluation')
    count = sum(len(s['context'].trusted_keys) for s in env['selection'])
    validated = []
    for record in source['archive'].values():
        if record['metrics']['evaluated_positions'] != count or \
           {s['id'] for s in record['shards']} != {s['id'] for s in env['selection']}:
            raise BOError('source validation archive is not full selection')
        validated.append(record)
    return {'schema': SCHEMA, 'development': list(records.values()), 'validated': validated,
            'sources': identities, 'source_state': tune.file_identity(config['source'] / 'loop_state.json')}


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


def restore_optimizer(state):
    """Resume only current checkpoints; old measurements use import_bo_runs."""
    if not isinstance(state, dict) or state.get('schema') != OPTIMIZER_SCHEMA:
        raise BOError(f'unsupported optimizer checkpoint; expected {OPTIMIZER_SCHEMA}. '
                      'Keep the original package to resume v1/v2, or import completed measurements '
                      'via import_bo_runs into a new run ID; do not relabel old checkpoints')
    try:
        return BayesianOptimizer.from_state(state, objective=None)
    except ValueError as exc:
        raise BOError(f'invalid optimizer checkpoint: {exc}') from exc


def candidate_pool(options, observations, rng, base):
    seen = {tuple(r['margins']) for r in observations}
    centers = sorted(observations, key=lambda r: (r['metrics']['mean_normalized_regret'], r['margins']))[:options['local_centers']]
    centers = sorted({tuple(base), *(tuple(r['margins']) for r in centers)})
    bounds = np.asarray(options['bounds'], dtype=np.int64)
    local_count = round(options['pool_size'] * options['local_fraction'])
    rows = []
    for local, count in ((True, local_count), (False, options['pool_size'] - local_count)):
        accepted = 0
        for _ in range(max(count * 200, 1000)):
            if accepted == count:
                break
            if local:
                center = centers[int(rng.integers(len(centers)))]
                x = np.asarray(center) + rng.integers(-options['local_radius'], options['local_radius'] + 1, len(bounds))
            else:
                x = rng.integers(bounds[:, 0], bounds[:, 1] + 1)
            x = np.sort(np.clip(x, bounds[:, 0], bounds[:, 1]))
            if np.any(x < bounds[:, 0]) or np.any(x > bounds[:, 1]):
                continue
            key = tuple(int(v) for v in x)
            if key not in seen:
                seen.add(key)
                rows.append(key)
                accepted += 1
        if accepted != count:
            raise BOError('cannot fill unseen candidate pool; enlarge the domain or local radius')
    return np.asarray(rows, dtype=np.int64)


def probe_settings(config, env):
    return SimpleNamespace(probe=env['probe'], inputs=(env['development']['input'],), weights=env['weights'],
                           candidate_nodes=env['candidate_nodes'], score_scale=env['score_scale'],
                           probe_report_every=env['report_every'], probe_cache_dir=env['probe_cache_dir'],
                           anchor=env['development']['context'])


def run_command(command, log):
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        return SimpleNamespace(returncode=process.wait())
    except BaseException:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        raise


def evaluate_pending(config, env, pending):
    settings = probe_settings(config, env)
    candidate = probes.probe_one(settings, config['root'], pending['alias'], tuple(pending['margins']), run_command=run_command)
    result = probes.evaluate(settings, config['root'], pending['alias'], tuple(pending['margins']), candidate)
    return result


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
