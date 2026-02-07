"""Statistical helper functions for pipeline analytics."""

from typing import Sequence

import numpy as np


def mean(values: Sequence[float | int]) -> float:
    """Calculate arithmetic mean, returning 0 for empty sequences."""
    if not values:
        return 0.0
    return float(np.mean(values))


def median(values: Sequence[float | int]) -> float:
    """Calculate median, returning 0 for empty sequences."""
    if not values:
        return 0.0
    return float(np.median(values))


def calculate_percentile(values: Sequence[float | int], pct: float) -> float:
    """Calculate a given percentile of a sequence."""
    if not values:
        return 0.0
    return float(np.percentile(values, pct))


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide safely, returning default when denominator is zero."""
    if denominator == 0:
        return default
    return numerator / denominator


def weighted_average(values: Sequence[float], weights: Sequence[float]) -> float:
    """Compute a weighted average."""
    if not values or not weights or len(values) != len(weights):
        return 0.0
    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_weight


def variance(values: Sequence[float | int]) -> float:
    """Calculate population variance."""
    if len(values) < 2:
        return 0.0
    return float(np.var(values))


def std_dev(values: Sequence[float | int]) -> float:
    """Calculate population standard deviation."""
    if len(values) < 2:
        return 0.0
    return float(np.std(values))


def coefficient_of_variation(values: Sequence[float | int]) -> float:
    """Calculate coefficient of variation (std / mean)."""
    m = mean(values)
    if m == 0:
        return 0.0
    return std_dev(values) / m


def rank_in_group(value: float, values: Sequence[float | int], ascending: bool = True) -> int:
    """Return 1-based rank of a value within a group."""
    sorted_vals = sorted(values, reverse=not ascending)
    for i, v in enumerate(sorted_vals):
        if v >= value:
            return i + 1
    return len(sorted_vals)


def percentile_rank(value: float, values: Sequence[float | int]) -> float:
    """Return the percentile rank (0-100) of a value within a distribution."""
    if not values:
        return 0.0
    count_below = sum(1 for v in values if v < value)
    return (count_below / len(values)) * 100
