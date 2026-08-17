#!/usr/bin/env python3

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA = "chilo.futility_tuning.v2"
RESULTS_SCHEMA = "chilo.futility_tuning_results.v2"
MAX_FUTILITY_DEPTH = 7
MATE_SCORE_FLOOR = 28936  # SEARCH_MATE_SCORE - MAX_SEARCH_DEPTH in engine.h


class TuningError(RuntimeError):
    pass


def require_int(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TuningError(f"{name} must be an integer >= {minimum}")
    return value


def require_number_list(value: Any, name: str) -> List[float]:
    if not isinstance(value, list) or not value:
        raise TuningError(f"{name} must be a non-empty list")
    result = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise TuningError(f"{name}[{index}] must be a finite number")
        result.append(float(item))
    return result


def require_path(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TuningError(f"{name} must be a non-empty path string")
    return value


def require_path_list(value: Any, name: str) -> List[str]:
    if not isinstance(value, list) or not value:
        raise TuningError(f"{name} must be a non-empty list of path strings")
    return [require_path(item, f"{name}[{index}]") for index, item in enumerate(value)]


def validate_margins(value: Any, name: str) -> Tuple[int, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_FUTILITY_DEPTH:
        raise TuningError(f"{name} must contain 1 to {MAX_FUTILITY_DEPTH} margins")
    margins = []
    for index, margin in enumerate(value):
        margins.append(require_int(margin, f"{name}[{index}]"))
    if any(left > right for left, right in zip(margins, margins[1:])):
        raise TuningError(f"{name} must be nondecreasing")
    return tuple(margins)


def rounded_margin(value: float) -> int:
    if not math.isfinite(value):
        raise TuningError("formula generated a non-finite margin")
    return int(math.floor(value + 0.5))


def candidate_key(margins: Sequence[int]) -> str:
    digest = hashlib.sha256(",".join(str(value) for value in margins).encode("ascii")).hexdigest()[:10]
    return f"d{len(margins)}-{digest}"


def expand_config(raw: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = {
        "candidate_nodes",
        "reference_nodes",
        "baseline_margins",
        "shortlist_size",
        "probe_report_every",
        "score_scale",
        "probe",
        "inputs",
        "weights",
        "explicit_candidates",
        "families",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise TuningError(f"unknown config field(s): {', '.join(unknown)}")

    candidate_nodes = require_int(raw.get("candidate_nodes"), "candidate_nodes", 1)
    reference_nodes = require_int(raw.get("reference_nodes"), "reference_nodes", 1)
    if reference_nodes <= candidate_nodes:
        raise TuningError("reference_nodes must be greater than candidate_nodes")
    baseline = validate_margins(raw.get("baseline_margins"), "baseline_margins")
    shortlist_size = require_int(raw.get("shortlist_size", 15), "shortlist_size", 1)
    report_every = require_int(raw.get("probe_report_every", 100), "probe_report_every")
    score_scale_raw = raw.get("score_scale", 600)
    if isinstance(score_scale_raw, bool) or not isinstance(score_scale_raw, (int, float)) or score_scale_raw <= 0:
        raise TuningError("score_scale must be a finite number > 0")
    score_scale = float(score_scale_raw)
    if not math.isfinite(score_scale):
        raise TuningError("score_scale must be a finite number > 0")
    probe_default = require_path(raw["probe"], "probe") if "probe" in raw else None
    input_defaults = require_path_list(raw["inputs"], "inputs") if "inputs" in raw else []
    weights_default = require_path(raw["weights"], "weights") if "weights" in raw else None

    candidates: Dict[Tuple[int, ...], Dict[str, Any]] = {}
    discarded: List[Dict[str, Any]] = []

    def add_candidate(margins: Tuple[int, ...], origin: str) -> None:
        if margins == baseline:
            discarded.append({"origin": origin, "margins": list(margins), "reason": "baseline"})
            return
        existing = candidates.get(margins)
        if existing is None:
            candidates[margins] = {"margins": list(margins), "origins": [origin]}
        else:
            existing["origins"].append(origin)

    explicit = raw.get("explicit_candidates", [])
    if not isinstance(explicit, list):
        raise TuningError("explicit_candidates must be a list")
    for index, value in enumerate(explicit):
        add_candidate(validate_margins(value, f"explicit_candidates[{index}]"), f"explicit[{index}]")

    families = raw.get("families", [])
    if not isinstance(families, list):
        raise TuningError("families must be a list")
    for family_index, family in enumerate(families):
        if not isinstance(family, dict):
            raise TuningError(f"families[{family_index}] must be an object")
        family_type = family.get("type")
        depths_raw = family.get("depths")
        if not isinstance(depths_raw, list) or not depths_raw:
            raise TuningError(f"families[{family_index}].depths must be a non-empty list")
        depths = [require_int(value, f"families[{family_index}].depths", 1) for value in depths_raw]
        if any(depth > MAX_FUTILITY_DEPTH for depth in depths):
            raise TuningError(f"families[{family_index}].depths cannot exceed {MAX_FUTILITY_DEPTH}")

        generated: Iterable[Tuple[str, Tuple[int, ...]]]
        if family_type == "linear":
            allowed_family = {"type", "depths", "slopes", "intercepts"}
            unknown_family = sorted(set(family) - allowed_family)
            if unknown_family:
                raise TuningError(
                    f"unknown linear family field(s): {', '.join(unknown_family)}"
                )
            slopes = require_number_list(family.get("slopes"), f"families[{family_index}].slopes")
            intercepts = require_number_list(
                family.get("intercepts"), f"families[{family_index}].intercepts"
            )
            generated = (
                (
                    f"linear[{family_index}]:depth={depth},slope={slope:g},intercept={intercept:g}",
                    tuple(rounded_margin(slope * ply + intercept) for ply in range(1, depth + 1)),
                )
                for depth in depths
                for slope in slopes
                for intercept in intercepts
            )
        elif family_type == "power":
            allowed_family = {"type", "depths", "scales", "exponents"}
            unknown_family = sorted(set(family) - allowed_family)
            if unknown_family:
                raise TuningError(
                    f"unknown power family field(s): {', '.join(unknown_family)}"
                )
            scales = require_number_list(family.get("scales"), f"families[{family_index}].scales")
            exponents = require_number_list(
                family.get("exponents"), f"families[{family_index}].exponents"
            )
            generated = (
                (
                    f"power[{family_index}]:depth={depth},scale={scale:g},exponent={exponent:g}",
                    tuple(rounded_margin(scale * (ply**exponent)) for ply in range(1, depth + 1)),
                )
                for depth in depths
                for scale in scales
                for exponent in exponents
            )
        else:
            raise TuningError(f"families[{family_index}].type must be 'linear' or 'power'")

        for origin, margins in generated:
            try:
                validated = validate_margins(list(margins), origin)
            except TuningError as exc:
                discarded.append({"origin": origin, "margins": list(margins), "reason": str(exc)})
                continue
            add_candidate(validated, origin)

    if not candidates:
        raise TuningError("configuration produced no non-baseline candidates")

    expanded_candidates = []
    for index, candidate in enumerate(candidates.values(), start=1):
        margins = candidate["margins"]
        expanded_candidates.append(
            {
                "id": f"candidate-{index:04d}-{candidate_key(margins)}",
                "margins": margins,
                "origins": candidate["origins"],
            }
        )

    return {
        "candidate_nodes": candidate_nodes,
        "reference_nodes": reference_nodes,
        "baseline_margins": list(baseline),
        "shortlist_size": shortlist_size,
        "probe_report_every": report_every,
        "score_scale": score_scale,
        "probe": probe_default,
        "inputs": input_defaults,
        "weights": weights_default,
        "candidates": expanded_candidates,
        "discarded": discarded,
    }


def load_and_expand_config(path: Path) -> Tuple[Dict[str, Any], str]:
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise TuningError(f"failed to read config {path}: {exc}") from exc
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise TuningError(f"invalid JSON config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise TuningError("config root must be an object")
    return expand_config(raw), hashlib.sha256(raw_bytes).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    except OSError as exc:
        raise TuningError(f"failed to hash {path}: {exc}") from exc
    return digest.hexdigest()


def file_identity(path: Path) -> Dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise TuningError(f"file does not exist: {resolved}")
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "size": stat.st_size,
        "sha256": sha256_file(resolved),
    }


def build_manifest(
    config_path: Path,
    config_sha256: str,
    expanded: Mapping[str, Any],
    probe: Path,
    inputs: Sequence[Path],
    weights: Optional[Path],
) -> Dict[str, Any]:
    # Paths in the config are execution defaults, not immutable run artifacts.
    # The manifest records only the resolved artifacts actually used.
    manifest_expanded = {key: value for key, value in expanded.items() if key not in {"probe", "inputs", "weights"}}
    return {
        "schema": SCHEMA,
        "config": file_identity(config_path),
        "config_sha256": config_sha256,
        "expanded_config": manifest_expanded,
        "probe": file_identity(probe),
        "weights": file_identity(weights) if weights is not None else None,
        "inputs": [file_identity(path) for path in inputs],
    }


def resolve_config_path(config_path: Path, path_text: str) -> Path:
    path = Path(path_text)
    return (config_path.parent / path).resolve() if not path.is_absolute() else path.resolve()


def resolve_effective_artifacts(
    config_path: Path, expanded: Mapping[str, Any], args: argparse.Namespace
) -> Tuple[Path, List[Path], Optional[Path]]:
    probe_text = args.probe if args.probe else expanded.get("probe")
    input_texts = args.input if args.input else expanded.get("inputs", [])
    if not probe_text:
        raise TuningError("--probe is required unless config.probe is set")
    if not input_texts:
        raise TuningError("at least one --input is required unless config.inputs is set")
    probe = Path(probe_text).resolve() if args.probe else resolve_config_path(config_path, probe_text)
    inputs = (
        [Path(path).resolve() for path in input_texts]
        if args.input
        else [resolve_config_path(config_path, path) for path in input_texts]
    )
    if args.no_weights:
        weights = None
    elif args.weights:
        weights = Path(args.weights).resolve()
    elif expanded.get("weights"):
        weights = resolve_config_path(config_path, expanded["weights"])
    else:
        weights = None
    return probe, inputs, weights


def atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def prepare_run_directory(run_dir: Path, manifest: Mapping[str, Any], resume: bool) -> None:
    manifest_path = run_dir / "manifest.json"
    if resume:
        if not manifest_path.is_file():
            raise TuningError(f"cannot resume: missing {manifest_path}")
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TuningError(f"cannot resume: invalid manifest: {exc}") from exc
        if existing != manifest:
            raise TuningError("cannot resume: run manifest does not match current inputs or configuration")
    else:
        if run_dir.exists() and any(run_dir.iterdir()):
            raise TuningError(f"run directory is not empty: {run_dir}")
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(manifest_path, manifest)
    (run_dir / "probes").mkdir(exist_ok=True)
    (run_dir / "logs").mkdir(exist_ok=True)


def margins_text(margins: Sequence[int]) -> str:
    return ",".join(str(value) for value in margins)


def build_probe_command(
    probe: Path,
    inputs: Sequence[Path],
    weights: Optional[Path],
    nodes: int,
    margins: Sequence[int],
    output_path: Path,
    report_every: int,
    all_root_scores: bool = False,
) -> List[str]:
    command = [
        str(probe.resolve()),
        "--nodes",
        str(nodes),
        "--futility-margins",
        margins_text(margins),
        "--report-every",
        str(report_every),
        "--output",
        str(output_path.resolve()),
        "--overwrite",
    ]
    if weights is not None:
        command.extend(["--weights", str(weights.resolve())])
    if all_root_scores:
        command.append("--all-root-scores")
    command.extend(str(path.resolve()) for path in inputs)
    return command


def record_key(record: Mapping[str, Any]) -> Tuple[str, int, str]:
    try:
        source = record["source"]
        line = record["line"]
        fen = record["fen"]
    except KeyError as exc:
        raise TuningError(f"position record missing {exc.args[0]}") from exc
    if (
        not isinstance(source, str)
        or isinstance(line, bool)
        or not isinstance(line, int)
        or line <= 0
        or not isinstance(fen, str)
    ):
        raise TuningError("position record has an invalid source, line, or FEN")
    return source, line, fen


def validate_root_scores(record: Mapping[str, Any], path: Path, line_number: int) -> None:
    scores = record.get("root_scores")
    if not isinstance(scores, dict) or not scores:
        raise TuningError(f"{path}:{line_number}: reference root_scores must be a non-empty object")
    for move, score in scores.items():
        valid_move = (
            isinstance(move, str)
            and len(move) in (4, 5)
            and move[0] in "abcdefgh"
            and move[1] in "12345678"
            and move[2] in "abcdefgh"
            and move[3] in "12345678"
            and (len(move) == 4 or move[4] in "qrbn")
        )
        if not valid_move or not isinstance(score, int) or isinstance(score, bool):
            raise TuningError(f"{path}:{line_number}: root_scores must map UCI move strings to integer scores")
    bestmove = record["bestmove"]
    if bestmove not in scores:
        raise TuningError(f"{path}:{line_number}: root_scores does not contain bestmove")
    if scores[bestmove] != record["score"]:
        raise TuningError(f"{path}:{line_number}: root_scores bestmove score does not match score")
    if record["score"] != max(scores.values()):
        raise TuningError(f"{path}:{line_number}: root_scores bestmove is not a highest-scoring root move")


def validate_position_record(
    record: Mapping[str, Any], path: Path, line_number: int, all_root_scores: bool
) -> None:
    integer_fields = ("node_limit", "nodes", "completed_nodes", "completed_depth", "elapsed_ms", "score")
    boolean_fields = ("iteration_interrupted", "terminal", "has_move")
    for field in integer_fields:
        if isinstance(record.get(field), bool) or not isinstance(record.get(field), int):
            raise TuningError(f"{path}:{line_number}: position field {field} must be an integer")
        if field != "score" and record[field] < 0:
            raise TuningError(f"{path}:{line_number}: position field {field} cannot be negative")
    if record["completed_nodes"] > record["nodes"]:
        raise TuningError(f"{path}:{line_number}: completed_nodes cannot exceed nodes")
    for field in boolean_fields:
        if not isinstance(record.get(field), bool):
            raise TuningError(f"{path}:{line_number}: position field {field} must be a boolean")
    if not isinstance(record.get("bestmove"), str):
        raise TuningError(f"{path}:{line_number}: position field bestmove must be a string")
    if record.get("all_root_scores") is not all_root_scores:
        raise TuningError(f"{path}:{line_number}: position all_root_scores does not match expected mode")
    if all_root_scores:
        if not record["terminal"] and record["has_move"] and record["completed_depth"] > 0:
            validate_root_scores(record, path, line_number)
    elif "root_scores" in record:
        raise TuningError(f"{path}:{line_number}: candidate output must not contain root_scores")
    for field in ("futility_prunes", "futility_prunes_in_check"):
        counts = record.get(field)
        if (
            not isinstance(counts, list)
            or len(counts) != MAX_FUTILITY_DEPTH
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts)
        ):
            raise TuningError(
                f"{path}:{line_number}: position field {field} must contain seven nonnegative integers"
            )


def parse_probe_output(
    path: Path, nodes: int, margins: Sequence[int], all_root_scores: bool = False
) -> Dict[str, Any]:
    positions: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
    summary = None
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise TuningError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
                if not isinstance(record, dict):
                    raise TuningError(f"{path}:{line_number}: record must be an object")
                record_type = record.get("type")
                if record_type == "position":
                    if summary is not None:
                        raise TuningError(f"{path}:{line_number}: position follows summary")
                    validate_position_record(record, path, line_number, all_root_scores)
                    if record.get("node_limit") != nodes or record.get("futility_margins") != list(margins):
                        raise TuningError(
                            f"{path}:{line_number}: position does not match expected nodes or margins"
                        )
                    key = record_key(record)
                    if key in positions:
                        raise TuningError(f"{path}:{line_number}: duplicate position record")
                    positions[key] = record
                elif record_type == "summary":
                    if summary is not None:
                        raise TuningError(f"{path}:{line_number}: duplicate summary")
                    summary = record
                else:
                    raise TuningError(f"{path}:{line_number}: unknown record type {record_type!r}")
    except OSError as exc:
        raise TuningError(f"failed to read probe output {path}: {exc}") from exc

    if summary is None:
        raise TuningError(f"{path}: missing summary record")
    if isinstance(summary.get("positions"), bool) or not isinstance(summary.get("positions"), int):
        raise TuningError(f"{path}: summary positions must be an integer")
    if summary.get("node_limit") != nodes or summary.get("futility_margins") != list(margins):
        raise TuningError(f"{path}: summary does not match expected nodes or margins")
    if summary.get("all_root_scores") is not all_root_scores:
        raise TuningError(f"{path}: summary all_root_scores does not match expected mode")
    if summary.get("positions") != len(positions):
        raise TuningError(f"{path}: summary position count does not match records")
    return {"positions": positions, "summary": summary}


def probe_output_complete(
    path: Path, nodes: int, margins: Sequence[int], all_root_scores: bool = False
) -> bool:
    if not path.is_file():
        return False
    try:
        parse_probe_output(path, nodes, margins, all_root_scores)
    except TuningError:
        return False
    return True


def run_probe_job(
    job: Mapping[str, Any],
    probe: Path,
    inputs: Sequence[Path],
    weights: Optional[Path],
    report_every: int,
    run_dir: Path,
    resume: bool,
) -> Dict[str, Any]:
    output_path = run_dir / "probes" / f"{job['id']}.jsonl"
    log_path = run_dir / "logs" / f"{job['id']}.log"
    all_root_scores = bool(job.get("all_root_scores", False))
    if resume and probe_output_complete(output_path, job["nodes"], job["margins"], all_root_scores):
        return {"id": job["id"], "status": "reused", "output": str(output_path)}

    command = build_probe_command(
        probe,
        inputs,
        weights,
        job["nodes"],
        job["margins"],
        output_path,
        report_every,
        all_root_scores,
    )
    with log_path.open("w", encoding="utf-8") as log:
        log.write("command=" + json.dumps(command) + "\n")
        log.flush()
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, text=True, check=False)
        log.write(f"exit_code={completed.returncode}\n")
    if completed.returncode != 0:
        raise TuningError(f"probe job {job['id']} failed; see {log_path}")
    parse_probe_output(output_path, job["nodes"], job["margins"], all_root_scores)
    return {"id": job["id"], "status": "completed", "output": str(output_path)}


def run_jobs(
    jobs: Sequence[Mapping[str, Any]],
    probe: Path,
    inputs: Sequence[Path],
    weights: Optional[Path],
    report_every: int,
    run_dir: Path,
    resume: bool,
    workers: int,
) -> None:
    failures = []
    completed_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_job = {
            executor.submit(
                run_probe_job,
                job,
                probe,
                inputs,
                weights,
                report_every,
                run_dir,
                resume,
            ): job
            for job in jobs
        }
        for future in concurrent.futures.as_completed(future_to_job):
            job = future_to_job[future]
            try:
                outcome = future.result()
                completed_count += 1
                print(
                    f"progress: {completed_count}/{len(jobs)} probe jobs ready "
                    f"({outcome['status']}: {job['id']})",
                    file=sys.stderr,
                    flush=True,
                )
            except Exception as exc:  # preserve all completed artifacts before reporting failures
                failures.append(f"{job['id']}: {exc}")
    if failures:
        raise TuningError("probe job failures:\n" + "\n".join(failures))


def standard_error(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return 0.0
    return statistics.stdev(values) / math.sqrt(len(values))


def percentile(values: Sequence[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def mate_class(score: int) -> int:
    if score >= MATE_SCORE_FLOOR:
        return 1
    if score <= -MATE_SCORE_FLOOR:
        return -1
    return 0


def normalized_score(score: int, score_scale: float) -> float:
    mate = mate_class(score)
    if mate:
        return float(mate)
    return math.tanh(score / score_scale)


def ensure_position_sets(reference: Mapping[str, Any], other: Mapping[str, Any], name: str) -> None:
    reference_keys = set(reference["positions"])
    other_keys = set(other["positions"])
    if reference_keys != other_keys:
        missing = len(reference_keys - other_keys)
        extra = len(other_keys - reference_keys)
        raise TuningError(f"{name}: position set differs from reference (missing={missing}, extra={extra})")


def compute_metrics(
    reference: Mapping[str, Any],
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    candidate_nodes: int,
    score_scale: float = 600.0,
) -> Dict[str, Any]:
    ensure_position_sets(reference, baseline, "baseline")
    ensure_position_sets(reference, candidate, "candidate")

    agreement_values: List[float] = []
    baseline_agreement_values: List[float] = []
    score_errors: List[float] = []
    mate_agreements: List[float] = []
    regrets: List[float] = []
    depths: List[float] = []
    depth_deltas: List[float] = []
    cap_hits = 0
    elapsed_ms = 0
    futility_prunes = [0] * MAX_FUTILITY_DEPTH
    futility_prunes_in_check = [0] * MAX_FUTILITY_DEPTH
    reference_winning_mates = 0
    missed_reference_winning_mates = 0
    mate_claim_categories = {
        "non_mate": 0,
        "winning_confirmed": 0,
        "winning_unconfirmed": 0,
        "losing_confirmed": 0,
        "losing_unconfirmed": 0,
    }

    for key, reference_record in reference["positions"].items():
        baseline_record = baseline["positions"][key]
        candidate_record = candidate["positions"][key]
        elapsed_ms += int(candidate_record.get("elapsed_ms", 0))
        for index, count in enumerate(candidate_record.get("futility_prunes", [])):
            if index < MAX_FUTILITY_DEPTH:
                futility_prunes[index] += int(count)
        for index, count in enumerate(candidate_record.get("futility_prunes_in_check", [])):
            if index < MAX_FUTILITY_DEPTH:
                futility_prunes_in_check[index] += int(count)

        if reference_record.get("terminal") or not reference_record.get("has_move"):
            continue
        if int(reference_record.get("completed_depth", 0)) <= 0:
            continue

        candidate_move = candidate_record.get("bestmove")
        reference_move = reference_record.get("bestmove")
        baseline_move = baseline_record.get("bestmove")
        agreement_values.append(float(candidate_move == reference_move))
        baseline_agreement_values.append(float(candidate_move == baseline_move))

        root_scores = reference_record.get("root_scores")
        if not isinstance(root_scores, dict) or candidate_move not in root_scores:
            raise TuningError(f"candidate move {candidate_move!r} is absent from reference root_scores")
        transformed_scores = [normalized_score(score, score_scale) for score in root_scores.values()]
        selected_reference_score = int(root_scores[candidate_move])
        regret = max(transformed_scores) - normalized_score(selected_reference_score, score_scale)
        regrets.append(regret)
        if any(mate_class(int(score)) == 1 for score in root_scores.values()):
            reference_winning_mates += 1
            if mate_class(selected_reference_score) != 1:
                missed_reference_winning_mates += 1

        candidate_score = int(candidate_record["score"])
        reference_score = int(reference_record["score"])
        candidate_mate = mate_class(candidate_score)
        reference_mate = mate_class(reference_score)
        mate_agreements.append(float(candidate_mate == reference_mate))
        selected_reference_mate = mate_class(selected_reference_score)
        if candidate_mate == 0:
            mate_claim_categories["non_mate"] += 1
        elif candidate_mate == 1:
            mate_claim_categories[
                "winning_confirmed" if selected_reference_mate == 1 else "winning_unconfirmed"
            ] += 1
        else:
            mate_claim_categories[
                "losing_confirmed" if selected_reference_mate == -1 else "losing_unconfirmed"
            ] += 1
        if candidate_mate == 0 and reference_mate == 0:
            score_errors.append(float(abs(candidate_score - reference_score)))

        candidate_depth = float(candidate_record.get("completed_depth", 0))
        baseline_depth = float(baseline_record.get("completed_depth", 0))
        depths.append(candidate_depth)
        depth_deltas.append(candidate_depth - baseline_depth)
        if int(candidate_record.get("nodes", 0)) == candidate_nodes and candidate_record.get(
            "iteration_interrupted"
        ):
            cap_hits += 1

    if not agreement_values:
        raise TuningError("reference contains no nonterminal completed positions")

    return {
        "position_count": len(reference["positions"]),
        "evaluated_positions": len(agreement_values),
        "move_agreement_rate": statistics.mean(agreement_values),
        "move_agreement_se": standard_error(agreement_values),
        "baseline_move_agreement_rate": statistics.mean(baseline_agreement_values),
        "score_cp_positions": len(score_errors),
        "score_mae": statistics.mean(score_errors) if score_errors else None,
        "score_mae_se": standard_error(score_errors),
        "score_median_error": statistics.median(score_errors) if score_errors else None,
        "score_p90_error": percentile(score_errors, 0.90),
        "mate_class_agreement_rate": statistics.mean(mate_agreements),
        "mean_normalized_regret": statistics.mean(regrets),
        "normalized_regret_se": standard_error(regrets),
        "median_normalized_regret": statistics.median(regrets),
        "p90_normalized_regret": percentile(regrets, 0.90),
        "missed_reference_winning_mate_rate": (
            missed_reference_winning_mates / reference_winning_mates if reference_winning_mates else None
        ),
        "reference_winning_mate_positions": reference_winning_mates,
        "candidate_mate_claim_categories": mate_claim_categories,
        "mean_completed_depth": statistics.mean(depths),
        "median_completed_depth": statistics.median(depths),
        "mean_completed_depth_se": standard_error(depths),
        "mean_depth_delta_vs_baseline": statistics.mean(depth_deltas),
        "cap_hit_rate": cap_hits / len(agreement_values),
        "elapsed_ms": elapsed_ms,
        "futility_prunes": futility_prunes,
        "futility_prunes_in_check": futility_prunes_in_check,
    }


def rank_and_select(candidates: List[Dict[str, Any]], shortlist_size: int) -> List[Dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            candidate["metrics"]["mean_normalized_regret"],
            candidate["metrics"]["p90_normalized_regret"],
            candidate["metrics"]["median_normalized_regret"],
            tuple(candidate["margins"]),
        ),
    )
    for rank, candidate in enumerate(ordered, start=1):
        candidate["regret_rank"] = rank
        candidate["selected"] = rank <= shortlist_size
    return [candidate for candidate in ordered if candidate["selected"]]


def flatten_result(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    metrics = candidate["metrics"]
    return {
        "id": candidate["id"],
        "margins": margins_text(candidate["margins"]),
        "origins": ";".join(candidate["origins"]),
        "selected": candidate["selected"],
        "regret_rank": candidate["regret_rank"],
        "mean_normalized_regret": metrics["mean_normalized_regret"],
        "normalized_regret_se": metrics["normalized_regret_se"],
        "median_normalized_regret": metrics["median_normalized_regret"],
        "p90_normalized_regret": metrics["p90_normalized_regret"],
        "missed_reference_winning_mate_rate": metrics["missed_reference_winning_mate_rate"],
        "reference_winning_mate_positions": metrics["reference_winning_mate_positions"],
        "candidate_mate_claim_categories": json.dumps(metrics["candidate_mate_claim_categories"], sort_keys=True),
        "move_agreement_rate": metrics["move_agreement_rate"],
        "move_agreement_se": metrics["move_agreement_se"],
        "score_mae": metrics["score_mae"],
        "score_mae_se": metrics["score_mae_se"],
        "score_median_error": metrics["score_median_error"],
        "score_p90_error": metrics["score_p90_error"],
        "mate_class_agreement_rate": metrics["mate_class_agreement_rate"],
        "mean_completed_depth": metrics["mean_completed_depth"],
        "median_completed_depth": metrics["median_completed_depth"],
        "mean_completed_depth_se": metrics["mean_completed_depth_se"],
        "mean_depth_delta_vs_baseline": metrics["mean_depth_delta_vs_baseline"],
        "baseline_move_agreement_rate": metrics["baseline_move_agreement_rate"],
        "cap_hit_rate": metrics["cap_hit_rate"],
        "elapsed_ms": metrics["elapsed_ms"],
        "futility_prunes": margins_text(metrics["futility_prunes"]),
        "futility_prunes_in_check": margins_text(metrics["futility_prunes_in_check"]),
    }


def write_csv(path: Path, candidates: Sequence[Mapping[str, Any]]) -> None:
    rows = [flatten_result(candidate) for candidate in candidates]
    if not rows:
        raise TuningError("cannot write empty candidate CSV")
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def format_percent(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100.0:.3f}%"


def format_number(value: Optional[float], precision: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{precision}f}"


def build_report(results: Mapping[str, Any]) -> str:
    baseline = results["baseline"]["metrics"]
    lines = [
        "# Futility Proxy Results",
        "",
        f"Candidate budget: `{results['candidate_nodes']}` nodes per position  ",
        f"Reference budget: `{results['reference_nodes']}` nodes per position  ",
        f"Score scale: `{results['score_scale']:g}`  ",
        f"Baseline margins: `{margins_text(results['baseline']['margins'])}`  ",
        f"Positions: `{baseline['position_count']}` total, `{baseline['evaluated_positions']}` evaluated",
        "",
        "The proxy screens candidates only. Playing strength still requires SPRT.",
        "",
        "## Baseline Anchor",
        "",
        f"- Mean normalized score regret: `{baseline['mean_normalized_regret']:.6f}`",
        f"- Reference move agreement: `{format_percent(baseline['move_agreement_rate'])}`",
        f"- Non-mate score MAE: `{format_number(baseline['score_mae'])}` cp",
        f"- Mean completed depth: `{baseline['mean_completed_depth']:.3f}`",
        "",
        "## Shortlist",
        "",
        "| Margins | Regret rank | Mean regret | P90 regret | Median regret | Move agreement |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for candidate in results["shortlist"]:
        metrics = candidate["metrics"]
        lines.append(
            f"| `{margins_text(candidate['margins'])}` | {candidate['regret_rank']} | "
            f"{metrics['mean_normalized_regret']:.6f} | {metrics['p90_normalized_regret']:.6f} | "
            f"{metrics['median_normalized_regret']:.6f} | {format_percent(metrics['move_agreement_rate'])} |"
        )
    lines.extend(
        [
            "",
            "Full per-candidate metrics are in `results.json` and `results.csv`; raw per-position evidence is under `probes/`.",
            "",
        ]
    )
    return "\n".join(lines)


def aggregate_results(run_dir: Path, expanded: Mapping[str, Any]) -> Dict[str, Any]:
    baseline_margins = expanded["baseline_margins"]
    reference = parse_probe_output(
        run_dir / "probes" / "reference.jsonl",
        expanded["reference_nodes"],
        baseline_margins,
        all_root_scores=True,
    )
    baseline = parse_probe_output(
        run_dir / "probes" / "baseline.jsonl",
        expanded["candidate_nodes"],
        baseline_margins,
    )
    baseline_metrics = compute_metrics(
        reference,
        baseline,
        baseline,
        expanded["candidate_nodes"],
        expanded["score_scale"],
    )

    candidates = []
    for candidate_spec in expanded["candidates"]:
        output = parse_probe_output(
            run_dir / "probes" / f"{candidate_spec['id']}.jsonl",
            expanded["candidate_nodes"],
            candidate_spec["margins"],
        )
        metrics = compute_metrics(
            reference, baseline, output, expanded["candidate_nodes"], expanded["score_scale"]
        )
        candidates.append({**candidate_spec, "metrics": metrics})

    shortlist = rank_and_select(candidates, expanded["shortlist_size"])
    results = {
        "schema": RESULTS_SCHEMA,
        "candidate_nodes": expanded["candidate_nodes"],
        "reference_nodes": expanded["reference_nodes"],
        "score_scale": expanded["score_scale"],
        "baseline": {"margins": baseline_margins, "metrics": baseline_metrics},
        "candidates": candidates,
        "shortlist": shortlist,
        "discarded": expanded["discarded"],
    }
    atomic_write_json(run_dir / "results.json", results)
    write_csv(run_dir / "results.csv", candidates)
    atomic_write_json(run_dir / "shortlist.json", shortlist)
    atomic_write_text(run_dir / "report.md", build_report(results))
    return results


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Screen futility-margin tuples with fixed-node searches and a deeper baseline reference."
    )
    parser.add_argument("--config", required=True, help="JSON tuning configuration")
    parser.add_argument("--probe", help="Path to the futility_probe binary")
    parser.add_argument("--input", action="append", default=[], help="FEN/CSV input; may be repeated")
    parser.add_argument("--weights", help="Optional runtime NNUE weights passed to every probe")
    parser.add_argument("--no-weights", action="store_true", help="Use built-in weights even if config sets weights")
    parser.add_argument("--run-dir", help="Directory for manifest, probe outputs, and reports")
    parser.add_argument("--jobs", type=int, default=1, help="Concurrent candidate probe processes (default: 1)")
    parser.add_argument("--resume", action="store_true", help="Resume an exactly matching existing run")
    parser.add_argument("--dry-run", action="store_true", help="Print expanded candidates without running probes")
    args = parser.parse_args(argv)
    if args.jobs <= 0:
        parser.error("--jobs must be positive")
    if args.no_weights and args.weights:
        parser.error("--no-weights cannot be combined with --weights")
    if not args.dry_run and not args.run_dir:
            parser.error("--run-dir is required unless --dry-run is used")
    if args.resume and args.dry_run:
        parser.error("--resume cannot be combined with --dry-run")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        config_path = Path(args.config).resolve()
        expanded, config_sha256 = load_and_expand_config(config_path)
        if args.dry_run:
            print(json.dumps(expanded, indent=2, sort_keys=True))
            return 0

        probe, inputs, weights = resolve_effective_artifacts(config_path, expanded, args)
        run_dir = Path(args.run_dir).resolve()
        manifest = build_manifest(
            config_path,
            config_sha256,
            expanded,
            probe,
            inputs,
            weights,
        )
        prepare_run_directory(run_dir, manifest, args.resume)

        reference_job = {
            "id": "reference",
            "nodes": expanded["reference_nodes"],
            "margins": expanded["baseline_margins"],
            "all_root_scores": True,
        }
        run_jobs(
            [reference_job],
            probe,
            inputs,
            weights,
            expanded["probe_report_every"],
            run_dir,
            args.resume,
            1,
        )

        candidate_jobs = [
            {
                "id": "baseline",
                "nodes": expanded["candidate_nodes"],
                "margins": expanded["baseline_margins"],
            }
        ]
        candidate_jobs.extend(
            {
                "id": candidate["id"],
                "nodes": expanded["candidate_nodes"],
                "margins": candidate["margins"],
            }
            for candidate in expanded["candidates"]
        )
        run_jobs(
            candidate_jobs,
            probe,
            inputs,
            weights,
            expanded["probe_report_every"],
            run_dir,
            args.resume,
            args.jobs,
        )
        results = aggregate_results(run_dir, expanded)
        print(build_report(results))
        return 0
    except TuningError as exc:
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
