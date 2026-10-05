#!/usr/bin/env python3
"""Offline validation-target GP study; never edits a loop or runs engine probes.

Train on full pooled validation labels, not SR4 targets or Elo. Development
measurements supply coordinates only for a finite, already-dev-measured pool.
Held-out prediction checks are descriptive on an adaptively collected dataset,
not an independent optimization or strength qualification.
"""
from __future__ import annotations
import argparse
import json
import math
import platform
from pathlib import Path
import futility_bo_core as core
from run_futility_loop import portable
from tinibo.gp import GP
from compare_futility_bo_lcb import load_rows


def add_rows(unique, rows, positions=141099, depth=5):
    for row in rows:
        margins = tuple(core.tune.validate_margins(row['margins'], 'validation tuple'))
        if len(margins) != depth:
            continue
        metrics = row.get('metrics', row.get('pooled_metrics'))
        if metrics['evaluated_positions'] != positions:
            raise ValueError('validation labels must cover the complete pooled population')
        target = metrics['mean_normalized_regret']
        if isinstance(target,bool) or not isinstance(target,(int,float)) or not math.isfinite(target):
            raise ValueError('invalid validation target')
        if margins in unique and unique[margins]['target'] != target:
            raise ValueError('conflicting validation labels')
        unique.setdefault(margins,dict(margins=list(margins),target=target))


def predict_check(rows, ard, seed=20261006, restarts=8, iterations=100):
    X = core.np.asarray([r['margins'] for r in rows], dtype=float)
    y = core.np.asarray([r['target'] for r in rows], dtype=float)
    prediction, baseline = core.np.empty_like(y), core.np.empty_like(y)
    folds = []
    for test in core.np.array_split(core.np.random.default_rng(seed).permutation(len(y)),5):
        train = core.np.setdiff1d(core.np.arange(len(y)),test)
        gp = make_gp(ard)
        gp.fit(X[train],y[train],n_restarts=restarts,max_iter=iterations)
        prediction[test] = gp.predict(X[test],return_std=False)
        baseline[test] = y[train].mean()
        folds.append(dict(train=train.tolist(),test=test.tolist()))
    rmse = float(core.np.sqrt(core.np.mean((prediction-y)**2)))
    reference = float(core.np.sqrt(core.np.mean((baseline-y)**2)))
    return dict(ard=ard,rmse=rmse,baseline_rmse=reference,
        rmse_ratio=rmse/reference if reference else None,
        folds=folds,predictions=prediction.tolist(),baseline_predictions=baseline.tolist())


def make_gp(ard):
    return GP('matern52',fit_mode='scaled',input_bounds=[[0,1200]]*5,
        noise_mode='learned',length_scale_bounds=(0.005,1000),
        restart_strategy='coverage',ard=ard)


