#!/usr/bin/env python3
"""Re-score existing futility outputs on deterministic trusted-set subsets.

No engine is run.  Fixed-node outputs already contain one result per input
position, so filtering them is exactly the desired smaller-corpus comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import optimize_futility
import tune_futility


SCHEMA = "chilo.futility_subset_analysis.v1"


def atomic_write(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def subset_id(keys: Sequence[Tuple[str, int, str]]) -> str:
    digest = hashlib.sha256()
    for key in sorted(keys):
        digest.update(json.dumps(key, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def parse_config(path: Path) -> Tuple[optimize_futility.AnchorContext, Dict[str, Any], List[Dict[str, Any]], int, List[float], int]:
    raw = optimize_futility.read_json(path, "subset-analysis config")
    allowed = {"candidate_nodes", "baseline_margins", "score_scale", "development", "variants", "sampling"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise optimize_futility.OptimizationError(f"unknown subset-analysis field(s): {', '.join(unknown)}")
    nodes = optimize_futility.require_int(raw.get("candidate_nodes"), "candidate_nodes", 1)
    margins = tune_futility.validate_margins(raw.get("baseline_margins"), "baseline_margins")
    scale = raw.get("score_scale", 600)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise optimize_futility.OptimizationError("score_scale must be a finite number > 0")
    development_raw = raw.get("development")
    if not isinstance(development_raw, dict):
        raise optimize_futility.OptimizationError("development must be an object")
    anchor = optimize_futility.load_anchor(path, "development", development_raw, nodes, margins)
    variants_raw = raw.get("variants")
    if not isinstance(variants_raw, list) or not variants_raw:
        raise optimize_futility.OptimizationError("variants must be a non-empty list")
    variants: List[Dict[str, Any]] = []
    identifiers = set()
    for item in variants_raw:
        if not isinstance(item, dict) or set(item) - {"id", "margins", "output"}:
            raise optimize_futility.OptimizationError("each variant must contain only id, margins, output")
        identifier = optimize_futility.require_string(item.get("id"), "variant.id")
        if identifier in identifiers:
            raise optimize_futility.OptimizationError(f"duplicate variant id {identifier}")
        identifiers.add(identifier)
        variant_margins = tune_futility.validate_margins(item.get("margins"), f"variant {identifier} margins")
        output = optimize_futility.resolve_path(path, optimize_futility.require_string(item.get("output"), "variant.output"))
        candidate = tune_futility.parse_probe_output(output, nodes, variant_margins)
        tune_futility.ensure_position_sets(anchor.reference, candidate, f"variant {identifier}")
        variants.append({"id": identifier, "margins": variant_margins, "output": tune_futility.file_identity(output), "candidate": candidate})
    sampling = raw.get("sampling")
    if not isinstance(sampling, dict) or set(sampling) - {"seed", "fractions", "replicates"}:
        raise optimize_futility.OptimizationError("sampling must contain only seed, fractions, replicates")
    seed = optimize_futility.require_int(sampling.get("seed"), "sampling.seed", 0)
    fractions_raw = sampling.get("fractions")
    if not isinstance(fractions_raw, list) or not fractions_raw:
        raise optimize_futility.OptimizationError("sampling.fractions must be a non-empty list")
    fractions = []
    for fraction in fractions_raw:
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 < fraction <= 1:
            raise optimize_futility.OptimizationError("sampling fractions must be in (0, 1]")
        fractions.append(float(fraction))
    replicates = optimize_futility.require_int(sampling.get("replicates"), "sampling.replicates", 1)
    return anchor, raw, variants, nodes, fractions, replicates


def run(config_path: Path, output_dir: Path) -> Dict[str, Any]:
    anchor, raw, variants, nodes, fractions, replicates = parse_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    trusted = list(anchor.trusted_keys)
    results: List[Dict[str, Any]] = []
    for fraction in fractions:
        count = max(1, int(math.ceil(len(trusted) * fraction)))
        for replicate in range(replicates):
            rng = random.Random(f"{raw['sampling']['seed']}:{fraction:.12g}:{replicate}")
            keys = sorted(rng.sample(trusted, count))
            rows = []
            for variant in variants:
                metrics = tune_futility.compute_metrics(anchor.reference, anchor.baseline, variant["candidate"], nodes, float(raw.get("score_scale", 600)), keys)
                rows.append({"id": variant["id"], "margins": list(variant["margins"]), "metrics": metrics})
            rows.sort(key=lambda row: (row["metrics"]["mean_normalized_regret"], row["metrics"]["p90_normalized_regret"], row["metrics"]["median_normalized_regret"], tuple(row["margins"])))
            for rank, row in enumerate(rows, 1):
                row["rank"] = rank
            results.append({"fraction": fraction, "replicate": replicate, "position_count": count, "position_keys_sha256": subset_id(keys), "ranked": rows})
    summaries = []
    baselines = [item for item in variants if item["margins"] == tuple(raw["baseline_margins"])]
    if len(baselines) != 1:
        raise optimize_futility.OptimizationError("variants must contain exactly one baseline_margins output")
    baseline_id = baselines[0]["id"]
    pairwise = []
    for fraction in fractions:
        observations = [entry for entry in results if entry["fraction"] == fraction]
        for variant in variants:
            ranked = [next(row for row in entry["ranked"] if row["id"] == variant["id"]) for entry in observations]
            values = [row["metrics"]["mean_normalized_regret"] for row in ranked]
            ranks = [row["rank"] for row in ranked]
            summaries.append({"fraction": fraction, "id": variant["id"], "mean_regret_mean": statistics.mean(values), "mean_regret_stdev": statistics.stdev(values) if len(values) > 1 else 0.0, "mean_rank": statistics.mean(ranks), "winner_count": sum(rank == 1 for rank in ranks)})
            if variant["id"] != baseline_id:
                deltas = []
                for entry, row in zip(observations, ranked):
                    baseline_row = next(value for value in entry["ranked"] if value["id"] == baseline_id)
                    deltas.append(row["metrics"]["mean_normalized_regret"] - baseline_row["metrics"]["mean_normalized_regret"])
                pairwise.append({"fraction": fraction, "variant": variant["id"], "baseline": baseline_id, "mean_regret_delta": statistics.mean(deltas), "mean_regret_delta_stdev": statistics.stdev(deltas) if len(deltas) > 1 else 0.0, "better_than_baseline_count": sum(delta < 0 for delta in deltas)})
    result = {"schema": SCHEMA, "config": {"path": str(config_path), "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()}, "anchor": {"reference": anchor.reference_identity, "baseline": anchor.baseline_identity, "trusted_set": anchor.trusted_set}, "variants": [{key: value for key, value in item.items() if key != "candidate"} for item in variants], "samples": results, "summary": summaries, "pairwise_vs_baseline": pairwise}
    atomic_write(output_dir / "subset_results.json", result)
    lines = ["# Futility subset sensitivity", "", "This is a read-only re-score of fixed-node outputs; no probes were run.", "", "| Fraction | Variant | Mean regret mean | Stdev | Mean rank | Wins |", "|---:|---|---:|---:|---:|---:|"]
    for item in summaries:
        lines.append(f"| {item['fraction']:.0%} | {item['id']} | {item['mean_regret_mean']:.6f} | {item['mean_regret_stdev']:.6f} | {item['mean_rank']:.2f} | {item['winner_count']} |")
    lines.extend(["", "## Pairwise mean-regret delta versus baseline", "", "Negative is better.", "", "| Fraction | Variant | Mean delta | Stdev | Better samples |", "|---:|---|---:|---:|---:|"])
    for item in pairwise:
        lines.append(f"| {item['fraction']:.0%} | {item['variant']} | {item['mean_regret_delta']:.6f} | {item['mean_regret_delta_stdev']:.6f} | {item['better_than_baseline_count']} |")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Measure subset sensitivity from existing futility probe outputs.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(Path(args.config).resolve(), Path(args.output_dir).resolve())
        print(f"subset samples={len(result['samples'])} variants={len(result['variants'])}")
        return 0
    except (optimize_futility.OptimizationError, tune_futility.TuningError, OSError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
