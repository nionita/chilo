"""Qualify the target runtime and configured acquisition without engine work."""
import hashlib
import json
import platform
import time
import argparse
from pathlib import Path

import numpy as np
from tinibo import BayesianOptimizer
from tinibo.gp import GP
from run_futility_bo import load_config, restore_optimizer


def checkpoint_replay(X, y, bounds, model, pool):
    optimizer = BayesianOptimizer(objective=None, bounds=bounds, seed=19, **model)
    for x, target in zip(X, y):
        optimizer.tell(x, target)
    saved = json.loads(json.dumps(optimizer.get_state(), allow_nan=False))
    first = optimizer.ask(candidates=pool, return_info=True)
    second = restore_optimizer(saved).ask(candidates=pool, return_info=True)
    if first.pool_index != second.pool_index or not np.array_equal(first.x, second.x) or any(
        getattr(first, name) != getattr(second, name) for name in
        ('mean', 'std', 'acquisition_value', 'effective_xi', 'diagnostics')
    ):
        raise ValueError('Checkpoint proposal replay differs')
    if model['acquisition'] == 'ucb':
        if not np.isclose(first.acquisition_value, first.mean - model['kappa'] * first.std,
                          rtol=0, atol=1e-15) or first.diagnostics['ei_reference'] is not None:
            raise ValueError('LCB acquisition/diagnostics differ')
    fit = first.diagnostics['fit']
    scales = np.asarray(fit['length_scale'])
    expected_shape = (len(bounds),) if model['gp_ard'] else ()
    if scales.shape != expected_shape or not np.all(np.isfinite(scales)) or np.any(scales <= 0):
        raise ValueError('Configured scalar/ARD length-scale diagnostics differ')
    if fit['ard'] != model['gp_ard'] or fit['kernel'] != model['kernel'] or fit['training_count'] != len(X):
        raise ValueError('Configured surrogate diagnostics differ')
    if not np.isclose(fit['scale_ratio'], np.max(scales) / np.min(scales)):
        raise ValueError('ARD scale-ratio diagnostics differ')
    return saved['schema']


def main(root, loop_config=None):
    if loop_config:
        import run_futility_loop
        parsed = run_futility_loop.load_config(Path(loop_config).resolve())
        config = {'options': parsed['options']['search']['bo']}
    else:
        config = load_config(root / 'config/pilot.json')
    model, bounds = config['options']['model'], config['options']['bounds']
    fixture = root / 'verification/development.jsonl'
    rows = [json.loads(s) for s in fixture.read_text().splitlines()]
    X = np.asarray([r['margins'] for r in rows], dtype=float)
    y = np.asarray([r['target'] for r in rows], dtype=float)
    started = time.perf_counter()
    predictions, baseline = np.empty_like(y), np.empty_like(y)
    # Retain the qualified current-surrogate control independently of acquisition.
    for test in np.array_split(np.random.default_rng(19).permutation(len(y)), 5):
        train = np.setdiff1d(np.arange(len(y)), test)
        gp = GP('matern52', fit_mode='scaled', input_bounds=bounds, noise_mode='learned',
                length_scale_bounds=(0.005, 1000), restart_strategy='coverage')
        gp.fit(X[train], y[train], n_restarts=8, max_iter=100)
        predictions[test] = gp.predict(X[test], return_std=False)
        baseline[test] = y[train].mean()
    ratio = float(np.sqrt(np.mean((predictions-y)**2)) / np.sqrt(np.mean((baseline-y)**2)))
    if not np.isfinite(ratio) or ratio > 0.95:
        raise ValueError(f'Numerical environment failed predictive check: RMSE ratio={ratio}')
    pool = np.sort(np.random.default_rng(23).integers(0, 1201, (100, 5)), axis=1)
    schema = checkpoint_replay(X, y, bounds, model, pool)
    report = {'python': platform.python_version(), 'numpy': np.__version__,
              'model': model, 'optimizer_schema': schema, 'rmse_ratio': ratio,
              'checkpoint_replay': True, 'elapsed_s': time.perf_counter()-started,
              'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}
    path = root / 'numerics-check.json'
    if path.exists():
        previous = json.loads(path.read_text())
        if any(previous.get(key) != report[key] for key in
               ('python', 'numpy', 'model', 'optimizer_schema', 'fixture_sha256')):
            raise ValueError('Verified runtime/model/fixture changed; restore the original package')
    else:
        path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--loop-config')
        args = parser.parse_args()
        main(Path(__file__).resolve().parent, args.loop_config)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
