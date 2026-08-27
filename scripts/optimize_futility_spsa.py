#!/usr/bin/env python3
"""SPSA futility-margin search against one existing per-root anchor.

Each SPSA plus/minus pair is measured on the same deterministic trusted-set
subset (common random numbers).  The next iteration receives a new subset.
The runner is deliberately development-only: it writes candidate evidence and
final projected tuples, then leaves full-corpus/selection decisions to review.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import optimize_futility
import spsa_optimizer
import tune_futility


SCHEMA = "chilo.futility_spsa.v1"
STATE_SCHEMA = "chilo.futility_spsa_state.v1"
Margins = Tuple[int, ...]
Key = Tuple[str, int, str]


@dataclass(frozen=True)
class Settings:
    config_path: Path
    config_sha256: str
    probe: Path
    inputs: Tuple[Path, ...]
    weights: Optional[Path]
    candidate_nodes: int
    baseline_margins: Margins
    score_scale: float
    probe_report_every: int
    anchor: optimize_futility.AnchorContext
    tracks: Tuple[Tuple[str, Margins], ...]
    iterations: int
    workers: int
    subset_fraction: float
    seed: int
    schedule: spsa_optimizer.Schedule


def atomic_write(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def require_number(value: Any, name: str, minimum: float, inclusive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise optimize_futility.OptimizationError(f"{name} must be a finite number")
    numeric = float(value)
    if numeric < minimum or (not inclusive and numeric <= minimum):
        relation = ">=" if inclusive else ">"
        raise optimize_futility.OptimizationError(f"{name} must be {relation} {minimum}")
    return numeric


def load_settings(config_path: Path) -> Settings:
    raw_bytes = config_path.read_bytes()
    raw = json.loads(raw_bytes)
    if not isinstance(raw, dict):
        raise optimize_futility.OptimizationError("SPSA config root must be an object")
    allowed = {"probe", "inputs", "weights", "candidate_nodes", "baseline_margins", "score_scale", "probe_report_every", "development", "spsa"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise optimize_futility.OptimizationError(f"unknown SPSA config field(s): {', '.join(unknown)}")
    probe = optimize_futility.resolve_path(config_path, optimize_futility.require_string(raw.get("probe"), "probe"))
    if not probe.is_file():
        raise optimize_futility.OptimizationError(f"probe does not exist: {probe}")
    inputs_raw = raw.get("inputs")
    if not isinstance(inputs_raw, list) or not inputs_raw:
        raise optimize_futility.OptimizationError("inputs must be a non-empty list")
    inputs = tuple(optimize_futility.resolve_path(config_path, optimize_futility.require_string(item, "inputs item")) for item in inputs_raw)
    if any(not path.is_file() for path in inputs):
        raise optimize_futility.OptimizationError("every input must exist")
    weights_raw = raw.get("weights")
    weights = optimize_futility.resolve_path(config_path, optimize_futility.require_string(weights_raw, "weights")) if weights_raw is not None else None
    if weights is not None and not weights.is_file():
        raise optimize_futility.OptimizationError(f"weights does not exist: {weights}")
    nodes = optimize_futility.require_int(raw.get("candidate_nodes"), "candidate_nodes", 1)
    baseline = tune_futility.validate_margins(raw.get("baseline_margins"), "baseline_margins")
    scale = require_number(raw.get("score_scale", 600), "score_scale", 0)
    report_every = optimize_futility.require_int(raw.get("probe_report_every", 1000), "probe_report_every", 0)
    development_raw = raw.get("development")
    if not isinstance(development_raw, dict):
        raise optimize_futility.OptimizationError("development must be an object")
    anchor = optimize_futility.load_anchor(config_path, "development", development_raw, nodes, baseline)
    spsa_raw = raw.get("spsa")
    if not isinstance(spsa_raw, dict):
        raise optimize_futility.OptimizationError("spsa must be an object")
    allowed_spsa = {"tracks", "iterations", "workers", "subset_fraction", "seed", "gain_a", "stability_A", "gain_alpha", "perturbation_c", "perturbation_gamma", "objective_scale", "max_margin"}
    unknown_spsa = sorted(set(spsa_raw) - allowed_spsa)
    if unknown_spsa:
        raise optimize_futility.OptimizationError(f"unknown spsa field(s): {', '.join(unknown_spsa)}")
    tracks_raw = spsa_raw.get("tracks")
    if not isinstance(tracks_raw, list) or not tracks_raw:
        raise optimize_futility.OptimizationError("spsa.tracks must be a non-empty list")
    tracks = []
    identifiers = set()
    for item in tracks_raw:
        if not isinstance(item, dict) or set(item) - {"id", "margins"}:
            raise optimize_futility.OptimizationError("each spsa track must contain only id and margins")
        identifier = optimize_futility.require_string(item.get("id"), "spsa track id")
        if identifier in identifiers:
            raise optimize_futility.OptimizationError(f"duplicate spsa track id {identifier}")
        identifiers.add(identifier)
        margins = tune_futility.validate_margins(item.get("margins"), f"spsa track {identifier} margins")
        if len(margins) > tune_futility.MAX_FUTILITY_DEPTH:
            raise optimize_futility.OptimizationError("spsa track depth exceeds maximum futility depth")
        tracks.append((identifier, margins))
    iterations = optimize_futility.require_int(spsa_raw.get("iterations"), "spsa.iterations", 1)
    workers = optimize_futility.require_int(spsa_raw.get("workers"), "spsa.workers", 1)
    subset_fraction = require_number(spsa_raw.get("subset_fraction"), "spsa.subset_fraction", 0)
    if subset_fraction > 1:
        raise optimize_futility.OptimizationError("spsa.subset_fraction must be <= 1")
    seed = optimize_futility.require_int(spsa_raw.get("seed"), "spsa.seed", 0)
    schedule = spsa_optimizer.Schedule(
        gain_a=require_number(spsa_raw.get("gain_a"), "spsa.gain_a", 0),
        stability_A=require_number(spsa_raw.get("stability_A"), "spsa.stability_A", 0, inclusive=True),
        gain_alpha=require_number(spsa_raw.get("gain_alpha"), "spsa.gain_alpha", 0),
        perturbation_c=require_number(spsa_raw.get("perturbation_c"), "spsa.perturbation_c", 0),
        perturbation_gamma=require_number(spsa_raw.get("perturbation_gamma"), "spsa.perturbation_gamma", 0),
        objective_scale=require_number(spsa_raw.get("objective_scale"), "spsa.objective_scale", 0),
        max_margin=optimize_futility.require_int(spsa_raw.get("max_margin"), "spsa.max_margin", 0),
    )
    spsa_optimizer.validate_schedule(schedule)
    if any(max(margins) > schedule.max_margin for _, margins in tracks):
        raise optimize_futility.OptimizationError("spsa track margins exceed spsa.max_margin")
    return Settings(config_path, hashlib.sha256(raw_bytes).hexdigest(), probe, inputs, weights, nodes, baseline, scale, report_every, anchor, tuple(tracks), iterations, workers, subset_fraction, seed, schedule)


def manifest(settings: Settings) -> Dict[str, Any]:
    return {"schema": SCHEMA, "config": {"path": str(settings.config_path), "sha256": settings.config_sha256}, "probe": tune_futility.file_identity(settings.probe), "inputs": [tune_futility.file_identity(path) for path in settings.inputs], "weights": tune_futility.file_identity(settings.weights) if settings.weights else None, "candidate_nodes": settings.candidate_nodes, "baseline_margins": list(settings.baseline_margins), "score_scale": settings.score_scale, "probe_report_every": settings.probe_report_every, "development": {"contract": settings.anchor.contract, "reference": settings.anchor.reference_identity, "baseline": settings.anchor.baseline_identity, "trusted_set": settings.anchor.trusted_set}, "spsa": {"tracks": [{"id": name, "margins": list(margins)} for name, margins in settings.tracks], "iterations": settings.iterations, "workers": settings.workers, "subset_fraction": settings.subset_fraction, "seed": settings.seed, "schedule": vars(settings.schedule)}}


def prepare(run_dir: Path, value: Mapping[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "optimizer_manifest.json"
    if path.exists():
        if optimize_futility.read_json(path, "SPSA manifest") != value:
            raise optimize_futility.OptimizationError("SPSA manifest does not match configured artifacts or anchor; use a new run directory")
    else:
        atomic_write(path, value)
    for track in value["spsa"]["tracks"]:
        name = track["id"]
        (run_dir / "tracks" / name / "probes").mkdir(parents=True, exist_ok=True)
        (run_dir / "tracks" / name / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "subsets").mkdir(parents=True, exist_ok=True)


def sample_keys(settings: Settings, track: str, iteration: int) -> List[Key]:
    population = list(settings.anchor.trusted_keys)
    count = max(1, int(math.ceil(len(population) * settings.subset_fraction)))
    rng = random.Random(f"{settings.seed}:subset:{track}:{iteration}")
    return sorted(rng.sample(population, count))


def keys_hash(keys: Sequence[Key]) -> str:
    digest = hashlib.sha256()
    for key in keys:
        digest.update(json.dumps(key, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def write_masked_inputs(settings: Settings, run_dir: Path, track: str, iteration: int, keys: Sequence[Key]) -> Tuple[Path, ...]:
    selected = {(source, line) for source, line, _ in keys}
    target_dir = run_dir / "subsets" / f"{track}-{iteration:04d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for input_path in settings.inputs:
        output = target_dir / input_path.name
        expected_source = input_path.name
        lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
        masked = []
        for line_number, line in enumerate(lines, 1):
            masked.append(line if line_number == 1 or (expected_source, line_number) in selected else "\n")
        contents = "".join(masked)
        if not output.exists() or output.read_text(encoding="utf-8") != contents:
            output.write_text(contents, encoding="utf-8")
        outputs.append(output)
    return tuple(outputs)


def subset_context(anchor: optimize_futility.AnchorContext, keys: Sequence[Key]) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
    wanted = set(keys)
    reference = {"positions": {key: value for key, value in anchor.reference["positions"].items() if key in wanted}, "summary": anchor.reference["summary"]}
    baseline = {"positions": {key: value for key, value in anchor.baseline["positions"].items() if key in wanted}, "summary": anchor.baseline["summary"]}
    if len(reference["positions"]) != len(wanted):
        raise optimize_futility.OptimizationError("sampled trusted key absent from anchor")
    return reference, baseline


def probe_one(settings: Settings, run_dir: Path, track: str, iteration: int, side: str, margins: Margins, masked_inputs: Sequence[Path]) -> Mapping[str, Any]:
    root = run_dir / "tracks" / track
    output = root / "probes" / f"iteration-{iteration:04d}-{side}.jsonl"
    log = root / "logs" / f"iteration-{iteration:04d}-{side}.log"
    try:
        if output.is_file():
            return tune_futility.parse_probe_output(output, settings.candidate_nodes, margins)
    except tune_futility.TuningError:
        pass
    command = tune_futility.build_probe_command(settings.probe, masked_inputs, settings.weights, settings.candidate_nodes, margins, output, settings.probe_report_every)
    with log.open("w", encoding="utf-8") as handle:
        handle.write("command=" + json.dumps(command) + "\n")
        handle.flush()
        completed = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, text=True, check=False)
        handle.write(f"exit_code={completed.returncode}\n")
    if completed.returncode:
        raise optimize_futility.OptimizationError(f"SPSA {track} iteration {iteration} {side} probe failed; see {log}")
    return tune_futility.parse_probe_output(output, settings.candidate_nodes, margins)


def load_state(path: Path, settings: Settings) -> Dict[str, Any]:
    if not path.exists():
        return {"schema": STATE_SCHEMA, "tracks": {name: {"theta": list(spsa_optimizer.to_vector(margins)), "completed_iterations": []} for name, margins in settings.tracks}}
    state = optimize_futility.read_json(path, "SPSA state")
    if state.get("schema") != STATE_SCHEMA or not isinstance(state.get("tracks"), dict):
        raise optimize_futility.OptimizationError("invalid SPSA state")
    return state


def run(settings: Settings, run_dir: Path) -> Dict[str, Any]:
    state_path = run_dir / "state.json"
    state = load_state(state_path, settings)
    atomic_write(state_path, state)
    for iteration in range(settings.iterations):
        jobs = []
        for track, _ in settings.tracks:
            record = state["tracks"].get(track)
            if not isinstance(record, dict):
                raise optimize_futility.OptimizationError(f"SPSA state lacks track {track}")
            completed = record.get("completed_iterations")
            if not isinstance(completed, list):
                raise optimize_futility.OptimizationError("invalid SPSA track history")
            if len(completed) > iteration:
                continue
            if len(completed) != iteration:
                raise optimize_futility.OptimizationError("SPSA state has a gap in iteration history")
            theta = tuple(float(value) for value in record.get("theta", []))
            rng = random.Random(f"{settings.seed}:direction:{track}:{iteration}")
            step = spsa_optimizer.make_step(theta, settings.schedule, iteration, rng)
            keys = sample_keys(settings, track, iteration)
            masked = write_masked_inputs(settings, run_dir, track, iteration, keys)
            jobs.append((track, theta, step, keys, masked))
        if not jobs:
            continue
        # All actions are durable before a process starts.  Resume parses a valid
        # output and only reruns a missing/invalid side of the pair.
        atomic_write(state_path, state)
        results: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=settings.workers) as executor:
            futures = {executor.submit(probe_one, settings, run_dir, track, iteration, side, margins, masked): (track, side) for track, _, step, _, masked in jobs for side, margins in (("plus", step.plus), ("minus", step.minus))}
            for future in concurrent.futures.as_completed(futures):
                track, side = futures[future]
                results[(track, side)] = future.result()
                print(f"SPSA progress: iteration {iteration + 1}/{settings.iterations} {track} {side} ready", file=sys.stderr, flush=True)
        for track, theta, step, keys, _ in sorted(jobs):
            reference, baseline = subset_context(settings.anchor, keys)
            plus_metrics = tune_futility.compute_metrics(reference, baseline, results[(track, "plus")], settings.candidate_nodes, settings.score_scale, keys)
            minus_metrics = tune_futility.compute_metrics(reference, baseline, results[(track, "minus")], settings.candidate_nodes, settings.score_scale, keys)
            theta_next = spsa_optimizer.update(theta, step, plus_metrics["mean_normalized_regret"], minus_metrics["mean_normalized_regret"], settings.schedule.objective_scale)
            history = state["tracks"][track]["completed_iterations"]
            history.append({"iteration": iteration, "subset_position_count": len(keys), "subset_keys_sha256": keys_hash(keys), "gain": step.gain, "perturbation": step.perturbation, "direction": list(step.direction), "plus": {"margins": list(step.plus), "metrics": plus_metrics, "output": tune_futility.file_identity(run_dir / "tracks" / track / "probes" / f"iteration-{iteration:04d}-plus.jsonl")}, "minus": {"margins": list(step.minus), "metrics": minus_metrics, "output": tune_futility.file_identity(run_dir / "tracks" / track / "probes" / f"iteration-{iteration:04d}-minus.jsonl")}, "theta_before": list(theta), "theta_after": list(theta_next), "projected_after": list(spsa_optimizer.project(theta_next, settings.schedule.max_margin))})
            state["tracks"][track]["theta"] = list(theta_next)
            atomic_write(state_path, state)
    finalists = []
    for track, start in settings.tracks:
        record = state["tracks"][track]
        finalists.append({"track": track, "start_margins": list(start), "final_theta": record["theta"], "projected_margins": list(spsa_optimizer.project(record["theta"], settings.schedule.max_margin)), "completed_iterations": len(record["completed_iterations"])})
    result = {"schema": SCHEMA, "finalists": finalists, "note": "Projected tuples are SPSA outputs only; they have not been ranked on the full development corpus or promoted to selection."}
    atomic_write(run_dir / "finalists.json", result)
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run development-only SPSA futility margin probes.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(Path(args.config).resolve())
        value = manifest(settings)
        if args.dry_run:
            print(json.dumps(value, indent=2, sort_keys=True))
            return 0
        run_dir = Path(args.run_dir).resolve()
        prepare(run_dir, value)
        result = run(settings, run_dir)
        print(f"SPSA finished tracks={len(result['finalists'])} iterations={settings.iterations}")
        return 0
    except (json.JSONDecodeError, OSError, optimize_futility.OptimizationError, spsa_optimizer.OptimizationError, tune_futility.TuningError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
