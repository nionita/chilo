#!/usr/bin/env python3
"""Read-only tail-risk analysis for fixed-node futility probe outputs.

The score-regret proxy ranks by mean normalized regret.  This companion tool
does not change that ranking rule; it measures absolute regret tails and the
candidate's downside relative to a declared control from already completed
JSONL outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import optimize_futility
import tune_futility


SCHEMA = "chilo.futility_risk_analysis.v1"


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


def parse_config(path: Path) -> Tuple[optimize_futility.AnchorContext, Dict[str, Any], List[Dict[str, Any]], str, List[float], List[float], int, int]:
    raw = optimize_futility.read_json(path, "risk-analysis config")
    allowed = {
        "candidate_nodes", "baseline_margins", "score_scale", "development", "variants", "control",
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
    control = optimize_futility.require_string(raw.get("control"), "control")
    if control not in identifiers:
        raise optimize_futility.OptimizationError("control must identify one variant")
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
    return anchor, raw, variants, control, tails, thresholds, advantage, loss


def selected_reference_score(reference_record: Mapping[str, Any], candidate_record: Mapping[str, Any]) -> int:
    scores = reference_record.get("root_scores")
    move = candidate_record.get("bestmove")
    if not isinstance(scores, dict) or move not in scores:
        raise optimize_futility.OptimizationError(f"candidate move {move!r} is absent from reference root_scores")
    return int(scores[move])


def regret(reference_record: Mapping[str, Any], candidate_record: Mapping[str, Any], score_scale: float) -> float:
    scores = reference_record.get("root_scores")
    if not isinstance(scores, dict) or not scores:
        raise optimize_futility.OptimizationError("reference root_scores is missing")
    best = max(tune_futility.normalized_score(int(value), score_scale) for value in scores.values())
    return best - tune_futility.normalized_score(selected_reference_score(reference_record, candidate_record), score_scale)


def tail_mean(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise optimize_futility.OptimizationError("cannot calculate a tail over no values")
    count = max(1, int(math.ceil(len(values) * fraction)))
    return statistics.mean(sorted(values)[-count:])


def rate_at_least(values: Sequence[float], threshold: float) -> float:
    return sum(value >= threshold for value in values) / len(values)


def compute_risk_metrics(
    reference: Mapping[str, Any],
    control: Mapping[str, Any],
    candidate: Mapping[str, Any],
    keys: Sequence[Tuple[str, int, str]],
    score_scale: float,
    tail_fractions: Sequence[float],
    regret_thresholds: Sequence[float],
    advantage_cp: int,
    loss_cp: int,
) -> Dict[str, Any]:
    candidate_regrets: List[float] = []
    control_regrets: List[float] = []
    candidate_scores: List[int] = []
    control_scores: List[int] = []
    for key in keys:
        reference_record = reference["positions"][key]
        candidate_record = candidate["positions"][key]
        control_record = control["positions"][key]
        candidate_regrets.append(regret(reference_record, candidate_record, score_scale))
        control_regrets.append(regret(reference_record, control_record, score_scale))
        candidate_scores.append(selected_reference_score(reference_record, candidate_record))
        control_scores.append(selected_reference_score(reference_record, control_record))
    excess = [value - control_value for value, control_value in zip(candidate_regrets, control_regrets)]
    positive_excess = [max(0.0, value) for value in excess]
    tails = {f"top_{fraction:g}": tail_mean(candidate_regrets, fraction) for fraction in tail_fractions}
    excess_tails = {f"top_{fraction:g}": tail_mean(excess, fraction) for fraction in tail_fractions}
    return {
        "position_count": len(keys),
        "absolute_regret": {
            "mean": statistics.mean(candidate_regrets),
            "p90": tune_futility.percentile(candidate_regrets, 0.90),
            "p95": tune_futility.percentile(candidate_regrets, 0.95),
            "p99": tune_futility.percentile(candidate_regrets, 0.99),
            "tail_mean": tails,
            "rate_at_least": {f"{threshold:g}": rate_at_least(candidate_regrets, threshold) for threshold in regret_thresholds},
        },
        "excess_vs_control": {
            "mean": statistics.mean(excess),
            "mean_positive": statistics.mean(positive_excess),
            "mean_squared_positive": statistics.mean(value * value for value in positive_excess),
            "p95": tune_futility.percentile(excess, 0.95),
            "p99": tune_futility.percentile(excess, 0.99),
            "tail_mean": excess_tails,
            "rate_at_least": {f"{threshold:g}": rate_at_least(excess, threshold) for threshold in regret_thresholds},
        },
        "semantic_regressions_vs_control": {
            "winning_mate_missed": sum(
                tune_futility.mate_class(control_score) == 1 and tune_futility.mate_class(candidate_score) != 1
                for control_score, candidate_score in zip(control_scores, candidate_scores)
            ),
            "clear_advantage_lost": sum(
                tune_futility.mate_class(control_score) != 1
                and control_score >= advantage_cp and candidate_score < advantage_cp
                for control_score, candidate_score in zip(control_scores, candidate_scores)
            ),
            "clear_advantage_to_nonpositive": sum(
                tune_futility.mate_class(control_score) != 1
                and control_score >= advantage_cp and candidate_score <= 0
                for control_score, candidate_score in zip(control_scores, candidate_scores)
            ),
            "nonlosing_to_losing": sum(
                tune_futility.mate_class(control_score) != 1
                and control_score >= 0 and candidate_score <= loss_cp
                for control_score, candidate_score in zip(control_scores, candidate_scores)
            ),
        },
    }


def run(config_path: Path, output_dir: Path) -> Dict[str, Any]:
    anchor, raw, variants, control_id, tail_fractions, thresholds, advantage, loss = parse_config(config_path)
    control = next(item for item in variants if item["id"] == control_id)
    scale = float(raw.get("score_scale", 600))
    rows = []
    for variant in variants:
        rows.append({
            "id": variant["id"],
            "margins": list(variant["margins"]),
            "output": variant["output"],
            "metrics": compute_risk_metrics(
                anchor.reference, control["candidate"], variant["candidate"], anchor.trusted_keys,
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
        "control": control_id,
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
        f"Control: `{control_id}`. Positive excess means a candidate is worse than that control on a position.", "",
        f"| Variant | Margins | Mean regret | P95 | P99 | CVaR top {primary_tail_label} | Positive excess | Squared positive excess | CVaR top {primary_tail_label} excess |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        metrics = row["metrics"]
        absolute = metrics["absolute_regret"]
        excess = metrics["excess_vs_control"]
        lines.append(
            f"| {row['id']} | `{','.join(str(value) for value in row['margins'])}` | "
            f"{absolute['mean']:.6f} | {absolute['p95']:.6f} | {absolute['p99']:.6f} | "
            f"{absolute['tail_mean'][primary_tail_key]:.6f} | {excess['mean_positive']:.6f} | "
            f"{excess['mean_squared_positive']:.6f} | {excess['tail_mean'][primary_tail_key]:.6f} |"
        )
    lines.extend(["", "## Semantic regressions versus control", "", "| Variant | Winning mate missed | Clear advantage lost | Advantage to nonpositive | Nonlosing to losing |", "|---|---:|---:|---:|---:|"])
    for row in rows:
        semantic = row["metrics"]["semantic_regressions_vs_control"]
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
