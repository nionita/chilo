#!/usr/bin/env python3
"""Additively collect portable match evidence, or prepare a fresh BO experiment."""
import argparse
from contextlib import nullcontext
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import tempfile

import run_selfplay_bo as bo

SCHEMA = "chilo.selfplay_bo_evidence.v1"
FILES = ("manifest.json", "games.jsonl", "results.json", "status.json")


def config_from(path, **overrides):
    """Resolve template paths before applying this machine's artifact overrides."""
    path = Path(path).resolve()
    raw = bo.read_json(path)
    raw.setdefault("tinibo_path", "../../tinibo")
    for key in ("executable", "weights", "openings", "tinibo_path"):
        if key in raw:
            raw[key] = bo.resolve(raw[key], path.parent)
    raw["bootstrap"] = [bo.resolve(p, path.parent) for p in raw.get("bootstrap", [])]
    if "bootstrap_summary" in raw:
        raw["bootstrap_summary"] = {**raw["bootstrap_summary"],
                                    "path": bo.resolve(raw["bootstrap_summary"]["path"], path.parent)}
    for key, value in overrides.items():
        if value is not None:
            raw[key] = str(Path(value).resolve())
    return validate_config(raw)


def validate_config(raw):
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.json"
        bo.atomic_json(path, raw)
        return bo.load_config(path)


def observation_data(observation):
    return {k: v for k, v in observation.items() if k != "path"}


def read_store(root, config, contract):
    index = bo.read_json(root / "index.json")
    bo.require(index.get("schema") == SCHEMA and index["contract"] == contract,
               "incompatible evidence store schema/contract")
    bo.require(isinstance(index["measurements"], dict), "invalid evidence index")
    seeds = set()
    for mid, item in index["measurements"].items():
        bo.require(re.fullmatch(r"[0-9a-f]{64}", mid) is not None and
                   item["path"] == f"measurements/{mid}", "invalid evidence path/id")
        folder = root / item["path"]
        bo.require(not folder.is_symlink() and folder.resolve().is_relative_to(root.resolve()),
                   "evidence path escapes store or uses a symlink")
        for name in FILES:
            bo.require(not (folder / name).is_symlink() and
                       bo.identity(folder / name) == item["files"][name], "stored evidence changed")
        observed = bo.import_match(folder, config, contract)
        bo.require(observed["id"] == mid and observation_data(observed) == item["observation"],
                   "stored observation changed")
        bo.require(observed["seed"] not in seeds, "stored measurements share an opening seed")
        bo.require(isinstance(item["sources"], list) and all(isinstance(s, str) for s in item["sources"]),
                   "invalid evidence provenance")
        seeds.add(observed["seed"])
    return index


def mapped_path(path, mappings):
    path = Path(path)
    for old, new in sorted(mappings, key=lambda pair: len(pair[0].parts), reverse=True):
        if path.is_relative_to(old):
            return new / path.relative_to(old)
    return path


def source_observations(source, config, contract, mappings):
    """Snapshot committed BO observations; never import a pending measurement."""
    source = Path(source).resolve()
    if (source / "index.json").is_file():
        index = read_store(source, config, contract)
        for item in index["measurements"].values():
            yield bo.import_match(source / item["path"], config, contract)
    elif (source / "state.json").is_file():
        state, manifest = bo.read_json(source / "state.json"), bo.read_json(source / "manifest.json")
        bo.require(state["schema"] == bo.SCHEMA and state["fingerprint"] == bo.digest(manifest),
                   "source state/manifest mismatch")
        imports = [{k: o[k] for k in ("id", "manifest_sha256", "journal")}
                   for o in state["observations"][:len(manifest["imports"])]]
        bo.require(imports == manifest["imports"] and
                   state["completed"] == len(state["observations"]) - len(imports),
                   "source import/count mismatch")
        compact = {}
        if "bootstrap_summary" in manifest["config"]:
            spec = dict(manifest["config"]["bootstrap_summary"])
            spec["path"] = str(mapped_path(spec["path"], mappings))
            compact = {o["id"]: o for o in bo.summary_observations(spec, config, contract)}
        for old in state["observations"]:
            if old["id"] in compact:
                bo.require(observation_data(old) == observation_data(compact[old["id"]]),
                           "compact source observation changed")
                continue  # Already archived on exporter; collect new full match evidence only.
            path = mapped_path(old["path"], mappings)
            bo.require(path.is_dir(), f"missing source match {path}; use --path-map OLD=NEW or collect on its source machine")
            observed = bo.import_match(path, config, contract)
            bo.require(observation_data(observed) == observation_data(old), "source measured evidence changed")
            yield observed
    else:
        yield bo.import_match(source, config, contract)


