#!/usr/bin/env python3
"""Small deterministic optimizer for ordered integer vectors.

The module deliberately does not know what a vector represents or how it is
scored.  Callers supply a cache lookup and an evaluator, which makes the
search useful for expensive black-box objectives without adding an optimizer
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


Margins = Tuple[int, ...]
Objective = Tuple[float, float, float, Margins]


class OptimizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchConfig:
    depths: Tuple[int, ...]
    steps: Tuple[int, ...]
    max_margin: int
    max_new_evaluations: int


@dataclass(frozen=True)
class SearchResult:
    evaluations: Mapping[Margins, Objective]
    new_evaluations: int
    stopped_by_budget: bool


Lookup = Callable[[Margins], Optional[Objective]]
Evaluate = Callable[[Margins], Objective]


def validate_margins(margins: Sequence[int], max_margin: int) -> Margins:
    if not margins:
        raise OptimizationError("a margin tuple must not be empty")
    if max_margin < 0:
        raise OptimizationError("max_margin must be nonnegative")
    result = tuple(margins)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in result):
        raise OptimizationError("margins must be integers")
    if any(value < 0 or value > max_margin for value in result):
        raise OptimizationError("margins fall outside the configured bounds")
    if any(left > right for left, right in zip(result, result[1:])):
        raise OptimizationError("margins must be nondecreasing")
    return result


def to_increments(margins: Sequence[int]) -> Margins:
    values = tuple(margins)
    return (values[0],) + tuple(right - left for left, right in zip(values, values[1:]))


def from_increments(values: Sequence[int]) -> Margins:
    if not values:
        raise OptimizationError("increment vector must not be empty")
    margins: List[int] = []
    total = 0
    for value in values:
        total += value
        margins.append(total)
    return tuple(margins)


def neighbours(margins: Sequence[int], step: int, max_margin: int) -> List[Margins]:
    """Return legal +/- one-coordinate moves in deterministic order."""
    current = validate_margins(margins, max_margin)
    if step <= 0:
        raise OptimizationError("search steps must be positive")
    increments = to_increments(current)
    result: List[Margins] = []
    for index in range(len(increments)):
        for delta in (-step, step):
            changed = list(increments)
            changed[index] += delta
            if changed[index] < 0:
                continue
            candidate = from_increments(changed)
            try:
                candidate = validate_margins(candidate, max_margin)
            except OptimizationError:
                continue
            if candidate != current:
                result.append(candidate)
    return result


def objective_key(objective: Objective) -> Objective:
    return objective


def validate_search_config(config: SearchConfig, seeds: Iterable[Sequence[int]]) -> List[Margins]:
    """Validate a search request without invoking its objective."""
    if not config.depths or any(depth <= 0 for depth in config.depths):
        raise OptimizationError("depths must contain positive values")
    if tuple(sorted(set(config.depths))) != config.depths:
        raise OptimizationError("depths must be strictly increasing")
    if not config.steps or any(step <= 0 for step in config.steps):
        raise OptimizationError("steps must contain positive values")
    if tuple(sorted(config.steps, reverse=True)) != config.steps:
        raise OptimizationError("steps must be in descending order")
    if config.max_new_evaluations < 0:
        raise OptimizationError("max_new_evaluations must be nonnegative")

    validated_seeds = [validate_margins(seed, config.max_margin) for seed in seeds]
    enabled_depths = set(config.depths)
    if not validated_seeds:
        raise OptimizationError("at least one seed is required")
    if any(len(seed) not in enabled_depths for seed in validated_seeds):
        raise OptimizationError("every seed depth must be enabled")
    missing_depths = enabled_depths - {len(seed) for seed in validated_seeds}
    if missing_depths:
        missing_text = ",".join(str(depth) for depth in sorted(missing_depths))
        raise OptimizationError(f"missing seed for enabled depth(s): {missing_text}")
    return validated_seeds


def optimize(
    config: SearchConfig,
    seeds: Iterable[Sequence[int]],
    lookup: Lookup,
    evaluate: Evaluate,
    initial_new_evaluations: int = 0,
) -> SearchResult:
    """Run coarse-to-fine coordinate search for every supplied seed.

    ``lookup`` is queried first for every tuple.  Only a cache miss calls
    ``evaluate`` and counts towards the hard new-evaluation budget.
    """
    validated_seeds = validate_search_config(config, seeds)
    if initial_new_evaluations < 0:
        raise OptimizationError("initial_new_evaluations must be nonnegative")

    evaluations: Dict[Margins, Objective] = {}
    new_evaluations = initial_new_evaluations
    stopped_by_budget = False

    def score(margins: Margins) -> Optional[Objective]:
        nonlocal new_evaluations, stopped_by_budget
        if margins in evaluations:
            return evaluations[margins]
        cached = lookup(margins)
        if cached is not None:
            evaluations[margins] = cached
            return cached
        if new_evaluations >= config.max_new_evaluations:
            stopped_by_budget = True
            return None
        objective = evaluate(margins)
        if objective[3] != margins:
            raise OptimizationError("evaluator objective tuple does not identify its margins")
        evaluations[margins] = objective
        new_evaluations += 1
        return objective

    for seed in validated_seeds:
        current = seed
        current_score = score(current)
        if current_score is None:
            break
        for step in config.steps:
            while True:
                best_margins = current
                best_score = current_score
                for candidate in neighbours(current, step, config.max_margin):
                    candidate_score = score(candidate)
                    if candidate_score is None:
                        continue
                    if objective_key(candidate_score) < objective_key(best_score):
                        best_margins = candidate
                        best_score = candidate_score
                if best_margins == current:
                    break
                current = best_margins
                current_score = best_score
                if stopped_by_budget:
                    break
            if stopped_by_budget:
                break
        if stopped_by_budget:
            break

    return SearchResult(evaluations, new_evaluations, stopped_by_budget)


def ranked(evaluations: Mapping[Margins, Objective]) -> List[Tuple[Margins, Objective]]:
    return sorted(evaluations.items(), key=lambda item: objective_key(item[1]))
