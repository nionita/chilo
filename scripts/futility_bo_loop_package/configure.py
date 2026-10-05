"""Prepare an existing stopped loop for BO; never reset state or start searches."""
import argparse
import copy
import json
from pathlib import Path

import run_futility_loop as loop

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-config', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    package = loop.read(root / 'package_manifest.json')
    path = root / 'config/loop.json'
    if args.check_only:
        config = loop.load_config(path)
    else:
        previous = loop.load_config(Path(args.previous_config).expanduser().resolve())
        state = loop.read(previous['root'] / 'loop_state.json')
        if not state['stopped'] or state['active'] is not None:
            raise loop.LoopError('Wait for the existing loop graceful stop before upgrading')
        if state['contract_sha256'] != package['external_contract_sha256']:
            raise loop.LoopError('Existing loop contract differs from the package')
        raw = copy.deepcopy(previous['raw'])
        # Use the live checkpoint policies, not the old package example defaults.
        raw.update(copy.deepcopy(state['options']))
        raw['search'] = loop.read(root / 'config/search.json')
        if path.exists() and loop.read(path) != raw:
            raise loop.LoopError('Prepared config already exists with different settings; inspect it')
        path.parent.mkdir(exist_ok=True)
        loop.write(path, raw)
        config = loop.load_config(path)
    env, contract = loop.environment(config)
    if loop.digest(contract) != package['external_contract_sha256']:
        raise loop.LoopError('External populations/artifacts differ')
    state = loop.initialize(config, contract)
    if not state['stopped'] or state['active'] is not None:
        raise loop.LoopError('Setup requires a stopped loop; use run.sh to continue an active phase')
    for identifier in config['options']['search']['bo']['import_bo_runs']:
        for name in ('manifest.json', 'state.json', 'observations.json'):
            if not (config['store'] / 'evals' / identifier / name).is_file():
                raise loop.LoopError(f'Missing completed BO pilot: {identifier}/{name}')
    print(json.dumps(dict(loop_id=config['raw']['loop_id'], cycle=state['cycle'],
        base=state['candidates'][state['base_id']], archive_size=len(state['archive']),
        search=config['options']['search'], dev_selector=config['options']['dev_selector'],
        validation_selector=config['options']['validation_selector']), indent=2))

if __name__ == '__main__':
    main()
