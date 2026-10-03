#!/usr/bin/env python3
"""Create a small Linux BO bundle using an established external cloud store."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

import run_futility_bo as bo


def revision(root):
    if subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip():
        raise RuntimeError(f'Commit source changes before packaging: {root}')
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--tinibo-root',required=True)
    parser.add_argument('--source-state',required=True,help='Verified returned loop_state.json for the external contract receipt')
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parent.parent
    backend=Path(args.tinibo_root).expanduser().resolve()
    output=Path(args.output_dir).expanduser().resolve()
    archive=output.with_suffix('.tgz')
    if output.exists() or archive.exists():
        raise RuntimeError('Use a fresh package output path')
    revisions={'chilo':revision(repo),'tinibo':revision(backend)}
    # Require that the runtime import used for staging/tests is this exact backend.
    if Path(bo.tinibo.__file__).resolve().parent != backend/'tinibo':
        raise RuntimeError('PYTHONPATH must select the requested tinibo source')
    config=json.loads(Path(args.config).read_text())
    source=json.loads(Path(args.source_state).read_text())
    if bo.digest(source['contract'])!=source['contract_sha256']:
        raise RuntimeError('Source contract digest differs')
    config['expected_contract_sha256']=source['contract_sha256']
    (output/'scripts').mkdir(parents=True)
    (output/'vendor').mkdir()
    (output/'config').mkdir()
    (output/'verification').mkdir()
    for path in bo.script_closure(repo/'scripts/run_futility_bo.py'):
        shutil.copy2(path,output/'scripts'/path.name)
    shutil.copytree(backend/'tinibo',output/'vendor/tinibo',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for path in (repo/'scripts/futility_bo_package').iterdir():
        shutil.copy2(path,output/path.name)
        if path.suffix=='.sh':
            (output/path.name).chmod(0o755)
    shutil.copy2(backend/'benchmarks/futility_cloud/development.jsonl',output/'verification/development.jsonl')
    (output/'config/pilot.json').write_text(json.dumps(config,indent=2)+'\n')
    readme=f'''# Futility BO depth-5 pilot

Source revisions: Chilo {revisions['chilo']}; tinibo {revisions['tinibo']}.
Five sequential new-to-model development observations, one worker, 120k nodes.
80% local / 20% broad candidate pool. No automatic validation or SPRT.
Existing external store: {config['store_root']}; source loop: {config['source_loop']}.
Output: {config['store_root']}/evals/{config['run_id']}.

First wait for the old loop's graceful phase-boundary stop. Its cron may remain enabled.
The pilot holds the old process lock while running, without changing its state.
Setup needs Python 3.10–3.14, venv/pip and network access to install only NumPy.
NumPy is pinned to 2.2.6 for Python 3.10–3.13, or the qualified 2.5.3 for 3.14;
the real-data numerical/replay check must pass before engine work.

```bash
cd ~/{output.name}
bash setup.sh
nohup ./run.sh > runner.log 2>&1 < /dev/null & echo $! > run.pid
```

Restart with the same run.sh command; it resumes a pending tuple and exits when complete.
For cron, after successful setup add (do not replace your other entries):

```cron
*/10 * * * * /home/ubuntu/{output.name}/run.sh >> /home/ubuntu/{output.name}/cron.log 2>&1
```

Cron also exits harmlessly when another pilot process is running or all five steps are done.
Comment out the pilot entry after completion. Keep the old loop stopped until then.
To bound a test invocation, use ./run.sh --max-evaluations 1. This does not disable cron.
SIGTERM/foreground Ctrl-C terminates the probe process group and retains the pending tuple.

Inspect results.json, report.md and nominee.json in the output directory.
observations.json contains the frozen imported development/validation evidence;
state.json is the authoritative checkpoint, with proposal predictions and diagnostics.
Nomination requires an unvalidated pilot tuple with lower dev mean regret than spsa150b.
Cache hits count as an acquired observation, and their receipt distinguishes saved work.

Collect the full small pilot, including its five raw probes:

```bash
bash collect.sh
```

Copy bo-d5-pilot1-results.tgz back through PUBLIC/transf for local review. Do not send
the old loop, shared probe cache, all populations or the package-local .venv.
Neither the setup nor packaging starts an engine probe. Only run.sh does.
'''
    (output/'README.md').write_text(readme)
    files={str(p.relative_to(output)):bo.tune.file_identity(p) for p in sorted(output.rglob('*')) if p.is_file()}
    receipt={'schema':'chilo.futility_bo_package.v1','revisions':revisions,
             'external_contract':source['contract'],'external_contract_sha256':source['contract_sha256'],
             'command':'nohup ./run.sh > runner.log 2>&1 < /dev/null & echo $! > run.pid',
             'files':{name:{k:v for k,v in identity.items() if k!='path'} for name,identity in files.items()}}
    (output/'package_manifest.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    checksums=[]
    for p in sorted(output.rglob('*')):
        if p.is_file():
            checksums.append(f'{bo.tune.sha256_file(p)}  {p.relative_to(output)}')
    (output/'package-files.sha256').write_text('\n'.join(checksums)+'\n')
    with tarfile.open(archive,'w:gz') as t:
        t.add(output,arcname=output.name)
    with tarfile.open(archive) as t:
        for member in t.getmembers():
            if member.isfile():
                local=output.parent/member.name
                if hashlib.sha256(t.extractfile(member).read()).hexdigest()!=bo.tune.sha256_file(local):
                    raise RuntimeError('archive content differs from staged file')
    print(json.dumps({'archive':str(archive),'sha256':bo.tune.sha256_file(archive),
                      'size':archive.stat().st_size,'revisions':revisions},indent=2))


if __name__=='__main__':
    main()
