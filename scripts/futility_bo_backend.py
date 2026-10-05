"""BO development phase adapter. No dependency on the loop controller."""
from __future__ import annotations

import copy
import os
import platform
from pathlib import Path

import futility_bo_core as core


def options(search, base, loop_id):
    if search['workers'] != 1:
        raise core.BOError('BO requires search.workers=1 (sequential ask/tell)')
    raw = search.get('bo', {})
    if not isinstance(raw, dict) or set(raw) - (set(core.DEFAULTS) - {'seed', 'max_proposals'} | {'import_bo_runs'}):
        raise core.BOError('unknown search.bo option; budget and seed belong in search')
    raw = copy.deepcopy(raw)
    imports = raw.pop('import_bo_runs', [])
    if not isinstance(imports, list):
        raise core.BOError('import_bo_runs must be a list')
    imports = [core.campaign.require_identifier(v, 'import_bo_runs') for v in imports]
    if len(set(imports)) != len(imports) or loop_id in imports:
        raise core.BOError('import_bo_runs must be distinct and exclude this loop')
    defaults = dict(local_fraction=1.0, bounds=[[0, search['max_margin']]] * len(base),
                    model={**core.PRESET, 'gp_ard': True, 'acquisition': 'ucb', 'kappa': 0.5})
    supplied_model = raw.pop('model', {})
    if not isinstance(supplied_model, dict):
        raise core.BOError('model must be an object')
    value = core.normalize_options({**defaults, **raw,
        'model': {**defaults['model'], **supplied_model},
        'max_proposals': search['max_proposals'], 'seed': search['seed']}, base)
    if any(hi > search['max_margin'] for lo, hi in value['bounds']):
        raise core.BOError('BO bounds exceed max_margin')
    return {k: v for k, v in value.items() if k not in {'max_proposals', 'seed'}} | {'import_bo_runs': imports}


def phase_config(config, state):
    active = state['active']
    search = active['options']['search']
    bo = copy.deepcopy(search['bo'])
    imports = bo.pop('import_bo_runs')
    bo.update(max_proposals=search['max_proposals'], seed=active['seed'])
    base = state['candidates'][active['base_id']]
    core.validate_tuple(base['margins'], bo['bounds'])
    return dict(root=config['root'] / 'cycles' / f"{active['cycle']:06d}" / 'search',
                source=config['root'], store=config['store'], options=bo, base=base,
                raw={'import_bo_runs': imports})


