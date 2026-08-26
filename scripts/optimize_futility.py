#!/usr/bin/env python3
"""Coordinate-search futility margins against an existing anchor pair.

The search mechanism lives in :mod:`discrete_optimizer`; this file is the
futility-specific adapter that knows how to run a candidate probe and how to
score it against either supported reference JSONL contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import discrete_optimizer
import tune_futility


SCHEMA = "chilo.futility_margin_optimization.v1"
STATE_SCHEMA = "chilo.futility_margin_optimization_state.v1"
CONTRACTS = ("per_root_v1", "shared_budget_v1")


class OptimizationError(RuntimeError):
    pass


Margins = Tuple[int, ...]


def require_int(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise OptimizationError(f"{name} must be an integer >= {minimum}")
    return value


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OptimizationError(f"{name} must be a non-empty string")
    return value


def resolve_path(config_path: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (config_path.parent / path).resolve()


def read_json(path: Path, description: str) -> Dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OptimizationError(f"invalid {description} {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise OptimizationError(f"invalid {description} {path}: root must be an object")
    return result


def raw_summary(path: Path) -> Dict[str, Any]:
    summary: Optional[Dict[str, Any]] = None
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise OptimizationError(f"{path}:{line_number}: JSONL record must be an object")
                if record.get("type") == "summary":
                    if summary is not None:
                        raise OptimizationError(f"{path}:{line_number}: duplicate summary")
                    summary = record
    except (OSError, json.JSONDecodeError) as exc:
        raise OptimizationError(f"failed to read probe summary {path}: {exc}") from exc
    if summary is None:
        raise OptimizationError(f"{path}: missing summary")
    return summary


def atomic_write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def margins_key(margins: Sequence[int]) -> str:
    return ",".join(str(value) for value in margins)


def margins_from_key(value: str) -> Margins:
    try:
        margins = tuple(int(part) for part in value.split(","))
    except ValueError as exc:
        raise OptimizationError(f"invalid cached margin key {value!r}") from exc
    return tune_futility.validate_margins(list(margins), "cached margins")


def metric_objective(metrics: Mapping[str, Any], margins: Margins) -> discrete_optimizer.Objective:
    try:
        return (
            float(metrics["mean_normalized_regret"]),
            float(metrics["p90_normalized_regret"]),
            float(metrics["median_normalized_regret"]),
            margins,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OptimizationError("cached metrics do not contain the ranking fields") from exc


@dataclass(frozen=True)
class AnchorContext:
    label: str
    contract: str
    directory: Path
    reference_path: Path
    baseline_path: Path
    reference: Mapping[str, Any]
    baseline: Mapping[str, Any]
    trusted_set: Mapping[str, Any]
    trusted_keys: Sequence[Tuple[str, int, str]]
    reference_identity: Mapping[str, Any]
    baseline_identity: Mapping[str, Any]


@dataclass(frozen=True)
class Settings:
    config_path: Path
    config_sha256: str
    probe: Path
    inputs: Sequence[Path]
    weights: Optional[Path]
    candidate_nodes: int
    baseline_margins: Margins
    score_scale: float
    probe_report_every: int
    search: discrete_optimizer.SearchConfig
    seeds: Sequence[Margins]
    validation_top: int
    development: AnchorContext
    validation: Optional[AnchorContext]


def load_anchor(
    config_path: Path,
    label: str,
    raw: Mapping[str, Any],
    candidate_nodes: int,
    baseline_margins: Margins,
) -> AnchorContext:
    allowed = {"reference_dir", "contract", "trusted_depth_gap"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise OptimizationError(f"{label}: unknown field(s): {', '.join(unknown)}")
    directory = resolve_path(config_path, require_string(raw.get("reference_dir"), f"{label}.reference_dir"))
    contract = require_string(raw.get("contract"), f"{label}.contract")
    if contract not in CONTRACTS:
        raise OptimizationError(f"{label}.contract must be one of: {', '.join(CONTRACTS)}")
    reference_path = directory / "probes" / "reference.jsonl"
    baseline_path = directory / "probes" / "baseline.jsonl"
    reference_summary = raw_summary(reference_path)
    reference_nodes = require_int(reference_summary.get("node_limit"), f"{label} reference node_limit", 1)
    if reference_summary.get("futility_margins") != list(baseline_margins):
        raise OptimizationError(f"{label}: reference margins do not match baseline_margins")

    if contract == "per_root_v1":
        if reference_summary.get("reference_mode") != tune_futility.REFERENCE_MODE:
            raise OptimizationError(f"{label}: reference does not use the per-root contract")
        depth_gap = require_int(reference_summary.get("reference_depth_gap"), f"{label} reference_depth_gap", 1)
        reference = tune_futility.parse_probe_output(
            reference_path,
            reference_nodes,
            baseline_margins,
            all_root_scores=True,
            per_root_reference=True,
            baseline_nodes=candidate_nodes,
            reference_depth_gap=depth_gap,
        )
    else:
        if reference_summary.get("reference_mode") is not None:
            raise OptimizationError(f"{label}: reference is not a shared-budget artifact")
        depth_gap = require_int(raw.get("trusted_depth_gap", 1), f"{label}.trusted_depth_gap", 1)
        reference = tune_futility.parse_probe_output(
            reference_path, reference_nodes, baseline_margins, all_root_scores=True
        )
    baseline = tune_futility.parse_probe_output(baseline_path, candidate_nodes, baseline_margins)
    trusted_set, trusted_keys = tune_futility.trusted_position_set(reference, baseline, depth_gap)
    return AnchorContext(
        label,
        contract,
        directory,
        reference_path,
        baseline_path,
        reference,
        baseline,
        trusted_set,
        trusted_keys,
        tune_futility.file_identity(reference_path),
        tune_futility.file_identity(baseline_path),
    )


def load_settings(config_path: Path, require_validation: bool) -> Settings:
    try:
        raw_bytes = config_path.read_bytes()
    except OSError as exc:
        raise OptimizationError(f"failed to read optimizer config {config_path}: {exc}") from exc
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise OptimizationError(f"invalid optimizer config {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise OptimizationError("optimizer config root must be an object")
    allowed = {
        "probe", "inputs", "weights", "candidate_nodes", "baseline_margins", "score_scale",
        "probe_report_every", "optimizer", "development", "validation",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise OptimizationError(f"unknown optimizer config field(s): {', '.join(unknown)}")
    probe = resolve_path(config_path, require_string(raw.get("probe"), "probe"))
    if not probe.is_file():
        raise OptimizationError(f"probe does not exist: {probe}")
    inputs_raw = raw.get("inputs")
    if not isinstance(inputs_raw, list) or not inputs_raw:
        raise OptimizationError("inputs must be a non-empty list")
    inputs = [resolve_path(config_path, require_string(value, "inputs item")) for value in inputs_raw]
    if any(not path.is_file() for path in inputs):
        raise OptimizationError("every input must exist")
    weights_value = raw.get("weights")
    weights = resolve_path(config_path, require_string(weights_value, "weights")) if weights_value is not None else None
    if weights is not None and not weights.is_file():
        raise OptimizationError(f"weights does not exist: {weights}")
    candidate_nodes = require_int(raw.get("candidate_nodes"), "candidate_nodes", 1)
    baseline_margins = tune_futility.validate_margins(raw.get("baseline_margins"), "baseline_margins")
    score_scale_raw = raw.get("score_scale", 600)
    if (
        isinstance(score_scale_raw, bool)
        or not isinstance(score_scale_raw, (int, float))
        or not math.isfinite(score_scale_raw)
        or score_scale_raw <= 0
    ):
        raise OptimizationError("score_scale must be a finite number > 0")
    score_scale = float(score_scale_raw)
    probe_report_every = require_int(raw.get("probe_report_every", 1000), "probe_report_every")

    optimizer = raw.get("optimizer")
    if not isinstance(optimizer, dict):
        raise OptimizationError("optimizer must be an object")
    allowed_optimizer = {
        "depths", "seeds", "steps", "max_margin", "max_new_evaluations", "validation_top",
    }
    unknown_optimizer = sorted(set(optimizer) - allowed_optimizer)
    if unknown_optimizer:
        raise OptimizationError(f"unknown optimizer field(s): {', '.join(unknown_optimizer)}")
    depths_raw = optimizer.get("depths")
    if not isinstance(depths_raw, list):
        raise OptimizationError("optimizer.depths must be a list")
    depths = tuple(require_int(value, "optimizer.depths item", 1) for value in depths_raw)
    if any(depth > tune_futility.MAX_FUTILITY_DEPTH for depth in depths):
        raise OptimizationError(f"optimizer.depths cannot exceed {tune_futility.MAX_FUTILITY_DEPTH}")
    seeds_raw = optimizer.get("seeds")
    if not isinstance(seeds_raw, list):
        raise OptimizationError("optimizer.seeds must be a list")
    seeds = tuple(tune_futility.validate_margins(value, "optimizer.seeds item") for value in seeds_raw)
    steps_raw = optimizer.get("steps", [80, 40, 20, 10])
    if not isinstance(steps_raw, list):
        raise OptimizationError("optimizer.steps must be a list")
    steps = tuple(require_int(value, "optimizer.steps item", 1) for value in steps_raw)
    search = discrete_optimizer.SearchConfig(
        depths=depths,
        steps=steps,
        max_margin=require_int(optimizer.get("max_margin", 2000), "optimizer.max_margin"),
        max_new_evaluations=require_int(
            optimizer.get("max_new_evaluations", 80), "optimizer.max_new_evaluations"
        ),
    )
    # Validate all generic constraints before any run directory is touched.
    discrete_optimizer.validate_search_config(search, seeds)
    validation_top = require_int(optimizer.get("validation_top", 5), "optimizer.validation_top", 1)

    development_raw = raw.get("development")
    if not isinstance(development_raw, dict):
        raise OptimizationError("development must be an object")
    development = load_anchor(config_path, "development", development_raw, candidate_nodes, baseline_margins)
    validation_raw = raw.get("validation")
    if require_validation and not isinstance(validation_raw, dict):
        raise OptimizationError("validation must be an object for the validate phase")
    validation = (
        load_anchor(config_path, "validation", validation_raw, candidate_nodes, baseline_margins)
        if isinstance(validation_raw, dict)
        else None
    )
    return Settings(
        config_path,
        hashlib.sha256(raw_bytes).hexdigest(),
        probe,
        inputs,
        weights,
        candidate_nodes,
        baseline_margins,
        score_scale,
        probe_report_every,
        search,
        seeds,
        validation_top,
        development,
        validation,
    )


def settings_manifest(settings: Settings) -> Dict[str, Any]:
    def anchor_identity(context: AnchorContext) -> Dict[str, Any]:
        return {
            "contract": context.contract,
            "directory": str(context.directory),
            "reference": context.reference_identity,
            "baseline": context.baseline_identity,
            "trusted_set": dict(context.trusted_set),
        }

    return {
        "schema": SCHEMA,
        "config": {"path": str(settings.config_path), "sha256": settings.config_sha256},
        "probe": tune_futility.file_identity(settings.probe),
        "inputs": [tune_futility.file_identity(path) for path in settings.inputs],
        "weights": tune_futility.file_identity(settings.weights) if settings.weights is not None else None,
        "candidate_nodes": settings.candidate_nodes,
        "baseline_margins": list(settings.baseline_margins),
        "score_scale": settings.score_scale,
        "probe_report_every": settings.probe_report_every,
        "optimizer": {
            "depths": list(settings.search.depths), "steps": list(settings.search.steps),
            "max_margin": settings.search.max_margin,
            "max_new_evaluations": settings.search.max_new_evaluations,
            "seeds": [list(seed) for seed in settings.seeds],
            "validation_top": settings.validation_top,
        },
        "development": anchor_identity(settings.development),
        "validation": anchor_identity(settings.validation) if settings.validation is not None else None,
    }


def prepare_run_directory(run_dir: Path, manifest: Mapping[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "optimizer_manifest.json"
    if path.exists():
        existing = read_json(path, "optimizer manifest")
        if existing != manifest:
            raise OptimizationError("optimizer manifest does not match the configured artifacts or anchors; use a new run directory")
    else:
        atomic_write_json(path, manifest)
    for phase in ("development", "validation"):
        (run_dir / phase / "probes").mkdir(parents=True, exist_ok=True)
        (run_dir / phase / "logs").mkdir(parents=True, exist_ok=True)


def load_state(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    raw = read_json(path, "optimizer state")
    if raw.get("schema") != STATE_SCHEMA or not isinstance(raw.get("entries"), dict):
        raise OptimizationError(f"invalid optimizer state {path}")
    return raw["entries"]


def save_state(path: Path, entries: Mapping[str, Mapping[str, Any]]) -> None:
    atomic_write_json(path, {"schema": STATE_SCHEMA, "entries": entries})


def candidate_path(phase_dir: Path, margins: Margins) -> Path:
    return phase_dir / "probes" / f"candidate-{tune_futility.candidate_key(margins)}.jsonl"


def score_candidate(context: AnchorContext, candidate: Mapping[str, Any], settings: Settings) -> Dict[str, Any]:
    return tune_futility.compute_metrics(
        context.reference,
        context.baseline,
        candidate,
        settings.candidate_nodes,
        settings.score_scale,
        context.trusted_keys,
    )


def parse_candidate(path: Path, margins: Margins, settings: Settings) -> Mapping[str, Any]:
    return tune_futility.parse_probe_output(path, settings.candidate_nodes, margins)


def write_probe(
    phase_dir: Path, margins: Margins, settings: Settings,
) -> Mapping[str, Any]:
    output = candidate_path(phase_dir, margins)
    if output.is_file():
        try:
            return parse_candidate(output, margins, settings)
        except tune_futility.TuningError:
            pass
    command = tune_futility.build_probe_command(
        settings.probe,
        settings.inputs,
        settings.weights,
        settings.candidate_nodes,
        margins,
        output,
        settings.probe_report_every,
    )
    log_path = phase_dir / "logs" / f"candidate-{tune_futility.candidate_key(margins)}.log"
    with log_path.open("w", encoding="utf-8") as log:
        log.write("command=" + json.dumps(command) + "\n")
        log.flush()
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, text=True, check=False)
        log.write(f"exit_code={completed.returncode}\n")
    if completed.returncode != 0:
        raise OptimizationError(f"candidate probe failed for {margins}; see {log_path}")
    return parse_candidate(output, margins, settings)


def cache_entry(
    context: AnchorContext,
    phase_dir: Path,
    margins: Margins,
    settings: Settings,
    new_probe: bool,
) -> Dict[str, Any]:
    if margins == settings.baseline_margins:
        candidate = context.baseline
        output: Any = {"kind": "anchor_baseline", "path": str(context.baseline_path)}
        new_probe = False
    else:
        candidate = write_probe(phase_dir, margins, settings)
        output = tune_futility.file_identity(candidate_path(phase_dir, margins))
    metrics = score_candidate(context, candidate, settings)
    return {
        "margins": list(margins),
        "metrics": metrics,
        "output": output,
        "new_probe": new_probe,
    }


def verify_cached_entry(entry: Mapping[str, Any], context: AnchorContext, margins: Margins) -> None:
    output = entry.get("output")
    if margins == tuple(context.baseline["summary"]["futility_margins"]):
        if not isinstance(output, dict) or output.get("kind") != "anchor_baseline":
            raise OptimizationError("cached baseline entry is invalid")
        if output.get("path") != str(context.baseline_path):
            raise OptimizationError("cached baseline path does not match the anchor")
        return
    if not isinstance(output, dict) or "path" not in output or "sha256" not in output:
        raise OptimizationError("cached candidate output identity is invalid")
    path = Path(output["path"])
    if tune_futility.file_identity(path) != output:
        raise OptimizationError(f"cached candidate output changed: {path}")


def report_rows(entries: Mapping[str, Mapping[str, Any]], baseline: Margins) -> List[Dict[str, Any]]:
    rows = []
    for key, entry in entries.items():
        margins = margins_from_key(key)
        metrics = entry["metrics"]
        rows.append({"margins": margins, "metrics": metrics, "new_probe": bool(entry.get("new_probe")), "baseline": margins == baseline})
    return sorted(rows, key=lambda row: metric_objective(row["metrics"], row["margins"]))


def write_report(path: Path, title: str, rows: Sequence[Mapping[str, Any]], stopped: Optional[bool] = None) -> None:
    lines = [f"# {title}", "", "| Rank | Margins | Mean regret | P90 regret | Median regret | New probe |", "|---:|---|---:|---:|---:|---|"]
    for index, row in enumerate(rows, start=1):
        metrics = row["metrics"]
        marker = "baseline" if row["baseline"] else ("yes" if row["new_probe"] else "reused")
        lines.append(
            f"| {index} | `{margins_key(row['margins'])}` | {metrics['mean_normalized_regret']:.6f} | "
            f"{metrics['p90_normalized_regret']:.6f} | {metrics['median_normalized_regret']:.6f} | {marker} |"
        )
    if stopped is not None:
        lines.extend(["", f"Stopped by new-probe budget: `{str(stopped).lower()}`."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_optimize(settings: Settings, run_dir: Path) -> Dict[str, Any]:
    phase_dir = run_dir / "development"
    state_path = phase_dir / "state.json"
    entries = load_state(state_path)
    verified_entries: set[str] = set()

    def lookup(margins: Margins) -> Optional[discrete_optimizer.Objective]:
        key = margins_key(margins)
        entry = entries.get(key)
        if entry is not None:
            if key not in verified_entries:
                verify_cached_entry(entry, settings.development, margins)
                verified_entries.add(key)
            return metric_objective(entry["metrics"], margins)
        output = candidate_path(phase_dir, margins)
        if margins == settings.baseline_margins or output.is_file():
            entry = cache_entry(settings.development, phase_dir, margins, settings, new_probe=margins != settings.baseline_margins)
            entries[key] = entry
            save_state(state_path, entries)
            return metric_objective(entry["metrics"], margins)
        return None

    def evaluate(margins: Margins) -> discrete_optimizer.Objective:
        entry = cache_entry(settings.development, phase_dir, margins, settings, new_probe=True)
        entries[margins_key(margins)] = entry
        save_state(state_path, entries)
        return metric_objective(entry["metrics"], margins)

    initial_new = sum(bool(entry.get("new_probe")) for entry in entries.values())
    result = discrete_optimizer.optimize(settings.search, settings.seeds, lookup, evaluate, initial_new)
    rows = report_rows(entries, settings.baseline_margins)
    output = {
        "schema": SCHEMA,
        "new_evaluations": result.new_evaluations,
        "stopped_by_budget": result.stopped_by_budget,
        "ranked": [
            {"rank": index, "margins": list(row["margins"]), "metrics": row["metrics"], "new_probe": row["new_probe"], "baseline": row["baseline"]}
            for index, row in enumerate(rows, start=1)
        ],
    }
    atomic_write_json(phase_dir / "results.json", output)
    write_report(phase_dir / "report.md", "Futility optimizer development results", rows, result.stopped_by_budget)
    return output


def select_promoted(
    development: Mapping[str, Any], baseline: Margins, count: int
) -> List[Margins]:
    if development.get("schema") != SCHEMA or not isinstance(development.get("ranked"), list):
        raise OptimizationError("missing valid development results; run --phase optimize first")
    promoted: List[Margins] = []
    for item in development["ranked"]:
        if not isinstance(item, dict):
            raise OptimizationError("invalid development ranking entry")
        margins = tune_futility.validate_margins(item.get("margins"), "development result margins")
        if margins != baseline:
            promoted.append(margins)
        if len(promoted) == count:
            return promoted
    raise OptimizationError("development results do not contain enough non-baseline candidates to validate")


def run_validate(settings: Settings, run_dir: Path) -> Dict[str, Any]:
    if settings.validation is None:
        raise OptimizationError("validation anchor is required")
    development = read_json(run_dir / "development" / "results.json", "development results")
    promoted = select_promoted(development, settings.baseline_margins, settings.validation_top)

    phase_dir = run_dir / "validation"
    state_path = phase_dir / "state.json"
    entries = load_state(state_path)
    for margins in (settings.baseline_margins, *promoted):
        key = margins_key(margins)
        if key in entries:
            verify_cached_entry(entries[key], settings.validation, margins)
        else:
            entries[key] = cache_entry(
                settings.validation, phase_dir, margins, settings, new_probe=margins != settings.baseline_margins
            )
            save_state(state_path, entries)
    selected_entries = {
        margins_key(margins): entries[margins_key(margins)]
        for margins in (settings.baseline_margins, *promoted)
    }
    rows = report_rows(selected_entries, settings.baseline_margins)
    output = {
        "schema": SCHEMA,
        "promoted_from_development": [list(margins) for margins in promoted],
        "ranked": [
            {"rank": index, "margins": list(row["margins"]), "metrics": row["metrics"], "new_probe": row["new_probe"], "baseline": row["baseline"]}
            for index, row in enumerate(rows, start=1)
        ],
    }
    atomic_write_json(phase_dir / "results.json", output)
    write_report(phase_dir / "report.md", "Futility optimizer validation results", rows)
    return output


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize futility margins using an existing reference anchor.")
    parser.add_argument("--config", required=True, help="Optimizer JSON configuration")
    parser.add_argument("--run-dir", required=True, help="Directory for optimizer cache and candidate outputs")
    parser.add_argument("--phase", choices=("optimize", "validate", "all"), default="optimize")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print resolved settings without probing")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        config_path = Path(args.config).resolve()
        settings = load_settings(config_path, args.phase in ("validate", "all"))
        manifest = settings_manifest(settings)
        if args.dry_run:
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0
        run_dir = Path(args.run_dir).resolve()
        prepare_run_directory(run_dir, manifest)
        if args.phase in ("optimize", "all"):
            results = run_optimize(settings, run_dir)
            print(f"development candidates={len(results['ranked'])} new_probes={results['new_evaluations']} budget_stop={results['stopped_by_budget']}")
        if args.phase in ("validate", "all"):
            results = run_validate(settings, run_dir)
            print(f"validation candidates={len(results['ranked'])}")
        return 0
    except (OptimizationError, discrete_optimizer.OptimizationError, tune_futility.TuningError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"fatal: filesystem or process error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("fatal: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
