"""Descending triangle detector: horizontal support + lower highs."""
from __future__ import annotations

from typing import Optional

import config
from models import Candle, PatternResult
from patterns.base import PatternDetector, clamp01
from utils.pivot import find_pivot_highs, find_pivot_lows
from utils.regression import angle_degrees, linear_regression_line, price_at_index


class DescendingTriangleDetector(PatternDetector):
    name = "descending_triangle"

    def detect(self, candles: list[Candle], symbol: str) -> Optional[PatternResult]:
        n = len(candles)
        if n < config.TRIANGLE_CANDLES_MIN:
            return None

        span = min(config.TRIANGLE_CANDLES_MAX, n)
        start = n - span
        window = candles[start:]

        # 1. Horizontal support from pivot lows.
        low_pivots = find_pivot_lows(window, config.PIVOT_LEFT, config.PIVOT_RIGHT)
        if len(low_pivots) < config.TRIANGLE_TOUCHES_MIN:
            return None
        support_level, support_idxs = _best_support_cluster(window, low_pivots)
        if support_level is None or len(support_idxs) < config.TRIANGLE_TOUCHES_MIN:
            return None

        # Support should be roughly horizontal.
        sup_points = [(start + i, window[i].low) for i in support_idxs]
        sup_slope, _ = linear_regression_line(sup_points)
        if abs(angle_degrees(sup_slope)) > config.TRIANGLE_SUPPORT_FLAT_DEG:
            return None

        # 2. Descending highs from pivot highs.
        high_pivots = find_pivot_highs(window, config.PIVOT_LEFT, config.PIVOT_RIGHT)
        if len(high_pivots) < config.DESCENDING_HIGHS_MIN:
            return None
        descending = _select_descending_highs(window, high_pivots)
        if len(descending) < config.DESCENDING_HIGHS_MIN:
            return None

        high_points = [(start + i, window[i].high) for i in descending]
        res_slope, res_int = linear_regression_line(high_points)
        if angle_degrees(res_slope) >= 0:  # must slope down
            return None

        # 3. "Forming" checks: price inside the triangle, apex not too close.
        last_idx = n - 1
        last_close = candles[-1].close
        res_now = price_at_index(res_slope, res_int, last_idx)
        if not (support_level < last_close < res_now):
            return None

        # Apex = where resistance meets support.
        if res_slope == 0:
            return None
        apex_x = (support_level - res_int) / res_slope
        if apex_x - last_idx <= 2:
            return None  # pattern is exhausted / about to converge

        # 4. Confidence.
        confidence = 0.5
        confidence += 0.2 * (len(support_idxs) - config.TRIANGLE_TOUCHES_MIN)
        confidence += 0.15 * (len(descending) - config.DESCENDING_HIGHS_MIN)
        if _volume_declining(window):
            confidence += 0.1
        if abs(candles[-1].low - support_level) <= support_level * 0.005:
            confidence += 0.1  # current candle testing support
        confidence = clamp01(confidence)

        return PatternResult(
            type="DESCENDING_TRIANGLE_FORMING",
            confidence=confidence,
            symbol=symbol,
            support_level=support_level,
            resistance_line=(res_slope, res_int),
            breakout_level=support_level,
            breakout_target=support_level - (res_now - support_level),
            meta={
                "support_touches": len(support_idxs),
                "descending_highs": len(descending),
                "apex_in_candles": round(apex_x - last_idx, 1),
                "support_idxs": [start + i for i in support_idxs],
                "high_idxs": [start + i for i in descending],
                "window_start": start,
            },
        )


def _best_support_cluster(
    window: list[Candle], low_pivots: list[int]
) -> tuple[Optional[float], list[int]]:
    """Find the support level (cluster of pivot lows) with the most touches."""
    best_level: Optional[float] = None
    best_members: list[int] = []
    for anchor in low_pivots:
        level = window[anchor].low
        members = [
            i
            for i in low_pivots
            if abs(window[i].low - level) <= level * config.SUPPORT_LEVEL_TOLERANCE
        ]
        if len(members) > len(best_members):
            best_members = members
            best_level = sum(window[i].low for i in members) / len(members)
    return best_level, best_members


def _select_descending_highs(window: list[Candle], high_pivots: list[int]) -> list[int]:
    """Forward-greedy run of strictly lower pivot highs (time-ordered)."""
    if not high_pivots:
        return []
    ordered = sorted(high_pivots)
    seq = [ordered[0]]
    for idx in ordered[1:]:
        if window[idx].high < window[seq[-1]].high:
            seq.append(idx)
    return seq


def _volume_declining(window: list[Candle]) -> bool:
    if len(window) < 4:
        return False
    half = len(window) // 2
    first = sum(c.volume for c in window[:half]) / max(1, half)
    second = sum(c.volume for c in window[half:]) / max(1, len(window) - half)
    return second < first