def identity(config, state):
    return dict(schema=core.SCHEMA, backend='bo', contract=state['contract'],
                contract_sha256=state['contract_sha256'], options=config['options'],
                base=config['base'], optimizer_schema=core.OPTIMIZER_SCHEMA,
                code=core.code_identity(Path(__file__)),
                environment={'python': platform.python_version(), 'numpy': core.np.__version__,
                    'blas_threads': {k: os.environ.get(k) for k in
                        ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')}})


def prepare(config, env, loop_state):
    root = config['root']
    root.mkdir(parents=True, exist_ok=True)
    expected = identity(config, loop_state)
    path = root / 'manifest.json'
    if path.exists():
        receipt = core.read(path)
        if any(receipt.get(k) != v for k, v in expected.items()):
            raise core.BOError('active BO code/config/runtime changed; restore its original package to finish the phase')
        if not core.campaign.same_identity(receipt['observations'], core.tune.file_identity(root / 'observations.json')):
            raise core.BOError('frozen BO observations differ')
        observations = core.read(root / 'observations.json')
    else:
        allowed = {'observations.json', 'observations.json.tmp', 'manifest.json.tmp'}
        if any(p.name not in allowed for p in root.iterdir()):
            raise core.BOError('nonempty BO phase without manifest')
        observations = core.import_observations(config, env, loop_state['contract'], loop_state)
        core.write(root / 'observations.json', observations)
        core.write(path, {**expected, 'observations': core.tune.file_identity(root / 'observations.json')})
    path = root / 'state.json'
    if path.exists():
        state = core.read(path)
        validate(config, observations, state)
    else:
        optimizer = core.BayesianOptimizer(objective=None, bounds=config['options']['bounds'],
                                          seed=config['options']['seed'], **config['options']['model'])
        for record in observations['development']:
            optimizer.tell(record['margins'], record['metrics']['mean_normalized_regret'])
        state = dict(schema=core.SCHEMA, status='running', completed=[], pending=None,
                     optimizer=optimizer.get_state(),
                     pool_rng=core.np.random.default_rng(config['options']['seed']).bit_generator.state)
        core.write(path, state)
    return observations, state


def validate(config, observations, state):
    if state.get('schema') != core.SCHEMA or state.get('status') not in {'running', 'complete'}:
        raise core.BOError('invalid BO phase state')
    completed = state.get('completed')
    count = config['options']['max_proposals']
    if not isinstance(completed, list) or len(completed) > count or \
       (state['status'] == 'complete') != (len(completed) == count):
        raise core.BOError('BO checkpoint count/status differs')
    optimizer = core.restore_optimizer(state['optimizer'])
    fresh = core.BayesianOptimizer(objective=None, bounds=config['options']['bounds'],
                                  seed=config['options']['seed'], **config['options']['model'])
    if optimizer.get_state()['settings'] != fresh.get_state()['settings']:
        raise core.BOError('BO checkpoint settings differ')
    history = observations['development'] + completed
    if state['optimizer']['observations'] != {
        'x': [[float(v) for v in r['margins']] for r in history],
        'y': [float(r['metrics']['mean_normalized_regret']) for r in history]}:
        raise core.BOError('BO checkpoint history differs')
    seen = {tuple(r['margins']) for r in observations['development']}
    for index, record in enumerate(completed):
        margins = core.validate_tuple(record['margins'], config['options']['bounds'])
        if margins in seen or record['id'] != f'bo-{index:04d}':
            raise core.BOError('duplicate or misnumbered BO measurement')
        seen.add(margins)
        if not core.campaign.same_identity(record['output'], core.tune.file_identity(config['root'] / 'probes' / f"{record['id']}.jsonl")):
            raise core.BOError('committed BO raw output differs')
    if state.get('pending') is not None:
        pending = state['pending']
        margins = core.validate_tuple(pending['margins'], config['options']['bounds'])
        if state['status'] == 'complete' or margins in seen or pending['alias'] != f'bo-{len(completed):04d}':
            raise core.BOError('invalid BO pending proposal')
    rng = core.np.random.default_rng()
    rng.bit_generator.state = state['pool_rng']


def run(config, env, loop_state, limit=0):
    """Persist ask before probing and tell plus result in one atomic transaction."""
    observations, state = prepare(config, env, loop_state)
    root = config['root']
    for name in ('probes', 'logs'):
        (root / name).mkdir(exist_ok=True)
    optimizer = core.restore_optimizer(state['optimizer'])
    rng = core.np.random.default_rng()
    rng.bit_generator.state = state['pool_rng']
    done = 0
    while len(state['completed']) < config['options']['max_proposals'] and (not limit or done < limit):
        if state['pending'] is None:
            pool = core.candidate_pool(config['options'], observations['development'] + state['completed'], rng, config['base']['margins'])
            suggestion = optimizer.ask(candidates=pool, return_info=True)
            margins = [int(v) for v in suggestion.x]
            state['pending'] = dict(alias=f"bo-{len(state['completed']):04d}", margins=margins,
                tuple_id='t-' + core.digest({'contract': loop_state['contract_sha256'], 'margins': margins})[:24],
                pool_sha256=core.digest(pool.tolist()), proposal=dict(mean=suggestion.mean,
                    std=suggestion.std, acquisition_value=suggestion.acquisition_value,
                    effective_xi=suggestion.effective_xi, diagnostics=suggestion.diagnostics))
            state['optimizer'], state['pool_rng'] = optimizer.get_state(), rng.bit_generator.state
            core.write(root / 'state.json', state)
        pending = state['pending']
        print(f"BO development {len(state['completed'])+1}/{config['options']['max_proposals']} "
              f"{pending['alias']} margins={','.join(map(str, pending['margins']))} "
              f"mean={pending['proposal']['mean']} std={pending['proposal']['std']} "
              f"acquisition={pending['proposal']['acquisition_value']}", flush=True)
        result = core.evaluate_pending(config, env, pending)
        result.update(tuple_id=pending['tuple_id'], proposal=pending['proposal'], pool_sha256=pending['pool_sha256'])
        optimizer.tell(result['margins'], result['metrics']['mean_normalized_regret'])
        state['completed'].append(result)
        state.update(pending=None, optimizer=optimizer.get_state(),
                     status='complete' if len(state['completed']) == config['options']['max_proposals'] else 'running')
        core.write(root / 'state.json', state)
        print(f"BO measured mean={result['metrics']['mean_normalized_regret']} "
              f"cache={result.get('cache', {}).get('status', 'disabled')}", flush=True)
        done += 1
    base = next(r for r in observations['development'] if r['margins'] == config['base']['margins'])
    return state, [dict(base, id='initial'), *state['completed']]
