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


def timeframe_for_pattern(pattern: PatternResult) -> str:
    """Return the chart/caption timeframe for a detected pattern."""
    if pattern.is_engulfing() or "ENGULFING" in pattern.type:
        return config.ENGULFING_TIMEFRAME
    return config.FLAG_TIMEFRAME


def run_flag_triangle_detectors(
    symbol: str, candles: list[Candle]
) -> list[PatternResult]:
    """Bear/bull flags and descending triangle — validated on 4H only."""
    results: list[PatternResult] = []
    for det in _FLAG_TRIANGLE_DETECTORS:
        try:
            res = det.detect(candles, symbol)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] detector %s failed", symbol, det.name)
            res = None
        if res is not None:
            results.append(res)
    return results


def run_engulfing_detectors(symbol: str, candles: list[Candle]) -> list[PatternResult]:
    """Bullish/bearish engulfing — validated on 1D only."""
    if len(candles) < 2:
        return []
    last_idx = len(candles) - 1
    results: list[PatternResult] = []
    bull = detect_bullish_engulfing(candles, last_idx, symbol)
    bear = detect_bearish_engulfing(candles, last_idx, symbol)
    if bull is not None:
        results.append(bull)
    if bear is not None:
        results.append(bear)
    return results


def run_combo_detectors(
    symbol: str,
    candles_4h: list[Candle],
    candles_1d: list[Candle],
) -> list[PatternResult]:
    """Combo signals when 4H structure and 1D engulfing align on the same check."""
    if not candles_4h or not candles_1d:
        return []

    flag_triangle = run_flag_triangle_detectors(symbol, candles_4h)
    engulfing = run_engulfing_detectors(symbol, candles_1d)
    bull_eng = next((p for p in engulfing if p.type == "BULLISH_ENGULFING"), None)
    bear_eng = next((p for p in engulfing if p.type == "BEARISH_ENGULFING"), None)

    combo = _combine(flag_triangle, bull_eng, bear_eng, candles_4h, candles_1d, symbol)
    return [combo] if combo is not None else []


def _combine(
    flag_triangle: list[PatternResult],
    bull_eng: Optional[PatternResult],
    bear_eng: Optional[PatternResult],
    candles_4h: list[Candle],
    candles_1d: list[Candle],
    symbol: str,
) -> Optional[PatternResult]:
    """Synthesize combo when 4H flag/triangle meets 1D engulfing."""
    last_4h = candles_4h[-1]
    last_1d = candles_1d[-1]
    by_type = {p.type: p for p in flag_triangle}

    bear_flag = by_type.get("BEAR_FLAG_FORMING")
    if bear_eng is not None and bear_flag is not None and bear_flag.breakout_level:
        if last_4h.close <= bear_flag.breakout_level * 1.001:
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
                    "timeframe": config.ENGULFING_TIMEFRAME,
                },
            )

    triangle = by_type.get("DESCENDING_TRIANGLE_FORMING")
    if bull_eng is not None and triangle is not None and triangle.support_level:
        if abs(last_1d.low - triangle.support_level) <= triangle.support_level * 0.01:
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
                    "timeframe": config.ENGULFING_TIMEFRAME,
                },
            )

    return None


def min_candles_required_flag() -> int:
    return config.CONSOLIDATION_MIN + config.IMPULSE_CANDLES_MIN


def min_candles_required_engulfing() -> int:
    return 2
