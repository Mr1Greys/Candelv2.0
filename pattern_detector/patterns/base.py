"""Base class and shared helpers for pattern detectors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import config
from models import Candle, PatternResult
from utils.regression import angle_degrees, linear_regression_line, price_at_index


class PatternDetector(ABC):
    """Common interface for all detectors.

    A detector inspects a list of closed candles (oldest-first, right-most is the
    most recently closed candle) and returns a ``PatternResult`` when a pattern
    is forming, or ``None``.
    """

    name: str = "base"

    @abstractmethod
    def detect(self, candles: list[Candle], symbol: str) -> Optional[PatternResult]:
        ...


def atr(candles: list[Candle], period: int = config.ATR_PERIOD) -> float:
    """Average True Range over the last ``period`` candles.

    Returns 0.0 if there are not enough candles.
    """
    if len(candles) < period + 1:
        return 0.0
    trs: list[float] = []
    for i in range(len(candles) - period, len(candles)):
        cur = candles[i]
        prev = candles[i - 1]
        tr = max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        )
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def pct_move(start_price: float, end_price: float) -> float:
    """Signed percentage move from ``start_price`` to ``end_price``."""
    if start_price == 0:
        return 0.0
    return (end_price - start_price) / start_price * 100.0


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def detect_flag(
    candles: list[Candle], symbol: str, direction: str
) -> Optional[PatternResult]:
    """Generic flag detector shared by bear and bull flags.

    Scans the full buffer: impulse may sit anywhere before the consolidation
    phase. Consolidation always runs from ``impulse_end`` through the last
    closed candle (still forming, not broken out).
    """
    is_bear = direction == "bear"
    n = len(candles)
    if n < config.IMPULSE_CANDLES_MIN + config.CONSOLIDATION_MIN:
        return None

    best: Optional[PatternResult] = None
    best_conf = -1.0

    # impulse_end = first index of the consolidation phase.
    lo = max(config.IMPULSE_CANDLES_MIN, n - config.CONSOLIDATION_MAX)
    hi = n - config.CONSOLIDATION_MIN
    for impulse_end in range(lo, hi + 1):
        cons = candles[impulse_end:]
        cons_len = len(cons)
        if cons_len < config.CONSOLIDATION_MIN or cons_len > config.CONSOLIDATION_MAX:
            continue

        for imp_len in range(config.IMPULSE_CANDLES_MIN, config.IMPULSE_CANDLES_MAX + 1):
            imp_start = impulse_end - imp_len
            if imp_start < 0:
                continue
            impulse = candles[imp_start:impulse_end]

            move = pct_move(impulse[0].open, impulse[-1].close)
            if is_bear and move > -config.IMPULSE_MOVE_MIN_PCT:
                continue
            if not is_bear and move < config.IMPULSE_MOVE_MIN_PCT:
                continue

            strong = sum(
                1
                for c in impulse
                if c.body_ratio >= config.IMPULSE_BODY_MIN_RATIO
                and (c.is_bearish if is_bear else c.is_bullish)
            )
            min_strong = _min_strong_candles(impulse, imp_len, move, is_bear)
            if strong < min_strong:
                continue

            result = _evaluate_channel(
                candles, cons, imp_start, impulse_end, move, is_bear, symbol
            )
            if result is not None and result.confidence > best_conf:
                best = result
                best_conf = result.confidence

    return best


def _min_strong_candles(
    impulse: list[Candle], imp_len: int, move: float, is_bear: bool
) -> int:
    """How many strong directional candles are required in the impulse."""
    all_dir = (
        all(c.is_bearish for c in impulse)
        if is_bear
        else all(c.is_bullish for c in impulse)
    )
    # Uniform impulse (all red/green) with a solid move — allow one wick-heavy candle.
    if all_dir and abs(move) >= config.IMPULSE_MOVE_MIN_PCT * config.FLAG_IMPULSE_UNIFORM_MOVE_MULT:
        return max(2, imp_len - 3)
    return max(2, imp_len - 2)


def _evaluate_channel(
    candles: list[Candle],
    cons: list[Candle],
    imp_start: int,
    cons_start: int,
    move: float,
    is_bear: bool,
    symbol: str,
) -> Optional[PatternResult]:
    """Fit the consolidation channel and validate flag geometry."""
    # X axis = absolute candle index in the buffer.
    highs = [(cons_start + i, c.high) for i, c in enumerate(cons)]
    lows = [(cons_start + i, c.low) for i, c in enumerate(cons)]

    top_slope, top_int = linear_regression_line(highs)
    bot_slope, bot_int = linear_regression_line(lows)

    top_angle = angle_degrees(top_slope)
    bot_angle = angle_degrees(bot_slope)

    # Counter-trend slope: bear flag rises, bull flag falls.
    if is_bear and not (top_angle > 0 and bot_angle > 0):
        return None
    if not is_bear and not (top_angle < 0 and bot_angle < 0):
        return None

    # Lines must be roughly parallel.
    if abs(top_angle - bot_angle) > config.CHANNEL_PARALLEL_TOLERANCE:
        return None

    # Channel width vs flagpole size.
    last_idx = cons_start + len(cons) - 1
    top_now = price_at_index(top_slope, top_int, last_idx)
    bot_now = price_at_index(bot_slope, bot_int, last_idx)
    channel_width = abs(top_now - bot_now)

    flagpole = candles[imp_start]
    flagpole_size = abs(candles[cons_start - 1].close - flagpole.open)
    if flagpole_size <= 0:
        return None
    if channel_width > config.CHANNEL_WIDTH_MAX_RATIO * flagpole_size:
        return None

    # Price must still be inside the channel (not yet broken in trend direction).
    last_close = cons[-1].close
    if is_bear and last_close < bot_now:
        return None  # already broke down -> not "forming"
    if not is_bear and last_close > top_now:
        return None  # already broke up -> not "forming"

    candles_in_cons = len(cons)

    # Confidence model.
    confidence = 0.5
    confidence += min(0.2, (abs(move) - config.IMPULSE_MOVE_MIN_PCT) * 0.04)
    parallel_quality = 1.0 - (abs(top_angle - bot_angle) / config.CHANNEL_PARALLEL_TOLERANCE)
    confidence += 0.15 * clamp01(parallel_quality)
    tightness = 1.0 - (channel_width / (config.CHANNEL_WIDTH_MAX_RATIO * flagpole_size))
    confidence += 0.15 * clamp01(tightness)

    # Declining volume during consolidation vs impulse adds confidence.
    imp_vol = _avg_vol(candles[imp_start:cons_start])
    cons_vol = _avg_vol(cons)
    if imp_vol > 0 and cons_vol < imp_vol:
        confidence += 0.05

    # Doji inside consolidation adds a touch of confidence.
    from patterns.candle_patterns import is_doji  # local import to avoid cycle

    if any(is_doji(c) for c in cons):
        confidence += 0.05

    confidence = clamp01(confidence)

    if is_bear:
        ptype = "BEAR_FLAG_FORMING"
        breakout_level = bot_now
        breakout_target = flagpole.open - flagpole_size
    else:
        ptype = "BULL_FLAG_FORMING"
        breakout_level = top_now
        breakout_target = candles[cons_start - 1].close + flagpole_size

    return PatternResult(
        type=ptype,
        confidence=confidence,
        symbol=symbol,
        impulse_start_idx=imp_start,
        consolidation_start_idx=cons_start,
        channel_top_line=(top_slope, top_int),
        channel_bottom_line=(bot_slope, bot_int),
        breakout_target=breakout_target,
        breakout_level=breakout_level,
        meta={
            "move_pct": round(move, 2),
            "impulse_candles": cons_start - imp_start,
            "consolidation_candles": candles_in_cons,
            "channel_angle": round((top_angle + bot_angle) / 2, 2),
            "channel_width": round(channel_width, 2),
        },
    )


def _avg_vol(candles: list[Candle]) -> float:
    if not candles:
        return 0.0
    return sum(c.volume for c in candles) / len(candles)
