#!/usr/bin/env python3
"""Offline matched LCB comparison: reveal labels only after pool selection.

This is a measured-pool benchmark, not a prediction for unseen engine tuples.
Accepts development.jsonl from the tinibo fixture, or observations.json, plus
optional completed BO state.json files. Never reads validation or Elo labels.
"""
from __future__ import annotations
import argparse
import json
import math
import platform
from pathlib import Path
import futility_bo_core as core


def load_rows(path, completed=()):
    text = path.read_text()
    if path.suffix == '.jsonl':
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        value = json.loads(text)
        records = value['development'] if isinstance(value, dict) else value
    for extra in completed:
        value = core.read(extra)
        if value.get('status') != 'complete' or value.get('pending') is not None:
            raise core.BOError('offline additions must be complete BO states')
        records.extend(value['completed'])
    unique = {}
    for record in records:
        margins = tuple(core.tune.validate_margins(record['margins'], 'offline tuple'))
        metrics = record['metrics'] if 'metrics' in record else record['diagnostics']
        target = metrics['mean_normalized_regret']
        if isinstance(target, bool) or not isinstance(target, (int, float)) or not math.isfinite(target):
            raise core.BOError('invalid offline development target')
        if 'target' in record and record['target'] != target:
            raise core.BOError('offline target differs from development metrics')
        if margins in unique and unique[margins]['target'] != target:
            raise core.BOError('conflicting offline tuple labels')
        unique.setdefault(margins, dict(margins=list(margins), target=target))
    if not unique or len({len(t) for t in unique}) != 1:
        raise core.BOError('offline tuples must have one fixed dimension')
    return list(unique.values())


def compare(rows, seeds=(0, 1, 2, 3, 4), warm_sizes=(40, 120), steps=15,
            kappas=(0.0, 0.2, 0.5), model=None):
    if not kappas or len(set(kappas)) != len(kappas) or any(not math.isfinite(k) or k < 0 for k in kappas):
        raise core.BOError('kappas must be distinct finite nonnegative values')
    if steps < 1 or any(n < 1 or n + steps > len(rows) for n in warm_sizes):
        raise core.BOError('warm size plus steps exceeds measured pool')
    bounds = [[0, 1200]] * len(rows[0]['margins'])
    for row in rows:
        core.validate_tuple(row['margins'], bounds)
    optimum = min(r['target'] for r in rows)
    results = []
    prefixes = sorted({min(5, steps), min(10, steps), steps})
    for seed in seeds:
        order = core.np.random.default_rng(seed).permutation(len(rows)).tolist()
        for warm in warm_sizes:
            for kappa in kappas:
                optimizer = core.BayesianOptimizer(objective=None, bounds=bounds, seed=seed,
                    **{**core.PRESET, 'gp_ard': True, 'acquisition': 'ucb',
                       **(model or {}), 'kappa': kappa})
                measured, remaining = order[:warm], order[warm:]
                for index in measured:
                    optimizer.tell(rows[index]['margins'], rows[index]['target'])
                best = min(rows[i]['target'] for i in measured)
                initial_best, reveals, scores = best, [], {}
                for step in range(1, steps + 1):
                    # Only coordinates reach the surrogate; no remaining labels.
                    pool = [rows[i]['margins'] for i in remaining]
                    info = optimizer.ask(candidates=pool, return_info=True)
                    index = next(i for i in remaining if rows[i]['margins'] == list(info.x))
                    remaining.remove(index)
                    value = rows[index]['target']
                    optimizer.tell(rows[index]['margins'], value)
                    best = min(best, value)
                    reveals.append(dict(index=index, margins=rows[index]['margins'], target=value))
                    if step in prefixes:
                        scores[str(step)] = dict(best=best, regret=best-optimum)
                results.append(dict(seed=seed, warm=warm, kappa=kappa,
                    optimum_in_warm=initial_best == optimum, prefixes=scores, reveals=reveals))
    paired = []
    control = 0.5 if 0.5 in kappas else kappas[-1]
    for warm in warm_sizes:
        for prefix in prefixes:
            for kappa in kappas:
                for optimal in (False, True):
                    comparisons = []
                    for seed in seeds:
                        a = next(r for r in results if (r['seed'], r['warm'], r['kappa']) == (seed, warm, kappa))
                        b = next(r for r in results if (r['seed'], r['warm'], r['kappa']) == (seed, warm, control))
                        if a['optimum_in_warm'] == optimal:
                            comparisons.append(a['prefixes'][str(prefix)]['best'] - b['prefixes'][str(prefix)]['best'])
                    paired.append(dict(warm=warm, prefix=prefix, kappa=kappa, control=control,
                        optimum_in_warm=optimal, pairs=len(comparisons), wins=sum(v < 0 for v in comparisons),
                        ties=sum(v == 0 for v in comparisons), losses=sum(v > 0 for v in comparisons)))
    return dict(schema='chilo.futility_bo_lcb_comparison.v1', positions=len(rows),
                configuration=dict(seeds=list(seeds), warm_sizes=list(warm_sizes),
                    steps=steps, kappas=list(kappas), bounds=bounds,
                    model={**core.PRESET, 'gp_ard':True, 'acquisition':'ucb', **(model or {})}),
                environment=dict(python=platform.python_version(), numpy=core.np.__version__),
                optimum=optimum, results=results, paired=paired,
                limitation='measured development pool only; no novel, validation or SPRT claim')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observations', required=True, type=Path)
    parser.add_argument('--completed', action='append', type=Path, default=[])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--steps', type=int, default=15)
    parser.add_argument('--seeds', type=int, nargs='+', default=list(range(5)))
    parser.add_argument('--warm-sizes', type=int, nargs='+', default=[40, 120])
    parser.add_argument('--kappas', type=float, nargs='+', default=[0, 0.2, 0.5])
    args = parser.parse_args(argv)
    if args.output.exists():
        raise core.BOError('refusing to overwrite comparison evidence')
    rows = load_rows(args.observations, args.completed)
    result = compare(rows, args.seeds, args.warm_sizes, args.steps, args.kappas)
    result['sources'] = [core.tune.file_identity(p) for p in [args.observations, *args.completed]]
    result['code'] = core.code_identity(Path(__file__))
    core.write(args.output, result)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (core.BOError, OSError, ValueError) as exc:
        raise SystemExit(f'fatal: {exc}')
