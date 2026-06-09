"""Candle patterns ported from a Pine Script strategy: engulfing and doji.

Detection runs only on closed candles (Pine: ``process_orders_on_close=true``).
"""
from __future__ import annotations

from typing import Optional

import config
from models import Candle, PatternResult


def is_prev_bearish(candles: list[Candle], idx: int, count: int = 2) -> bool:
    """True if the ``count`` candles before ``idx`` are all bearish (close < open)."""
    if idx - count < 0:
        return False
    return all(candles[idx - k].is_bearish for k in range(1, count + 1))


def is_prev_bullish(candles: list[Candle], idx: int, count: int = 2) -> bool:
    """True if the ``count`` candles before ``idx`` are all bullish (close > open)."""
    if idx - count < 0:
        return False
    return all(candles[idx - k].is_bullish for k in range(1, count + 1))


def is_doji(candle: Candle) -> bool:
    """Body < 10% of the full range. Flat candles (high == low) are not doji."""
    if candle.range <= 0:
        return False
    return candle.body / candle.range < config.DOJI_BODY_RATIO


def _prev_bearish_count(candles: list[Candle], idx: int) -> int:
    """How many preceding candles are bearish (capped at 3), for the caption."""
    n = 0
    for k in range(1, 4):
        if idx - k < 0 or not candles[idx - k].is_bearish:
            break
        n += 1
    return n


def _prev_bullish_count(candles: list[Candle], idx: int) -> int:
    n = 0
    for k in range(1, 4):
        if idx - k < 0 or not candles[idx - k].is_bullish:
            break
        n += 1
    return n


def _min_body() -> float:
    return config.MIN_ENGULFING_BODY_POINTS * config.POINT_VALUE


def detect_bullish_engulfing(
    candles: list[Candle], idx: int, symbol: str = ""
) -> Optional[PatternResult]:
    """Bullish engulfing: a bullish candle that engulfs the previous bearish one."""
    if idx < 1 or idx >= len(candles):
        return None

    cur = candles[idx]
    prev = candles[idx - 1]

    bear_count = _prev_bearish_count(candles, idx)
    if bear_count < config.ENGULFING_PREV_CANDLES_MIN:
        return None
    if bear_count > config.ENGULFING_PREV_CANDLES_MAX:
        return None
    if not cur.is_bullish:
        return None
    if not (cur.open <= prev.close):
        return None
    if not (cur.close >= prev.open):
        return None

    body = cur.body
    prev_body = prev.body
    if not (body > prev_body):
        return None
    if body < _min_body():
        return None

    body_points = round(body / config.POINT_VALUE)
    engulf_pct = 100.0 if prev_body <= 0 else min(100.0, body / prev_body * 100.0)

    # Confidence: stronger when more preceding bearish candles / bigger body.
    confidence = 0.55
    if bear_count >= 2:
        confidence += 0.1
    if bear_count >= 3:
        confidence += 0.1
    if body >= 2 * _min_body():
        confidence += 0.1
    confidence = min(confidence, 0.95)

    return PatternResult(
        type="BULLISH_ENGULFING",
        confidence=confidence,
        symbol=symbol,
        meta={
            "idx": idx,
            "body_points": body_points,
            "body_usd": round(body, 2),
            "prev_bearish": bear_count,
            "engulf_pct": round(engulf_pct),
        },
    )


def detect_bearish_engulfing(
    candles: list[Candle], idx: int, symbol: str = ""
) -> Optional[PatternResult]:
    """Bearish engulfing: a bearish candle that engulfs the previous bullish one."""
    if idx < 1 or idx >= len(candles):
        return None

    cur = candles[idx]
    prev = candles[idx - 1]

    bull_count = _prev_bullish_count(candles, idx)
    if bull_count < config.ENGULFING_PREV_CANDLES_MIN:
        return None
    if bull_count > config.ENGULFING_PREV_CANDLES_MAX:
        return None
    if not cur.is_bearish:
        return None
    if not (cur.open >= prev.close):
        return None
    if not (cur.close <= prev.open):
        return None

    body = cur.body
    prev_body = prev.body
    if not (body > prev_body):
        return None
    if body < _min_body():
        return None

    body_points = round(body / config.POINT_VALUE)
    engulf_pct = 100.0 if prev_body <= 0 else min(100.0, body / prev_body * 100.0)

    confidence = 0.55
    if bull_count >= 2:
        confidence += 0.1
    if bull_count >= 3:
        confidence += 0.1
    if body >= 2 * _min_body():
        confidence += 0.1
    confidence = min(confidence, 0.95)

    return PatternResult(
        type="BEARISH_ENGULFING",
        confidence=confidence,
        symbol=symbol,
        meta={
            "idx": idx,
            "body_points": body_points,
            "body_usd": round(body, 2),
            "prev_bullish": bull_count,
            "engulf_pct": round(engulf_pct),
        },
    )


def detect_doji(candles: list[Candle], idx: int, symbol: str = "") -> Optional[PatternResult]:
    """Doji: indecision candle. Informational, used as extra context only."""
    if idx < 0 or idx >= len(candles):
        return None
    if not is_doji(candles[idx]):
        return None
    return PatternResult(
        type="DOJI",
        confidence=0.0,
        symbol=symbol,
        meta={"idx": idx},
    )
