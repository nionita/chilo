#!/usr/bin/env python3
"""Continuous, phase-checkpointed futility development and selection loop (Linux).

The process lock covers initialization, phases, and atomic state transitions.
Control commands use a separate short lock so stop/base/SPRT updates remain
available while a multi-hour phase is running. No command launches an SPRT.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import fcntl
import hashlib
import json
import sys
from pathlib import Path

import backfill_futility_probe_cache as backfill
import futility_probe_cache as cache
import optimize_futility_gated as pareto
import run_futility_campaign as campaign
import run_futility_validation_batch as batch
import tune_futility as tune

SCHEMA = "chilo.futility_loop.v1"
METRIC_VERSION = "reference_regret_risk_v1"
FILTERS = [{"metric": "winning_mate_missed", "discard_worst_fraction": 0.25},
           {"metric": "nonlosing_to_losing", "discard_worst_fraction": 0.25}]
SEARCH_DEFAULTS = dict(max_proposals=15, workers=1, seed=20260919,
                       perturbation_c=40, perturbation_gamma=0.101, max_margin=1200)
CONTRACT_FIELDS = {"store_root", "artifacts", "candidate_nodes", "baseline_margins",
                   "score_scale", "development", "selection"}


class LoopError(RuntimeError):
    pass


write = campaign.atomic_json


def read(path):
    return campaign.read_json(path, str(path))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def portable(value):
    if isinstance(value, dict):
        if "sha256" in value and "size" in value:
            return {key: value[key] for key in ("sha256", "size")}
        return {key: portable(item) for key, item in value.items() if key not in {"path", "directory"}}
    if isinstance(value, list):
        return [portable(item) for item in value]
    return value


def selector(raw):
    if not isinstance(raw, dict) or set(raw) - {"objectives", "semantic_filters"}:
        raise LoopError("selector accepts only objectives and semantic_filters")
    objectives = pareto.parse_objectives(raw.get("objectives", list(pareto.OBJECTIVES)))
    filters = raw.get("semantic_filters", FILTERS)
    if filters:
        pareto.parse_semantic_filters(filters)
    elif filters != []:
        raise LoopError("semantic_filters must be a list")
    return {"objectives": list(objectives), "semantic_filters": filters}


def candidate(raw):
    if not isinstance(raw, dict) or set(raw) - {"margins", "alias", "provenance"}:
        raise LoopError("candidate accepts margins, alias, provenance")
    margins = list(tune.validate_margins(raw.get("margins"), "candidate margins"))
    return {"margins": margins, "alias": str(raw.get("alias", tune.candidate_key(margins))),
            "provenance": str(raw.get("provenance", "operator"))}


def load_config(path):
    raw = read(path)
    allowed = CONTRACT_FIELDS | {"schema", "loop_id", "report_every", "search", "dev_selector",
                                  "validation_selector", "initialization"}
    if raw.get("schema") != SCHEMA or set(raw) - allowed:
        raise LoopError("invalid loop schema or unknown configuration fields")
    identifier = campaign.require_identifier(raw.get("loop_id"), "loop_id")
    store = campaign.resolve(path, raw.get("store_root"), "store_root")
    if not isinstance(raw.get("search", {}), dict):
        raise LoopError("search must be an object")
    search = {**SEARCH_DEFAULTS, **raw.get("search", {})}
    if set(search) != set(SEARCH_DEFAULTS):
        raise LoopError("unknown search parameter")
    for key in ("max_proposals", "workers", "seed", "max_margin"):
        campaign.require_int(search[key], key, 0 if key in {"seed", "max_margin"} else 1)
    for key in ("perturbation_c", "perturbation_gamma"):
        pareto.require_number(search[key], key, 0)
    init = raw.get("initialization")
    if not isinstance(init, dict) or set(init) - {"base", "validation_pool", "imports"}:
        raise LoopError("initialization requires base, with optional validation_pool and imports")
    base = candidate(init.get("base"))
    if max(base["margins"]) > search["max_margin"]:
        raise LoopError("base exceeds max_margin")
    pool = init.get("validation_pool", [])
    imports = init.get("imports", [])
    if not isinstance(pool, list) or not isinstance(imports, list) or any(not isinstance(p, str) for p in imports):
        raise LoopError("validation_pool and imports must be lists")
    options = {"search": search, "dev_selector": selector(raw.get("dev_selector", {})),
               "validation_selector": selector(raw.get("validation_selector", {})),
               "report_every": campaign.require_int(raw.get("report_every", 1000), "report_every", 0)}
    return {"path": path, "raw": raw, "root": store / "evals" / identifier, "store": store,
            "options": options, "initialization": {"base": base, "validation_pool": [candidate(p) for p in pool],
              "imports": [str(campaign.resolve(path, p, "import")) for p in imports]}}


def environment(config):
    document = {key: config["raw"][key] for key in CONTRACT_FIELDS if key in config["raw"]}
    document.update(schema=campaign.SCHEMA, run_id=config["raw"]["loop_id"],
                    report_every=config["options"]["report_every"])
    env = campaign.load_campaign(config["path"], document)
    identity = {"metric_version": METRIC_VERSION, "probe": tune.file_identity(env["probe"]),
                "weights": tune.file_identity(env["weights"]), "candidate_nodes": env["candidate_nodes"],
                "baseline_margins": list(env["baseline_margins"]), "score_scale": env["score_scale"],
                "development": campaign.context_identity(env["development"]),
                "selection": [campaign.context_identity(s) for s in env["selection"]]}
    # Validate shard disjointness before spending any probe work.
    keys = batch.merged_keys(env["selection"])
    development_fens = {key[2] for key in env["development"]["context"].trusted_keys}
    if development_fens.intersection(key[2] for key in keys):
        raise LoopError("development and selection trusted FENs overlap")
    return env, portable(identity)


@contextlib.contextmanager
def locked(path, blocking=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def edit_control(root, update):
    with locked(root / "control.lock", blocking=True):
        path = root / "control.json"
        if not path.is_file():
            raise LoopError("loop is not initialized")
        value = read(path)
        update(value)
        write(path, value)


def tuple_id(state, margins):
    return "t-" + digest({"contract": state["contract_sha256"], "margins": list(margins)})[:24]


def register(state, item):
    key = tuple_id(state, item["margins"])
    record = state["candidates"].setdefault(key, {"id": key, "margins": item["margins"], "aliases": [], "provenance": []})
    for source, target in (("alias", "aliases"), ("provenance", "provenance")):
        if item[source] not in record[target]:
            record[target].append(item[source])
    return key


def enqueue(state, key):
    if key not in state["archive"] and key not in state["pending"]:
        state["pending"].append(key)


def set_status(state, key, status, reason):
    record = state["sprt_queue"].setdefault(key, {"status": None, "history": []})
    if record["status"] != status:
        record["status"] = status
        record["history"].append({"status": status, "reason": reason, "phase": state["phase_number"], "revision": state["revision"]})


def select(records, policy):
    frontier = []
    for record in sorted(records, key=lambda r: r["id"]):
        frontier, _ = pareto.archive_update(frontier, record, policy["objectives"])
    filters = tuple(pareto.SemanticFilter(**f) for f in policy["semantic_filters"])
    survivors, filtering = pareto.decimate_semantic_frontier(frontier, filters)
    return frontier, survivors, filtering


def rebuild(state):
    frontier, survivors, filtering = select(list(state["archive"].values()), state["options"]["validation_selector"])
    state["selection"] = {"frontier": [r["id"] for r in frontier], "survivors": [r["id"] for r in survivors], "filtering": filtering}
    # A proven control needs full matching coverage before publishing challenges.
    qualified = {r["id"] for r in survivors} if state["base_id"] in state["archive"] else set()
    for key in set(state["sprt_queue"]) | qualified:
        status = state["sprt_queue"].get(key, {}).get("status")
        if status in {"running", "accepted", "rejected"}:
            continue
        if key in qualified and key not in state["proven_bases"]:
            set_status(state, key, "pending", "selection qualified")
        elif status == "pending":
            set_status(state, key, "superseded", "no longer selection qualified")


def apply_test_updates(state, control):
    for key, command in control["sprt"].items():
        if key not in state["candidates"] or key not in state["archive"]:
            raise LoopError(f"SPRT status refers to unknown or unvalidated tuple: {key}")
        if state["applied_sprt"].get(key) != command["revision"]:
            set_status(state, key, command["status"], command["note"])
            state["applied_sprt"][key] = command["revision"]


def save(root, state):
    # This is the authoritative transaction. Reports are replaceable projections.
    write(root / "loop_state.json", state)
    write(root / "selection_frontier.json", state["selection"])
    write(root / "sprt_queue.json", {key: {**value, "candidate": state["candidates"][key]}
                                    for key, value in state["sprt_queue"].items()})


def initialize(config, contract):
    root = config["root"]
    state_path = root / "loop_state.json"
    if state_path.is_file():
        state = read(state_path)
        if state.get("schema") != SCHEMA or state["contract_sha256"] != digest(contract):
            raise LoopError("evaluation contract changed; create a new loop")
        if state["initialization"] != config["initialization"]:
            raise LoopError("initialization changed; use control commands for an existing loop")
        return state
    # Allow remnants of a failed first atomic write, not a pre-existing campaign
    # or an evaluation directory whose authoritative state has been lost.
    initial_files = {"loop.lock", "control.lock", "control.json", "control.json.tmp", "loop_state.json.tmp"}
    if root.exists() and any(path.name not in initial_files for path in root.iterdir()):
        raise LoopError("loop directory is nonempty without loop_state.json; recover its state or use a new loop_id")
    state = {"schema": SCHEMA, "contract": contract, "contract_sha256": digest(contract),
             "initialization": config["initialization"], "options": config["options"], "revision": 1,
             "revisions": [{"revision": 1, "options": config["options"]}], "cycle": 0,
             "phase_number": 0, "active": None, "next_phase": "dev", "stopped": False,
             "candidates": {}, "pending": [], "archive": {}, "selection": {}, "sprt_queue": {},
             "applied_sprt": {}, "proven_bases": [], "dev_results": [], "imports_done": False}
    key = register(state, config["initialization"]["base"])
    state["base_id"] = key
    state["proven_bases"].append(key)
    for item in config["initialization"]["validation_pool"]:
        enqueue(state, register(state, item))
    if state["pending"]:
        enqueue(state, key)
        state["next_phase"] = "validation"
    rebuild(state)
    # Recoverable if initialization dies between these two writes.
    with locked(root / "control.lock", blocking=True):
        if not (root / "control.json").exists():
            write(root / "control.json", {"base": config["initialization"]["base"], "stop_requested": False, "sprt": {}})
    save(root, state)
    return state


def import_sources(config, env, state):
    """Import explicit batch/campaign raw evidence into cache; metrics are recomputed.

    A batch may cover only some shards. Its candidates enter pending once and
    the normal full-selection phase fills only cache misses. No source is edited.
    """
    for directory in state["initialization"]["imports"]:
        run = Path(directory)
        path = run / "batch_manifest.json"
        manifest = read(path if path.is_file() else run / "campaign_manifest.json")
        for name in ("probe", "weights"):
            if not campaign.same_identity(manifest.get(name), tune.file_identity(env[name])):
                raise LoopError(f"import {run}: incompatible {name}")
        if manifest.get("candidate_nodes") != env["candidate_nodes"]:
            raise LoopError(f"import {run}: incompatible nodes")
        if manifest.get("schema") == backfill.BATCH_SCHEMA:
            items = backfill.batch_items(run, manifest)
            results = read(run / "results.json")
            identities = {r["id"] + "/" + shard["id"]: shard["output"]
                          for r in results["candidates"] for shard in r["shards"]}
            is_selection = True
        elif manifest.get("schema") == campaign.MANIFEST_SCHEMA:
            items = backfill.campaign_items(run, manifest)
            identities = {r["id"]: r["output"] for r in read(run / "search" / "state.json")["evaluations"]}
            is_selection = False
        else:
            raise LoopError(f"unsupported import manifest: {run}")
        allowed = {tune.file_identity(s["input"])["sha256"] for s in (env["selection"] if is_selection else [env["development"]])}
        for label, probe, weights, inputs, nodes, margins, output in items:
            if label not in identities or not campaign.same_identity(identities[label], tune.file_identity(output)):
                raise LoopError(f"import {run}/{label}: output differs from recorded evidence")
            if len(inputs) != 1 or tune.file_identity(inputs[0])["sha256"] not in allowed:
                raise LoopError(f"import {run}/{label}: incompatible population input")
            backfill.import_item(env["probe_cache_dir"], probe, weights, inputs, nodes, margins, output, False)
            key = register(state, candidate({"margins": margins, "alias": label, "provenance": str(run)}))
            if is_selection:
                enqueue(state, key)
    state["imports_done"] = True
    if state["pending"]:
        enqueue(state, state["base_id"])
        state["next_phase"] = "validation"
    save(config["root"], state)


def begin_phase(state, control):
    options = state["options"]
    phase = state["next_phase"]
    if phase == "dev":
        base = candidate(control["base"])
        if max(base["margins"]) > options["search"]["max_margin"]:
            raise LoopError("new base exceeds max_margin")
        state["base_id"] = register(state, base)
        if state["base_id"] not in state["proven_bases"]:
            state["proven_bases"].append(state["base_id"])
        state["cycle"] += 1
    state["active"] = {"phase": phase, "cycle": state["cycle"], "base_id": state["base_id"],
                       "number": state["phase_number"], "options": copy.deepcopy(options)}
    if phase == "validation":
        enqueue(state, state["base_id"])
        state["active"]["candidates"] = list(state["pending"])
    else:
        state["active"]["seed"] = options["search"]["seed"] + state["cycle"] - 1
    rebuild(state)


def search_settings(env, state, root):
    active = state["active"]
    options = active["options"]
    policy = options["dev_selector"]
    settings = {**env, "report_every": options["report_every"], "pareto_search": {
        **options["search"], "seed": active["seed"], "initial_margins": state["candidates"][active["base_id"]]["margins"],
        **policy}}
    path = root / "cycles" / f"{active['cycle']:06d}" / "search_config.json"
    value = campaign.search_config(settings)
    if path.exists() and read(path) != value:
        raise LoopError("active dev config changed")
    write(path, value)
    loaded = pareto.load_settings(path)
    return loaded, path.parent / "search"


def execute_dev(config, env, state):
    settings, run_dir = search_settings(env, state, config["root"])
    pareto.prepare(run_dir, pareto.manifest(settings))
    result = pareto.run(settings, run_dir)
    if result["status"] != "max_proposals":
        raise LoopError("development phase did not finish")
    return read(run_dir / "state.json")["evaluations"]


def execute_validation(config, env, state):
    active = state["active"]
    run_dir = config["root"] / "validation" / f"{active['number']:06d}"
    settings = {**env, "run_dir": run_dir.parent, "report_every": active["options"]["report_every"], "validation": {
        "candidates": [{"id": key, "margins": state["candidates"][key]["margins"]} for key in active["candidates"]],
        "tail_fractions": [0.01, 0.05], "regret_thresholds": [0.1, 0.25],
        "semantic_thresholds": {"advantage_cp": 150, "loss_cp": -150}}}
    value = campaign.validation_config(settings)
    value["run_dir"] = str(run_dir)
    path = run_dir.parent / f"{active['number']:06d}.json"
    if path.exists() and read(path) != value:
        raise LoopError("active validation config changed")
    write(path, value)
    loaded = batch.load_settings(path)
    contexts = batch.load_contexts(loaded)
    result = batch.run_batch(loaded, contexts, set(active["candidates"]))
    if not result["complete"]:
        raise LoopError("validation phase did not finish")
    results = read(run_dir / "results.json")
    expected = sum(len(s["context"].trusted_keys) for s in contexts)
    if results["trusted_position_count"] != expected:
        raise LoopError("incomplete pooled selection coverage")
    return results["candidates"]


def finish_phase(state, results):
    active = state["active"]
    if active["phase"] == "dev":
        _, survivors, _ = select(results, active["options"]["dev_selector"])
        state["dev_results"].append({"cycle": active["cycle"], "base_id": active["base_id"]})
        for record in survivors:
            key = register(state, candidate({"margins": record["margins"], "alias": record["id"],
                                            "provenance": f"cycle-{active['cycle']}"}))
            enqueue(state, key)
        enqueue(state, state["base_id"])
        state["next_phase"] = "validation" if state["pending"] else "dev"
    else:
        if {r["id"] for r in results} != set(active["candidates"]):
            raise LoopError("validation result candidates do not match frozen batch")
        for result in results:
            key = result["id"]
            state["archive"][key] = {"id": key, "margins": state["candidates"][key]["margins"],
                "metrics": result["pooled_metrics"], "risk": result["pooled_risk"],
                "semantic": result["pooled_risk"]["semantic_regressions_vs_reference"], "shards": result["shards"]}
        state["pending"] = [key for key in state["pending"] if key not in state["archive"]]
        state["next_phase"] = "dev"
    state["phase_number"] += 1
    state["active"] = None
    rebuild(state)


def run_loop(config, env, state, max_phases=0):
    completed = 0
    if state["stopped"]:
        print("loop is stopped; use resume explicitly", flush=True)
        return
    if not state["imports_done"]:
        import_sources(config, env, state)
    while True:
        control = read(config["root"] / "control.json")
        if state["active"] is None:
            apply_test_updates(state, control)
            rebuild(state)
            if control["stop_requested"]:
                state["stopped"] = True
                save(config["root"], state)
                print("loop stopped at phase boundary", flush=True)
                return
            if max_phases and completed >= max_phases:
                save(config["root"], state)
                return
            # Do not silently accept an edited config while a live loop runs.
            latest = load_config(config["path"])
            if latest["raw"] != config["raw"]:
                raise LoopError("configuration changed; stop and explicitly reconfigure")
            begin_phase(state, control)
            save(config["root"], state)
        active = state["active"]
        print(f"loop phase={active['phase']} cycle={active['cycle']} start/resume", flush=True)
        results = execute_dev(config, env, state) if active["phase"] == "dev" else execute_validation(config, env, state)
        finish_phase(state, results)
        save(config["root"], state)
        completed += 1
        print(f"loop phase complete; pending_validation={len(state['pending'])} queue="
              f"{sum(q['status'] == 'pending' for q in state['sprt_queue'].values())}", flush=True)


def reconfigure(config, state):
    if not state["stopped"] or state["active"] is not None:
        raise LoopError("reconfigure requires a graceful phase-boundary stop")
    state["options"] = config["options"]
    state["revision"] += 1
    state["revisions"].append({"revision": state["revision"], "options": config["options"]})
    # Re-select previous development evidence, scheduling only new survivors.
    for completed in state["dev_results"]:
        path = config["root"] / "cycles" / f"{completed['cycle']:06d}" / "search" / "state.json"
        records = read(path)["evaluations"]
        _, survivors, _ = select(records, state["options"]["dev_selector"])
        for record in survivors:
            enqueue(state, register(state, candidate({"margins": record["margins"], "alias": record["id"],
                                                     "provenance": f"cycle-{completed['cycle']}"})))
    if state["pending"]:
        state["next_phase"] = "validation"
    rebuild(state)
    save(config["root"], state)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "status", "stop", "resume", "reconfigure", "set-base", "sprt"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--max-phases", type=int, default=0)
    parser.add_argument("--margins", help="comma-separated new proven base")
    parser.add_argument("--alias", default="sprt-best")
    parser.add_argument("--candidate", help="stable tuple ID from sprt_queue.json")
    parser.add_argument("--status", choices=["pending", "running", "accepted", "rejected", "superseded"])
    parser.add_argument("--note", default="operator")
    args = parser.parse_args(argv)
    if args.max_phases < 0:
        raise LoopError("max-phases must be nonnegative")
    config = load_config(Path(args.config).expanduser().resolve())
    root = config["root"]
    if args.command == "status":
        state = read(root / "loop_state.json")
        print(json.dumps({key: state[key] for key in ("stopped", "cycle", "active", "next_phase", "pending", "base_id", "selection", "sprt_queue")}, indent=2))
        print(json.dumps({"control": read(root / "control.json")}, indent=2))
        return 0
    if args.command in {"stop", "set-base", "sprt"}:
        def update(control):
            if args.command == "stop":
                control["stop_requested"] = True
            elif args.command == "set-base":
                if not args.margins:
                    raise LoopError("set-base requires --margins")
                control["base"] = candidate({"margins": [int(v) for v in args.margins.split(",")], "alias": args.alias, "provenance": args.note})
            else:
                state = read(root / "loop_state.json")
                if args.candidate not in state["archive"] or not args.status:
                    raise LoopError("sprt requires a fully validated --candidate and --status")
                revision = control["sprt"].get(args.candidate, {}).get("revision", 0) + 1
                control["sprt"][args.candidate] = {"status": args.status, "note": args.note, "revision": revision}
        edit_control(root, update)
        print(f"{args.command} recorded; applied at phase boundary", flush=True)
        return 0
    with locked(root / "loop.lock") as acquired:
        if not acquired:
            if args.command == "run":
                print("loop already running", flush=True)
                return 0
            raise LoopError("loop is running; wait for its phase-boundary stop")
        env, contract = environment(config)
        state = initialize(config, contract)
        if args.command == "reconfigure":
            reconfigure(config, state)
            return 0
        if state["options"] != config["options"]:
            raise LoopError("parameters changed; use stop then reconfigure")
        if args.command == "resume":
            edit_control(root, lambda control: control.update(stop_requested=False))
            state["stopped"] = False
            save(root, state)
        run_loop(config, env, state, args.max_phases)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (LoopError, campaign.CampaignError, batch.BatchError, pareto.optimize_futility.OptimizationError,
            tune.TuningError, cache.CacheError, OSError, ValueError, RuntimeError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise SystemExit(1)
