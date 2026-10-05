#!/usr/bin/env python3
"""Package a stopped-boundary BO upgrade of an existing cloud futility loop."""
import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

import futility_bo_core as core
from package_futility_bo_pilot import revision

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tinibo-root', required=True)
    parser.add_argument('--source-state', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    tinibo = Path(args.tinibo_root).resolve()
    target = Path(args.output_dir).resolve()
    archive = target.with_suffix('.tgz')
    if target.exists() or archive.exists():
        raise RuntimeError('Use a fresh package output directory')
    if Path(core.tinibo.__file__).resolve().parent != tinibo / 'tinibo':
        raise RuntimeError('PYTHONPATH must select the requested tinibo runtime')
    revisions = dict(chilo=revision(repo), tinibo=revision(tinibo))
    source = core.read(Path(args.source_state))
    if core.digest(source['contract']) != source['contract_sha256']:
        raise RuntimeError('Source contract receipt differs')
    for directory in ('scripts','vendor','config','verification'):
        (target / directory).mkdir(parents=True, exist_ok=True)
    closure = {p.name:p for entry in ('run_futility_loop.py','run_futility_bo.py')
               for p in core.script_closure(repo / 'scripts' / entry)}
    for path in closure.values():
        shutil.copy2(path, target / 'scripts' / path.name)
    shutil.copytree(tinibo / 'tinibo', target / 'vendor/tinibo', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('configure.py','setup.sh','loop.sh','run.sh'):
        path = repo / 'scripts/futility_bo_loop_package' / name
        shutil.copy2(path, target / path.name)
        if path.suffix == '.sh': (target / path.name).chmod(0o755)
    shutil.copy2(repo / 'scripts/futility_bo_package/verify-numerics.py', target / 'verify-numerics.py')
    shutil.copy2(tinibo / 'benchmarks/futility_cloud/development.jsonl', target / 'verification/development.jsonl')
    search = dict(backend='bo', max_proposals=15, workers=1, seed=20261006, max_margin=1200,
        bo=dict(import_bo_runs=['bo-d5-pilot1','bo-d5-pilot2','bo-d5-pilot3-lcb05','bo-d5-pilot4-ard-lcb05'],
            pool_size=10000, local_fraction=1.0, local_radius=80, local_centers=10,
            bounds=[[0,1200]]*5, model=dict(kernel='matern52',gp_ard=True,acquisition='ucb',kappa=0.5)))
    core.write(target / 'config/search.json', search)
    readme = f'''# BO continuous-loop upgrade

Sources: Chilo {revisions['chilo']}; tinibo {revisions['tinibo']}.
Retain futility-loop-v1 and its live initialization, selectors, queue and control.
Setup changes only search settings, imports the completed pilot4 validation,
and leaves the loop stopped. BO uses compatible SR4 mean-regret labels only;
all four completed pilots and the loop's completed cycles seed the model.
One engine worker, one BLAS thread, 15 new observations per dev phase.
Validation is unchanged and serial across eight shards (141,099 positions).
No SPRT is launched. spsa150b remains the manually proven base.

1. Request graceful stop with the OLD package's command and wait for stopped=true,
   active=null. Disable/comment its cron entry. Do not kill an active phase.
2. Unpack this package and run `bash setup.sh` as ubuntu, never sudo.
   Optional argument: path to the live old loop config. Setup installs only NumPy
   in its local venv and qualifies prediction/checkpoint replay before changes.
   If venv support is missing, install python3-venv separately, then retry as ubuntu.
3. Inspect `config/loop.json`: selectors came from the actual stopped checkpoint.
4. Start: `nohup ./loop.sh resume > loop.log 2>&1 < /dev/null & echo $! > run.pid`.
5. Add/uncomment only this cron entry (not the old one):
   `*/10 * * * * /home/ubuntu/{target.name}/run.sh >> /home/ubuntu/{target.name}/cron.log 2>&1`

Progress: tail loop.log; use `./loop.sh status`. Output remains in
~/futility-validation/evals/futility-loop-v1/. BO per-cycle evidence is under
cycles/NNNNNN/search/. First model import should include at least 284 distinct
compatible SR4 tuples; later completed cycles may add more. Previously validated
pilot4-bo0001 must already be in loop_state.json.archive and must not be pending.

After 2–3 days request `./loop.sh stop`, wait for the phase boundary, and comment
cron if desired. There is no automatic wall-clock termination: long validation
phases finish in full. A process interruption resumes through cron/run.sh; a
graceful stop remains sticky until explicit `loop.sh resume`.
Do not run setup.sh again during an active phase; retain this package/runtime.

Before the first local SPRT, bo0001 can be marked running with:
`./loop.sh sprt --candidate ID --status running --note "pilot4-bo0001 local SPRT"`.
Find ID by its margins [20,23,315,512,810] in loop_state.json.candidates.
Manual SPRT statuses are applied at phase boundaries. Only set-base changes
the proven base; recording accepted does not do that automatically.
'''
    (target / 'README.md').write_text(readme)
    identities = {str(p.relative_to(target)): {k:v for k,v in core.tune.file_identity(p).items() if k != 'path'}
                  for p in sorted(target.rglob('*')) if p.is_file()}
    core.write(target / 'package_manifest.json', dict(schema='chilo.futility_bo_loop_package.v1',
        revisions=revisions, external_contract=source['contract'],
        external_contract_sha256=source['contract_sha256'], files=identities))
    (target / 'package-files.sha256').write_text(''.join(
        f'{core.tune.sha256_file(p)}  {p.relative_to(target)}\n' for p in sorted(target.rglob('*')) if p.is_file()))
    with tarfile.open(archive,'w:gz') as handle: handle.add(target, arcname=target.name)
    with tarfile.open(archive) as handle:
        for member in handle.getmembers():
            if member.isfile():
                assert hashlib.sha256(handle.extractfile(member).read()).hexdigest() == core.tune.sha256_file(target.parent/member.name)
    print(json.dumps(dict(archive=str(archive),sha256=core.tune.sha256_file(archive),size=archive.stat().st_size),indent=2))

if __name__ == '__main__': main()
