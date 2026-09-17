#!/usr/bin/env python3
"""Initialize and backfill the canonical cloud futility normal-PVS cache."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

import futility_probe_cache as cache
import tune_futility


CAMPAIGN_SCHEMA = "chilo.futility_campaign_manifest.v1"
BATCH_SCHEMA = "chilo.futility_validation_batch_manifest.v1"


def read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("root must be an object")
    return value


def checked_path(identity: Any, label: str) -> Path:
    if not isinstance(identity, dict) or not isinstance(identity.get("path"), str):
        raise RuntimeError(f"{label} lacks a path identity")
    path = Path(identity["path"])
    if not path.is_file():
        raise RuntimeError(f"{label} does not exist: {path}")
    actual = tune_futility.file_identity(path)
    if actual.get("sha256") != identity.get("sha256") or actual.get("size") != identity.get("size"):
        raise RuntimeError(f"{label} differs from its recorded identity: {path}")
    return path


def campaign_items(run: Path, manifest: Mapping[str, Any]) -> Iterable[tuple[str, Path, Path | None, list[Path], int, list[int], Path]]:
    state = read_json(run / "search" / "state.json")
    if state.get("schema") != "chilo.futility_pareto_search_state.v4" or not isinstance(state.get("evaluations"), list):
        raise RuntimeError("invalid campaign Pareto state")
    probe = checked_path(manifest.get("probe"), "campaign probe")
    weights_identity = manifest.get("weights")
    weights = checked_path(weights_identity, "campaign weights") if weights_identity is not None else None
    development = manifest.get("development")
    if not isinstance(development, dict):
        raise RuntimeError("campaign manifest lacks development")
    inputs = [checked_path(development.get("input"), "campaign development input")]
    nodes = manifest.get("candidate_nodes")
    if not isinstance(nodes, int) or nodes <= 0:
        raise RuntimeError("campaign manifest has invalid candidate nodes")
    for record in state["evaluations"]:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not isinstance(record.get("margins"), list):
            raise RuntimeError("campaign state has invalid evaluation")
        output = run / "search" / "probes" / (record["id"] + ".jsonl")
        yield record["id"], probe, weights, inputs, nodes, [int(value) for value in record["margins"]], output


def batch_items(run: Path, manifest: Mapping[str, Any]) -> Iterable[tuple[str, Path, Path | None, list[Path], int, list[int], Path]]:
    probe = checked_path(manifest.get("probe"), "batch probe")
    weights_identity = manifest.get("weights")
    weights = checked_path(weights_identity, "batch weights") if weights_identity is not None else None
    nodes = manifest.get("candidate_nodes")
    candidates = manifest.get("candidates")
    shards = manifest.get("shards")
    if not isinstance(nodes, int) or nodes <= 0 or not isinstance(candidates, list) or not isinstance(shards, list):
        raise RuntimeError("batch manifest has invalid candidates or shards")
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str) or not isinstance(candidate.get("margins"), list):
            raise RuntimeError("batch manifest has invalid candidate")
        margins = [int(value) for value in candidate["margins"]]
        for shard in shards:
            if not isinstance(shard, dict) or not isinstance(shard.get("id"), str):
                raise RuntimeError("batch manifest has invalid shard")
            input_path = checked_path(shard.get("input"), f"batch input {shard['id']}")
            output = run / "candidates" / candidate["id"] / shard["id"] / "probes" / "candidate.jsonl"
            yield candidate["id"] + "/" + shard["id"], probe, weights, [input_path], nodes, margins, output


def import_item(root: Path, probe: Path, weights: Path | None, inputs: list[Path], nodes: int, margins: list[int], output: Path, dry_run: bool) -> tuple[str, str]:
    if not output.is_file():
        raise RuntimeError(f"missing output: {output}")
    tune_futility.parse_probe_output(output, nodes, margins)
    value = cache.descriptor(probe, weights, inputs, nodes, margins)
    entry = cache.entry_for(root, value)
    if entry.directory.exists():
        cache.validate(entry, nodes, margins)
        return "existing", entry.key
    if dry_run:
        return "would_import", entry.key
    with cache.lock(root, entry.key):
        if entry.directory.exists():
            cache.validate(entry, nodes, margins)
            return "existing", entry.key
        cache.publish(entry, output, nodes, margins)
    return "imported", entry.key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", help="Optional JSON report path")
    args = parser.parse_args(argv)
    store = Path(args.store_root).expanduser().resolve()
    evals = store / "evals"
    root = store / "candidate-probe-cache"
    if not evals.is_dir():
        raise RuntimeError(f"canonical evals directory does not exist: {evals}")
    if not args.dry_run:
        cache.initialize(root)
    report: dict[str, Any] = {"schema": cache.SCHEMA, "store_root": str(store), "dry_run": args.dry_run, "items": [], "summary": {}}
    counts: dict[str, int] = {}
    for run in sorted(path for path in evals.iterdir() if path.is_dir()):
        manifest_path = run / "campaign_manifest.json"
        if not manifest_path.is_file():
            manifest_path = run / "batch_manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = read_json(manifest_path)
            if manifest.get("schema") == CAMPAIGN_SCHEMA:
                items = campaign_items(run, manifest)
            elif manifest.get("schema") == BATCH_SCHEMA:
                items = batch_items(run, manifest)
            else:
                continue
            for label, probe, weights, inputs, nodes, margins, output in items:
                try:
                    status, key = import_item(root, probe, weights, inputs, nodes, margins, output, args.dry_run)
                    report["items"].append({"run": run.name, "item": label, "status": status, "key": key})
                    counts[status] = counts.get(status, 0) + 1
                except (OSError, ValueError, cache.CacheError, tune_futility.TuningError, RuntimeError) as exc:
                    report["items"].append({"run": run.name, "item": label, "status": "skipped", "reason": str(exc)})
                    counts["skipped"] = counts.get("skipped", 0) + 1
        except (OSError, ValueError, cache.CacheError, tune_futility.TuningError, RuntimeError) as exc:
            report["items"].append({"run": run.name, "status": "skipped", "reason": str(exc)})
            counts["skipped"] = counts.get("skipped", 0) + 1
    report["summary"] = counts
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        report_path = Path(args.report).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise SystemExit(1)
