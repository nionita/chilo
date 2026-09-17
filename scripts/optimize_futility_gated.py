#!/usr/bin/env python3
"""Full-development Pareto search for futility margins.

Every tuple is evaluated on the fixed complete development population. The
primary archive contains the non-dominated tuples on mean normalized regret,
reference-relative squared regret, and reference-relative CVaR-1%. At the end
of a fixed proposal budget, configured semantic metrics decimate that archive
sequentially; ties at a cutoff are retained.
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


SCHEMA = "chilo.futility_pareto_search.v4"
STATE_SCHEMA = "chilo.futility_pareto_search_state.v4"
Margins = Tuple[int, ...]
Key = Tuple[str, int, str]
SEMANTIC_METRICS = {
    "winning_mate_missed",
    "clear_advantage_lost",
    "clear_advantage_to_nonpositive",
    "nonlosing_to_losing",
}
MAX_DUPLICATE_REPLACEMENTS = 1000


@dataclass(frozen=True)
class SemanticFilter:
    metric: str
    discard_worst_fraction: float


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
    initial_margins: Margins
    max_proposals: int
    workers: int
    seed: int
    perturbation_c: float
    perturbation_gamma: float
    max_margin: int
    semantic_filters: Tuple[SemanticFilter, ...]


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


def parse_semantic_filters(value: Any) -> Tuple[SemanticFilter, ...]:
    if not isinstance(value, list) or not value:
        raise optimize_futility.OptimizationError("pareto_search.semantic_filters must be a non-empty list")
    filters = []
    seen = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"metric", "discard_worst_fraction"}:
            raise optimize_futility.OptimizationError(
                "each pareto_search.semantic_filters item must contain only metric and discard_worst_fraction"
            )
        metric = optimize_futility.require_string(item.get("metric"), f"pareto_search.semantic_filters[{index}].metric")
        if metric not in SEMANTIC_METRICS:
            raise optimize_futility.OptimizationError(
                f"pareto_search.semantic_filters[{index}].metric must be one of: {', '.join(sorted(SEMANTIC_METRICS))}"
            )
        if metric in seen:
            raise optimize_futility.OptimizationError(f"duplicate pareto semantic filter metric {metric}")
        seen.add(metric)
        fraction = require_number(item.get("discard_worst_fraction"), f"pareto_search.semantic_filters[{index}].discard_worst_fraction", 0)
        if fraction >= 1:
            raise optimize_futility.OptimizationError(f"pareto_search.semantic_filters[{index}].discard_worst_fraction must be < 1")
        filters.append(SemanticFilter(metric, fraction))
    return tuple(filters)


def load_settings(config_path: Path) -> Settings:
    raw_bytes = config_path.read_bytes()
    raw = json.loads(raw_bytes)
    if not isinstance(raw, dict):
        raise optimize_futility.OptimizationError("Pareto futility config root must be an object")
    allowed = {"probe", "inputs", "weights", "candidate_nodes", "baseline_margins", "score_scale", "probe_report_every", "development", "pareto_search"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise optimize_futility.OptimizationError(f"unknown Pareto futility config field(s): {', '.join(unknown)}")
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
    pareto = raw.get("pareto_search")
    if not isinstance(pareto, dict):
        raise optimize_futility.OptimizationError("pareto_search must be an object")
    allowed_pareto = {"initial_margins", "max_proposals", "workers", "seed", "perturbation_c", "perturbation_gamma", "max_margin", "semantic_filters"}
    unknown = sorted(set(pareto) - allowed_pareto)
    if unknown:
        raise optimize_futility.OptimizationError(f"unknown pareto_search field(s): {', '.join(unknown)}")
    if set(pareto) != allowed_pareto:
        missing = sorted(allowed_pareto - set(pareto))
        raise optimize_futility.OptimizationError(f"pareto_search missing required field(s): {', '.join(missing)}")
    initial = tune_futility.validate_margins(pareto.get("initial_margins"), "pareto_search.initial_margins")
    max_margin = optimize_futility.require_int(pareto.get("max_margin"), "pareto_search.max_margin", 0)
    if max(initial) > max_margin:
        raise optimize_futility.OptimizationError("pareto_search.initial_margins exceed pareto_search.max_margin")
    return Settings(
        config_path=config_path, config_sha256=hashlib.sha256(raw_bytes).hexdigest(), probe=probe, inputs=inputs, weights=weights,
        candidate_nodes=nodes, baseline_margins=baseline, score_scale=score_scale, probe_report_every=report_every, anchor=anchor,
        initial_margins=initial,
        max_proposals=optimize_futility.require_int(pareto.get("max_proposals"), "pareto_search.max_proposals", 1),
        workers=optimize_futility.require_int(pareto.get("workers"), "pareto_search.workers", 1),
        seed=optimize_futility.require_int(pareto.get("seed"), "pareto_search.seed", 0),
        perturbation_c=require_number(pareto.get("perturbation_c"), "pareto_search.perturbation_c", 0),
        perturbation_gamma=require_number(pareto.get("perturbation_gamma"), "pareto_search.perturbation_gamma", 0),
        max_margin=max_margin, semantic_filters=parse_semantic_filters(pareto.get("semantic_filters")),
    )


def manifest(settings: Settings) -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "config": {"path": str(settings.config_path), "sha256": settings.config_sha256},
        "probe": tune_futility.file_identity(settings.probe),
        "inputs": [tune_futility.file_identity(path) for path in settings.inputs],
        "weights": tune_futility.file_identity(settings.weights) if settings.weights else None,
        "candidate_nodes": settings.candidate_nodes, "baseline_margins": list(settings.baseline_margins), "score_scale": settings.score_scale, "probe_report_every": settings.probe_report_every,
        "development": {"contract": settings.anchor.contract, "reference": settings.anchor.reference_identity, "baseline": settings.anchor.baseline_identity, "trusted_set": settings.anchor.trusted_set, "rescue": dict(settings.anchor.rescue) if settings.anchor.rescue is not None else None},
        "pareto_search": {
            "initial_margins": list(settings.initial_margins), "max_proposals": settings.max_proposals, "workers": settings.workers,
            "seed": settings.seed, "perturbation_c": settings.perturbation_c, "perturbation_gamma": settings.perturbation_gamma, "max_margin": settings.max_margin,
            "semantic_filters": [{"metric": item.metric, "discard_worst_fraction": item.discard_worst_fraction} for item in settings.semantic_filters],
        },
    }


def prepare(run_dir: Path, value: Mapping[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "optimizer_manifest.json"
    if path.exists():
        existing = optimize_futility.read_json(path, "Pareto futility manifest")
        if existing.get("schema") in {"chilo.futility_gated_hillclimb.v1", "chilo.futility_gated_hillclimb.v2", "chilo.futility_relative_risk_hillclimb.v3"}:
            raise optimize_futility.OptimizationError("an earlier sampled/single-incumbent manifest cannot resume under the v4 full-development Pareto contract; use a new run directory")
        if existing != value:
            raise optimize_futility.OptimizationError("Pareto futility manifest does not match configured artifacts or anchor; use a new run directory")
    else:
        atomic_write(path, value)
    (run_dir / "probes").mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)


def perturbation(settings: Settings, proposal_index: int) -> float:
    return settings.perturbation_c / ((proposal_index + 1) ** settings.perturbation_gamma)


def make_proposal(parent: Margins, settings: Settings, proposal_index: int, replacement_attempt: int = 0) -> Tuple[Margins, Tuple[int, ...], float]:
    vector = spsa_optimizer.to_vector(parent)
    size = perturbation(settings, proposal_index)
    rng = random.Random(
        f"{settings.seed}:direction:{proposal_index}:{replacement_attempt}:{','.join(map(str, parent))}"
    )
    for _ in range(100):
        direction = tuple(1 if rng.randrange(2) else -1 for _ in vector)
        proposal = spsa_optimizer.project(tuple(value + size * sign for value, sign in zip(vector, direction)), settings.max_margin)
        if proposal != parent:
            return proposal, direction, size
    raise optimize_futility.OptimizationError("Pareto perturbation collapses after projection; increase perturbation_c or move away from bounds")


def select_parent(
    frontier: Sequence[Mapping[str, Any]], settings: Settings, proposal_index: int, replacement_attempt: int = 0
) -> Mapping[str, Any]:
    if not frontier:
        raise optimize_futility.OptimizationError("cannot select a parent from an empty Pareto frontier")
    ordered = sorted(frontier, key=lambda item: (tuple(item["margins"]), str(item["id"])))
    return ordered[
        random.Random(f"{settings.seed}:parent:{proposal_index}:{replacement_attempt}").randrange(len(ordered))
    ]


def make_unique_proposal(
    frontier: Sequence[Mapping[str, Any]], settings: Settings, proposal_index: int, considered: set[Margins]
) -> Tuple[Mapping[str, Any], Margins, Tuple[int, ...], float, int]:
    """Generate a deterministic, as-yet-unevaluated tuple from a frozen frontier."""
    for replacement_attempt in range(MAX_DUPLICATE_REPLACEMENTS):
        parent = select_parent(frontier, settings, proposal_index, replacement_attempt)
        parent_margins = tune_futility.validate_margins(parent["margins"], "Pareto parent margins")
        margins, direction, size = make_proposal(parent_margins, settings, proposal_index, replacement_attempt)
        if margins not in considered:
            return parent, margins, direction, size, replacement_attempt
    raise optimize_futility.OptimizationError(
        "could not generate an unevaluated Pareto tuple after "
        f"{MAX_DUPLICATE_REPLACEMENTS} attempts; increase perturbation_c or enlarge the feasible margin space"
    )


def probe_one(settings: Settings, run_dir: Path, identifier: str, margins: Margins) -> Mapping[str, Any]:
    output = run_dir / "probes" / f"{identifier}.jsonl"
    log = run_dir / "logs" / f"{identifier}.log"
    try:
        if output.is_file():
            return tune_futility.parse_probe_output(output, settings.candidate_nodes, margins)
    except tune_futility.TuningError:
        pass
    command = tune_futility.build_probe_command(settings.probe, settings.inputs, settings.weights, settings.candidate_nodes, margins, output, settings.probe_report_every)
    with log.open("w", encoding="utf-8") as handle:
        handle.write("command=" + json.dumps(command) + "\n")
        handle.flush()
        completed = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, text=True, check=False)
        handle.write(f"exit_code={completed.returncode}\n")
    if completed.returncode:
        raise optimize_futility.OptimizationError(f"Pareto futility {identifier} probe failed; see {log}")
    return tune_futility.parse_probe_output(output, settings.candidate_nodes, margins)


def risk_metrics(reference: Mapping[str, Any], candidate: Mapping[str, Any], keys: Sequence[Key], score_scale: float) -> Dict[str, Any]:
    return futility_risk.compute_risk_metrics(reference, candidate, keys, score_scale, [0.01], [], 150, -150)


def evaluate(settings: Settings, run_dir: Path, identifier: str, margins: Margins, candidate: Mapping[str, Any]) -> Dict[str, Any]:
    keys = settings.anchor.trusted_keys
    metrics = tune_futility.compute_metrics(settings.anchor.reference, settings.anchor.baseline, candidate, settings.candidate_nodes, settings.score_scale, keys)
    risk = risk_metrics(settings.anchor.reference, candidate, keys, settings.score_scale)
    semantic = risk["semantic_regressions_vs_reference"]
    return {"id": identifier, "margins": list(margins), "metrics": metrics, "risk": risk, "semantic": {metric: int(semantic[metric]) for metric in sorted(SEMANTIC_METRICS)}, "output": tune_futility.file_identity(run_dir / "probes" / f"{identifier}.jsonl")}


def primary_values(item: Mapping[str, Any]) -> Tuple[float, float, float]:
    return float(item["metrics"]["mean_normalized_regret"]), float(item["risk"]["absolute_regret"]["mean_squared"]), float(item["risk"]["absolute_regret"]["tail_mean"]["top_0.01"])


def dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """True only for strict Pareto dominance on the three primary minimization metrics."""
    left_values, right_values = primary_values(left), primary_values(right)
    return all(a <= b for a, b in zip(left_values, right_values)) and any(a < b for a, b in zip(left_values, right_values))


def archive_update(frontier: Sequence[Mapping[str, Any]], candidate: Mapping[str, Any]) -> Tuple[List[Mapping[str, Any]], Dict[str, Any]]:
    dominators = [str(item["id"]) for item in frontier if dominates(item, candidate)]
    if dominators:
        return list(frontier), {"action": "dominated", "dominators": dominators, "removed": []}
    removed = [str(item["id"]) for item in frontier if dominates(candidate, item)]
    removed_set = set(removed)
    return [*([item for item in frontier if str(item["id"]) not in removed_set]), candidate], {"action": "admitted", "dominators": [], "removed": removed}


def decimate_semantic_frontier(frontier: Sequence[Mapping[str, Any]], filters: Sequence[SemanticFilter]) -> Tuple[List[Mapping[str, Any]], List[Dict[str, Any]]]:
    """Sequentially discard the worst fraction, retaining all ties at the cutoff."""
    survivors = list(frontier)
    history: List[Dict[str, Any]] = []
    for item in filters:
        before = len(survivors)
        desired_discard = min(before - 1, int(math.ceil(before * item.discard_worst_fraction)))
        if desired_discard <= 0:
            history.append({"metric": item.metric, "before": before, "desired_discard": 0, "cutoff": None, "discarded": [], "after": before, "ties_at_cutoff_retained": True})
            continue
        sorted_values = sorted(int(candidate["semantic"][item.metric]) for candidate in survivors)
        cutoff = sorted_values[before - desired_discard - 1]
        discarded = [str(candidate["id"]) for candidate in survivors if int(candidate["semantic"][item.metric]) > cutoff]
        survivors = [candidate for candidate in survivors if int(candidate["semantic"][item.metric]) <= cutoff]
        history.append({"metric": item.metric, "before": before, "desired_discard": desired_discard, "cutoff": cutoff, "discarded": discarded, "after": len(survivors), "ties_at_cutoff_retained": True})
    return survivors, history


def new_state() -> Dict[str, Any]:
    return {"schema": STATE_SCHEMA, "status": "running", "next_proposal": 0, "evaluations": [], "frontier_ids": []}


def validate_state(state: Mapping[str, Any], settings: Settings) -> None:
    if state.get("schema") != STATE_SCHEMA:
        raise optimize_futility.OptimizationError("invalid Pareto futility state")
    if state.get("status") not in {"running", "max_proposals"}:
        raise optimize_futility.OptimizationError("invalid Pareto futility state status")
    if not isinstance(state.get("next_proposal"), int) or not 0 <= state["next_proposal"] <= settings.max_proposals:
        raise optimize_futility.OptimizationError("invalid Pareto next_proposal")
    if not isinstance(state.get("evaluations"), list) or not isinstance(state.get("frontier_ids"), list):
        raise optimize_futility.OptimizationError("invalid Pareto state evaluations or frontier")
    identifiers = [item.get("id") for item in state["evaluations"] if isinstance(item, dict)]
    if len(identifiers) != len(state["evaluations"]) or len(set(identifiers)) != len(identifiers):
        raise optimize_futility.OptimizationError("invalid Pareto evaluation identifiers")
    if not set(state["frontier_ids"]).issubset(set(identifiers)):
        raise optimize_futility.OptimizationError("Pareto frontier references an unknown evaluation")


def load_state(path: Path, settings: Settings) -> Dict[str, Any]:
    if not path.exists():
        return new_state()
    state = optimize_futility.read_json(path, "Pareto futility state")
    if state.get("schema") in {"chilo.futility_gated_hillclimb_state.v1", "chilo.futility_gated_hillclimb_state.v2", "chilo.futility_relative_risk_hillclimb_state.v3"}:
        raise optimize_futility.OptimizationError("an earlier sampled/single-incumbent state cannot resume under the v4 full-development Pareto contract; use a new run directory")
    validate_state(state, settings)
    return state


def evaluation_index(state: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {str(item["id"]): item for item in state["evaluations"]}


def current_frontier(state: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    indexed = evaluation_index(state)
    return [indexed[str(identifier)] for identifier in state["frontier_ids"]]


def write_result(settings: Settings, run_dir: Path, state: Mapping[str, Any], work_units_completed: int) -> Dict[str, Any]:
    """Persist the current archive, including an incomplete archive after bounded work."""
    frontier = current_frontier(state)
    complete = state["status"] == "max_proposals"
    shortlisted, filtering = (
        decimate_semantic_frontier(frontier, settings.semantic_filters) if complete else ([], [])
    )
    result = {
        "schema": SCHEMA,
        "status": state["status"],
        "initial": next(item for item in state["evaluations"] if item["id"] == "initial") if state["evaluations"] else None,
        "evaluated_count": len(state["evaluations"]),
        "proposal_count": state["next_proposal"],
        "numeric_pareto_frontier": frontier,
        "semantic_filtering": filtering,
        "selection_shortlist": shortlisted,
        "work_units_completed": work_units_completed,
        "note": (
            "All metrics are fixed full-development-population values. The selection_shortlist remains development-only "
            "and requires one full untouched-selection evaluation before promotion."
            if complete else
            "The Pareto search is incomplete; semantic selection and untouched-selection promotion are deferred."
        ),
    }
    atomic_write(run_dir / "pareto_frontier.json", result)
    lines = ["# Full-development futility Pareto frontier", "", "Every evaluated tuple used the complete fixed development population. The primary frontier minimizes mean regret, squared regret, and CVaR-1%.", "", "## Numeric Pareto frontier", "", "| ID | Margins | Mean regret | Squared regret | CVaR-1% | Mate misses | Nonlosing to losing |", "|---|---|---:|---:|---:|---:|---:|"]
    for item in frontier:
        absolute, semantic = item["risk"]["absolute_regret"], item["semantic"]
        lines.append(f"| {item['id']} | `{','.join(str(value) for value in item['margins'])}` | {item['metrics']['mean_normalized_regret']:.6f} | {absolute['mean_squared']:.6f} | {absolute['tail_mean']['top_0.01']:.6f} | {semantic['winning_mate_missed']} | {semantic['nonlosing_to_losing']} |")
    if complete:
        lines.extend(["", "## Sequential semantic filtering", "", "Worst configured fractions are discarded sequentially; ties at each cutoff are retained.", "", "| Metric | Before | Cutoff retained | Discarded | After |", "|---|---:|---:|---:|---:|"])
        for item in filtering:
            cutoff = "-" if item["cutoff"] is None else str(item["cutoff"])
            lines.append(f"| {item['metric']} | {item['before']} | {cutoff} | {len(item['discarded'])} | {item['after']} |")
        lines.extend(["", "## Untouched-selection shortlist", "", "| ID | Margins |", "|---|---|"])
        for item in shortlisted:
            lines.append(f"| {item['id']} | `{','.join(str(value) for value in item['margins'])}` |")
    else:
        lines.extend(["", "Search is incomplete; rerun with the same manifest to continue."])
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def run(settings: Settings, run_dir: Path, max_work_units: int = 0) -> Dict[str, Any]:
    if max_work_units < 0:
        raise optimize_futility.OptimizationError("max_work_units must be >= 0")
    state_path = run_dir / "state.json"
    state = load_state(state_path, settings)
    work_units_completed = 0
    if "initial" not in evaluation_index(state) and (not max_work_units or work_units_completed < max_work_units):
        initial_candidate = probe_one(settings, run_dir, "initial", settings.initial_margins)
        initial = evaluate(settings, run_dir, "initial", settings.initial_margins, initial_candidate)
        initial["kind"] = "initial"
        state["evaluations"].append(initial)
        state["frontier_ids"] = ["initial"]
        atomic_write(state_path, state)
        work_units_completed += 1
    while state["next_proposal"] < settings.max_proposals and (not max_work_units or work_units_completed < max_work_units):
        frontier_snapshot = current_frontier(state)
        batch_start = state["next_proposal"]
        remaining_budget = settings.max_proposals - batch_start
        if max_work_units:
            remaining_budget = min(remaining_budget, max_work_units - work_units_completed)
        batch_count = min(settings.workers, remaining_budget)
        considered = {
            tune_futility.validate_margins(item["margins"], "Pareto evaluated margins")
            for item in state["evaluations"]
        }
        jobs = []
        for offset in range(batch_count):
            proposal_index = batch_start + offset
            parent, margins, direction, size, duplicate_dismissals = make_unique_proposal(
                frontier_snapshot, settings, proposal_index, considered
            )
            considered.add(margins)
            jobs.append((proposal_index, parent, margins, direction, size, duplicate_dismissals))
        candidates: Dict[int, Mapping[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=settings.workers) as executor:
            futures = {
                executor.submit(probe_one, settings, run_dir, f"candidate-{index:04d}", margins): index
                for index, _, margins, _, _, _ in jobs
            }
            for future in concurrent.futures.as_completed(futures):
                index = futures[future]
                candidates[index] = future.result()
                print(f"Pareto futility progress: proposal {index + 1}/{settings.max_proposals} ready", file=sys.stderr, flush=True)
        for index, parent, margins, direction, size, duplicate_dismissals in jobs:
            identifier = f"candidate-{index:04d}"
            record = evaluate(settings, run_dir, identifier, margins, candidates[index])
            record.update({"kind": "proposal", "proposal_index": index, "parent_id": parent["id"], "parent_margins": list(parent["margins"]), "direction": list(direction), "perturbation": size, "duplicate_tuple_dismissals": duplicate_dismissals, "batch_start": batch_start})
            frontier, update = archive_update(current_frontier(state), record)
            record["archive_update"] = update
            state["evaluations"].append(record)
            state["frontier_ids"] = [item["id"] for item in frontier]
        state["next_proposal"] += batch_count
        atomic_write(state_path, state)
        work_units_completed += batch_count
    state["status"] = "max_proposals"
    if state["next_proposal"] < settings.max_proposals:
        state["status"] = "running"
    atomic_write(state_path, state)
    return write_result(settings, run_dir, state, work_units_completed)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run full-development Pareto futility-margin search.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-work-units", type=int, default=0, help="Maximum initial/proposal probes this invocation; 0 means unlimited.")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(Path(args.config).resolve())
        value = manifest(settings)
        if args.dry_run:
            print(json.dumps(value, indent=2, sort_keys=True))
            return 0
        if args.max_work_units < 0:
            raise optimize_futility.OptimizationError("--max-work-units must be >= 0")
        run_dir = Path(args.run_dir).resolve()
        prepare(run_dir, value)
        result = run(settings, run_dir, args.max_work_units)
        print(f"Pareto futility {result['status']} proposals={result['proposal_count']} frontier={len(result['numeric_pareto_frontier'])} shortlist={len(result['selection_shortlist'])} work_units={result['work_units_completed']}")
        return 0
    except (json.JSONDecodeError, OSError, optimize_futility.OptimizationError, spsa_optimizer.OptimizationError, tune_futility.TuningError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
