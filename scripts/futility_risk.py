#!/usr/bin/env python3
"""Shared score-regret downside metrics for futility tools.

This module is deliberately process- and configuration-free.  Consumers own
their anchor/probe handling and pass already validated records here.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import optimize_futility
import tune_futility


Key = Tuple[str, int, str]


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
    keys: Sequence[Key],
    score_scale: float,
    tail_fractions: Sequence[float],
    regret_thresholds: Sequence[float],
    advantage_cp: int,
    loss_cp: int,
) -> Dict[str, Any]:
    """Calculate absolute regret and candidate-versus-control risk metrics."""
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
