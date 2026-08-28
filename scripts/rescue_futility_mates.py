#!/usr/bin/env python3
"""Post-anchor mate rescue for rejected per-root futility positions.

Completed anchors are immutable.  This runner masks their rejected input rows,
uses the probe's dedicated rescue contract, and optionally scores supplied
candidate JSONL files on the rescued and combined trusted populations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import tune_futility


SCHEMA = "chilo.futility_mate_rescue.v1"
RESCUE_MODE = "per_root_mate_rescue_v1"
Key = Tuple[str, int, str]


class RescueError(RuntimeError):
    pass


def read_json(path: Path) -> Dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RescueError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise RescueError(f"{path}: root must be an object")
    return result


def resolve(config_path: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (config_path.parent / path).resolve()


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RescueError(f"{name} must be a non-empty string")
    return value


def require_int(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RescueError(f"{name} must be an integer >= {minimum}")
    return value


def identity(path: Path) -> Dict[str, Any]:
    return tune_futility.file_identity(path)


def atomic_write(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_rescue(path: Path, nodes: int, margins: Sequence[int], baseline_nodes: int, gap: int) -> Dict[str, Any]:
    positions: Dict[Key, Dict[str, Any]] = {}
    summary: Optional[Dict[str, Any]] = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RescueError(f"cannot read rescue output {path}: {exc}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RescueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(record, dict):
            raise RescueError(f"{path}:{line_number}: record must be an object")
        if record.get("type") == "summary":
            if summary is not None:
                raise RescueError(f"{path}:{line_number}: duplicate summary")
            summary = record
            continue
        if record.get("type") != "position":
            raise RescueError(f"{path}:{line_number}: unknown record type")
        if record.get("reference_mode") != RESCUE_MODE or record.get("all_root_scores") is not True:
            raise RescueError(f"{path}:{line_number}: not a mate-rescue record")
        if record.get("node_limit") != nodes or record.get("baseline_node_limit") != baseline_nodes:
            raise RescueError(f"{path}:{line_number}: node budget mismatch")
        if record.get("futility_margins") != list(margins):
            raise RescueError(f"{path}:{line_number}: margins mismatch")
        status = record.get("reference_status")
        if status not in ("rescued", "not_rescued", "terminal"):
            raise RescueError(f"{path}:{line_number}: invalid rescue status")
        if status == "rescued":
            scores = record.get("root_scores")
            depths = record.get("root_score_depths")
            if not isinstance(scores, dict) or not scores or not isinstance(depths, dict) or set(scores) != set(depths):
                raise RescueError(f"{path}:{line_number}: rescued record lacks matching root maps")
            if record.get("score") != max(scores.values()) or record.get("bestmove") not in scores:
                raise RescueError(f"{path}:{line_number}: invalid rescued best root")
            if int(record.get("mate_score", 0)) < tune_futility.MATE_SCORE_FLOOR:
                raise RescueError(f"{path}:{line_number}: rescued record does not certify a winning mate")
        key = tune_futility.record_key(record)
        if key in positions:
            raise RescueError(f"{path}:{line_number}: duplicate position")
        positions[key] = record
    if summary is None or summary.get("reference_mode") != RESCUE_MODE:
        raise RescueError(f"{path}: missing mate-rescue summary")
    if summary.get("positions") != len(positions) or summary.get("node_limit") != nodes:
        raise RescueError(f"{path}: invalid mate-rescue summary")
    if summary.get("baseline_node_limit") != baseline_nodes or summary.get("reference_depth_gap") != gap:
        raise RescueError(f"{path}: mate-rescue contract mismatch")
    return {"positions": positions, "summary": summary}


def rejected_keys(reference: Mapping[str, Any]) -> List[Key]:
    return sorted(key for key, record in reference["positions"].items() if record.get("reference_status") == "rejected")


def write_masked_inputs(inputs: Sequence[Path], keys: Sequence[Key], output_dir: Path) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = {(source, line) for source, line, _ in keys}
    outputs = []
    for source in inputs:
        lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
        destination = output_dir / source.name
        contents = "".join(
            line if line_number == 1 or (source.name, line_number) in selected else "\n"
            for line_number, line in enumerate(lines, 1)
        )
        destination.write_text(contents, encoding="utf-8")
        outputs.append(destination)
    return outputs


def rescue_as_reference(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Adapt a verified rescue record for the existing regret calculator."""
    result = dict(record)
    result["reference_mode"] = tune_futility.REFERENCE_MODE
    result["reference_status"] = "complete"
    result["target_depth"] = result["completed_depth"]
    result["completed_root_moves"] = result["legal_root_moves"]
    return result


