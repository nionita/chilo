#!/usr/bin/env python3
"""Read-only tail-risk analysis for fixed-node futility probe outputs.

The score-regret proxy ranks by mean normalized regret. This companion tool
does not change that ranking rule; it measures candidate risk directly against
the deep reference-root scores from already completed JSONL outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import optimize_futility
import futility_risk
import tune_futility


SCHEMA = "chilo.futility_risk_analysis.v2"


def atomic_write(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def require_fraction_list(value: Any, label: str) -> List[float]:
    if not isinstance(value, list) or not value:
        raise optimize_futility.OptimizationError(f"{label} must be a non-empty list")
    result: List[float] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or not 0 < item < 1:
            raise optimize_futility.OptimizationError(f"{label}[{index}] must be a finite fraction in (0, 1)")
        result.append(float(item))
    if len(set(result)) != len(result):
        raise optimize_futility.OptimizationError(f"{label} must not contain duplicates")
    return result


def require_threshold_list(value: Any, label: str) -> List[float]:
    if not isinstance(value, list) or not value:
        raise optimize_futility.OptimizationError(f"{label} must be a non-empty list")
    result: List[float] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or item < 0:
            raise optimize_futility.OptimizationError(f"{label}[{index}] must be a finite number >= 0")
        result.append(float(item))
    if len(set(result)) != len(result):
        raise optimize_futility.OptimizationError(f"{label} must not contain duplicates")
    return result


def parse_config(path: Path) -> Tuple[optimize_futility.AnchorContext, Dict[str, Any], List[Dict[str, Any]], List[float], List[float], int, int]:
    raw = optimize_futility.read_json(path, "risk-analysis config")
    allowed = {
        "candidate_nodes", "baseline_margins", "score_scale", "development", "variants",
        "tail_fractions", "regret_thresholds", "semantic_thresholds",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise optimize_futility.OptimizationError(f"unknown risk-analysis field(s): {', '.join(unknown)}")
    nodes = optimize_futility.require_int(raw.get("candidate_nodes"), "candidate_nodes", 1)
    margins = tune_futility.validate_margins(raw.get("baseline_margins"), "baseline_margins")
    scale = raw.get("score_scale", 600)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise optimize_futility.OptimizationError("score_scale must be a finite number > 0")
    development = raw.get("development")
    if not isinstance(development, dict):
        raise optimize_futility.OptimizationError("development must be an object")
    anchor = optimize_futility.load_anchor(path, "development", development, nodes, margins)
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
    tails = require_fraction_list(raw.get("tail_fractions", [0.05, 0.01]), "tail_fractions")
    thresholds = require_threshold_list(raw.get("regret_thresholds", [0.1, 0.25, 0.5, 1.0]), "regret_thresholds")
    semantic = raw.get("semantic_thresholds", {"advantage_cp": 150, "loss_cp": -150})
    if not isinstance(semantic, dict) or set(semantic) != {"advantage_cp", "loss_cp"}:
        raise optimize_futility.OptimizationError("semantic_thresholds must contain advantage_cp and loss_cp")
    advantage = optimize_futility.require_int(semantic.get("advantage_cp"), "semantic_thresholds.advantage_cp", 1)
    loss_raw = semantic.get("loss_cp")
    if isinstance(loss_raw, bool) or not isinstance(loss_raw, int):
        raise optimize_futility.OptimizationError("semantic_thresholds.loss_cp must be an integer")
    loss = loss_raw
    if loss >= 0:
        raise optimize_futility.OptimizationError("semantic_thresholds.loss_cp must be < 0")
    return anchor, raw, variants, tails, thresholds, advantage, loss


selected_reference_score = futility_risk.selected_reference_score
regret = futility_risk.regret
tail_mean = futility_risk.tail_mean
rate_at_least = futility_risk.rate_at_least
compute_risk_metrics = futility_risk.compute_risk_metrics


def run(config_path: Path, output_dir: Path) -> Dict[str, Any]:
    anchor, raw, variants, tail_fractions, thresholds, advantage, loss = parse_config(config_path)
    scale = float(raw.get("score_scale", 600))
    rows = []
    for variant in variants:
        rows.append({
            "id": variant["id"],
            "margins": list(variant["margins"]),
            "output": variant["output"],
            "metrics": compute_risk_metrics(
                anchor.reference, variant["candidate"], anchor.trusted_keys,
                scale, tail_fractions, thresholds, advantage, loss,
            ),
        })
    rows.sort(key=lambda row: (row["metrics"]["absolute_regret"]["mean"], tuple(row["margins"])))
    result = {
        "schema": SCHEMA,
        "config": {"path": str(config_path), "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()},
        "anchor": {
            "reference": anchor.reference_identity,
            "baseline": anchor.baseline_identity,
            "trusted_set": anchor.trusted_set,
            "rescue": dict(anchor.rescue) if anchor.rescue is not None else None,
        },
        "tail_fractions": list(tail_fractions),
        "regret_thresholds": list(thresholds),
        "semantic_thresholds": {"advantage_cp": advantage, "loss_cp": loss},
        "variants": rows,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(output_dir / "risk_results.json", result)
    primary_tail = min(tail_fractions)
    primary_tail_key = f"top_{primary_tail:g}"
    primary_tail_label = f"{primary_tail * 100:g}%"
    lines = [
        "# Futility proxy tail-risk analysis", "",
        "This is a read-only analysis of completed fixed-node probe JSONL; no engine was run.",
        "All statistics compare the candidate-selected move directly with the deep reference-root score.", "",
        f"| Variant | Margins | Mean regret | Mean squared regret | P95 | P99 | CVaR top {primary_tail_label} |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        metrics = row["metrics"]
        absolute = metrics["absolute_regret"]
        lines.append(
            f"| {row['id']} | `{','.join(str(value) for value in row['margins'])}` | "
            f"{absolute['mean']:.6f} | {absolute['mean_squared']:.6f} | {absolute['p95']:.6f} | "
            f"{absolute['p99']:.6f} | {absolute['tail_mean'][primary_tail_key]:.6f} |"
        )
    lines.extend(["", "## Semantic regressions versus reference", "", "| Variant | Winning mate missed | Clear advantage lost | Advantage to nonpositive | Nonlosing to losing |", "|---|---:|---:|---:|---:|"])
    for row in rows:
        semantic = row["metrics"]["semantic_regressions_vs_reference"]
        lines.append(f"| {row['id']} | {semantic['winning_mate_missed']} | {semantic['clear_advantage_lost']} | {semantic['clear_advantage_to_nonpositive']} | {semantic['nonlosing_to_losing']} |")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze futility proxy tail risk from completed probe JSONL.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(Path(args.config).resolve(), Path(args.output_dir).resolve())
        print(f"risk variants={len(result['variants'])} positions={result['anchor']['trusted_set']['trusted_position_count']}")
        return 0
    except (json.JSONDecodeError, OSError, optimize_futility.OptimizationError, tune_futility.TuningError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
