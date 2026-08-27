#!/usr/bin/env python3
"""Deterministic, resumable-friendly SPSA primitives for ordered margins.

This module deliberately has no chess or process knowledge.  The caller owns
sampling, probes, persistence, and the objective; this module only produces a
legal simultaneous perturbation and the next floating point parameter vector.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple


Margins = Tuple[int, ...]
Vector = Tuple[float, ...]


class OptimizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Schedule:
    gain_a: float
    stability_A: float
    gain_alpha: float
    perturbation_c: float
    perturbation_gamma: float
    objective_scale: float
    max_margin: int


@dataclass(frozen=True)
class Step:
    iteration: int
    gain: float
    perturbation: float
    direction: Tuple[int, ...]
    plus: Margins
    minus: Margins


def validate_schedule(schedule: Schedule) -> None:
    for name in ("gain_a", "gain_alpha", "perturbation_c", "perturbation_gamma", "objective_scale"):
        value = getattr(schedule, name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise OptimizationError(f"{name} must be a finite number > 0")
    if not isinstance(schedule.stability_A, (int, float)) or isinstance(schedule.stability_A, bool) or not math.isfinite(schedule.stability_A) or schedule.stability_A < 0:
        raise OptimizationError("stability_A must be a finite number >= 0")
    if not isinstance(schedule.max_margin, int) or isinstance(schedule.max_margin, bool) or schedule.max_margin < 0:
        raise OptimizationError("max_margin must be an integer >= 0")


def to_vector(margins: Sequence[int]) -> Vector:
    if not margins:
        raise OptimizationError("margins must not be empty")
    previous = 0
    result = []
    for margin in margins:
        if not isinstance(margin, int) or isinstance(margin, bool) or margin < previous:
            raise OptimizationError("margins must be nondecreasing integers")
        result.append(float(margin - previous))
        previous = margin
    return tuple(result)


def project(vector: Sequence[float], max_margin: int) -> Margins:
    """Project increment coordinates to legal, ordered integer margins.

    Each coordinate is an increment.  Negative increments are clipped, and
    sequential clipping guarantees that cumulative rounded margins stay inside
    the maximum.  This is intentionally simple and deterministic, which makes
    resumed SPSA observations reproducible.
    """
    if not vector:
        raise OptimizationError("parameter vector must not be empty")
    if max_margin < 0:
        raise OptimizationError("max_margin must be nonnegative")
    total = 0
    margins = []
    for value in vector:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise OptimizationError("parameter vector must contain finite numbers")
        increment = max(0, int(math.floor(float(value) + 0.5)))
        increment = min(increment, max_margin - total)
        total += increment
        margins.append(total)
    return tuple(margins)


def schedule_values(schedule: Schedule, iteration: int) -> Tuple[float, float]:
    validate_schedule(schedule)
    if iteration < 0:
        raise OptimizationError("iteration must be nonnegative")
    index = iteration + 1
    gain = float(schedule.gain_a) / ((float(schedule.stability_A) + index) ** float(schedule.gain_alpha))
    perturbation = float(schedule.perturbation_c) / (index ** float(schedule.perturbation_gamma))
    return gain, perturbation


def make_step(vector: Sequence[float], schedule: Schedule, iteration: int, rng: random.Random, attempts: int = 100) -> Step:
    validate_schedule(schedule)
    if attempts < 1:
        raise OptimizationError("attempts must be positive")
    values = tuple(float(value) for value in vector)
    gain, perturbation = schedule_values(schedule, iteration)
    for _ in range(attempts):
        direction = tuple(1 if rng.randrange(2) else -1 for _ in values)
        plus = project(tuple(value + perturbation * sign for value, sign in zip(values, direction)), schedule.max_margin)
        minus = project(tuple(value - perturbation * sign for value, sign in zip(values, direction)), schedule.max_margin)
        if plus != minus:
            return Step(iteration, gain, perturbation, direction, plus, minus)
    raise OptimizationError("SPSA perturbation collapses after projection; increase perturbation_c or move away from bounds")


def update(vector: Sequence[float], step: Step, plus_objective: float, minus_objective: float, objective_scale: float) -> Vector:
    if not math.isfinite(plus_objective) or not math.isfinite(minus_objective):
        raise OptimizationError("objectives must be finite")
    if objective_scale <= 0 or not math.isfinite(objective_scale):
        raise OptimizationError("objective_scale must be finite and > 0")
    if len(vector) != len(step.direction):
        raise OptimizationError("parameter vector and SPSA direction dimensions differ")
    difference = (plus_objective - minus_objective) * objective_scale
    return tuple(
        float(value) - step.gain * difference / (2.0 * step.perturbation * direction)
        for value, direction in zip(vector, step.direction)
    )