def collect(config, store, sources=None, mappings=()):
    store = Path(store).resolve()
    sources = list(sources if sources is not None else config["bootstrap"])
    # Materialize and validate all source observations before changing the store.
    contract = bo.match_contract(config)
    incoming = [(str(Path(s).resolve()), o) for s in sources
                for o in source_observations(s, config, contract, mappings)]
    store.mkdir(parents=True, exist_ok=True)
    with bo.run_lock(store / "store.lock"):
        index = (read_store(store, config, contract) if (store / "index.json").exists() else
                 {"schema": SCHEMA, "contract": contract, "measurements": {}})
        entries = index["measurements"]
        seeds = {item["observation"]["seed"]: mid for mid, item in entries.items()}
        # Check conflicts for the entire batch before copying any files.
        planned = dict(entries)
        for source, observed in incoming:
            mid, seed = observed["id"], observed["seed"]
            if mid in planned:
                bo.require(planned[mid]["observation"] == observation_data(observed),
                           "conflicting duplicate measurement")
            bo.require(seed not in seeds or seeds[seed] == mid,
                       "different measurements share an opening seed; independence not established")
            seeds[seed] = mid
            planned[mid] = {"observation": observation_data(observed)}
        added, existing = 0, 0
        for source, observed in incoming:
            mid = observed["id"]
            if mid in entries:
                existing += 1
                entries[mid]["sources"] = sorted(set(entries[mid]["sources"]) | {source})
                continue
            destination = store / "measurements" / mid
            destination.parent.mkdir(exist_ok=True)
            if destination.exists():
                # Recover a fully copied orphan from an interrupted index commit.
                bo.require(not destination.is_symlink() and all(not (destination / n).is_symlink() for n in FILES),
                           "orphan evidence must not use symlinks")
                copied = bo.import_match(destination, config, contract)
                bo.require(observation_data(copied) == observation_data(observed),
                           "conflicting orphan evidence directory")
            else:
                with tempfile.TemporaryDirectory(prefix=".incoming-", dir=store) as temp:
                    stage = Path(temp) / "match"
                    stage.mkdir()
                    for name in FILES:
                        shutil.copyfile(Path(observed["path"]) / name, stage / name)
                        with (stage / name).open("rb") as stream:
                            os.fsync(stream.fileno())
                    copied = bo.import_match(stage, config, contract)
                    bo.require(observation_data(copied) == observation_data(observed),
                               "source changed while copying evidence")
                    fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    os.rename(stage, destination)
                    fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
            entries[mid] = {"path": f"measurements/{mid}", "observation": observation_data(observed),
                            "files": {name: bo.identity(destination / name) for name in FILES},
                            "sources": [source]}
            added += 1
        bo.atomic_json(store / "index.json", index)
        return {"added": added, "existing": existing, "total": len(entries), "store": str(store)}


def export_summary(config, store, output):
    """Verify full evidence once, then export portable BO-only observations."""
    output, store = Path(output).resolve(), Path(store).resolve()
    bo.require(not output.exists(), f"refusing to overwrite {output}")
    contract = bo.match_contract(config)
    with bo.run_lock(store / "store.lock"):
        index = read_store(store, config, contract)
        observations = [dict(item["observation"]) for item in index["measurements"].values()]
        for o in observations:
            o["path"] = "verified-summary:" + o["id"]
            o["result"] = {k: o["result"][k] for k in
                           ("status", "pairs", "pentanomial", "elo", "elo_error95")}
        bo.atomic_json(output, {"schema": "chilo.selfplay_bo_bootstrap.v1", "contract": contract,
                               "source_index": bo.identity(store / "index.json"),
                               "observations": observations})
    return {"path": str(output), "sha256": bo.identity(output)["sha256"]}


