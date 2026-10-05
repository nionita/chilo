"""Shared numerical and evidence adapter for standalone and loop BO.

Imported lazily by the loop; Pareto execution needs no numerical dependencies.
"""
from __future__ import annotations
import ast
import copy
import fcntl
import hashlib
import json
import math
import os
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace
import optimize_futility_gated as probes
import run_futility_campaign as campaign
import tune_futility as tune
try:
    import numpy as np
    import tinibo
    from tinibo import BayesianOptimizer
except ImportError as exc:
    raise ImportError('BO requires NumPy and tinibo on PYTHONPATH; see futility-tuning.md') from exc

class BOError(RuntimeError):
    pass

write = campaign.atomic_json

def read(path):
    return campaign.read_json(path, str(path))

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

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


def code_identity(entry=None):
    files = {f'scripts/{p.name}': tune.sha256_file(p) for p in script_closure(Path(entry) if entry else Path(__file__).with_name('run_futility_bo.py'))}
    files.update({f'tinibo/{p.name}': tune.sha256_file(p)
                  for p in sorted(Path(tinibo.__file__).parent.glob('*.py'))})
    return files


def normalize_options(raw_options, base):
    if not isinstance(raw_options, dict):
        raise BOError('bo must be an object')
    options = {**copy.deepcopy(DEFAULTS), **raw_options}
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
    validate_tuple(base, bounds)
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
    return options


def validate_tuple(margins, bounds):
    values = tune.validate_margins(margins, 'BO margins')
    if len(values) != len(bounds) or any(not lo <= v <= hi for v, (lo, hi) in zip(values, bounds)):
        raise BOError('tuple dimension or bounds mismatch')
    return tuple(values)


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


def evaluate_pending(config, env, pending, runner=None):
    settings = probe_settings(config, env)
    candidate = probes.probe_one(settings, config['root'], pending['alias'], tuple(pending['margins']), run_command=runner or run_command)
    result = probes.evaluate(settings, config['root'], pending['alias'], tuple(pending['margins']), candidate)
    return result


def import_observations(config, env, contract, source):
    if source.get('schema') != 'chilo.futility_loop.v1' or source['contract'] != contract or source['contract_sha256'] != digest(contract):
        raise BOError('source loop contract is incompatible')
    records, identities, scored_outputs = {}, [], {}

    def add_record(record, output, provenance):
        margins = validate_tuple(record['margins'], config['options']['bounds'])
        output_identity = tune.file_identity(output)
        if not campaign.same_identity(record.get('output'), output_identity):
            raise BOError(f'source raw probe differs: {output}')
        target = record['metrics']['mean_normalized_regret']
        if isinstance(target, bool) or not isinstance(target, (int, float)) or not math.isfinite(target):
            raise BOError('nonfinite source target')
        if record['metrics']['evaluated_positions'] != env['development']['context'].trusted_set['trusted_position_count']:
            raise BOError('source scored population differs')
        if margins in records and records[margins]['metrics']['mean_normalized_regret'] != target:
            raise BOError('conflicting targets for an imported tuple')
        # Warm snapshots and cache hits repeat the same raw evidence many times.
        # Hash every source, but parse/score identical bytes only once per import.
        key = (margins, output_identity['sha256'])
        if key not in scored_outputs:
            candidate = tune.parse_probe_output(output, env['candidate_nodes'], margins)
            if set(candidate['positions']) != set(env['development']['context'].baseline['positions']):
                raise BOError(f'source probe position coverage differs: {output}')
            scored_outputs[key] = probes.evaluate(probe_settings(config, env), output.parents[1],
                                                 output.stem, margins, candidate)
        scored = scored_outputs[key]
        if any(record[k] != scored[k] for k in ('metrics', 'risk', 'semantic')):
            raise BOError(f'source scored metrics differ from raw evidence: {output}')
        if margins not in records:
            records[margins] = {k: record[k] for k in ('margins', 'metrics', 'risk', 'semantic')}
            records[margins]['sources'] = []
        records[margins]['sources'].append({**provenance, 'output': output_identity})

    for state_path in sorted(config['source'].glob('cycles/*/search/state.json')):
        state = read(state_path)
        if state.get('schema') == SCHEMA:
            if state.get('status') != 'complete':
                continue
            root = state_path.parent
            receipt = read(root / 'manifest.json')
            if receipt.get('contract') != contract or receipt.get('contract_sha256') != digest(contract):
                raise BOError(f'incompatible BO cycle contract: {root}')
            frozen = completed_history(root, receipt, state)
            identities.append({'state': tune.file_identity(state_path),
                               'manifest': tune.file_identity(root / 'manifest.json')})
            for record in frozen['development']:
                if not record.get('sources'):
                    raise BOError('BO warm observation has no raw provenance')
                origin = record['sources'][0]
                output = evidence_path(config, origin)
                add_record({**record, 'output': origin['output']}, output,
                           {'cycle': state_path.parents[1].name, 'alias': 'warm'})
            for record in state['completed']:
                add_record(record, root / 'probes' / f"{record['id']}.jsonl",
                           {'cycle': state_path.parents[1].name, 'alias': record['id']})
            continue
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


def evidence_path(config, origin):
    """Resolve stable producer IDs before informational absolute cloud paths."""
    alias = campaign.require_identifier(origin['alias'], 'source alias')
    if 'bo_run' in origin:
        identifier = campaign.require_identifier(origin['bo_run'], 'source BO run')
        relocated = config['store'] / 'evals' / identifier / 'probes' / f'{alias}.jsonl'
    else:
        cycle = origin['cycle']
        if not isinstance(cycle, str) or not cycle.isascii() or not cycle.isdigit():
            raise BOError('source cycle must be numeric')
        relocated = config['source'] / 'cycles' / cycle / 'search' / 'probes' / f'{alias}.jsonl'
    return relocated if relocated.is_file() else Path(origin['output']['path'])


def completed_history(root, receipt, state):
    """Verify a complete numerical transaction, not just its status string."""
    frozen_path = root / 'observations.json'
    if not campaign.same_identity(receipt.get('observations'), tune.file_identity(frozen_path)):
        raise BOError('frozen BO observations differ')
    frozen = read(frozen_path)
    completed = state.get('completed')
    if not isinstance(completed, list) or state.get('pending') is not None or \
       len(completed) != receipt['options']['max_proposals']:
        raise BOError('incomplete BO cycle history')
    history = frozen['development'] + completed
    if len({tuple(r['margins']) for r in history}) != len(history):
        raise BOError('BO cycle contains duplicate measured tuples')
    if state.get('optimizer', {}).get('observations') != {
        'x': [[float(v) for v in r['margins']] for r in history],
        'y': [float(r['metrics']['mean_normalized_regret']) for r in history],
    }:
        raise BOError('BO cycle optimizer history differs')
    if any(r['id'] != f'bo-{i:04d}' for i, r in enumerate(completed)):
        raise BOError('BO cycle evaluations are misnumbered')
    return frozen
