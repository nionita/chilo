#!/usr/bin/env python3
"""Install a receipt-bound controller upgrade into an idle BO loop package."""
import fcntl
import hashlib
import json
import shutil
import sys
from pathlib import Path

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def require(condition, message):
    if not condition: raise RuntimeError(message)
def write_json(path,value):
    temp=path.with_name(path.name+'.repair-tmp')
    temp.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    temp.replace(path)

def main():
    package=Path(sys.argv[1]).expanduser().resolve()
    payload=Path(__file__).resolve().parent/'run_futility_loop.py'
    receipt=json.loads((payload.parent/'upgrade.json').read_text())
    require(sha(payload)==receipt['payload_sha256'], 'Upgrade payload hash differs')
    config=json.loads((package/'config/loop.json').read_text())
    store=Path(config['store_root']).expanduser()
    if not store.is_absolute(): store=(package/'config'/store).resolve()
    root=store/'evals'/config['loop_id']
    with (root/'loop.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=json.loads((root/'loop_state.json').read_text())
        require(state['stopped'] and state['active'] is None, 'Wait for a graceful stop')
        manifest_path=package/'package_manifest.json'
        manifest=json.loads(manifest_path.read_text())
        require(manifest['schema']=='chilo.futility_bo_loop_package.v1', 'Unexpected package')
        require(manifest['external_contract_sha256']==state['contract_sha256'], 'Contract differs')
        target=package/'scripts/run_futility_loop.py'
        require(sha(target) in [*receipt['supported_script_sha256'],receipt['payload_sha256']], 'Unknown script revision; refusing overwrite')
        for line in (package/'package-files.sha256').read_text().splitlines():
            expected,name=line.split('  ',1)
            require(sha(package/name)==expected, 'Existing package integrity differs: '+name)
        backup=package/'repair-backup'
        backup.mkdir(exist_ok=True)
        for file in (target,manifest_path,package/'package-files.sha256'):
            destination=backup/(file.name+'.'+sha(file))
            if not destination.exists(): shutil.copy2(file,destination)
        temporary=target.with_name(target.name+'.repair-tmp')
        shutil.copy2(payload,temporary)
        temporary.replace(target)
        manifest['files']['scripts/run_futility_loop.py']={'sha256':sha(target),'size':target.stat().st_size}
        manifest['upgrade']=receipt
        write_json(manifest_path,manifest)
        checksum_path=package/'package-files.sha256'
        lines=[]
        for line in checksum_path.read_text().splitlines():
            _,name=line.split('  ',1)
            lines.append(sha(package/name)+'  '+name+'\n')
        temporary=checksum_path.with_name(checksum_path.name+'.repair-tmp')
        temporary.write_text(''.join(lines))
        temporary.replace(checksum_path)
    print('Installed loop upgrade. State and venv unchanged; loop remains stopped.')

if __name__=='__main__': main()
