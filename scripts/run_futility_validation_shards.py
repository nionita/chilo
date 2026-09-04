#!/usr/bin/env python3
"""Create and anchor deterministic, disjoint futility-validation shards.

The runner performs one durable phase per invocation.  A cron wrapper may call
it repeatedly: a long per-root anchor is resumed through the probe's paired
JSONL journal, while completed anchors and rescues are never rerun.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import rescue_futility_mates
import tune_futility


SCHEMA = "chilo.futility_validation_shards.v1"
SHARD_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class ShardError(RuntimeError):
    pass


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShardError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ShardError(f"invalid {label} {path}: root must be an object")
    return value


def identity(path: Path) -> dict[str, Any]:
    try:
        return tune_futility.file_identity(path)
    except tune_futility.TuningError as exc:
        raise ShardError(str(exc)) from exc


def resolve(config_path: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ShardError(f"{label} must be a non-empty path")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (config_path.parent / path).resolve()


def require_int(value: object, label: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ShardError(f"{label} must be an integer >= {minimum}")
    return value


def parse_config(path: Path) -> dict[str, Any]:
    raw_bytes = path.read_bytes()
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ShardError(f"invalid config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ShardError("config root must be an object")
    allowed = {"schema", "run_dir", "source", "exclude_inputs", "shards", "anchor", "rescue"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ShardError(f"unknown config field(s): {', '.join(unknown)}")
    if raw.get("schema") != SCHEMA:
        raise ShardError(f"config schema must be {SCHEMA}")

    source = resolve(path, raw.get("source"), "source")
    if not source.is_file():
        raise ShardError(f"source does not exist: {source}")
    exclude_raw = raw.get("exclude_inputs")
    if not isinstance(exclude_raw, list) or not exclude_raw:
        raise ShardError("exclude_inputs must be a non-empty list")
    excludes = [resolve(path, item, "exclude_inputs item") for item in exclude_raw]
    if any(not item.is_file() for item in excludes):
        raise ShardError("every exclude_inputs entry must exist")

    shards_raw = raw.get("shards")
    if not isinstance(shards_raw, list) or not shards_raw:
        raise ShardError("shards must be a non-empty list")
    shards: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_seeds: set[int] = set()
    for index, item in enumerate(shards_raw, 1):
        if not isinstance(item, dict) or set(item) != {"id", "seed", "count"}:
            raise ShardError(f"shards[{index}] must contain exactly id, seed, and count")
        identifier = item["id"]
        if not isinstance(identifier, str) or not SHARD_ID_RE.fullmatch(identifier):
            raise ShardError(f"shards[{index}].id must be a short lowercase identifier")
        seed = require_int(item["seed"], f"shards[{index}].seed", 0)
        count = require_int(item["count"], f"shards[{index}].count")
        if identifier in seen_ids or seed in seen_seeds:
            raise ShardError("shard ids and seeds must each be unique")
        seen_ids.add(identifier)
        seen_seeds.add(seed)
        shards.append({"id": identifier, "seed": seed, "count": count})

    anchor_raw = raw.get("anchor")
    if not isinstance(anchor_raw, dict):
        raise ShardError("anchor must be an object")
    allowed_anchor = {"probe", "weights", "candidate_nodes", "reference_nodes_per_root", "reference_depth_gap", "baseline_margins", "report_every"}
    if set(anchor_raw) != allowed_anchor:
        raise ShardError("anchor must contain exactly probe, weights, candidate_nodes, reference_nodes_per_root, reference_depth_gap, baseline_margins, and report_every")
    probe = resolve(path, anchor_raw["probe"], "anchor.probe")
    weights = resolve(path, anchor_raw["weights"], "anchor.weights")
    if not probe.is_file() or not weights.is_file():
        raise ShardError("anchor probe and weights must exist")
    margins = tune_futility.validate_margins(anchor_raw["baseline_margins"], "anchor.baseline_margins")
    anchor = {
        "probe": probe,
        "weights": weights,
        "candidate_nodes": require_int(anchor_raw["candidate_nodes"], "anchor.candidate_nodes"),
        "reference_nodes_per_root": require_int(anchor_raw["reference_nodes_per_root"], "anchor.reference_nodes_per_root"),
        "reference_depth_gap": require_int(anchor_raw["reference_depth_gap"], "anchor.reference_depth_gap"),
        "baseline_margins": margins,
        "report_every": require_int(anchor_raw["report_every"], "anchor.report_every", 0),
    }
    rescue_raw = raw.get("rescue")
    if not isinstance(rescue_raw, dict) or set(rescue_raw) != {"report_every"}:
        raise ShardError("rescue must contain exactly report_every")
    rescue = {"report_every": require_int(rescue_raw["report_every"], "rescue.report_every", 0)}
    run_dir = resolve(path, raw.get("run_dir"), "run_dir")
    return {
        "config_path": path,
        "config_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "run_dir": run_dir,
        "source": source,
        "excludes": excludes,
        "shards": shards,
        "anchor": anchor,
        "rescue": rescue,
    }


def read_fens(path: Path) -> set[str]:
    values: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["eval_fen", "score", "result"]:
            raise ShardError(f"unexpected CSV header in {path}: {reader.fieldnames}")
        for row in reader:
            fen = row.get("eval_fen")
            if not isinstance(fen, str) or not fen:
                raise ShardError(f"missing eval_fen in {path}")
            values.add(fen)
    return values


def sample_shard(source: Path, excluded: set[str], seed: int, count: int) -> tuple[list[tuple[str, str, str]], dict[str, int]]:
    rng = random.Random(seed)
    sample: list[tuple[str, str, str]] = []
    selected: set[str] = set()
    source_rows = 0
    eligible_events = 0
    skipped_excluded = 0
    skipped_selected = 0
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["eval_fen", "score", "result"]:
            raise ShardError(f"unexpected source header: {reader.fieldnames}")
        for row in reader:
            source_rows += 1
            fen = row["eval_fen"]
            if fen in excluded:
                skipped_excluded += 1
                continue
            if fen in selected:
                skipped_selected += 1
                continue
            eligible_events += 1
            candidate = (fen, row["score"], row["result"])
            if len(sample) < count:
                sample.append(candidate)
                selected.add(fen)
            else:
                slot = rng.randrange(eligible_events)
                if slot < count:
                    selected.remove(sample[slot][0])
                    sample[slot] = candidate
                    selected.add(fen)
    if len(sample) != count:
        raise ShardError(f"only {len(sample)} eligible source FENs available for requested {count}")
    return sample, {
        "source_rows": source_rows,
        "eligible_events": eligible_events,
        "skipped_excluded": skipped_excluded,
        "skipped_selected": skipped_selected,
    }


def write_csv(path: Path, rows: Iterable[tuple[str, str, str]]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["eval_fen", "score", "result"])
        writer.writerows(rows)
    temporary.replace(path)


def expected_plan(settings: dict[str, Any]) -> dict[str, Any]:
    anchor_settings = {
        key: (list(value) if key == "baseline_margins" else value)
        for key, value in settings["anchor"].items()
        if key not in {"probe", "weights"}
    }
    return {
        "schema": SCHEMA,
        "config_sha256": settings["config_sha256"],
        "source": identity(settings["source"]),
        "exclude_inputs": [identity(path) for path in settings["excludes"]],
        "probe": identity(settings["anchor"]["probe"]),
        "weights": identity(settings["anchor"]["weights"]),
        "shards": settings["shards"],
        "anchor": anchor_settings,
        "rescue": settings["rescue"],
    }


def ensure_inputs(settings: dict[str, Any]) -> dict[str, Any]:
    run_dir = settings["run_dir"]
    manifest_path = run_dir / "input_manifest.json"
    provisional_path = run_dir / "input_manifest.pending.json"
    inputs_dir = run_dir / "inputs"
    staging_dir = run_dir / "inputs.pending"
    plan = expected_plan(settings)
    if manifest_path.exists():
        manifest = read_json(manifest_path, "input manifest")
        if manifest.get("plan") != plan:
            raise ShardError("input manifest does not match current package artifacts or configuration")
        for item in manifest.get("inputs", []):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("output"), dict):
                raise ShardError("input manifest is malformed")
            output = run_dir / "inputs" / f"{item['id']}.csv"
            if identity(output) != item["output"]:
                raise ShardError(f"generated input is missing or changed: {output}")
        return manifest

    if provisional_path.exists():
        provisional = read_json(provisional_path, "pending input manifest")
        if provisional.get("plan") != plan or not inputs_dir.is_dir():
            raise ShardError("pending input manifest does not match the current package or generated inputs")
        generated = []
        for item in provisional.get("inputs", []):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ShardError("pending input manifest is malformed")
            output = inputs_dir / f"{item['id']}.csv"
            metadata = inputs_dir / f"{item['id']}.json"
            expected_output = item.get("output")
            if not isinstance(expected_output, dict) or identity(output)["size"] != expected_output.get("size") or \
                    identity(output)["sha256"] != expected_output.get("sha256"):
                raise ShardError(f"pending generated input is missing or changed: {output}")
            provenance = item.get("provenance")
            if not isinstance(provenance, dict):
                raise ShardError("pending input provenance is malformed")
            finalized_provenance = dict(provenance)
            finalized_provenance["output"] = identity(output)
            atomic_json(metadata, finalized_provenance)
            generated.append({"id": item["id"], "output": identity(output), "metadata": identity(metadata)})
        result = {"schema": "chilo.futility_validation_inputs.v1", "plan": plan, "inputs": generated}
        atomic_json(manifest_path, result)
        provisional_path.unlink()
        return result

    if inputs_dir.exists():
        raise ShardError(f"generated input directory exists without a manifest: {inputs_dir}")
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)
    excluded: set[str] = set()
    for path in settings["excludes"]:
        excluded.update(read_fens(path))
    pending: list[dict[str, Any]] = []
    for shard in settings["shards"]:
        rows, statistics = sample_shard(settings["source"], excluded, shard["seed"], shard["count"])
        output = staging_dir / f"{shard['id']}.csv"
        write_csv(output, rows)
        selected = {row[0] for row in rows}
        if len(selected) != shard["count"] or selected & excluded:
            raise ShardError(f"internal disjointness failure for shard {shard['id']}")
        provenance = {
            "schema": "chilo.futility_validation_input.v1",
            "id": shard["id"],
            "seed": shard["seed"],
            "count": shard["count"],
            "source": identity(settings["source"]),
            "excluded_fens_before_sampling": len(excluded),
            "statistics": statistics,
        }
        output_identity = identity(output)
        pending.append({
            "id": shard["id"],
            "output": {"size": output_identity["size"], "sha256": output_identity["sha256"]},
            "provenance": provenance,
        })
        excluded.update(selected)
    atomic_json(provisional_path, {"schema": "chilo.futility_validation_pending_inputs.v1", "plan": plan, "inputs": pending})
    staging_dir.replace(inputs_dir)
    return ensure_inputs(settings)


def shard_input(settings: dict[str, Any], identifier: str) -> Path:
    return settings["run_dir"] / "inputs" / f"{identifier}.csv"


def run_command(command: list[str], cwd: Path) -> None:
    print("run:", json.dumps(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode:
        raise ShardError(f"command failed with exit code {completed.returncode}")


def anchor_config(settings: dict[str, Any], input_path: Path) -> dict[str, Any]:
    anchor = settings["anchor"]
    return {
        "probe": str(anchor["probe"]),
        "inputs": [str(input_path)],
        "weights": str(anchor["weights"]),
        "candidate_nodes": anchor["candidate_nodes"],
        "reference_nodes_per_root": anchor["reference_nodes_per_root"],
        "reference_depth_gap": anchor["reference_depth_gap"],
        "baseline_margins": anchor["baseline_margins"],
        "reference_report_every": anchor["report_every"],
    }


def rescue_config(settings: dict[str, Any], anchor_dir: Path, input_path: Path) -> dict[str, Any]:
    anchor = settings["anchor"]
    return {
        "anchor_dir": str(anchor_dir),
        "probe": str(anchor["probe"]),
        "inputs": [str(input_path)],
        "weights": str(anchor["weights"]),
        "candidate_nodes": anchor["candidate_nodes"],
        "reference_nodes_per_root": anchor["reference_nodes_per_root"],
        "reference_depth_gap": anchor["reference_depth_gap"],
        "baseline_margins": anchor["baseline_margins"],
        "report_every": settings["rescue"]["report_every"],
    }


def anchor_complete(settings: dict[str, Any], anchor_dir: Path) -> bool:
    anchor = settings["anchor"]
    return tune_futility.probe_output_complete(
        anchor_dir / "probes" / "reference.jsonl", anchor["reference_nodes_per_root"], anchor["baseline_margins"],
        True, True, anchor["candidate_nodes"], anchor["reference_depth_gap"],
    ) and tune_futility.probe_output_complete(
        anchor_dir / "probes" / "baseline.jsonl", anchor["candidate_nodes"], anchor["baseline_margins"],
    )


def write_status(settings: dict[str, Any], identifier: str, phase: str) -> None:
    atomic_json(settings["run_dir"] / "status.json", {
        "schema": SCHEMA,
        "config_sha256": settings["config_sha256"],
        "current_shard": identifier,
        "phase": phase,
    })


def complete_shard(settings: dict[str, Any], identifier: str, anchor_dir: Path, rescue_dir: Path) -> None:
    input_path = shard_input(settings, identifier)
    required = [
        anchor_dir / "anchor_manifest.json", anchor_dir / "probes" / "reference.jsonl", anchor_dir / "probes" / "baseline.jsonl",
        rescue_dir / "rescue_manifest.json", rescue_dir / "rescue_reference.jsonl", rescue_dir / "rescue_baseline.jsonl",
        rescue_dir / "rescue_results.json", rescue_dir / "combined_population.json",
    ]
    if any(not path.is_file() for path in required):
        raise ShardError(f"cannot complete {identifier}: required anchor or rescue evidence is missing")
    temporary_input = rescue_dir / "input"
    if temporary_input.exists():
        shutil.rmtree(temporary_input)
    atomic_json(rescue_dir / "completion.json", {
        "schema": "chilo.futility_validation_shard_completion.v1",
        "config_sha256": settings["config_sha256"],
        "id": identifier,
        "input": identity(input_path),
        "anchor_manifest": identity(anchor_dir / "anchor_manifest.json"),
        "reference": identity(anchor_dir / "probes" / "reference.jsonl"),
        "baseline": identity(anchor_dir / "probes" / "baseline.jsonl"),
        "rescue_manifest": identity(rescue_dir / "rescue_manifest.json"),
        "rescue_reference": identity(rescue_dir / "rescue_reference.jsonl"),
        "rescue_baseline": identity(rescue_dir / "rescue_baseline.jsonl"),
        "combined_population": identity(rescue_dir / "combined_population.json"),
    })


def run_once(settings: dict[str, Any]) -> None:
    settings["run_dir"].mkdir(parents=True, exist_ok=True)
    ensure_inputs(settings)
    script_dir = Path(__file__).resolve().parent
    for shard in settings["shards"]:
        identifier = shard["id"]
        shard_root = settings["run_dir"] / "shards" / identifier
        anchor_dir = shard_root / "anchor"
        rescue_dir = shard_root / "rescue"
        completion = rescue_dir / "completion.json"
        if completion.is_file():
            continue
        input_path = shard_input(settings, identifier)
        if not anchor_complete(settings, anchor_dir):
            write_status(settings, identifier, "anchor")
            config_path = shard_root / "anchor.json"
            atomic_json(config_path, anchor_config(settings, input_path))
            run_command([sys.executable, str(script_dir / "tune_futility.py"), "--config", str(config_path),
                         "--run-dir", str(anchor_dir), "--phase", "anchor", "--resume"], settings["run_dir"])
            return
        write_status(settings, identifier, "mate-rescue")
        config_path = shard_root / "rescue.json"
        atomic_json(config_path, rescue_config(settings, anchor_dir, input_path))
        run_command([sys.executable, str(script_dir / "rescue_futility_mates.py"), "--config", str(config_path),
                     "--run-dir", str(rescue_dir)], settings["run_dir"])
        complete_shard(settings, identifier, anchor_dir, rescue_dir)
        return
    atomic_json(settings["run_dir"] / "complete.json", {
        "schema": "chilo.futility_validation_shards_complete.v1",
        "config_sha256": settings["config_sha256"],
        "shards": [item["id"] for item in settings["shards"]],
    })
    print("all configured validation shards are complete", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Advance one resumable futility-validation shard phase.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--prepare-inputs", action="store_true", help="Create/validate inputs only; do not probe")
    args = parser.parse_args(argv)
    try:
        settings = parse_config(Path(args.config).resolve())
        if args.prepare_inputs:
            settings["run_dir"].mkdir(parents=True, exist_ok=True)
            ensure_inputs(settings)
            print("validation-shard inputs are ready", flush=True)
        else:
            run_once(settings)
        return 0
    except (ShardError, rescue_futility_mates.RescueError, tune_futility.TuningError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
