#!/usr/bin/env python3
"""Run a resumable Pareto-search and/or selection-validation futility campaign.

The campaign config describes immutable populations in a local or cloud
``per-root-v1`` store.  It creates only one new directory below ``evals/``;
anchors and mate-rescue evidence are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import optimize_futility
import optimize_futility_gated
import futility_probe_cache
import run_futility_validation_batch as validation_batch
import tune_futility


SCHEMA = "chilo.futility_campaign.v1"
MANIFEST_SCHEMA = "chilo.futility_campaign_manifest.v1"
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


class CampaignError(RuntimeError):
    pass


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CampaignError(f"invalid {label}: {path}: root must be an object")
    return raw


def resolve(config_path: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise CampaignError(f"{label} must be a non-empty path")
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (config_path.parent / path).resolve()


def require_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise CampaignError(f"{label} must be a lowercase identifier")
    return value


def require_int(value: Any, label: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CampaignError(f"{label} must be an integer >= {minimum}")
    return value


def file_identity(path: Path) -> dict[str, Any]:
    try:
        return tune_futility.file_identity(path)
    except OSError as exc:
        raise CampaignError(f"cannot hash {path}: {exc}") from exc


def parse_descriptor(store_root: Path, value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"id", "kind", "path"}:
        raise CampaignError(f"{label} must contain exactly id, kind, path")
    identifier = require_identifier(value["id"], f"{label}.id")
    kind = value["kind"]
    if kind not in {"single", "sharded"}:
        raise CampaignError(f"{label}.kind must be single or sharded")
    path_value = value["path"]
    if not isinstance(path_value, str) or not path_value:
        raise CampaignError(f"{label}.path must be a non-empty path")
    path = Path(path_value).expanduser()
    root = path.resolve() if path.is_absolute() else (store_root / path).resolve()
    if not root.is_dir():
        raise CampaignError(f"{label}.path does not exist: {root}")
    return {"id": identifier, "kind": kind, "root": root}


def only_input(root: Path, label: str) -> Path:
    inputs = sorted((root / "inputs").glob("*.csv"))
    if len(inputs) != 1:
        raise CampaignError(f"{label} must contain exactly one inputs/*.csv artifact")
    return inputs[0]


def optional_population_manifest(root: Path, input_path: Path, label: str) -> dict[str, Any] | None:
    path = root / "population_manifest.json"
    if not path.is_file():
        return None
    manifest = read_json(path, f"{label} population manifest")
    if manifest.get("schema") != "chilo.futility_population.v1":
        raise CampaignError(f"{label} has an unsupported population manifest schema")
    expected = manifest.get("input")
    actual = file_identity(input_path)
    if not isinstance(expected, dict) or any(expected.get(key) != actual.get(key) for key in ("sha256", "size")):
        raise CampaignError(f"{label} input does not match its population manifest")
    return file_identity(path)


def resolve_single(descriptor: Mapping[str, Any], config_path: Path) -> list[dict[str, Any]]:
    root = Path(descriptor["root"])
    identifier = str(descriptor["id"])
    input_path = only_input(root, identifier)
    manifest = optional_population_manifest(root, input_path, identifier)
    anchor_dir, rescue_dir = root, root / "rescue"
    if not (anchor_dir / "probes" / "reference.jsonl").is_file() or not rescue_dir.is_dir():
        raise CampaignError(f"{identifier} does not contain an anchor probes/ directory and rescue/ sidecar")
    context = optimize_futility.load_anchor(
        config_path,
        identifier,
        {"reference_dir": str(anchor_dir), "contract": "per_root_v1", "rescue_dir": str(rescue_dir)},
        120000,
        (120, 240, 360),
    )
    return [{
        "id": identifier,
        "population": identifier,
        "input": input_path,
        "anchor_dir": anchor_dir,
        "rescue_dir": rescue_dir,
        "population_manifest": manifest,
        "context": context,
    }]


def resolve_sharded(descriptor: Mapping[str, Any], config_path: Path) -> list[dict[str, Any]]:
    root = Path(descriptor["root"])
    identifier = str(descriptor["id"])
    receipt_path = root / "complete.json"
    receipt = read_json(receipt_path, f"{identifier} completion receipt")
    if receipt.get("schema") != "chilo.futility_validation_shards_complete.v1" or not isinstance(receipt.get("shards"), list):
        raise CampaignError(f"{identifier} has an invalid completed-shards receipt")
    shard_ids = receipt["shards"]
    if not shard_ids or any(not isinstance(item, str) or not IDENTIFIER_RE.fullmatch(item) for item in shard_ids):
        raise CampaignError(f"{identifier} completion receipt has invalid shard IDs")
    if len(set(shard_ids)) != len(shard_ids):
        raise CampaignError(f"{identifier} completion receipt contains duplicate shard IDs")
    resolved = []
    for shard_id in shard_ids:
        input_path = root / "inputs" / f"{shard_id}.csv"
        anchor_dir = root / "shards" / shard_id / "anchor"
        rescue_dir = root / "shards" / shard_id / "rescue"
        if not input_path.is_file() or not anchor_dir.is_dir() or not rescue_dir.is_dir():
            raise CampaignError(f"{identifier}/{shard_id} is incomplete")
        context = optimize_futility.load_anchor(
            config_path,
            shard_id,
            {"reference_dir": str(anchor_dir), "contract": "per_root_v1", "rescue_dir": str(rescue_dir)},
            120000,
            (120, 240, 360),
        )
        resolved.append({
            "id": shard_id,
            "population": identifier,
            "input": input_path,
            "anchor_dir": anchor_dir,
            "rescue_dir": rescue_dir,
            "population_manifest": file_identity(receipt_path),
            "context": context,
        })
    return resolved


def resolve_population(descriptor: Mapping[str, Any], config_path: Path) -> list[dict[str, Any]]:
    return resolve_single(descriptor, config_path) if descriptor["kind"] == "single" else resolve_sharded(descriptor, config_path)


def context_identity(item: Mapping[str, Any]) -> dict[str, Any]:
    context = item["context"]
    anchor_manifest_path = Path(item["anchor_dir"]) / "anchor_manifest.json"
    rescue_manifest_path = Path(item["rescue_dir"]) / "rescue_manifest.json"
    historical: dict[str, Any] = {}
    if anchor_manifest_path.is_file():
        anchor_manifest = read_json(anchor_manifest_path, f"{item['id']} anchor manifest")
        historical["anchor_manifest"] = file_identity(anchor_manifest_path)
        historical["reference_probe"] = anchor_manifest.get("reference_probe")
        historical["anchor_weights"] = anchor_manifest.get("weights")
    if rescue_manifest_path.is_file():
        rescue_manifest = read_json(rescue_manifest_path, f"{item['id']} rescue manifest")
        historical["rescue_manifest"] = file_identity(rescue_manifest_path)
        historical["rescue_probe"] = rescue_manifest.get("probe")
        historical["rescue_weights"] = rescue_manifest.get("weights")
    return {
        "id": item["id"],
        "population": item["population"],
        "input": file_identity(item["input"]),
        "population_manifest": item["population_manifest"],
        "reference": context.reference_identity,
        "baseline": context.baseline_identity,
        "rescue": dict(context.rescue) if context.rescue is not None else None,
        "trusted_set": dict(context.trusted_set),
        "historical_artifacts": historical,
    }


def same_identity(left: Any, right: Any) -> bool:
    return isinstance(left, dict) and isinstance(right, dict) and all(left.get(key) == right.get(key) for key in ("sha256", "size"))


def same_rescue_contract(left: Any, right: Any) -> bool:
    """Compare immutable rescue evidence without tying a campaign to its host path."""
    if left is None or right is None:
        return left is None and right is None
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return all(same_identity(left.get(key), right.get(key)) for key in (
        "manifest", "results", "combined_population", "reference", "baseline",
    ))


def require_reuse_contract(source: Mapping[str, Any], settings: Mapping[str, Any], source_run_id: str) -> None:
    expected_development = context_identity(settings["development"])
    checks = (
        ("probe", source.get("probe"), file_identity(settings["probe"])),
        ("weights", source.get("weights"), file_identity(settings["weights"])),
        ("development.reference", source.get("development", {}).get("reference") if isinstance(source.get("development"), dict) else None, expected_development["reference"]),
        ("development.baseline", source.get("development", {}).get("baseline") if isinstance(source.get("development"), dict) else None, expected_development["baseline"]),
    )
    for label, actual, expected in checks:
        if not same_identity(actual, expected):
            raise CampaignError(f"initial_evaluation source campaign {source_run_id} has incompatible {label}")
    source_development = source.get("development")
    if not isinstance(source_development, dict) or source.get("candidate_nodes") != settings["candidate_nodes"] or \
       source.get("baseline_margins") != list(settings["baseline_margins"]) or source.get("score_scale") != settings["score_scale"] or \
       source_development.get("trusted_set") != expected_development["trusted_set"] or \
       not same_rescue_contract(source_development.get("rescue"), expected_development["rescue"]):
        raise CampaignError(f"initial_evaluation source campaign {source_run_id} has an incompatible development contract")


def resolve_initial_evaluation(settings: Mapping[str, Any], value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"campaign_run_id", "evaluation_id"}:
        raise CampaignError("initial_evaluation must contain exactly campaign_run_id and evaluation_id")
    source_run_id = require_identifier(value["campaign_run_id"], "initial_evaluation.campaign_run_id")
    evaluation_id = require_identifier(value["evaluation_id"], "initial_evaluation.evaluation_id")
    source_run = Path(settings["store_root"]) / "evals" / source_run_id
    if source_run.resolve() == Path(settings["run_dir"]).resolve():
        raise CampaignError("initial_evaluation cannot reference the campaign being created")
    source_manifest_path = source_run / "campaign_manifest.json"
    source_state_path = source_run / "search" / "state.json"
    source_manifest = read_json(source_manifest_path, f"initial_evaluation campaign {source_run_id} manifest")
    if source_manifest.get("schema") != MANIFEST_SCHEMA:
        raise CampaignError(f"initial_evaluation source campaign {source_run_id} has unsupported manifest schema")
    require_reuse_contract(source_manifest, settings, source_run_id)
    state = read_json(source_state_path, f"initial_evaluation campaign {source_run_id} search state")
    if state.get("schema") != optimize_futility_gated.STATE_SCHEMA or not isinstance(state.get("evaluations"), list):
        raise CampaignError(f"initial_evaluation source campaign {source_run_id} has invalid Pareto state")
    matches = [item for item in state["evaluations"] if isinstance(item, dict) and item.get("id") == evaluation_id]
    if len(matches) != 1:
        raise CampaignError(f"initial_evaluation source evaluation does not exist: {source_run_id}/{evaluation_id}")
    record = matches[0]
    try:
        margins = tuple(tune_futility.validate_margins(record.get("margins"), "initial_evaluation source margins"))
    except tune_futility.TuningError as exc:
        raise CampaignError(f"initial_evaluation source {source_run_id}/{evaluation_id} has invalid margins") from exc
    output_path = source_run / "search" / "probes" / f"{evaluation_id}.jsonl"
    if not output_path.is_file() or not same_identity(record.get("output"), file_identity(output_path)):
        raise CampaignError(f"initial_evaluation source output is missing or differs from its recorded evaluation: {source_run_id}/{evaluation_id}")
    try:
        tune_futility.parse_probe_output(output_path, settings["candidate_nodes"], margins)
    except tune_futility.TuningError as exc:
        raise CampaignError(f"initial_evaluation source output is not a complete normal-PVS probe: {source_run_id}/{evaluation_id}") from exc
    return {
        "campaign_run_id": source_run_id,
        "evaluation_id": evaluation_id,
        "margins": list(margins),
        "campaign_manifest": file_identity(source_manifest_path),
        "state": file_identity(source_state_path),
        "source_output": file_identity(output_path),
        "source_output_path": str(output_path),
        "source_kind": record.get("kind"),
    }


def load_campaign(config_path: Path) -> dict[str, Any]:
    raw_bytes = config_path.read_bytes()
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise CampaignError(f"invalid campaign config: {exc}") from exc
    if not isinstance(raw, dict):
        raise CampaignError("campaign config root must be an object")
    allowed = {
        "schema", "store_root", "run_id", "artifacts", "candidate_nodes", "baseline_margins", "score_scale", "report_every",
        "development", "selection", "pareto_search", "validation", "initial_evaluation",
    }
    unknown = sorted(set(raw) - allowed)
    if raw.get("schema") != SCHEMA or unknown:
        details = [f"schema must be {SCHEMA}"] if raw.get("schema") != SCHEMA else []
        if unknown:
            details.append("unknown=" + ", ".join(unknown))
        raise CampaignError("invalid campaign config: " + "; ".join(details))
    store_root = resolve(config_path, raw.get("store_root"), "store_root")
    if not store_root.is_dir():
        raise CampaignError(f"store_root does not exist: {store_root}")
    run_id = require_identifier(raw.get("run_id"), "run_id")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"probe", "weights"}:
        raise CampaignError("artifacts must contain exactly probe and weights")
    probe, weights = resolve(config_path, artifacts["probe"], "artifacts.probe"), resolve(config_path, artifacts["weights"], "artifacts.weights")
    if not probe.is_file() or not weights.is_file():
        raise CampaignError("configured probe and weights must exist")
    candidate_nodes = require_int(raw.get("candidate_nodes"), "candidate_nodes")
    baseline_margins = tuple(tune_futility.validate_margins(raw.get("baseline_margins"), "baseline_margins"))
    if candidate_nodes != 120000 or baseline_margins != (120, 240, 360):
        raise CampaignError("current per-root-v1 populations require candidate_nodes=120000 and baseline_margins=[120,240,360]")
    score_scale_raw = raw.get("score_scale", 600)
    if isinstance(score_scale_raw, bool) or not isinstance(score_scale_raw, (int, float)) or score_scale_raw <= 0:
        raise CampaignError("score_scale must be a number > 0")
    report_every = require_int(raw.get("report_every", 1000), "report_every", 0)
    development = parse_descriptor(store_root, raw.get("development"), "development")
    if development["kind"] != "single":
        raise CampaignError("development must currently be a single population")
    selection_raw = raw.get("selection")
    if not isinstance(selection_raw, list) or not selection_raw:
        raise CampaignError("selection must be a non-empty population list")
    selection = [parse_descriptor(store_root, item, f"selection[{index}]") for index, item in enumerate(selection_raw)]
    population_ids = [development["id"], *(item["id"] for item in selection)]
    if len(set(population_ids)) != len(population_ids):
        raise CampaignError("development and selection population IDs must be distinct")
    development_shards = resolve_population(development, config_path)
    selection_shards = [item for descriptor in selection for item in resolve_population(descriptor, config_path)]
    resolved_ids = [item["id"] for item in selection_shards]
    if len(set(resolved_ids)) != len(resolved_ids):
        raise CampaignError("selection shard IDs overlap")
    if development_shards[0]["id"] in set(resolved_ids):
        raise CampaignError("development position source overlaps a selection shard ID")
    settings = {
        "raw": raw,
        "config_path": config_path,
        "config_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "store_root": store_root,
        "run_id": run_id,
        "run_dir": store_root / "evals" / run_id,
        "probe_cache_dir": store_root / "candidate-probe-cache",
        "probe": probe,
        "weights": weights,
        "candidate_nodes": candidate_nodes,
        "baseline_margins": baseline_margins,
        "score_scale": float(score_scale_raw),
        "report_every": report_every,
        "development": development_shards[0],
        "selection": selection_shards,
        "pareto_search": raw.get("pareto_search"),
        "validation": raw.get("validation"),
    }
    initial_evaluation_raw = raw.get("initial_evaluation")
    if initial_evaluation_raw is not None:
        if not isinstance(settings["pareto_search"], dict):
            raise CampaignError("initial_evaluation requires pareto_search")
        if "initial_margins" in settings["pareto_search"]:
            raise CampaignError("pareto_search.initial_margins must be omitted when initial_evaluation is supplied")
        seed = resolve_initial_evaluation(settings, initial_evaluation_raw)
        effective_pareto = dict(settings["pareto_search"])
        effective_pareto["initial_margins"] = seed["margins"]
        settings["pareto_search"] = effective_pareto
        settings["initial_evaluation"] = seed
    else:
        settings["initial_evaluation"] = None
    return settings


def search_config(settings: Mapping[str, Any]) -> dict[str, Any]:
    development = settings["development"]
    pareto = settings["pareto_search"]
    if not isinstance(pareto, dict):
        raise CampaignError("pareto_search is required for search")
    return {
        "probe": str(settings["probe"]), "inputs": [str(development["input"])], "weights": str(settings["weights"]),
        "candidate_nodes": settings["candidate_nodes"], "baseline_margins": list(settings["baseline_margins"]),
        "score_scale": settings["score_scale"], "probe_report_every": settings["report_every"],
        "development": {"reference_dir": str(development["anchor_dir"]), "contract": "per_root_v1", "rescue_dir": str(development["rescue_dir"])},
        "pareto_search": pareto,
        "probe_cache_dir": str(settings["probe_cache_dir"]),
    }


def validation_config(settings: Mapping[str, Any]) -> dict[str, Any]:
    validation = settings["validation"]
    if not isinstance(validation, dict) or set(validation) != {"candidates", "tail_fractions", "regret_thresholds", "semantic_thresholds"}:
        raise CampaignError("validation must contain exactly candidates, tail_fractions, regret_thresholds, semantic_thresholds")
    return {
        "schema": validation_batch.SCHEMA,
        "run_dir": str(settings["run_dir"] / "validation"),
        "probe": str(settings["probe"]), "weights": str(settings["weights"]),
        "candidate_nodes": settings["candidate_nodes"], "baseline_margins": list(settings["baseline_margins"]),
        "score_scale": settings["score_scale"], "report_every": settings["report_every"],
        "tail_fractions": validation["tail_fractions"], "regret_thresholds": validation["regret_thresholds"],
        "semantic_thresholds": validation["semantic_thresholds"],
        "shards": [{"id": item["id"], "input": str(item["input"]), "anchor_dir": str(item["anchor_dir"]), "rescue_dir": str(item["rescue_dir"])} for item in settings["selection"]],
        "candidates": validation["candidates"],
        "probe_cache_dir": str(settings["probe_cache_dir"]),
    }


def campaign_manifest(settings: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "config": {"path": str(settings["config_path"]), "sha256": settings["config_sha256"]},
        "probe": file_identity(settings["probe"]), "weights": file_identity(settings["weights"]),
        "candidate_nodes": settings["candidate_nodes"], "baseline_margins": list(settings["baseline_margins"]),
        "score_scale": settings["score_scale"], "report_every": settings["report_every"],
        "development": context_identity(settings["development"]),
        "selection": [context_identity(item) for item in settings["selection"]],
        "pareto_search": settings["pareto_search"], "validation": settings["validation"],
        "initial_evaluation": settings["initial_evaluation"],
    }


def stage_initial_evaluation(settings: Mapping[str, Any]) -> None:
    seed = settings["initial_evaluation"]
    if seed is None:
        return
    source = Path(seed["source_output_path"])
    target = Path(settings["run_dir"]) / "search" / "probes" / "initial.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = futility_probe_cache.descriptor(
            settings["probe"], settings["weights"], [settings["development"]["input"]], settings["candidate_nodes"], seed["margins"],
        )
        cache_root = Path(settings.get("probe_cache_dir", Path(settings["store_root"]) / "candidate-probe-cache"))
        entry = futility_probe_cache.entry_for(cache_root, value)
        with futility_probe_cache.lock(cache_root, entry.key):
            if entry.directory.exists():
                futility_probe_cache.restore(entry, target, settings["candidate_nodes"], seed["margins"])
                status = "hit"
            else:
                if not source.is_file() or not same_identity(file_identity(source), seed["source_output"]):
                    raise CampaignError("initial_evaluation source changed before it could be imported into the cache")
                futility_probe_cache.publish(entry, source, settings["candidate_nodes"], seed["margins"])
                futility_probe_cache.restore(entry, target, settings["candidate_nodes"], seed["margins"])
                status = "imported_seed"
        atomic_json(target.parent.parent / "logs" / "initial.cache.json", futility_probe_cache.receipt(entry, status))
    except futility_probe_cache.CacheError as exc:
        raise CampaignError(f"initial_evaluation cache failure: {exc}") from exc
    try:
        tune_futility.parse_probe_output(target, settings["candidate_nodes"], tuple(seed["margins"]))
    except tune_futility.TuningError as exc:
        raise CampaignError("staged initial_evaluation is not a complete normal-PVS probe") from exc


def prepare(settings: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    run_dir = settings["run_dir"]
    manifest_path = run_dir / "campaign_manifest.json"
    if manifest_path.is_file():
        if read_json(manifest_path, "campaign manifest") != manifest:
            raise CampaignError("campaign manifest does not match configured artifacts or populations; use a new run_id")
    elif run_dir.exists() and any(run_dir.iterdir()):
        raise CampaignError(f"campaign run directory exists without campaign_manifest.json: {run_dir}")
    else:
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(manifest_path, manifest)
    if isinstance(settings["pareto_search"], dict):
        atomic_json(run_dir / "search_config.json", search_config(settings))
    if isinstance(settings["validation"], dict):
        atomic_json(run_dir / "validation_config.json", validation_config(settings))
    stage_initial_evaluation(settings)


def write_progress(settings: Mapping[str, Any], phase: str, search: Mapping[str, Any] | None, validation: Mapping[str, Any] | None) -> None:
    atomic_json(settings["run_dir"] / "campaign_progress.json", {
        "schema": SCHEMA, "requested_phase": phase, "search": search, "validation": validation,
    })


def run_campaign(settings: Mapping[str, Any], phase: str, max_work_units: int) -> None:
    if phase not in {"search", "validate", "all"}:
        raise CampaignError("phase must be search, validate, or all")
    if max_work_units < 0:
        raise CampaignError("max_work_units must be >= 0")
    do_search, do_validation = phase in {"search", "all"}, phase in {"validate", "all"}
    if do_search and not isinstance(settings["pareto_search"], dict):
        raise CampaignError("search phase requires pareto_search")
    if do_validation and not isinstance(settings["validation"], dict):
        raise CampaignError("validation phase requires validation")
    search_result = None
    validation_result = None
    if do_search:
        search_settings = optimize_futility_gated.load_settings(settings["run_dir"] / "search_config.json")
        optimize_futility_gated.prepare(settings["run_dir"] / "search", optimize_futility_gated.manifest(search_settings))
        search_result = optimize_futility_gated.run(search_settings, settings["run_dir"] / "search", max_work_units)
        print(f"campaign search: {search_result['status']} work_units={search_result['work_units_completed']}")
        if phase == "all" and (search_result["status"] != "max_proposals" or (max_work_units and search_result["work_units_completed"] > 0)):
            write_progress(settings, phase, search_result, validation_result)
            return
    if do_validation:
        validation_settings = validation_batch.load_settings(settings["run_dir"] / "validation_config.json")
        contexts = validation_batch.load_contexts(validation_settings)
        selected = {item["id"] for item in validation_settings["candidates"]}
        validation_result = validation_batch.run_batch(validation_settings, contexts, selected, max_work_units)
        print(f"campaign validation: {'complete' if validation_result['complete'] else 'partial'} work_units={validation_result['work_units_completed']}")
    write_progress(settings, phase, search_result, validation_result)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--phase", choices=("search", "validate", "all"), required=True)
    parser.add_argument("--max-work-units", type=int, default=0, help="Maximum initial/proposal or candidate/shard probes; 0 means unlimited.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        config_path = Path(args.config).expanduser().resolve()
        settings = load_campaign(config_path)
        manifest = campaign_manifest(settings)
        if args.dry_run:
            print(json.dumps({"run_dir": str(settings["run_dir"]), "manifest": manifest}, indent=2, sort_keys=True))
            return 0
        prepare(settings, manifest)
        run_campaign(settings, args.phase, args.max_work_units)
        return 0
    except (CampaignError, OSError, json.JSONDecodeError, optimize_futility.OptimizationError, tune_futility.TuningError, validation_batch.BatchError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
