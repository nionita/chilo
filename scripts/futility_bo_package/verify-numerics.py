"""Qualify the target Python/NumPy runtime on the packaged development fixture."""
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
from tinibo import BayesianOptimizer
from tinibo.gp import GP
from run_futility_bo import PRESET

root = Path(__file__).resolve().parent
rows = [json.loads(s) for s in (root/'verification/development.jsonl').read_text().splitlines()]
X = np.asarray([r['margins'] for r in rows],dtype=float)
y = np.asarray([r['target'] for r in rows],dtype=float)
bounds = [(0,1200)]*5
started = time.perf_counter()
predictions, baseline = np.empty_like(y), np.empty_like(y)
for test in np.array_split(np.random.default_rng(19).permutation(len(y)),5):
    train = np.setdiff1d(np.arange(len(y)),test)
    gp = GP('matern52',fit_mode='scaled',input_bounds=bounds,noise_mode='learned',
            length_scale_bounds=(0.005,1000),restart_strategy='coverage')
    gp.fit(X[train],y[train],n_restarts=8,max_iter=100)
    predictions[test] = gp.predict(X[test],return_std=False)
    baseline[test] = y[train].mean()
ratio = float(np.sqrt(np.mean((predictions-y)**2))/np.sqrt(np.mean((baseline-y)**2)))
if not np.isfinite(ratio) or ratio > 0.95:
    raise SystemExit(f'Numerical environment failed predictive check: RMSE ratio={ratio}')
optimizer = BayesianOptimizer(objective=None,bounds=bounds,seed=19,**PRESET)
for x,target in zip(X,y):
    optimizer.tell(x,target)
pool = np.sort(np.random.default_rng(23).integers(0,1201,(100,5)),axis=1)
saved = json.loads(json.dumps(optimizer.get_state(),allow_nan=False))
first = optimizer.ask(candidates=pool,return_info=True)
second = BayesianOptimizer.from_state(saved,objective=None).ask(candidates=pool,return_info=True)
if first.pool_index != second.pool_index or not np.array_equal(first.x,second.x) or first.mean != second.mean:
    raise SystemExit('Checkpoint proposal replay differs')
report = {'python':platform.python_version(),'numpy':np.__version__,'rmse_ratio':ratio,
          'checkpoint_replay':True,'elapsed_s':time.perf_counter()-started,
          'fixture_sha256':hashlib.sha256((root/'verification/development.jsonl').read_bytes()).hexdigest()}
old = root/'numerics-check.json'
if old.exists():
    previous=json.loads(old.read_text())
    if previous['python']!=report['python'] or previous['numpy']!=report['numpy']:
        raise SystemExit('Verified Python/NumPy environment changed; restore the original runtime')
else:
    old.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
