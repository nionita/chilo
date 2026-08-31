#!/usr/bin/env python3
"""Relative-risk random hill-climb for futility margins.

Each attempt probes a current incumbent and one deterministic random
perturbation on the same fresh trusted-set sample. A proposal is accepted only
when it makes the selected incumbent-relative safety progress while staying
inside its predeclared mean-regret concession budget. Optional absolute limits
are backstops, never the progress objective. This is deliberately
development-only; full-development and untouched selection evaluation remain
separate decisions.
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

import futility_risk
import optimize_futility
import spsa_optimizer
import tune_futility


SCHEMA = "chilo.futility_relative_risk_hillclimb.v3"
STATE_SCHEMA = "chilo.futility_relative_risk_hillclimb_state.v3"
Margins = Tuple[int, ...]
Key = Tuple[str, int, str]
ACCEPTANCE_MODES = {"squared", "cvar1", "both"}


@dataclass(frozen=True)
class Acceptance:
    mode: str
    max_mean_regret_concession: float
    min_squared_regret_improvement: float
    min_cvar1_regret_improvement: float
    max_squared_regret_worsening: float
    max_cvar1_regret_worsening: float
    max_squared_regret: Optional[float]
    max_cvar1_regret: Optional[float]
    max_stalled_attempts: int


@dataclass(frozen=True)
class Track:
    identifier: str
    margins: Margins
    acceptance: Acceptance


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
    tracks: Tuple[Track, ...]
    max_attempts: int
    workers: int
    subset_fraction: float
    seed: int
    perturbation_c: float
    perturbation_gamma: float
    max_margin: int


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


def require_optional_number(value: Any, name: str) -> Optional[float]:
    if value is None:
        return None
    return require_number(value, name, 0, True)


def parse_acceptance(value: Any, label: str) -> Acceptance:
    if not isinstance(value, dict):
        raise optimize_futility.OptimizationError(f"{label} must be an object")
    allowed = {
        "mode",
        "max_mean_regret_concession",
        "min_squared_regret_improvement",
        "min_cvar1_regret_improvement",
        "max_squared_regret_worsening",
        "max_cvar1_regret_worsening",
        "max_squared_regret",
        "max_cvar1_regret",
        "max_stalled_attempts",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise optimize_futility.OptimizationError(f"unknown {label} field(s): {', '.join(unknown)}")
    required = allowed - {"max_squared_regret", "max_cvar1_regret"}
    if not required.issubset(value):
        missing = sorted(required - set(value))
        raise optimize_futility.OptimizationError(f"{label} missing required field(s): {', '.join(missing)}")
    mode = optimize_futility.require_string(value.get("mode"), f"{label}.mode")
    if mode not in ACCEPTANCE_MODES:
        raise optimize_futility.OptimizationError(f"{label}.mode must be squared, cvar1, or both")
    squared_improvement = require_number(
        value.get("min_squared_regret_improvement"), f"{label}.min_squared_regret_improvement", 0, True
    )
    cvar1_improvement = require_number(
        value.get("min_cvar1_regret_improvement"), f"{label}.min_cvar1_regret_improvement", 0, True
    )
    if mode in {"squared", "both"} and squared_improvement <= 0:
        raise optimize_futility.OptimizationError(f"{label}.min_squared_regret_improvement must be > 0 for {mode} mode")
    if mode in {"cvar1", "both"} and cvar1_improvement <= 0:
        raise optimize_futility.OptimizationError(f"{label}.min_cvar1_regret_improvement must be > 0 for {mode} mode")
    return Acceptance(
        mode=mode,
        max_mean_regret_concession=require_number(
            value.get("max_mean_regret_concession"), f"{label}.max_mean_regret_concession", 0, True
        ),
        min_squared_regret_improvement=squared_improvement,
        min_cvar1_regret_improvement=cvar1_improvement,
        max_squared_regret_worsening=require_number(
            value.get("max_squared_regret_worsening"), f"{label}.max_squared_regret_worsening", 0, True
        ),
        max_cvar1_regret_worsening=require_number(
            value.get("max_cvar1_regret_worsening"), f"{label}.max_cvar1_regret_worsening", 0, True
        ),
        max_squared_regret=require_optional_number(value.get("max_squared_regret"), f"{label}.max_squared_regret"),
        max_cvar1_regret=require_optional_number(value.get("max_cvar1_regret"), f"{label}.max_cvar1_regret"),
        max_stalled_attempts=optimize_futility.require_int(
            value.get("max_stalled_attempts"), f"{label}.max_stalled_attempts", 1
        ),
    )


def load_settings(config_path: Path) -> Settings:
    raw_bytes = config_path.read_bytes()
    raw = json.loads(raw_bytes)
    if not isinstance(raw, dict):
        raise optimize_futility.OptimizationError("gated hill-climb config root must be an object")
    allowed = {
        "probe", "inputs", "weights", "candidate_nodes", "baseline_margins", "score_scale",
        "probe_report_every", "development", "gated_hillclimb",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise optimize_futility.OptimizationError(f"unknown gated hill-climb config field(s): {', '.join(unknown)}")
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
    score_scale = require_number(raw.get("score_scale", 600), "score_scale", 0)
    report_every = optimize_futility.require_int(raw.get("probe_report_every", 1000), "probe_report_every", 0)
    development = raw.get("development")
    if not isinstance(development, dict):
        raise optimize_futility.OptimizationError("development must be an object")
    anchor = optimize_futility.load_anchor(config_path, "development", development, nodes, baseline)
    hillclimb = raw.get("gated_hillclimb")
    if not isinstance(hillclimb, dict):
        raise optimize_futility.OptimizationError("gated_hillclimb must be an object")
    allowed_hillclimb = {
        "tracks", "max_attempts", "workers", "subset_fraction", "seed",
        "perturbation_c", "perturbation_gamma", "max_margin",
    }
    unknown = sorted(set(hillclimb) - allowed_hillclimb)
    if unknown:
        raise optimize_futility.OptimizationError(f"unknown gated_hillclimb field(s): {', '.join(unknown)}")
    tracks_raw = hillclimb.get("tracks")
    if not isinstance(tracks_raw, list) or not tracks_raw:
        raise optimize_futility.OptimizationError("gated_hillclimb.tracks must be a non-empty list")
    tracks: List[Track] = []
    identifiers = set()
    for index, item in enumerate(tracks_raw):
        if not isinstance(item, dict) or set(item) != {"id", "margins", "acceptance"}:
            raise optimize_futility.OptimizationError("each gated_hillclimb track must contain only id, margins, and acceptance")
        identifier = optimize_futility.require_string(item.get("id"), "gated_hillclimb track id")
        if identifier in identifiers:
            raise optimize_futility.OptimizationError(f"duplicate gated_hillclimb track id {identifier}")
        identifiers.add(identifier)
        margins = tune_futility.validate_margins(item.get("margins"), f"gated_hillclimb track {identifier} margins")
        tracks.append(Track(identifier, margins, parse_acceptance(item.get("acceptance"), f"gated_hillclimb track {identifier}.acceptance")))
    max_margin = optimize_futility.require_int(hillclimb.get("max_margin"), "gated_hillclimb.max_margin", 0)
    if any(max(track.margins) > max_margin for track in tracks):
        raise optimize_futility.OptimizationError("gated_hillclimb track margins exceed gated_hillclimb.max_margin")
    subset_fraction = require_number(hillclimb.get("subset_fraction"), "gated_hillclimb.subset_fraction", 0)
    if subset_fraction > 1:
        raise optimize_futility.OptimizationError("gated_hillclimb.subset_fraction must be <= 1")
    return Settings(
        config_path=config_path,
        config_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        probe=probe,
        inputs=inputs,
        weights=weights,
        candidate_nodes=nodes,
        baseline_margins=baseline,
        score_scale=score_scale,
        probe_report_every=report_every,
        anchor=anchor,
        tracks=tuple(tracks),
        max_attempts=optimize_futility.require_int(hillclimb.get("max_attempts"), "gated_hillclimb.max_attempts", 1),
        workers=optimize_futility.require_int(hillclimb.get("workers"), "gated_hillclimb.workers", 1),
        subset_fraction=subset_fraction,
        seed=optimize_futility.require_int(hillclimb.get("seed"), "gated_hillclimb.seed", 0),
        perturbation_c=require_number(hillclimb.get("perturbation_c"), "gated_hillclimb.perturbation_c", 0),
        perturbation_gamma=require_number(hillclimb.get("perturbation_gamma"), "gated_hillclimb.perturbation_gamma", 0),
        max_margin=max_margin,
    )


def acceptance_json(acceptance: Acceptance) -> Dict[str, Any]:
    return {
        "mode": acceptance.mode,
        "max_mean_regret_concession": acceptance.max_mean_regret_concession,
        "min_squared_regret_improvement": acceptance.min_squared_regret_improvement,
        "min_cvar1_regret_improvement": acceptance.min_cvar1_regret_improvement,
        "max_squared_regret_worsening": acceptance.max_squared_regret_worsening,
        "max_cvar1_regret_worsening": acceptance.max_cvar1_regret_worsening,
        "max_squared_regret": acceptance.max_squared_regret,
        "max_cvar1_regret": acceptance.max_cvar1_regret,
        "max_stalled_attempts": acceptance.max_stalled_attempts,
    }


def manifest(settings: Settings) -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "config": {"path": str(settings.config_path), "sha256": settings.config_sha256},
        "probe": tune_futility.file_identity(settings.probe),
        "inputs": [tune_futility.file_identity(path) for path in settings.inputs],
        "weights": tune_futility.file_identity(settings.weights) if settings.weights else None,
        "candidate_nodes": settings.candidate_nodes,
        "baseline_margins": list(settings.baseline_margins),
        "score_scale": settings.score_scale,
        "probe_report_every": settings.probe_report_every,
        "development": {
            "contract": settings.anchor.contract,
            "reference": settings.anchor.reference_identity,
            "baseline": settings.anchor.baseline_identity,
            "trusted_set": settings.anchor.trusted_set,
            "rescue": dict(settings.anchor.rescue) if settings.anchor.rescue is not None else None,
        },
        "gated_hillclimb": {
            "tracks": [
                {"id": track.identifier, "margins": list(track.margins), "acceptance": acceptance_json(track.acceptance)}
                for track in settings.tracks
            ],
            "max_attempts": settings.max_attempts,
            "workers": settings.workers,
            "subset_fraction": settings.subset_fraction,
            "seed": settings.seed,
            "perturbation_c": settings.perturbation_c,
            "perturbation_gamma": settings.perturbation_gamma,
            "max_margin": settings.max_margin,
        },
    }


def prepare(run_dir: Path, value: Mapping[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "optimizer_manifest.json"
    if path.exists():
        existing = optimize_futility.read_json(path, "gated hill-climb manifest")
        if existing.get("schema") in {"chilo.futility_gated_hillclimb.v1", "chilo.futility_gated_hillclimb.v2"}:
            raise optimize_futility.OptimizationError(
                "v1/v2 gated hill-climb manifest cannot resume under the v3 relative-risk contract; use a new run directory"
            )
        if existing != value:
            raise optimize_futility.OptimizationError("gated hill-climb manifest does not match configured artifacts or anchor; use a new run directory")
    else:
        atomic_write(path, value)
    for track in value["gated_hillclimb"]["tracks"]:
        root = run_dir / "tracks" / track["id"]
        (root / "probes").mkdir(parents=True, exist_ok=True)
        (root / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "subsets").mkdir(parents=True, exist_ok=True)


def sample_keys(settings: Settings, track: str, attempt: int) -> List[Key]:
    population = list(settings.anchor.trusted_keys)
    count = max(1, int(math.ceil(len(population) * settings.subset_fraction)))
    rng = random.Random(f"{settings.seed}:subset:{track}:{attempt}")
    return sorted(rng.sample(population, count))


def keys_hash(keys: Sequence[Key]) -> str:
    digest = hashlib.sha256()
    for key in keys:
        digest.update(json.dumps(key, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def write_masked_inputs(settings: Settings, run_dir: Path, track: str, attempt: int, keys: Sequence[Key]) -> Tuple[Path, ...]:
    selected = {(source, line) for source, line, _ in keys}
    target_dir = run_dir / "subsets" / f"{track}-{attempt:04d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for input_path in settings.inputs:
        output = target_dir / input_path.name
        lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
        contents = "".join(line if line_number == 1 or (input_path.name, line_number) in selected else "\n" for line_number, line in enumerate(lines, 1))
        if not output.exists() or output.read_text(encoding="utf-8") != contents:
            output.write_text(contents, encoding="utf-8")
        outputs.append(output)
    return tuple(outputs)


def subset_context(anchor: optimize_futility.AnchorContext, keys: Sequence[Key]) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
    wanted = set(keys)
    reference = {"positions": {key: value for key, value in anchor.reference["positions"].items() if key in wanted}, "summary": anchor.reference["summary"]}
    baseline = {"positions": {key: value for key, value in anchor.baseline["positions"].items() if key in wanted}, "summary": anchor.baseline["summary"]}
    if len(reference["positions"]) != len(wanted) or len(baseline["positions"]) != len(wanted):
        raise optimize_futility.OptimizationError("sampled trusted key absent from anchor")
    return reference, baseline


def perturbation(settings: Settings, track: str, attempt: int) -> float:
    return settings.perturbation_c / ((attempt + 1) ** settings.perturbation_gamma)


def make_proposal(current: Margins, settings: Settings, track: str, attempt: int) -> Tuple[Margins, Tuple[int, ...], float]:
    vector = spsa_optimizer.to_vector(current)
    size = perturbation(settings, track, attempt)
    rng = random.Random(f"{settings.seed}:direction:{track}:{attempt}")
    for _ in range(100):
        direction = tuple(1 if rng.randrange(2) else -1 for _ in vector)
        proposal = spsa_optimizer.project(
            tuple(value + size * sign for value, sign in zip(vector, direction)), settings.max_margin
        )
        if proposal != current:
            return proposal, direction, size
    raise optimize_futility.OptimizationError("hill-climb perturbation collapses after projection; increase perturbation_c or move away from bounds")


def probe_one(
    settings: Settings,
    run_dir: Path,
    track: str,
    attempt: int,
    role: str,
    margins: Margins,
    masked_inputs: Sequence[Path],
) -> Mapping[str, Any]:
    root = run_dir / "tracks" / track
    output = root / "probes" / f"attempt-{attempt:04d}-{role}.jsonl"
    log = root / "logs" / f"attempt-{attempt:04d}-{role}.log"
    try:
        if output.is_file():
            return tune_futility.parse_probe_output(output, settings.candidate_nodes, margins)
    except tune_futility.TuningError:
        pass
    command = tune_futility.build_probe_command(
        settings.probe, masked_inputs, settings.weights, settings.candidate_nodes,
        margins, output, settings.probe_report_every,
    )
    with log.open("w", encoding="utf-8") as handle:
        handle.write("command=" + json.dumps(command) + "\n")
        handle.flush()
        completed = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, text=True, check=False)
        handle.write(f"exit_code={completed.returncode}\n")
    if completed.returncode:
        raise optimize_futility.OptimizationError(f"gated hill-climb {track} attempt {attempt} {role} probe failed; see {log}")
    return tune_futility.parse_probe_output(output, settings.candidate_nodes, margins)


def risk_metrics(reference: Mapping[str, Any], candidate: Mapping[str, Any], keys: Sequence[Key], score_scale: float) -> Dict[str, Any]:
    return futility_risk.compute_risk_metrics(
        reference, candidate, keys, score_scale, [0.01], [], 150, -150,
    )


def risk_values(metrics: Mapping[str, Any]) -> Dict[str, float]:
    absolute = metrics["absolute_regret"]
    return {
        "mean_squared_regret": float(absolute["mean_squared"]),
        "cvar1_regret": float(absolute["tail_mean"]["top_0.01"]),
    }


def evaluate_absolute_backstops(metrics: Mapping[str, Any], acceptance: Acceptance) -> Dict[str, Any]:
    values = risk_values(metrics)
    failures = []
    if acceptance.max_squared_regret is not None and values["mean_squared_regret"] > acceptance.max_squared_regret:
        failures.append("max_squared_regret")
    if acceptance.max_cvar1_regret is not None and values["cvar1_regret"] > acceptance.max_cvar1_regret:
        failures.append("max_cvar1_regret")
    return {
        "passed": not failures,
        "failures": failures,
        **values,
        "limits": {
            "max_squared_regret": acceptance.max_squared_regret,
            "max_cvar1_regret": acceptance.max_cvar1_regret,
        },
    }


def evaluate_acceptance(
    current_metrics: Mapping[str, Any], proposal_metrics: Mapping[str, Any],
    current_risk: Mapping[str, Any], proposal_risk: Mapping[str, Any], acceptance: Acceptance,
) -> Dict[str, Any]:
    """Evaluate paired deltas; negative risk deltas are safer."""
    current = risk_values(current_risk)
    proposal = risk_values(proposal_risk)
    deltas = {
        "mean_normalized_regret": float(proposal_metrics["mean_normalized_regret"]) - float(current_metrics["mean_normalized_regret"]),
        "mean_squared_regret": proposal["mean_squared_regret"] - current["mean_squared_regret"],
        "cvar1_regret": proposal["cvar1_regret"] - current["cvar1_regret"],
    }
    failures = []
    if deltas["mean_normalized_regret"] > acceptance.max_mean_regret_concession:
        failures.append("mean_regret_concession_exceeded")
    if acceptance.mode in {"squared", "both"}:
        if deltas["mean_squared_regret"] > -acceptance.min_squared_regret_improvement:
            failures.append("squared_regret_not_improved")
    elif deltas["mean_squared_regret"] > acceptance.max_squared_regret_worsening:
        failures.append("squared_regret_worsened")
    if acceptance.mode in {"cvar1", "both"}:
        if deltas["cvar1_regret"] > -acceptance.min_cvar1_regret_improvement:
            failures.append("cvar1_regret_not_improved")
    elif deltas["cvar1_regret"] > acceptance.max_cvar1_regret_worsening:
        failures.append("cvar1_regret_worsened")
    return {
        "mode": acceptance.mode,
        "passed": not failures,
        "failures": failures,
        "deltas": deltas,
        "thresholds": {
            "max_mean_regret_concession": acceptance.max_mean_regret_concession,
            "min_squared_regret_improvement": acceptance.min_squared_regret_improvement,
            "min_cvar1_regret_improvement": acceptance.min_cvar1_regret_improvement,
            "max_squared_regret_worsening": acceptance.max_squared_regret_worsening,
            "max_cvar1_regret_worsening": acceptance.max_cvar1_regret_worsening,
        },
    }


def new_state(settings: Settings) -> Dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "tracks": {
            track.identifier: {
                "current_margins": list(track.margins),
                "status": "running",
                "stalled_attempts": 0,
                "accepted_improvements": 0,
                "completed_attempts": [],
            }
            for track in settings.tracks
        },
    }


def validate_state(state: Mapping[str, Any], settings: Settings) -> None:
    if state.get("schema") != STATE_SCHEMA or not isinstance(state.get("tracks"), dict):
        raise optimize_futility.OptimizationError("invalid gated hill-climb state")
    expected = {track.identifier for track in settings.tracks}
    if set(state["tracks"]) != expected:
        raise optimize_futility.OptimizationError("gated hill-climb state track set does not match configuration")
    for track in settings.tracks:
        record = state["tracks"][track.identifier]
        if not isinstance(record, dict):
            raise optimize_futility.OptimizationError("invalid gated hill-climb track state")
        current = tune_futility.validate_margins(record.get("current_margins"), f"state {track.identifier} current_margins")
        if len(current) != len(track.margins):
            raise optimize_futility.OptimizationError("gated hill-climb state current_margins depth does not match track")
        if record.get("status") not in {"running", "stalled", "initial_backstop_failed", "max_attempts"}:
            raise optimize_futility.OptimizationError("invalid gated hill-climb track status")
        if not isinstance(record.get("stalled_attempts"), int) or record["stalled_attempts"] < 0:
            raise optimize_futility.OptimizationError("invalid gated hill-climb stalled_attempts")
        if not isinstance(record.get("accepted_improvements"), int) or record["accepted_improvements"] < 0:
            raise optimize_futility.OptimizationError("invalid gated hill-climb accepted_improvements")
        history = record.get("completed_attempts")
        if not isinstance(history, list) or len(history) > settings.max_attempts:
            raise optimize_futility.OptimizationError("invalid gated hill-climb attempt history")
        for index, item in enumerate(history):
            if not isinstance(item, dict) or item.get("attempt") != index:
                raise optimize_futility.OptimizationError("gated hill-climb state has a gap in attempt history")


def load_state(path: Path, settings: Settings) -> Dict[str, Any]:
    if not path.exists():
        return new_state(settings)
    state = optimize_futility.read_json(path, "gated hill-climb state")
    if state.get("schema") in {
        "chilo.futility_gated_hillclimb_state.v1",
        "chilo.futility_gated_hillclimb_state.v2",
    }:
        raise optimize_futility.OptimizationError(
            "v1/v2 gated hill-climb state cannot resume under the v3 relative-risk contract; use a new run directory"
        )
    validate_state(state, settings)
    return state


def record_output(run_dir: Path, track: str, attempt: int, role: str) -> Dict[str, Any]:
    return tune_futility.file_identity(run_dir / "tracks" / track / "probes" / f"attempt-{attempt:04d}-{role}.jsonl")


def run(settings: Settings, run_dir: Path) -> Dict[str, Any]:
    state_path = run_dir / "state.json"
    state = load_state(state_path, settings)
    atomic_write(state_path, state)
    for attempt in range(settings.max_attempts):
        jobs = []
        for track in settings.tracks:
            record = state["tracks"][track.identifier]
            if record["status"] != "running":
                continue
            history = record["completed_attempts"]
            if len(history) > attempt:
                continue
            if len(history) != attempt:
                raise optimize_futility.OptimizationError("gated hill-climb state has a gap in attempt history")
            current = tune_futility.validate_margins(record["current_margins"], f"state {track.identifier} current_margins")
            proposal, direction, size = make_proposal(current, settings, track.identifier, attempt)
            keys = sample_keys(settings, track.identifier, attempt)
            masked = write_masked_inputs(settings, run_dir, track.identifier, attempt, keys)
            jobs.append((track, current, proposal, direction, size, keys, masked))
        if not jobs:
            break
        atomic_write(state_path, state)
        results: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=settings.workers) as executor:
            futures = {
                executor.submit(probe_one, settings, run_dir, track.identifier, attempt, role, margins, masked): (track.identifier, role)
                for track, current, proposal, _, _, _, masked in jobs
                for role, margins in (("current", current), ("proposal", proposal))
            }
            for future in concurrent.futures.as_completed(futures):
                track, role = futures[future]
                results[(track, role)] = future.result()
                print(f"gated hill-climb progress: attempt {attempt + 1}/{settings.max_attempts} {track} {role} ready", file=sys.stderr, flush=True)
        for track, current, proposal, direction, size, keys, _ in sorted(jobs, key=lambda item: item[0].identifier):
            reference, baseline = subset_context(settings.anchor, keys)
            current_candidate = results[(track.identifier, "current")]
            proposal_candidate = results[(track.identifier, "proposal")]
            current_metrics = tune_futility.compute_metrics(reference, baseline, current_candidate, settings.candidate_nodes, settings.score_scale, keys)
            proposal_metrics = tune_futility.compute_metrics(reference, baseline, proposal_candidate, settings.candidate_nodes, settings.score_scale, keys)
            current_risk = risk_metrics(reference, current_candidate, keys, settings.score_scale)
            proposal_risk = risk_metrics(reference, proposal_candidate, keys, settings.score_scale)
            current_backstop = evaluate_absolute_backstops(current_risk, track.acceptance)
            proposal_backstop = evaluate_absolute_backstops(proposal_risk, track.acceptance)
            paired_acceptance = evaluate_acceptance(
                current_metrics, proposal_metrics, current_risk, proposal_risk, track.acceptance
            )
            record = state["tracks"][track.identifier]
            accepted = False
            if attempt == 0 and not current_backstop["passed"]:
                decision = "initial_backstop_failed"
                record["status"] = "initial_backstop_failed"
            elif not proposal_backstop["passed"]:
                decision = "absolute_backstop_rejected"
                record["stalled_attempts"] += 1
            elif not paired_acceptance["passed"]:
                decision = paired_acceptance["failures"][0]
                record["stalled_attempts"] += 1
            else:
                decision = "accepted"
                accepted = True
                record["current_margins"] = list(proposal)
                record["stalled_attempts"] = 0
                record["accepted_improvements"] += 1
            if record["status"] == "running" and record["stalled_attempts"] >= track.acceptance.max_stalled_attempts:
                record["status"] = "stalled"
            record["completed_attempts"].append({
                "attempt": attempt,
                "subset_position_count": len(keys),
                "subset_keys_sha256": keys_hash(keys),
                "current_margins": list(current),
                "proposal_margins": list(proposal),
                "direction": list(direction),
                "perturbation": size,
                "current": {
                    "metrics": current_metrics,
                    "risk": current_risk,
                    "absolute_backstop": current_backstop,
                    "output": record_output(run_dir, track.identifier, attempt, "current"),
                },
                "proposal": {
                    "metrics": proposal_metrics,
                    "risk": proposal_risk,
                    "absolute_backstop": proposal_backstop,
                    "output": record_output(run_dir, track.identifier, attempt, "proposal"),
                },
                "acceptance": paired_acceptance,
                "mean_regret_improvement": -paired_acceptance["deltas"]["mean_normalized_regret"],
                "accepted": accepted,
                "decision": decision,
                "stalled_attempts_after": record["stalled_attempts"],
                "status_after": record["status"],
                "current_margins_after": list(record["current_margins"]),
            })
            atomic_write(state_path, state)
    for track in settings.tracks:
        record = state["tracks"][track.identifier]
        if record["status"] == "running":
            record["status"] = "max_attempts"
    atomic_write(state_path, state)
    finalists = []
    for track in settings.tracks:
        record = state["tracks"][track.identifier]
        finalists.append({
            "track": track.identifier,
            "start_margins": list(track.margins),
            "final_margins": list(record["current_margins"]),
            "status": record["status"],
            "attempted_count": len(record["completed_attempts"]),
            "accepted_improvements": record["accepted_improvements"],
            "stalled_attempts": record["stalled_attempts"],
        })
    result = {
        "schema": SCHEMA,
        "finalists": finalists,
        "note": "Final tuples are development-only constrained hill-climb outputs; they require full-development and untouched selection evaluation before promotion.",
    }
    atomic_write(run_dir / "finalists.json", result)
    lines = ["# Gated hill-climb finalists", "", "| Track | Start | Final | Status | Attempts | Accepted |", "|---|---|---|---|---:|---:|"]
    for item in finalists:
        lines.append(f"| {item['track']} | `{','.join(str(value) for value in item['start_margins'])}` | `{','.join(str(value) for value in item['final_margins'])}` | {item['status']} | {item['attempted_count']} | {item['accepted_improvements']} |")
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run development-only gated futility-margin hill climbing.")
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
        print(f"gated hill-climb finished tracks={len(result['finalists'])} max_attempts={settings.max_attempts}")
        return 0
    except (json.JSONDecodeError, OSError, optimize_futility.OptimizationError, spsa_optimizer.OptimizationError, tune_futility.TuningError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