def parse_settings(config_path: Path) -> Dict[str, Any]:
    raw_bytes = config_path.read_bytes()
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise RescueError(f"invalid JSON {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RescueError(f"{config_path}: root must be an object")
    allowed = {"anchor_dir", "probe", "inputs", "weights", "candidate_nodes", "reference_nodes_per_root", "reference_depth_gap", "baseline_margins", "report_every", "candidates"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise RescueError(f"unknown config field(s): {', '.join(unknown)}")
    anchor_dir = resolve(config_path, require_string(raw.get("anchor_dir"), "anchor_dir"))
    probe = resolve(config_path, require_string(raw.get("probe"), "probe"))
    inputs_raw = raw.get("inputs")
    if not isinstance(inputs_raw, list) or not inputs_raw:
        raise RescueError("inputs must be a non-empty list")
    inputs = [resolve(config_path, require_string(item, "input")) for item in inputs_raw]
    weights_raw = raw.get("weights")
    weights = resolve(config_path, require_string(weights_raw, "weights")) if weights_raw is not None else None
    if not probe.is_file() or any(not path.is_file() for path in inputs) or (weights is not None and not weights.is_file()):
        raise RescueError("probe, inputs, and optional weights must exist")
    margins = tune_futility.validate_margins(raw.get("baseline_margins"), "baseline_margins")
    return {"raw": raw, "config": {"path": str(config_path), "sha256": hashlib.sha256(raw_bytes).hexdigest()}, "anchor_dir": anchor_dir, "probe": probe, "inputs": inputs, "weights": weights, "candidate_nodes": require_int(raw.get("candidate_nodes"), "candidate_nodes", 1), "reference_nodes_per_root": require_int(raw.get("reference_nodes_per_root"), "reference_nodes_per_root", 1), "reference_depth_gap": require_int(raw.get("reference_depth_gap"), "reference_depth_gap", 1), "baseline_margins": margins, "report_every": require_int(raw.get("report_every", 100), "report_every", 0)}


def manifest(settings: Mapping[str, Any], anchor: Mapping[str, Any]) -> Dict[str, Any]:
    return {"schema": SCHEMA, "config": settings["config"], "probe": identity(settings["probe"]), "inputs": [identity(path) for path in settings["inputs"]], "weights": identity(settings["weights"]) if settings["weights"] else None, "anchor": {"directory": str(settings["anchor_dir"]), "reference": identity(settings["anchor_dir"] / "probes" / "reference.jsonl"), "baseline": identity(settings["anchor_dir"] / "probes" / "baseline.jsonl"), "rejected_position_count": len(rejected_keys(anchor))}, "candidate_nodes": settings["candidate_nodes"], "reference_nodes_per_root": settings["reference_nodes_per_root"], "reference_depth_gap": settings["reference_depth_gap"], "baseline_margins": list(settings["baseline_margins"])}


def run(settings: Mapping[str, Any], run_dir: Path) -> Dict[str, Any]:
    reference_path = settings["anchor_dir"] / "probes" / "reference.jsonl"
    baseline_path = settings["anchor_dir"] / "probes" / "baseline.jsonl"
    reference = tune_futility.parse_probe_output(reference_path, settings["reference_nodes_per_root"], settings["baseline_margins"], True, True, settings["candidate_nodes"], settings["reference_depth_gap"])
    baseline = tune_futility.parse_probe_output(baseline_path, settings["candidate_nodes"], settings["baseline_margins"])
    value = manifest(settings, reference)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "rescue_manifest.json"
    if manifest_path.exists() and read_json(manifest_path) != value:
        raise RescueError("rescue manifest mismatch; use a new run directory")
    if not manifest_path.exists():
        atomic_write(manifest_path, value)
    keys = rejected_keys(reference)
    masked_inputs = write_masked_inputs(settings["inputs"], keys, run_dir / "input")
    rescue_path = run_dir / "rescue_reference.jsonl"
    rescue_baseline_path = run_dir / "rescue_baseline.jsonl"
    try:
        rescue = parse_rescue(rescue_path, settings["reference_nodes_per_root"], settings["baseline_margins"], settings["candidate_nodes"], settings["reference_depth_gap"])
        rescue_baseline = tune_futility.parse_probe_output(rescue_baseline_path, settings["candidate_nodes"], settings["baseline_margins"])
    except (RescueError, tune_futility.TuningError):
        command = [str(settings["probe"]), "--per-root-mate-rescue", "--baseline-nodes", str(settings["candidate_nodes"]), "--reference-nodes-per-root", str(settings["reference_nodes_per_root"]), "--reference-depth-gap", str(settings["reference_depth_gap"]), "--futility-margins", ",".join(str(value) for value in settings["baseline_margins"]), "--baseline-output", str(rescue_baseline_path), "--output", str(rescue_path), "--overwrite", "--report-every", str(settings["report_every"])]
        if settings["weights"] is not None:
            command += ["--weights", str(settings["weights"])]
        command += [str(path) for path in masked_inputs]
        log_path = run_dir / "rescue.log"
        with log_path.open("w", encoding="utf-8") as log:
            log.write("command=" + json.dumps(command) + "\n")
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, text=True, check=False)
            log.write(f"exit_code={completed.returncode}\n")
        if completed.returncode:
            raise RescueError(f"mate rescue probe failed; see {log_path}")
        rescue = parse_rescue(rescue_path, settings["reference_nodes_per_root"], settings["baseline_margins"], settings["candidate_nodes"], settings["reference_depth_gap"])
        rescue_baseline = tune_futility.parse_probe_output(rescue_baseline_path, settings["candidate_nodes"], settings["baseline_margins"])
    rescued_keys = sorted(key for key, record in rescue["positions"].items() if record.get("reference_status") == "rescued")
    rescued_reference = {"positions": {key: rescue_as_reference(rescue["positions"][key]) for key in rescued_keys}, "summary": rescue["summary"]}
    rescue_baseline_positions = {"positions": {key: rescue_baseline["positions"][key] for key in rescued_keys}, "summary": rescue_baseline["summary"]}
    ordinary_trusted, ordinary_trusted_keys = tune_futility.trusted_position_set(
        reference, baseline, settings["reference_depth_gap"]
    )
    combined_keys = sorted(set(ordinary_trusted_keys) | set(rescued_keys))
    candidates = []
    for item in settings["raw"].get("candidates", []):
        if not isinstance(item, dict) or set(item) - {"id", "margins", "output"}:
            raise RescueError("candidate must contain only id, margins, output")
        candidate_id = require_string(item.get("id"), "candidate.id")
        margins = tune_futility.validate_margins(item.get("margins"), f"candidate {candidate_id} margins")
        output = resolve(Path(settings["raw"].get("_config_path", ".")), require_string(item.get("output"), "candidate.output"))
        candidate = tune_futility.parse_probe_output(output, settings["candidate_nodes"], margins)
        rescue_candidate = {"positions": {key: candidate["positions"][key] for key in rescued_keys}, "summary": candidate["summary"]}
        rescue_metrics = tune_futility.compute_metrics(rescued_reference, rescue_baseline_positions, rescue_candidate, settings["candidate_nodes"], 600.0, rescued_keys) if rescued_keys else None
        merged_reference = {"positions": dict(reference["positions"]), "summary": reference["summary"]}
        merged_reference["positions"].update(rescued_reference["positions"])
        combined_metrics = tune_futility.compute_metrics(merged_reference, baseline, candidate, settings["candidate_nodes"], 600.0, combined_keys)
        candidates.append({"id": candidate_id, "margins": list(margins), "output": identity(output), "rescue_metrics": rescue_metrics, "combined_metrics": combined_metrics})
    result = {"schema": SCHEMA, "ordinary_trusted_set": ordinary_trusted, "rejected_position_count": len(keys), "rescued_position_count": len(rescued_keys), "combined_position_count": len(combined_keys), "rescued_position_keys": [list(key) for key in rescued_keys], "rescue_reference": identity(rescue_path), "rescue_baseline": identity(rescue_baseline_path), "candidates": candidates}
    atomic_write(run_dir / "rescue_results.json", result)
    atomic_write(run_dir / "combined_population.json", {"schema": SCHEMA, "ordinary_trusted_set": ordinary_trusted, "rescued_position_count": len(rescued_keys), "combined_position_count": len(combined_keys), "position_keys": [list(key) for key in combined_keys]})
    lines = ["# Futility mate-rescue results", "", f"Rejected inputs: `{len(keys)}`", f"Reference-proven rescued mates: `{len(rescued_keys)}`", f"Combined ordinary-trusted plus rescue population: `{len(combined_keys)}`"]
    if candidates:
        lines.extend(["", "| Candidate | Margins | Rescue mean regret | Combined mean regret |", "|---|---|---:|---:|"])
        for candidate in candidates:
            rescue_mean = "n/a" if candidate["rescue_metrics"] is None else f"{candidate['rescue_metrics']['mean_normalized_regret']:.6f}"
            lines.append(f"| {candidate['id']} | `{','.join(str(value) for value in candidate['margins'])}` | {rescue_mean} | {candidate['combined_metrics']['mean_normalized_regret']:.6f} |")
    (run_dir / "rescue_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Rescue reference-proven mate positions from rejected per-root anchors.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args(argv)
    try:
        config_path = Path(args.config).resolve()
        settings = parse_settings(config_path)
        settings["raw"]["_config_path"] = str(config_path)
        result = run(settings, Path(args.run_dir).resolve())
        print(f"mate rescue rejected={result['rejected_position_count']} rescued={result['rescued_position_count']}")
        return 0
    except (RescueError, tune_futility.TuningError, OSError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
