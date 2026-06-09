"""Pivot (local extreme) detection on a candle series."""
from __future__ import annotations

from models import Candle


def find_pivot_highs(candles: list[Candle], left: int = 2, right: int = 2) -> list[int]:
    """Return indices of candles that are local highs.

    ``candles[i]`` is a pivot high if its ``high`` is strictly greater than the
    ``high`` of every neighbour within ``left`` bars before and ``right`` bars
    after. Endpoints that lack enough neighbours are skipped.
    """
    pivots: list[int] = []
    n = len(candles)
    for i in range(left, n - right):
        h = candles[i].high
        is_pivot = True
        for j in range(i - left, i + right + 1):
            if j == i:
                continue
            if candles[j].high >= h:
                is_pivot = False
                break
        if is_pivot:
            pivots.append(i)
    return pivots


def find_pivot_lows(candles: list[Candle], left: int = 2, right: int = 2) -> list[int]:
    """Return indices of candles that are local lows (mirror of pivot highs)."""
    pivots: list[int] = []
    n = len(candles)
    for i in range(left, n - right):
        lo = candles[i].low
        is_pivot = True
        for j in range(i - left, i + right + 1):
            if j == i:
                continue
            if candles[j].low <= lo:
                is_pivot = False
                break
        if is_pivot:
            pivots.append(i)
    return pivots
