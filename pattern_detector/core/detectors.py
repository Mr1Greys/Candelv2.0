"""Shared pattern detection pipeline used by the live bot and Vercel cron."""
from __future__ import annotations

import logging
from typing import Optional

import config
from models import Candle, PatternResult
from patterns.bear_flag import BearFlagDetector
from patterns.bull_flag import BullFlagDetector
from patterns.candle_patterns import (
    detect_bearish_engulfing,
    detect_bullish_engulfing,
)
from patterns.descending_triangle import DescendingTriangleDetector

logger = logging.getLogger(__name__)

_FLAG_TRIANGLE_DETECTORS = [
    BearFlagDetector(),
    BullFlagDetector(),
    DescendingTriangleDetector(),
]


def run_detectors(symbol: str, candles: list[Candle]) -> list[PatternResult]:
    """Run flag, triangle and engulfing detectors; apply combo logic."""
    results: list[PatternResult] = []

    flag_triangle: list[PatternResult] = []
    for det in _FLAG_TRIANGLE_DETECTORS:
        try:
            res = det.detect(candles, symbol)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] detector %s failed", symbol, det.name)
            res = None
        if res is not None:
            flag_triangle.append(res)

    last_idx = len(candles) - 1
    bull_eng = detect_bullish_engulfing(candles, last_idx, symbol)
    bear_eng = detect_bearish_engulfing(candles, last_idx, symbol)

    combo = _combine(flag_triangle, bull_eng, bear_eng, candles, symbol)
    if combo is not None:
        results.append(combo)

    results.extend(flag_triangle)
    if combo is None:
        if bull_eng is not None:
            results.append(bull_eng)
        if bear_eng is not None:
            results.append(bear_eng)

    return results


def _combine(
    flag_triangle: list[PatternResult],
    bull_eng: Optional[PatternResult],
    bear_eng: Optional[PatternResult],
    candles: list[Candle],
    symbol: str,
) -> Optional[PatternResult]:
    """Synthesize a stronger combined signal when patterns coincide."""
    last = candles[-1]
    by_type = {p.type: p for p in flag_triangle}

    bear_flag = by_type.get("BEAR_FLAG_FORMING")
    if bear_eng is not None and bear_flag is not None and bear_flag.breakout_level:
        if last.close <= bear_flag.breakout_level * 1.001:
            conf = min(0.95, max(bear_flag.confidence, bear_eng.confidence) + 0.1)
            return PatternResult(
                type="BEAR_FLAG_BREAKOUT_CONFIRMED",
                confidence=conf,
                symbol=symbol,
                channel_top_line=bear_flag.channel_top_line,
                channel_bottom_line=bear_flag.channel_bottom_line,
                impulse_start_idx=bear_flag.impulse_start_idx,
                consolidation_start_idx=bear_flag.consolidation_start_idx,
                breakout_level=bear_flag.breakout_level,
                breakout_target=bear_flag.breakout_target,
                meta={
                    **bear_eng.meta,
                    "headline": "BEAR FLAG BREAKOUT CONFIRMED by BEARISH ENGULFING",
                },
            )

    triangle = by_type.get("DESCENDING_TRIANGLE_FORMING")
    if bull_eng is not None and triangle is not None and triangle.support_level:
        if abs(last.low - triangle.support_level) <= triangle.support_level * 0.01:
            conf = min(0.95, max(triangle.confidence, bull_eng.confidence) + 0.1)
            return PatternResult(
                type="TRIANGLE_SUPPORT_TEST_BULLISH_ENGULFING",
                confidence=conf,
                symbol=symbol,
                support_level=triangle.support_level,
                resistance_line=triangle.resistance_line,
                breakout_level=triangle.breakout_level,
                meta={
                    **bull_eng.meta,
                    "window_start": triangle.meta.get("window_start"),
                    "headline": "TRIANGLE SUPPORT TEST + BULLISH ENGULFING",
                },
            )

    return None


def min_candles_required() -> int:
    """Minimum closed candles before detectors can run meaningfully."""
    return config.CONSOLIDATION_MIN + config.IMPULSE_CANDLES_MIN
