"""Linear regression helpers for trend/channel lines."""
from __future__ import annotations

import math

import numpy as np


def linear_regression_line(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Least-squares fit through ``points`` (x = candle index, y = price).

    Returns ``(slope, intercept)`` for ``y = slope * x + intercept``.
    With a single point slope is 0. Raises ValueError on empty input.
    """
    if not points:
        raise ValueError("linear_regression_line requires at least one point")
    if len(points) == 1:
        return 0.0, points[0][1]

    xs = np.array([p[0] for p in points], dtype=float)
    ys = np.array([p[1] for p in points], dtype=float)
    # polyfit degree 1 -> [slope, intercept]
    slope, intercept = np.polyfit(xs, ys, 1)
    return float(slope), float(intercept)


def angle_degrees(slope: float) -> float:
    """Angle of a line with the given slope, in degrees."""
    return math.degrees(math.atan(slope))


def price_at_index(slope: float, intercept: float, idx: float) -> float:
    """Price on the line ``y = slope * x + intercept`` at ``x = idx``."""
    return slope * idx + intercept
