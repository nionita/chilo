#!/usr/bin/env python3
"""Calibrate relative futility-risk tracks from retained, completed evidence.

This tool is read-only: it validates the historical v1/v2 attempt artifacts,
then reports paired mean/squared/CVaR deltas and explicitly mapped full
development/selection endpoints.  It deliberately does not produce a runnable
optimizer configuration or recommend numeric thresholds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import futility_risk
import optimize_futility
import tune_futility


SCHEMA = "chilo.futility_gated_calibration.v1"
SUPPORTED_MANIFESTS = {
    "chilo.futility_gated_hillclimb.v1",
    "chilo.futility_gated_hillclimb.v2",
}
SUPPORTED_STATES = {
    "chilo.futility_gated_hillclimb_state.v1",
    "chilo.futility_gated_hillclimb_state.v2",
}
QUANTILES = (0.05, 0.10, 0.50, 0.90, 0.95)


def atomic_write(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def identity_matches(actual: Mapping[str, Any], recorded: Mapping[str, Any], label: str) -> None:
    for field in ("sha256", "size"):
        if recorded.get(field) != actual.get(field):
            raise optimize_futility.OptimizationError(
                f"{label} {field} does not match retained state identity"
            )


def quantile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise optimize_futility.OptimizationError("cannot summarize an empty calibration population")
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = int(math.floor(index))
    high = int(math.ceil(index))
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def summarize(values: Sequence[float]) -> Dict[str, Any]:
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": statistics.mean(values),
        "quantiles": {f"p{int(value * 100):02d}": quantile(values, value) for value in QUANTILES},
    }


def value_at(item: Mapping[str, Any], path: Sequence[str], label: str) -> float:
    current: Any = item
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise optimize_futility.OptimizationError(f"{label} lacks {'.'.join(path)}")
        current = current[key]
    if isinstance(current, bool) or not isinstance(current, (int, float)) or not math.isfinite(current):
        raise optimize_futility.OptimizationError(f"{label} {'.'.join(path)} must be finite")
    return float(current)


def read_historical_run(config_path: Path, item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict) or set(item) != {"id", "run_dir", "anchor"}:
        raise optimize_futility.OptimizationError("each attempt_runs item must contain only id, run_dir, and anchor")
    identifier = optimize_futility.require_string(item.get("id"), "attempt_runs.id")
    run_dir = optimize_futility.resolve_path(config_path, optimize_futility.require_string(item.get("run_dir"), "attempt_runs.run_dir"))
    manifest_path, state_path = run_dir / "optimizer_manifest.json", run_dir / "state.json"
    manifest = optimize_futility.read_json(manifest_path, f"attempt run {identifier} manifest")
    state = optimize_futility.read_json(state_path, f"attempt run {identifier} state")
    if manifest.get("schema") not in SUPPORTED_MANIFESTS or state.get("schema") not in SUPPORTED_STATES:
        raise optimize_futility.OptimizationError(f"attempt run {identifier} must use a retained v1 or v2 gated state and manifest")
    if not isinstance(manifest.get("candidate_nodes"), int) or manifest["candidate_nodes"] <= 0:
        raise optimize_futility.OptimizationError(f"attempt run {identifier} manifest has invalid candidate_nodes")
    baseline_margins = tune_futility.validate_margins(manifest.get("baseline_margins"), f"attempt run {identifier} baseline_margins")
    anchor_raw = item.get("anchor")
    if not isinstance(anchor_raw, dict):
        raise optimize_futility.OptimizationError(f"attempt run {identifier}.anchor must be an object")
    anchor = optimize_futility.load_anchor(
        config_path, f"attempt run {identifier}.anchor", anchor_raw, manifest["candidate_nodes"], baseline_margins
    )
    tracks = state.get("tracks")
    if not isinstance(tracks, dict) or not tracks:
        raise optimize_futility.OptimizationError(f"attempt run {identifier} state has no tracks")
    all_attempts: List[Dict[str, Any]] = []
    for track, track_state in sorted(tracks.items()):
        if not isinstance(track_state, Mapping) or not isinstance(track_state.get("completed_attempts"), list):
            raise optimize_futility.OptimizationError(f"attempt run {identifier} track {track} has invalid history")
        for attempt in track_state["completed_attempts"]:
            if not isinstance(attempt, Mapping) or not isinstance(attempt.get("attempt"), int):
                raise optimize_futility.OptimizationError(f"attempt run {identifier} track {track} has invalid attempt")
            rows: Dict[str, Mapping[str, Any]] = {}
            for role in ("current", "proposal"):
                role_item = attempt.get(role)
                if not isinstance(role_item, Mapping):
                    raise optimize_futility.OptimizationError(f"attempt run {identifier} track {track} attempt lacks {role}")
                recorded = role_item.get("output")
                margins = attempt.get(f"{role}_margins")
                if not isinstance(recorded, Mapping):
                    raise optimize_futility.OptimizationError(f"attempt run {identifier} track {track} {role} lacks output identity")
                margins_tuple = tune_futility.validate_margins(margins, f"attempt run {identifier} {track} {role} margins")
                output = run_dir / "tracks" / str(track) / "probes" / f"attempt-{attempt['attempt']:04d}-{role}.jsonl"
                if not output.is_file():
                    raise optimize_futility.OptimizationError(f"attempt run {identifier} missing retained probe: {output}")
                identity_matches(tune_futility.file_identity(output), recorded, f"attempt run {identifier} {track} {role}")
                rows[role] = tune_futility.parse_probe_output(output, manifest["candidate_nodes"], margins_tuple)
            current, proposal = attempt["current"], attempt["proposal"]
            tune_futility.ensure_position_sets(rows["current"], rows["proposal"], f"attempt run {identifier} {track} paired probe")
            keys = sorted(rows["current"]["positions"])
            if not set(keys).issubset(set(anchor.trusted_keys)):
                raise optimize_futility.OptimizationError(f"attempt run {identifier} {track} probe contains a key outside its configured anchor")
            subset_reference = {
                "positions": {key: anchor.reference["positions"][key] for key in keys},
                "summary": anchor.reference["summary"],
            }
            subset_baseline = {
                "positions": {key: anchor.baseline["positions"][key] for key in keys},
                "summary": anchor.baseline["summary"],
            }
            current_metrics = tune_futility.compute_metrics(
                subset_reference, subset_baseline, rows["current"], manifest["candidate_nodes"], float(manifest.get("score_scale", 600)), keys
            )
            proposal_metrics = tune_futility.compute_metrics(
                subset_reference, subset_baseline, rows["proposal"], manifest["candidate_nodes"], float(manifest.get("score_scale", 600)), keys
            )
            current_risk = futility_risk.compute_risk_metrics(subset_reference, rows["current"], keys, float(manifest.get("score_scale", 600)), [0.01], [], 150, -150)
            proposal_risk = futility_risk.compute_risk_metrics(subset_reference, rows["proposal"], keys, float(manifest.get("score_scale", 600)), [0.01], [], 150, -150)
            deltas = {
                "mean_normalized_regret": value_at(proposal_metrics, ("mean_normalized_regret",), "proposal metrics") - value_at(current_metrics, ("mean_normalized_regret",), "current metrics"),
                "mean_squared_regret": value_at(proposal_risk, ("absolute_regret", "mean_squared"), "proposal risk") - value_at(current_risk, ("absolute_regret", "mean_squared"), "current risk"),
                "cvar1_regret": value_at(proposal_risk, ("absolute_regret", "tail_mean", "top_0.01"), "proposal risk") - value_at(current_risk, ("absolute_regret", "tail_mean", "top_0.01"), "current risk"),
            }
            all_attempts.append({
                "run": identifier, "track": track, "attempt": attempt["attempt"],
                "decision": attempt.get("decision"), "accepted": bool(attempt.get("accepted")),
                "subset_position_count": attempt.get("subset_position_count"),
                "current_margins": list(tune_futility.validate_margins(attempt.get("current_margins"), "current margins")),
                "proposal_margins": list(tune_futility.validate_margins(attempt.get("proposal_margins"), "proposal margins")),
                "deltas": deltas,
            })
    return {
        "id": identifier,
        "run_dir": str(run_dir),
        "manifest": tune_futility.file_identity(manifest_path),
        "state": tune_futility.file_identity(state_path),
        "manifest_schema": manifest["schema"],
        "state_schema": state["schema"],
        "anchor": {"reference": anchor.reference_identity, "baseline": anchor.baseline_identity, "trusted_set": anchor.trusted_set, "rescue": dict(anchor.rescue) if anchor.rescue else None},
        "track_final_margins": {
            str(track): list(tune_futility.validate_margins(value.get("current_margins"), f"attempt run {identifier} {track} final margins"))
            for track, value in tracks.items()
            if isinstance(value, Mapping) and value.get("current_margins") is not None
        },
        "attempts": all_attempts,
    }


def read_full_evaluation(config_path: Path, item: Any) -> Dict[str, Any]:
    allowed = {"id", "attempt_run", "track", "margins", "populations"}
    if not isinstance(item, dict) or set(item) != allowed:
        raise optimize_futility.OptimizationError("each full_evaluations item must contain id, attempt_run, track, margins, and populations")
    identifier = optimize_futility.require_string(item.get("id"), "full_evaluations.id")
    margins = tune_futility.validate_margins(item.get("margins"), f"full evaluation {identifier} margins")
    populations = item.get("populations")
    if not isinstance(populations, list) or not populations:
        raise optimize_futility.OptimizationError(f"full evaluation {identifier}.populations must be non-empty")
    output_rows = []
    seen = set()
    for population in populations:
        allowed_population = {"id", "candidate_nodes", "baseline_margins", "score_scale", "anchor", "output"}
        if not isinstance(population, dict) or set(population) != allowed_population:
            raise optimize_futility.OptimizationError("each full-evaluation population must contain id, candidate_nodes, baseline_margins, score_scale, anchor, and output")
        population_id = optimize_futility.require_string(population.get("id"), "full-evaluation population id")
        if population_id in seen:
            raise optimize_futility.OptimizationError(f"duplicate full-evaluation population id {population_id}")
        seen.add(population_id)
        nodes = optimize_futility.require_int(population.get("candidate_nodes"), f"{population_id}.candidate_nodes", 1)
        baseline = tune_futility.validate_margins(population.get("baseline_margins"), f"{population_id}.baseline_margins")
        scale = value_at({"score_scale": population.get("score_scale")}, ("score_scale",), f"{population_id} score_scale")
        anchor_raw = population.get("anchor")
        if not isinstance(anchor_raw, dict):
            raise optimize_futility.OptimizationError(f"{population_id}.anchor must be an object")
        anchor = optimize_futility.load_anchor(config_path, f"full evaluation {identifier} {population_id}.anchor", anchor_raw, nodes, baseline)
        output = optimize_futility.resolve_path(config_path, optimize_futility.require_string(population.get("output"), f"{population_id}.output"))
        candidate = tune_futility.parse_probe_output(output, nodes, margins)
        tune_futility.ensure_position_sets(anchor.reference, candidate, f"full evaluation {identifier} {population_id}")
        mean_metrics = tune_futility.compute_metrics(anchor.reference, anchor.baseline, candidate, nodes, scale, anchor.trusted_keys)
        risk = futility_risk.compute_risk_metrics(anchor.reference, candidate, anchor.trusted_keys, scale, [0.01], [], 150, -150)
        output_rows.append({
            "id": population_id, "output": tune_futility.file_identity(output),
            "anchor": {"reference": anchor.reference_identity, "baseline": anchor.baseline_identity, "trusted_set": anchor.trusted_set, "rescue": dict(anchor.rescue) if anchor.rescue else None},
            "metrics": mean_metrics, "risk": risk,
        })
    return {"id": identifier, "attempt_run": item["attempt_run"], "track": item["track"], "margins": list(margins), "populations": output_rows}


def run(config_path: Path, output_dir: Path) -> Dict[str, Any]:
    raw = optimize_futility.read_json(config_path, "gated calibration config")
    if not isinstance(raw, dict) or set(raw) != {"attempt_runs", "full_evaluations"}:
        raise optimize_futility.OptimizationError("gated calibration config must contain only attempt_runs and full_evaluations")
    attempt_runs_raw = raw.get("attempt_runs")
    if not isinstance(attempt_runs_raw, list) or not attempt_runs_raw:
        raise optimize_futility.OptimizationError("attempt_runs must be a non-empty list")
    runs = [read_historical_run(config_path, item) for item in attempt_runs_raw]
    run_ids = [item["id"] for item in runs]
    if len(set(run_ids)) != len(run_ids):
        raise optimize_futility.OptimizationError("attempt_runs ids must be unique")
    attempts = [attempt for run_item in runs for attempt in run_item["attempts"]]
    if not attempts:
        raise optimize_futility.OptimizationError("attempt_runs contain no completed attempts")
    full_raw = raw.get("full_evaluations")
    if not isinstance(full_raw, list) or not full_raw:
        raise optimize_futility.OptimizationError("full_evaluations must be a non-empty list")
    full_evaluations = [read_full_evaluation(config_path, item) for item in full_raw]
    runs_by_id = {item["id"]: item for item in runs}
    for endpoint in full_evaluations:
        if endpoint["attempt_run"] not in run_ids:
            raise optimize_futility.OptimizationError(f"full evaluation {endpoint['id']} references unknown attempt_run")
        final_margins = runs_by_id[endpoint["attempt_run"]]["track_final_margins"].get(str(endpoint["track"]))
        if final_margins is None:
            raise optimize_futility.OptimizationError(f"full evaluation {endpoint['id']} references an unknown historical track")
        if final_margins != endpoint["margins"]:
            raise optimize_futility.OptimizationError(f"full evaluation {endpoint['id']} margins do not match its historical track final tuple")
    columns = ("mean_normalized_regret", "mean_squared_regret", "cvar1_regret")
    summaries = {column: summarize([item["deltas"][column] for item in attempts]) for column in columns}
    by_decision = {}
    for decision in sorted({str(item["decision"]) for item in attempts}):
        rows = [item for item in attempts if str(item["decision"]) == decision]
        by_decision[decision] = {column: summarize([item["deltas"][column] for item in rows]) for column in columns}
    result = {
        "schema": SCHEMA,
        "config": tune_futility.file_identity(config_path),
        "attempt_runs": [{key: value for key, value in item.items() if key != "attempts"} for item in runs],
        "attempts": attempts,
        "paired_delta_summary": summaries,
        "paired_delta_summary_by_decision": by_decision,
        "full_evaluations": full_evaluations,
        "note": "Read-only calibration evidence. It reports empirical paired deltas but does not recommend or generate v3 thresholds.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(output_dir / "calibration.json", result)
    lines = ["# Gated futility relative-risk calibration", "", "Read-only report from retained v1/v2 paired probes and explicitly mapped full endpoints. It does not recommend thresholds or prepare a run.", "", "## Paired attempt deltas", "", "Positive deltas are worse. A v3 safety improvement is a negative squared/CVaR delta; mean regression is positive.", "", "| Metric | Count | Mean | P05 | P10 | P50 | P90 | P95 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for column in columns:
        summary = summaries[column]
        q = summary["quantiles"]
        lines.append(f"| {column} | {summary['count']} | {summary['mean']:.8f} | {q['p05']:.8f} | {q['p10']:.8f} | {q['p50']:.8f} | {q['p90']:.8f} | {q['p95']:.8f} |")
    lines.extend(["", "## Explicitly mapped full endpoints", "", "| Endpoint | Source run / track | Margins | Population | Mean regret | Squared regret | CVaR-1% |", "|---|---|---|---|---:|---:|---:|"])
    for endpoint in full_evaluations:
        for population in endpoint["populations"]:
            risk = population["risk"]["absolute_regret"]
            lines.append(f"| {endpoint['id']} | {endpoint['attempt_run']} / {endpoint['track']} | `{','.join(str(value) for value in endpoint['margins'])}` | {population['id']} | {population['metrics']['mean_normalized_regret']:.6f} | {risk['mean_squared']:.6f} | {risk['tail_mean']['top_0.01']:.6f} |")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read retained v1/v2 gated futility attempts and full endpoints for v3 calibration.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(Path(args.config).resolve(), Path(args.output_dir).resolve())
        print(f"gated calibration attempts={len(result['attempts'])} endpoints={len(result['full_evaluations'])}")
        return 0
    except (json.JSONDecodeError, OSError, optimize_futility.OptimizationError, tune_futility.TuningError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