def prepare(config, store, output_config, run_dir=None, seed=None, measurements=None,
            max_pairs=None, gp_ard=None, gp_length_scale_bounds=None, bootstrap_summary=None):
    store, output_config = Path(store).resolve(), Path(output_config).resolve()
    run_dir = (Path(run_dir).resolve() if run_dir is not None else
               output_config.parent.parent / "runs" / output_config.stem)
    bo.require(not run_dir.exists() or not any(run_dir.iterdir()), "new run directory is not empty")
    bo.require(not output_config.exists(), f"refusing to overwrite {output_config}")
    receipt_path = output_config.with_name(output_config.name + ".preparation.json")
    bo.require(not receipt_path.exists(), f"refusing to overwrite {receipt_path}")
    contract = bo.match_contract(config)
    with bo.run_lock(store / "store.lock") if bootstrap_summary is None else nullcontext():
        if bootstrap_summary is None:
            index = read_store(store, config, contract)
        else:
            spec = {"path": str(Path(bootstrap_summary).resolve()),
                    "sha256": bo.identity(bootstrap_summary)["sha256"]}
            observations = bo.summary_observations(spec, config, contract)
            index = {"measurements": {o["id"]: o for o in observations}}
        config = dict(config)
        config["model"] = dict(config["model"])
        config["seed"] = secrets.randbits(64) if seed is None else seed
        for key, value in (("measurements", measurements), ("max_pairs", max_pairs)):
            if value is not None:
                config[key] = value
        if gp_ard is not None:
            config["model"]["gp_ard"] = gp_ard
        if gp_length_scale_bounds is not None:
            config["model"]["gp_length_scale_bounds"] = list(gp_length_scale_bounds)
        if bootstrap_summary is None:
            config.pop("bootstrap_summary", None)
            config["bootstrap"] = [str(store / item["path"]) for item in index["measurements"].values()]
        else:
            config["bootstrap"] = []
            config["bootstrap_summary"] = spec
        config = validate_config(config)
        bo.optimizer(config)  # New model validation, not old checkpoint restoration.
        receipt = {"schema": "chilo.selfplay_bo_preparation.v1", "contract": contract,
                   "store": str(store), "index": bo.identity(store / "index.json") if bootstrap_summary is None else spec,
                   "measurement_ids": list(index["measurements"]), "seed": config["seed"],
                   "run_dir": str(run_dir), "config_sha256": bo.digest(config),
                   "driver": bo.identity(Path(bo.__file__))}
        # Bootstrap paths are relative so copying the store plus config remains portable.
        written = dict(config)
        written["bootstrap"] = [os.path.relpath(p, output_config.parent) for p in config["bootstrap"]]
        bo.atomic_json(receipt_path, receipt)
        bo.atomic_json(output_config, written)
    return receipt


def path_mapping(value):
    old, separator, new = value.partition("=")
    if not separator or not old or not new:
        raise argparse.ArgumentTypeError("expected OLD=NEW")
    return Path(old).absolute(), Path(new).resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("collect", "prepare", "export-bootstrap"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, required=True, help="template with this machine's frozen match artifacts")
        command.add_argument("--store", type=Path, help="default: config parent-parent/evidence")
        for artifact in ("executable", "weights", "openings", "tinibo-path"):
            command.add_argument("--" + artifact, type=Path, help="override template path on this machine")
        if name == "collect":
            command.add_argument("--source", type=Path, nargs="+", action="extend",
                                 help="match, BO run or evidence store; repeatable; default: template bootstrap")
            command.add_argument("--path-map", type=path_mapping, action="append", default=[],
                                 help="relocate paths in copied BO states: OLD=NEW (repeatable)")
        elif name == "export-bootstrap":
            command.add_argument("--output-summary", type=Path, required=True)
        else:
            command.add_argument("--bootstrap-summary", type=Path,
                                 help="trusted compact export; no source journals required")
            command.add_argument("--output-config", type=Path, required=True)
            command.add_argument("--run-dir", type=Path, help="default: output parent-parent/runs/output stem")
            command.add_argument("--seed", type=int, help="default: fresh random 64-bit seed")
            command.add_argument("--measurements", type=int, help="new budget; default: template budget")
            command.add_argument("--max-pairs", type=int, help="default: template cap; earlier caps may differ")
            command.add_argument("--gp-ard", action=argparse.BooleanOptionalAction, default=None)
            command.add_argument("--gp-length-scale-bounds", type=float, nargs=2, metavar=("LOW", "HIGH"))
    args = parser.parse_args()
    try:
        config = config_from(args.config, **{k: getattr(args, k) for k in
                                            ("executable", "weights", "openings", "tinibo_path")})
        store = args.store or args.config.resolve().parent.parent / "evidence"
        if args.command == "collect":
            result = collect(config, store, args.source, args.path_map)
            print(f"evidence collected: added={result['added']} existing={result['existing']} "
                  f"total={result['total']} store={result['store']}")
        elif args.command == "export-bootstrap":
            result = export_summary(config, store, args.output_summary)
            print(bo.canonical(result))
        else:
            result = prepare(config, store, args.output_config, args.run_dir, args.seed,
                             args.measurements, args.max_pairs, args.gp_ard, args.gp_length_scale_bounds,
                             args.bootstrap_summary)
            print(f"experiment prepared: imported={len(result['measurement_ids'])} seed={result['seed']} "
                  f"config={args.output_config.resolve()} run={result['run_dir']}; no match started")
        return 0
    except (bo.BOError, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