def study(rows, pool, seed=20261006, restarts=8, iterations=100):
    if len(rows) < 10:
        raise ValueError('at least 10 full-validation tuples required')
    checked = [predict_check(rows,ard,seed,restarts,iterations) for ard in (False,True)]
    winner = min(checked,key=lambda r:r['rmse'])
    gp = make_gp(winner['ard'])
    gp.fit(core.np.asarray([r['margins'] for r in rows],float),
           core.np.asarray([r['target'] for r in rows],float),n_restarts=restarts,max_iter=iterations)
    observed = {tuple(r['margins']) for r in rows}
    remaining = sorted({tuple(core.validate_tuple(r,[[0,1200]]*5)) for r in pool} - observed)
    if not remaining:
        raise ValueError('no unvalidated coordinates in candidate pool')
    mean,std = gp.predict(core.np.asarray(remaining,float))
    selected = []
    for kappa in (0.0,0.2,0.5):
        index = int(core.np.argmin(mean-kappa*std))
        selected.append(dict(kappa=kappa,margins=list(remaining[index]),mean=float(mean[index]),
            std=float(std[index]),lcb=float(mean[index]-kappa*std[index])))
    return dict(schema='chilo.futility_validation_bo_offline.v1',seed=seed,positions=141099,
        target='pooled_selection_mean_normalized_regret',training_count=len(rows),
        rows=rows,candidate_pool=remaining,prediction_checks=checked,
        selected_model_ard=winner['ard'],beats_constant_baseline=winner['rmse_ratio'] is not None and winner['rmse_ratio'] < 1,
        proposals=selected,fit=gp.fit_diagnostics,
        qualification='Exploratory adaptive-data cross-validation only; not validation or Elo improvement')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loop-state',required=True)
    parser.add_argument('--validation-dir',required=True)
    parser.add_argument('--development',required=True)
    parser.add_argument('--completed',action='append',default=[])
    parser.add_argument('--observations-manifest',help='Verified newer BO manifest supplying frozen validated labels')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    path=Path(args.output)
    if path.exists(): raise ValueError('Use a fresh output path')
    source=core.read(Path(args.loop_state))
    if source['contract_sha256'] != core.digest(source['contract']):
        raise ValueError('invalid loop contract receipt')
    validation=Path(args.validation_dir)
    manifest=core.read(validation/'batch_manifest.json')
    completion=core.read(validation/'complete.json')
    for name,file in (('batch_manifest','batch_manifest.json'),('results','results.json')):
        if not core.campaign.same_identity(completion[name],core.tune.file_identity(validation/file)):
            raise ValueError('batch completion hashes differ')
    for name in ('probe','weights'):
        if not core.campaign.same_identity(manifest[name],source['contract'][name]):
            raise ValueError('batch artifact contract differs')
    for name in ('candidate_nodes','baseline_margins','score_scale'):
        if manifest[name] != source['contract'][name]: raise ValueError('batch scoring contract differs')
    contracted=source['contract']['selection']
    if [s['id'] for s in manifest['shards']] != [s['id'] for s in contracted]:
        raise ValueError('batch selection population contract differs')
    for actual,expected in zip(manifest['shards'],contracted):
        for name in ('input','reference','baseline','rescue'):
            if portable(actual[name]) != expected[name]:
                raise ValueError('batch selection population artifacts differ')
        if actual['trusted_position_count'] != expected['trusted_set']['trusted_position_count'] or \
           actual['trusted_position_keys_sha256'] != expected['trusted_set']['position_keys_sha256']:
            raise ValueError('batch trusted selection keys differ')
    unique={}
    archived=list(source['archive'].values())
    extra_sources=[]
    if args.observations_manifest:
        receipt_path=Path(args.observations_manifest)
        receipt=core.read(receipt_path)
        observations_path=receipt_path.parent/'observations.json'
        if receipt['contract_sha256'] != source['contract_sha256'] or receipt['contract'] != source['contract']:
            raise ValueError('frozen observations contract differs')
        if not core.campaign.same_identity(receipt['observations'],core.tune.file_identity(observations_path)):
            raise ValueError('frozen observations hash differs')
        archived.extend(core.read(observations_path)['validated'])
        extra_sources=[core.tune.file_identity(receipt_path),core.tune.file_identity(observations_path)]
    expected_shards={s['id'] for s in source['contract']['selection']}
    for row in archived:
        if len(row['shards']) != len(expected_shards) or {s['id'] for s in row['shards']} != expected_shards:
            raise ValueError('archived validation is not full selection')
    add_rows(unique,archived)
    batch=core.read(validation/'results.json')
    add_rows(unique,batch['candidates'])
    development=load_rows(Path(args.development),[Path(p) for p in args.completed])
    result=study(list(unique.values()),[r['margins'] for r in development])
    result['sources']=[core.tune.file_identity(Path(args.loop_state)),
        core.tune.file_identity(validation/'results.json'),core.tune.file_identity(validation/'batch_manifest.json'),
        core.tune.file_identity(Path(args.development)),*[core.tune.file_identity(Path(p)) for p in args.completed],*extra_sources]
    result['contract_sha256']=source['contract_sha256']
    result['environment']=dict(python=platform.python_version(),numpy=core.np.__version__)
    result['code']=core.code_identity(Path(__file__))
    core.write(path,result)
    print(json.dumps({k:result[k] for k in ('training_count','selected_model_ard','beats_constant_baseline','proposals')},indent=2))

if __name__=='__main__': main()
