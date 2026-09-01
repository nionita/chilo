#!/usr/bin/env python3
"""Evaluate final full-development Pareto-frontier tuples on untouched selection.

The script is package-root relative and intentionally separate from the
optimizer's ``run/`` directory.  With no ``--candidate-id`` it evaluates the
mechanical selection shortlist.  An operator may additionally name any tuple
from the final numeric Pareto frontier after manual review.  Valid completed
candidate JSONL files are reused on restart.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import tune_futility


SCHEMA = "chilo.futility_pareto_selection_evaluation.v1"
STATE_SCHEMA = "chilo.futility_pareto_selection_evaluation_state.v1"


def atomic_write(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object: {path}")
    return value


def package_path(root: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} must be a non-empty package-relative path")
    path = (root / value).resolve()
    if root not in path.parents and path != root:
        raise RuntimeError(f"{label} escapes package root: {value}")
    return path


def require_file(root: Path, value: str, label: str) -> Path:
    path = package_path(root, value, label)
    if not path.is_file():
        raise RuntimeError(f"missing {label}: {path}")
    return path


def file_identity(path: Path) -> Dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest(), "size": path.stat().st_size}


def candidate_map(frontier: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    values = frontier.get("numeric_pareto_frontier")
    if not isinstance(values, list):
        raise RuntimeError("Pareto frontier lacks numeric_pareto_frontier")
    result: Dict[str, Mapping[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str):
            raise RuntimeError("invalid numeric Pareto frontier candidate")
        margins = value.get("margins")
        if not isinstance(margins, list) or not margins or not all(isinstance(item, int) and not isinstance(item, bool) for item in margins):
            raise RuntimeError(f"invalid margins for numeric Pareto candidate {value['id']}")
        if margins != sorted(margins):
            raise RuntimeError(f"non-monotonic margins for numeric Pareto candidate {value['id']}")
        if value["id"] in result:
            raise RuntimeError(f"duplicate numeric Pareto candidate id: {value['id']}")
        result[value["id"]] = value
    return result


def selected_ids(frontier: Mapping[str, Any], requested_ids: Sequence[str]) -> List[str]:
    candidates = candidate_map(frontier)
    if requested_ids:
        requested = list(requested_ids)
    else:
        shortlist = frontier.get("selection_shortlist")
        if not isinstance(shortlist, list) or not shortlist:
            raise RuntimeError("Pareto frontier has no mechanical selection shortlist; supply --candidate-id explicitly")
        requested = []
        for value in shortlist:
            if not isinstance(value, dict) or not isinstance(value.get("id"), str):
                raise RuntimeError("invalid Pareto selection shortlist")
            requested.append(value["id"])
    if not requested:
        raise RuntimeError("at least one selection candidate is required")
    unknown = [identifier for identifier in requested if identifier not in candidates]
    if unknown:
        raise RuntimeError(f"requested candidate is not on the final numeric Pareto frontier: {', '.join(unknown)}")
    if len(set(requested)) != len(requested):
        raise RuntimeError("duplicate --candidate-id")
    return requested


def required_config(root: Path, config: Mapping[str, Any]) -> Dict[str, Any]:
    if config.get("schema") != SCHEMA:
        raise RuntimeError(f"unexpected selection-evaluation schema (expected {SCHEMA})")
    required = {
        "source_run_dir", "probe", "weights", "candidate_nodes", "baseline_margins", "score_scale",
        "report_every", "worker_limit", "selection", "required_existing_artifacts",
    }
    unknown = sorted(set(config) - (required | {"schema", "purpose"}))
    missing = sorted(required - set(config))
    if unknown or missing:
        detail = []
        if unknown:
            detail.append("unknown=" + ", ".join(unknown))
        if missing:
            detail.append("missing=" + ", ".join(missing))
        raise RuntimeError("invalid selection-evaluation config: " + "; ".join(detail))
    nodes, workers = config["candidate_nodes"], config["worker_limit"]
    if not isinstance(nodes, int) or isinstance(nodes, bool) or nodes < 1:
        raise RuntimeError("candidate_nodes must be an integer >= 1")
    if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
        raise RuntimeError("worker_limit must be an integer >= 1")
    margins = config["baseline_margins"]
    if not isinstance(margins, list) or not margins or not all(isinstance(item, int) and not isinstance(item, bool) for item in margins) or margins != sorted(margins):
        raise RuntimeError("baseline_margins must be a non-empty nondecreasing integer list")
    selection = config["selection"]
    if not isinstance(selection, dict) or set(selection) != {"id", "input", "anchor_dir", "rescue_dir"}:
        raise RuntimeError("selection must contain only id, input, anchor_dir, and rescue_dir")
    if not isinstance(selection["id"], str) or not selection["id"]:
        raise RuntimeError("selection.id must be a non-empty string")
    source_run = package_path(root, config["source_run_dir"], "source_run_dir")
    if not source_run.is_dir():
        raise RuntimeError(f"missing optimizer run directory: {source_run}")
    probe = require_file(root, config["probe"], "probe")
    weights = require_file(root, config["weights"], "weights")
    expected = config["required_existing_artifacts"]
    if not isinstance(expected, dict) or set(expected) != {"probe_sha256", "weights_sha256", "source_frontier_sha256"}:
        raise RuntimeError("required_existing_artifacts must contain only probe_sha256, weights_sha256, and source_frontier_sha256")
    frontier_path = source_run / "pareto_frontier.json"
    if not frontier_path.is_file():
        raise RuntimeError(f"missing completed optimizer frontier: {frontier_path}")
    for label, path, expected_hash in (
        ("probe", probe, expected["probe_sha256"]),
        ("weights", weights, expected["weights_sha256"]),
        ("source frontier", frontier_path, expected["source_frontier_sha256"]),
    ):
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise RuntimeError(f"required {label} SHA-256 must be a 64-character string")
        actual_hash = file_identity(path)["sha256"]
        if actual_hash != expected_hash:
            raise RuntimeError(f"{label} SHA-256 does not match this selection package: expected {expected_hash}, got {actual_hash}")
    source = require_file(root, selection["input"], "selection input")
    anchor = package_path(root, selection["anchor_dir"], "selection anchor_dir")
    rescue = package_path(root, selection["rescue_dir"], "selection rescue_dir")
    for required_path in (
        anchor / "probes" / "reference.jsonl", anchor / "probes" / "baseline.jsonl",
        rescue / "rescue_reference.jsonl", rescue / "rescue_baseline.jsonl", rescue / "rescue_manifest.json",
        rescue / "combined_population.json",
    ):
        if not required_path.is_file():
            raise RuntimeError(f"missing selection provenance artifact: {required_path}")
    return {
        "source_run": source_run, "probe": probe, "weights": weights, "source": source,
        "anchor": anchor, "rescue": rescue, "selection_id": selection["id"],
    }


def manifest(config_path: Path, paths: Mapping[str, Any]) -> Dict[str, Any]:
    frontier_path = Path(paths["source_run"]) / "pareto_frontier.json"
    return {
        "schema": SCHEMA,
        "config": file_identity(config_path),
        "source_frontier": file_identity(frontier_path),
        "probe": file_identity(Path(paths["probe"])),
        "weights": file_identity(Path(paths["weights"])),
        "selection_input": file_identity(Path(paths["source"])),
        "selection_reference": file_identity(Path(paths["anchor"]) / "probes" / "reference.jsonl"),
        "selection_baseline": file_identity(Path(paths["anchor"]) / "probes" / "baseline.jsonl"),
        "selection_rescue_manifest": file_identity(Path(paths["rescue"]) / "rescue_manifest.json"),
        "selection_rescue_reference": file_identity(Path(paths["rescue"]) / "rescue_reference.jsonl"),
        "selection_rescue_baseline": file_identity(Path(paths["rescue"]) / "rescue_baseline.jsonl"),
    }


def load_state(path: Path, identity: Mapping[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return {"schema": STATE_SCHEMA, "manifest": identity, "candidates": []}
    state = read_json(path, "selection-evaluation state")
    if state.get("schema") != STATE_SCHEMA or state.get("manifest") != identity or not isinstance(state.get("candidates"), list):
        raise RuntimeError("selection-evaluation state does not match the package/configuration; use a new --run-dir")
    return dict(state)


def run_candidate(config: Mapping[str, Any], paths: Mapping[str, Any], run_dir: Path, candidate: Mapping[str, Any]) -> Dict[str, Any]:
    identifier = str(candidate["id"])
    margins = candidate["margins"]
    output = run_dir / "probes" / f"{identifier}.jsonl"
    log = run_dir / "logs" / f"{identifier}.log"
    try:
        if output.is_file():
            tune_futility.parse_probe_output(output, int(config["candidate_nodes"]), tuple(margins))
            return {"id": identifier, "margins": margins, "output": file_identity(output), "reused": True}
    except tune_futility.TuningError:
        pass
    command = [
        str(paths["probe"]), "--nodes", str(config["candidate_nodes"]), "--futility-margins", ",".join(str(value) for value in margins),
        "--report-every", str(config["report_every"]), "--output", str(output), "--overwrite", "--weights", str(paths["weights"]), str(paths["source"]),
    ]
    with log.open("w", encoding="utf-8") as handle:
        handle.write("command=" + json.dumps(command) + "\n")
        handle.flush()
        completed = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, text=True, check=False)
        handle.write(f"exit_code={completed.returncode}\n")
    if completed.returncode:
        raise RuntimeError(f"selection probe failed for {identifier}; see {log}")
    tune_futility.parse_probe_output(output, int(config["candidate_nodes"]), tuple(margins))
    return {"id": identifier, "margins": margins, "output": file_identity(output), "reused": False}


def analyze(config: Mapping[str, Any], paths: Mapping[str, Any], run_dir: Path, state: Mapping[str, Any]) -> None:
    variants = [{"id": "f01", "margins": config["baseline_margins"], "output": str(Path(paths["anchor"]) / "probes" / "baseline.jsonl")}]
    for candidate in state["candidates"]:
        variants.append({"id": candidate["id"], "margins": candidate["margins"], "output": str(run_dir / "probes" / f"{candidate['id']}.jsonl")})
    risk_config = {
        "candidate_nodes": config["candidate_nodes"], "baseline_margins": config["baseline_margins"], "score_scale": config["score_scale"],
        "development": {"reference_dir": str(paths["anchor"]), "contract": "per_root_v1", "rescue_dir": str(paths["rescue"])},
        "variants": variants, "tail_fractions": [0.05, 0.01], "regret_thresholds": [0.1, 0.25, 0.5, 1.0],
        "semantic_thresholds": {"advantage_cp": 150, "loss_cp": -150},
    }
    risk_config_path = run_dir / "risk_config.json"
    atomic_write(risk_config_path, risk_config)
    analyzer = Path(__file__).resolve().parent / "analyze_futility_risk.py"
    subprocess.run([sys.executable, str(analyzer), "--config", str(risk_config_path), "--output-dir", str(run_dir / "risk-analysis")], cwd=run_dir.parent, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--run-dir", default="selection-r2m")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    config_path = package_path(root, args.config, "config")
    config = read_json(config_path, "selection-evaluation config")
    paths = required_config(root, config)
    frontier_path = Path(paths["source_run"]) / "pareto_frontier.json"
    if not frontier_path.is_file():
        raise RuntimeError(f"missing completed optimizer frontier: {frontier_path}")
    frontier = read_json(frontier_path, "Pareto frontier")
    if frontier.get("schema") != "chilo.futility_pareto_search.v4" or frontier.get("status") != "max_proposals":
        raise RuntimeError("selection requires a completed v4 Pareto frontier")
    identifiers = selected_ids(frontier, args.candidate_id)
    candidates = candidate_map(frontier)
    if args.dry_run:
        print(f"validated {len(identifiers)} untouched-selection candidate(s); worker ceiling={config['worker_limit']}")
        for identifier in identifiers:
            print(f"{identifier}: margins={','.join(str(value) for value in candidates[identifier]['margins'])}")
        return 0

    run_dir = package_path(root, args.run_dir, "run-dir")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "probes").mkdir(exist_ok=True)
    (run_dir / "logs").mkdir(exist_ok=True)
    identity = manifest(config_path, paths)
    state_path = run_dir / "state.json"
    state = load_state(state_path, identity)
    known = {str(value.get("id")): value for value in state["candidates"] if isinstance(value, dict)}
    for identifier in identifiers:
        candidate = candidates[identifier]
        existing = known.get(identifier)
        if existing is not None and existing.get("margins") != candidate["margins"]:
            raise RuntimeError(f"selection state has different margins for {identifier}; use a new --run-dir")
        if existing is None:
            record = {"id": identifier, "margins": candidate["margins"], "source_frontier": file_identity(frontier_path)}
            state["candidates"].append(record)
            known[identifier] = record
    atomic_write(run_dir / "selection_manifest.json", identity)
    atomic_write(state_path, state)

    pending = [known[identifier] for identifier in identifiers]
    workers = min(int(config["worker_limit"]), len(pending))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_candidate, config, paths, run_dir, candidate) for candidate in pending]
        for future in concurrent.futures.as_completed(futures):
            outcome = future.result()
            known[outcome["id"]].update(outcome)
            atomic_write(state_path, state)
            print(f"selection progress: {outcome['id']} {'reused' if outcome['reused'] else 'complete'}", file=sys.stderr, flush=True)
    analyze(config, paths, run_dir, state)
    atomic_write(run_dir / "selection_results.json", {"schema": SCHEMA, "manifest": identity, "candidates": state["candidates"], "risk_results": file_identity(run_dir / "risk-analysis" / "risk_results.json")})
    print(f"selection evaluation complete: {len(state['candidates'])} candidate(s) under {run_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise SystemExit(1)
