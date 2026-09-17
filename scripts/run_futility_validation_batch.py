#!/usr/bin/env python3
"""Serial, resumable candidate probes over immutable futility validation shards.

An anchor/rescue population is never changed by this tool.  It only writes
normal PVS candidate probes below ``run_dir/candidates`` and a pooled report.
Rerunning the same config reuses complete JSONL outputs; an incomplete output
is deliberately rerun from scratch because normal candidate probes have no
safe partial-output contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import futility_risk
import futility_probe_cache
import optimize_futility
import tune_futility


SCHEMA = "chilo.futility_validation_batch.v1"
MANIFEST_SCHEMA = "chilo.futility_validation_batch_manifest.v1"
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
Key = Tuple[str, int, str]


class BatchError(RuntimeError):
    pass


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BatchError(f"invalid {label} {path}: root must be an object")
    return raw


def resolve(config_path: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise BatchError(f"{label} must be a non-empty path")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (config_path.parent / path).resolve()


def require_int(value: Any, label: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise BatchError(f"{label} must be an integer >= {minimum}")
    return value


def require_number(value: Any, label: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= minimum:
        raise BatchError(f"{label} must be a finite number > {minimum}")
    return float(value)


def require_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise BatchError(f"{label} must be a short lowercase identifier")
    return value


def parse_float_list(value: Any, label: str) -> List[float]:
    if not isinstance(value, list) or not value:
        raise BatchError(f"{label} must be a non-empty list")
    result = [require_number(item, f"{label} item") for item in value]
    if len(set(result)) != len(result):
        raise BatchError(f"{label} must not contain duplicates")
    return result


def load_settings(config_path: Path) -> Dict[str, Any]:
    try:
        raw_bytes = config_path.read_bytes()
    except OSError as exc:
        raise BatchError(f"cannot read config {config_path}: {exc}") from exc
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise BatchError(f"invalid config {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BatchError("config root must be an object")
    allowed = {
        "schema", "run_dir", "probe", "weights", "candidate_nodes", "baseline_margins", "score_scale",
        "report_every", "tail_fractions", "regret_thresholds", "semantic_thresholds", "shards", "candidates", "probe_cache_dir",
    }
    unknown = sorted(set(raw) - allowed)
    missing = sorted((allowed - {"probe_cache_dir"}) - set(raw))
    if raw.get("schema") != SCHEMA or unknown or missing:
        details = []
        if raw.get("schema") != SCHEMA:
            details.append(f"schema must be {SCHEMA}")
        if unknown:
            details.append("unknown=" + ", ".join(unknown))
        if missing:
            details.append("missing=" + ", ".join(missing))
        raise BatchError("invalid batch config: " + "; ".join(details))

    probe = resolve(config_path, raw["probe"], "probe")
    weights = resolve(config_path, raw["weights"], "weights")
    if not probe.is_file() or not weights.is_file():
        raise BatchError("probe and weights must both exist")
    cache_raw = raw.get("probe_cache_dir")
    cache_dir = resolve(config_path, cache_raw, "probe_cache_dir") if cache_raw is not None else None
    candidate_nodes = require_int(raw["candidate_nodes"], "candidate_nodes")
    baseline_margins = tuple(tune_futility.validate_margins(raw["baseline_margins"], "baseline_margins"))
    score_scale = require_number(raw["score_scale"], "score_scale")
    report_every = require_int(raw["report_every"], "report_every", 0)
    tail_fractions = parse_float_list(raw["tail_fractions"], "tail_fractions")
    if any(value > 1.0 for value in tail_fractions):
        raise BatchError("tail_fractions must be <= 1")
    regret_thresholds = parse_float_list(raw["regret_thresholds"], "regret_thresholds")
    semantic = raw["semantic_thresholds"]
    if not isinstance(semantic, dict) or set(semantic) != {"advantage_cp", "loss_cp"}:
        raise BatchError("semantic_thresholds must contain exactly advantage_cp and loss_cp")
    advantage_cp = require_int(semantic["advantage_cp"], "semantic_thresholds.advantage_cp", 0)
    loss_cp = semantic["loss_cp"]
    if isinstance(loss_cp, bool) or not isinstance(loss_cp, int) or loss_cp >= 0:
        raise BatchError("semantic_thresholds.loss_cp must be a negative integer")

    shards_raw = raw["shards"]
    if not isinstance(shards_raw, list) or not shards_raw:
        raise BatchError("shards must be a non-empty list")
    shards: List[Dict[str, Any]] = []
    shard_ids = set()
    for index, item in enumerate(shards_raw):
        if not isinstance(item, dict) or set(item) != {"id", "input", "anchor_dir", "rescue_dir"}:
            raise BatchError(f"shards[{index}] must contain exactly id, input, anchor_dir, rescue_dir")
        identifier = require_identifier(item["id"], f"shards[{index}].id")
        if identifier in shard_ids:
            raise BatchError(f"duplicate shard id: {identifier}")
        shard_ids.add(identifier)
        input_path = resolve(config_path, item["input"], f"shards[{index}].input")
        anchor_dir = resolve(config_path, item["anchor_dir"], f"shards[{index}].anchor_dir")
        rescue_dir = resolve(config_path, item["rescue_dir"], f"shards[{index}].rescue_dir")
        if not input_path.is_file() or not anchor_dir.is_dir() or not rescue_dir.is_dir():
            raise BatchError(f"shard {identifier}: input, anchor_dir, and rescue_dir must exist")
        shards.append({"id": identifier, "input": input_path, "anchor_dir": anchor_dir, "rescue_dir": rescue_dir})

    candidates_raw = raw["candidates"]
    if not isinstance(candidates_raw, list) or not candidates_raw:
        raise BatchError("candidates must be a non-empty list")
    candidates: List[Dict[str, Any]] = []
    candidate_ids = set()
    for index, item in enumerate(candidates_raw):
        if not isinstance(item, dict) or set(item) != {"id", "margins"}:
            raise BatchError(f"candidates[{index}] must contain exactly id and margins")
        identifier = require_identifier(item["id"], f"candidates[{index}].id")
        if identifier == "f01" or identifier in candidate_ids:
            raise BatchError(f"candidate id must be unique and not f01: {identifier}")
        candidate_ids.add(identifier)
        candidates.append({"id": identifier, "margins": tuple(tune_futility.validate_margins(item["margins"], f"candidate {identifier} margins"))})

    return {
        "raw": raw,
        "config_path": config_path,
        "config_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "run_dir": resolve(config_path, raw["run_dir"], "run_dir"),
        "probe": probe,
        "weights": weights,
        "candidate_nodes": candidate_nodes,
        "baseline_margins": baseline_margins,
        "score_scale": score_scale,
        "report_every": report_every,
        "tail_fractions": tail_fractions,
        "regret_thresholds": regret_thresholds,
        "advantage_cp": advantage_cp,
        "loss_cp": loss_cp,
        "shards": shards,
        "candidates": candidates,
        "probe_cache_dir": cache_dir,
    }


def load_contexts(settings: Mapping[str, Any]) -> List[Dict[str, Any]]:
    contexts: List[Dict[str, Any]] = []
    for shard in settings["shards"]:
        anchor_manifest_path = shard["anchor_dir"] / "anchor_manifest.json"
        rescue_completion = shard["rescue_dir"] / "completion.json"
        # Earlier per-root populations predate anchor_manifest/completion receipts.
        # Their immutable JSONL plus mate-rescue sidecars are still validated by
        # load_anchor below.  When an anchor manifest exists, use it to bind the
        # input artifact, but deliberately record rather than require equality of
        # its historical probe/net: a campaign freezes one candidate probe while
        # the historical references can have been produced on another platform.
        anchor_manifest = None
        if anchor_manifest_path.is_file():
            anchor_manifest = read_json(anchor_manifest_path, f"{shard['id']} anchor manifest")
            inputs = anchor_manifest.get("inputs")
            actual_input = tune_futility.file_identity(shard["input"])
            if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict) or any(
                inputs[0].get(key) != actual_input.get(key) for key in ("sha256", "size")
            ):
                raise BatchError(f"{shard['id']}: configured input does not match its immutable anchor")
        try:
            context = optimize_futility.load_anchor(
                settings["config_path"],
                shard["id"],
                {
                    "reference_dir": str(shard["anchor_dir"]),
                    "contract": "per_root_v1",
                    "rescue_dir": str(shard["rescue_dir"]),
                },
                settings["candidate_nodes"],
                settings["baseline_margins"],
            )
        except (optimize_futility.OptimizationError, tune_futility.TuningError) as exc:
            raise BatchError(f"invalid immutable anchor for {shard['id']}: {exc}") from exc
        contexts.append({
            **shard,
            "context": context,
            "anchor_manifest": tune_futility.file_identity(anchor_manifest_path) if anchor_manifest is not None else None,
            "rescue_completion": tune_futility.file_identity(rescue_completion) if rescue_completion.is_file() else None,
        })
    return contexts


def execution_manifest(settings: Mapping[str, Any], contexts: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "config_sha256": settings["config_sha256"],
        "probe": tune_futility.file_identity(settings["probe"]),
        "weights": tune_futility.file_identity(settings["weights"]),
        "probe_cache_dir": str(settings["probe_cache_dir"]) if settings["probe_cache_dir"] is not None else None,
        "candidate_nodes": settings["candidate_nodes"],
        "baseline_margins": list(settings["baseline_margins"]),
        "score_scale": settings["score_scale"],
        "candidates": [{"id": item["id"], "margins": list(item["margins"])} for item in settings["candidates"]],
        "shards": [
            {
                "id": shard["id"],
                "input": tune_futility.file_identity(shard["input"]),
                "anchor_manifest": shard["anchor_manifest"],
                "reference": shard["context"].reference_identity,
                "baseline": shard["context"].baseline_identity,
                "rescue": shard["context"].rescue,
                "rescue_completion": shard["rescue_completion"],
                "trusted_position_count": len(shard["context"].trusted_keys),
                "trusted_position_keys_sha256": shard["context"].trusted_set["position_keys_sha256"],
            }
            for shard in contexts
        ],
    }


def verify_or_write_manifest(run_dir: Path, expected: Mapping[str, Any]) -> None:
    path = run_dir / "batch_manifest.json"
    if path.is_file():
        actual = read_json(path, "batch manifest")
        if actual != expected:
            raise BatchError(f"batch manifest mismatch: {path}; use a new run_dir for changed artifacts or config")
        return
    if run_dir.exists() and any(run_dir.iterdir()):
        raise BatchError(f"run_dir exists without batch_manifest.json: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(path, expected)


def candidate_output_path(run_dir: Path, candidate_id: str, shard_id: str) -> Path:
    return run_dir / "candidates" / candidate_id / shard_id / "probes" / "candidate.jsonl"


def run_candidate_probe(settings: Mapping[str, Any], candidate: Mapping[str, Any], shard: Mapping[str, Any]) -> str:
    job_root = candidate_output_path(settings["run_dir"], candidate["id"], shard["id"]).parent.parent
    (job_root / "probes").mkdir(parents=True, exist_ok=True)
    (job_root / "logs").mkdir(exist_ok=True)
    job = {"id": "candidate", "nodes": settings["candidate_nodes"], "margins": candidate["margins"]}
    cache_dir = settings["probe_cache_dir"]
    if cache_dir is not None:
        output = candidate_output_path(settings["run_dir"], candidate["id"], shard["id"])
        value = futility_probe_cache.descriptor(
            settings["probe"], settings["weights"], [shard["input"]], settings["candidate_nodes"], candidate["margins"],
        )
        entry = futility_probe_cache.entry_for(cache_dir, value)
        try:
            with futility_probe_cache.lock(cache_dir, entry.key):
                if entry.directory.exists():
                    futility_probe_cache.restore(entry, output, settings["candidate_nodes"], candidate["margins"])
                    (job_root / "logs" / "candidate.log").write_text(
                        "cache_key=" + entry.key + "\ncache_status=hit\n", encoding="utf-8"
                    )
                    atomic_json(job_root / "logs" / "candidate.cache.json", futility_probe_cache.receipt(entry, "hit"))
                    return "cache-hit"
                if tune_futility.probe_output_complete(output, settings["candidate_nodes"], candidate["margins"]):
                    status = "promoted_existing_output"
                else:
                    try:
                        outcome = tune_futility.run_probe_job(
                            job, settings["probe"], [shard["input"]], settings["weights"], settings["report_every"], job_root, True
                        )
                    except tune_futility.TuningError as exc:
                        raise BatchError(f"{candidate['id']} on {shard['id']}: {exc}") from exc
                    status = "miss" if outcome["status"] == "completed" else "promoted_existing_output"
                futility_probe_cache.publish(entry, output, settings["candidate_nodes"], candidate["margins"])
                atomic_json(job_root / "logs" / "candidate.cache.json", futility_probe_cache.receipt(entry, status))
                return status
        except futility_probe_cache.CacheError as exc:
            raise BatchError(f"{candidate['id']} on {shard['id']}: cache failure: {exc}") from exc
    try:
        outcome = tune_futility.run_probe_job(
            job, settings["probe"], [shard["input"]], settings["weights"], settings["report_every"], job_root, True
        )
    except tune_futility.TuningError as exc:
        raise BatchError(f"{candidate['id']} on {shard['id']}: {exc}") from exc
    return str(outcome["status"])


def parse_candidate(settings: Mapping[str, Any], candidate: Mapping[str, Any], shard: Mapping[str, Any]) -> Mapping[str, Any]:
    path = candidate_output_path(settings["run_dir"], candidate["id"], shard["id"])
    try:
        return tune_futility.parse_probe_output(path, settings["candidate_nodes"], candidate["margins"])
    except tune_futility.TuningError as exc:
        raise BatchError(f"invalid candidate output for {candidate['id']} on {shard['id']}: {exc}") from exc


def candidate_cache_receipt(run_dir: Path, candidate_id: str, shard_id: str) -> Mapping[str, Any] | None:
    path = candidate_output_path(run_dir, candidate_id, shard_id).parent.parent / "logs" / "candidate.cache.json"
    return read_json(path, f"candidate cache receipt {candidate_id}/{shard_id}") if path.is_file() else None


def merge_records(items: Iterable[Tuple[Mapping[str, Any], Sequence[Key]]], label: str) -> Mapping[str, Any]:
    positions: Dict[Key, Any] = {}
    for records, _ in items:
        for key, value in records["positions"].items():
            if key in positions:
                raise BatchError(f"duplicate position key while merging {label}: {key}")
            positions[key] = value
    return {"positions": positions, "summary": {"merged": True}}


def merged_keys(contexts: Sequence[Mapping[str, Any]]) -> List[Key]:
    keys: List[Key] = []
    for shard in contexts:
        keys.extend(shard["context"].trusted_keys)
    if len(set(keys)) != len(keys):
        raise BatchError("trusted validation keys overlap across shards")
    return sorted(keys)


def calculate_results(settings: Mapping[str, Any], contexts: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    reference = merge_records(((item["context"].reference, item["context"].trusted_keys) for item in contexts), "reference")
    baseline = merge_records(((item["context"].baseline, item["context"].trusted_keys) for item in contexts), "baseline")
    keys = merged_keys(contexts)
    results: Dict[str, Any] = {"schema": SCHEMA, "trusted_position_count": len(keys), "candidates": []}
    for candidate in settings["candidates"]:
        per_shard: List[Dict[str, Any]] = []
        candidate_parts = []
        for shard in contexts:
            output = parse_candidate(settings, candidate, shard)
            context = shard["context"]
            try:
                metrics = tune_futility.compute_metrics(
                    context.reference, context.baseline, output, settings["candidate_nodes"], settings["score_scale"], context.trusted_keys
                )
                risk = futility_risk.compute_risk_metrics(
                    context.reference, output, context.trusted_keys, settings["score_scale"], settings["tail_fractions"],
                    settings["regret_thresholds"], settings["advantage_cp"], settings["loss_cp"],
                )
            except (tune_futility.TuningError, optimize_futility.OptimizationError) as exc:
                raise BatchError(f"cannot score {candidate['id']} on {shard['id']}: {exc}") from exc
            per_shard.append({"id": shard["id"], "position_count": len(context.trusted_keys), "metrics": metrics, "risk": risk,
                              "output": tune_futility.file_identity(candidate_output_path(settings["run_dir"], candidate["id"], shard["id"])),
                              "cache": candidate_cache_receipt(settings["run_dir"], candidate["id"], shard["id"])})
            candidate_parts.append((output, context.trusted_keys))
        merged_candidate = merge_records(candidate_parts, f"candidate {candidate['id']}")
        try:
            pooled_metrics = tune_futility.compute_metrics(reference, baseline, merged_candidate, settings["candidate_nodes"], settings["score_scale"], keys)
            pooled_risk = futility_risk.compute_risk_metrics(reference, merged_candidate, keys, settings["score_scale"], settings["tail_fractions"],
                                                              settings["regret_thresholds"], settings["advantage_cp"], settings["loss_cp"])
        except (tune_futility.TuningError, optimize_futility.OptimizationError) as exc:
            raise BatchError(f"cannot pool {candidate['id']}: {exc}") from exc
        results["candidates"].append({"id": candidate["id"], "margins": list(candidate["margins"]), "pooled_metrics": pooled_metrics,
                                      "pooled_risk": pooled_risk, "shards": per_shard})
    results["candidates"].sort(key=lambda item: (item["pooled_metrics"]["mean_normalized_regret"], item["id"]))
    return results


def write_report(path: Path, results: Mapping[str, Any]) -> None:
    lines = ["# Futility validation batch", "", f"Trusted positions pooled: {results['trusted_position_count']}", "",
             "| Candidate | Margins | Mean regret | P90 regret | Move agreement | Squared regret | CVaR-1% |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for candidate in results["candidates"]:
        metrics = candidate["pooled_metrics"]
        risk = candidate["pooled_risk"]["absolute_regret"]
        cvar = risk["tail_mean"].get("top_0.01")
        lines.append(
            f"| {candidate['id']} | {','.join(str(value) for value in candidate['margins'])} | "
            f"{metrics['mean_normalized_regret']:.6f} | {metrics['p90_normalized_regret']:.6f} | "
            f"{metrics['move_agreement_rate']:.6f} | {risk['mean_squared']:.6f} | {cvar:.6f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def progress(settings: Mapping[str, Any], contexts: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    completed = []
    for candidate in settings["candidates"]:
        for shard in contexts:
            output = candidate_output_path(settings["run_dir"], candidate["id"], shard["id"])
            complete = tune_futility.probe_output_complete(output, settings["candidate_nodes"], candidate["margins"])
            completed.append({"candidate": candidate["id"], "shard": shard["id"], "complete": complete})
    return {"schema": SCHEMA, "complete_jobs": sum(item["complete"] for item in completed), "total_jobs": len(completed), "jobs": completed}


def run_batch(settings: Mapping[str, Any], contexts: Sequence[Mapping[str, Any]], selected: set[str], max_work_units: int = 0) -> Dict[str, Any]:
    if max_work_units < 0:
        raise BatchError("max_work_units must be >= 0")
    known = {item["id"] for item in settings["candidates"]}
    unknown = selected - known
    if unknown:
        raise BatchError("unknown candidate(s): " + ", ".join(sorted(unknown)))
    jobs = [(candidate, shard) for candidate in settings["candidates"] if candidate["id"] in selected for shard in contexts]
    verify_or_write_manifest(settings["run_dir"], execution_manifest(settings, contexts))
    pending = [
        (candidate, shard) for candidate, shard in jobs
        if not tune_futility.probe_output_complete(
            candidate_output_path(settings["run_dir"], candidate["id"], shard["id"]), settings["candidate_nodes"], candidate["margins"]
        )
    ]
    work = pending if not max_work_units else pending[:max_work_units]
    for index, (candidate, shard) in enumerate(work, 1):
        status = run_candidate_probe(settings, candidate, shard)
        print(f"batch progress: {index}/{len(work)} {candidate['id']} {shard['id']} {status}", file=sys.stderr, flush=True)
        atomic_json(settings["run_dir"] / "progress.json", progress(settings, contexts))
    current_progress = progress(settings, contexts)
    atomic_json(settings["run_dir"] / "progress.json", current_progress)
    if current_progress["complete_jobs"] == current_progress["total_jobs"]:
        results = calculate_results(settings, contexts)
        atomic_json(settings["run_dir"] / "results.json", results)
        write_report(settings["run_dir"] / "report.md", results)
        atomic_json(settings["run_dir"] / "complete.json", {
            "schema": SCHEMA, "batch_manifest": tune_futility.file_identity(settings["run_dir"] / "batch_manifest.json"),
            "results": tune_futility.file_identity(settings["run_dir"] / "results.json"),
            "trusted_position_count": results["trusted_position_count"],
        })
        print(f"batch complete: {current_progress['total_jobs']} candidate probes; report={settings['run_dir'] / 'report.md'}")
    else:
        print(f"batch partial: {current_progress['complete_jobs']}/{current_progress['total_jobs']} jobs complete; rerun to continue")
    return {"work_units_completed": len(work), "progress": current_progress, "complete": current_progress["complete_jobs"] == current_progress["total_jobs"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--candidate", action="append", help="Run only this candidate id; may be repeated.")
    parser.add_argument("--dry-run", action="store_true", help="Validate anchors and print the serial job plan only.")
    parser.add_argument("--max-work-units", type=int, default=0, help="Maximum candidate/shard probes this invocation; 0 means unlimited.")
    args = parser.parse_args(argv)
    config_path = Path(args.config).resolve()
    settings = load_settings(config_path)
    contexts = load_contexts(settings)
    selected = set(args.candidate or [item["id"] for item in settings["candidates"]])
    known = {item["id"] for item in settings["candidates"]}
    unknown = selected - known
    if unknown:
        raise BatchError("unknown candidate(s): " + ", ".join(sorted(unknown)))
    jobs = [(candidate, shard) for candidate in settings["candidates"] if candidate["id"] in selected for shard in contexts]
    if args.dry_run:
        print(f"validated {len(contexts)} immutable shards and {len(jobs)} serial candidate jobs")
        for candidate, shard in jobs:
            print(f"{candidate['id']} {shard['id']} margins={','.join(str(value) for value in candidate['margins'])}")
        return 0
    if args.max_work_units < 0:
        raise BatchError("--max-work-units must be >= 0")
    run_batch(settings, contexts, selected, args.max_work_units)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BatchError, OSError, json.JSONDecodeError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise SystemExit(1)
