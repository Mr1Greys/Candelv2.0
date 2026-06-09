"""Signal state: dedup, cooldown and invalidation per (symbol, pattern family).

Rules implemented (from the spec):
1. A formation is signalled only once; a repeat for the same family is not
   allowed sooner than ``SIGNAL_COOLDOWN_CANDLES`` candles, or until it resets
   (breakout / invalidation).
2. Invalidation:
   - Flags: price breaks the channel (either direction).
   - Triangle: price breaks support or makes a new high above the resistance line.
3. confidence < MIN_CONFIDENCE -> no signal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import config
from models import Candle, PatternResult
from utils.regression import price_at_index

logger = logging.getLogger(__name__)


def _family(pattern_type: str) -> str:
    """Group pattern variants into a family for dedup purposes."""
    if pattern_type.startswith("BEAR_FLAG"):
        return "BEAR_FLAG"
    if pattern_type.startswith("BULL_FLAG"):
        return "BULL_FLAG"
    if pattern_type.startswith("DESCENDING_TRIANGLE"):
        return "DESCENDING_TRIANGLE"
    return pattern_type  # engulfing / combo handled per-candle below


@dataclass
class ActiveSignal:
    pattern: PatternResult
    candle_index: int  # buffer-relative index at signal time
    open_time: int


class StateManager:
    """Tracks active signals per symbol and decides whether to emit."""

    def __init__(self) -> None:
        # symbol -> family -> ActiveSignal
        self._active: dict[str, dict[str, ActiveSignal]] = {}
        # global candle counter per symbol (increments on each closed candle)
        self._candle_no: dict[str, int] = {}
        # last engulfing open_time signalled per symbol (avoid duplicate on resend)
        self._last_engulf_time: dict[str, int] = {}

    def on_new_candle(self, symbol: str, candles: list[Candle]) -> None:
        """Advance the per-symbol candle counter and run invalidation checks."""
        self._candle_no[symbol] = self._candle_no.get(symbol, 0) + 1
        self._invalidate(symbol, candles)

    def should_emit(self, symbol: str, result: PatternResult, candles: list[Candle]) -> bool:
        """Return True if this detection should be sent to Telegram now."""
        if result.confidence < config.MIN_CONFIDENCE:
            return False

        # Engulfing / combo: signal once per candle close (dedup by open_time).
        if result.is_engulfing() or result.type.endswith("CONFIRMED") or "+" in result.type:
            last_time = self._last_engulf_time.get(symbol, 0)
            cur_time = candles[-1].open_time
            if cur_time <= last_time:
                return False
            self._last_engulf_time[symbol] = cur_time
            return True

        family = _family(result.type)
        active = self._active.get(symbol, {}).get(family)
        cur_no = self._candle_no.get(symbol, 0)

        if active is not None:
            # Still on cooldown -> suppress.
            if cur_no - active.candle_index < config.SIGNAL_COOLDOWN_CANDLES:
                return False

        # Register / refresh the active signal and emit.
        self._active.setdefault(symbol, {})[family] = ActiveSignal(
            pattern=result,
            candle_index=cur_no,
            open_time=candles[-1].open_time,
        )
        return True

    def _invalidate(self, symbol: str, candles: list[Candle]) -> None:
        """Drop active signals whose formation has resolved or broken."""
        active = self._active.get(symbol)
        if not active:
            return
        if not candles:
            return

        last = candles[-1]
        last_idx = len(candles) - 1
        dead: list[str] = []

        for family, sig in active.items():
            p = sig.pattern
            if family in ("BEAR_FLAG", "BULL_FLAG"):
                if p.channel_top_line and p.channel_bottom_line:
                    top = price_at_index(*p.channel_top_line, last_idx)
                    bot = price_at_index(*p.channel_bottom_line, last_idx)
                    if last.close < bot or last.close > top:
                        dead.append(family)
            elif family == "DESCENDING_TRIANGLE":
                if p.support_level is not None and last.close < p.support_level:
                    dead.append(family)
                elif p.resistance_line is not None:
                    res = price_at_index(*p.resistance_line, last_idx)
                    if last.high > res:
                        dead.append(family)

        for family in dead:
            logger.info("[%s] %s invalidated", symbol, family)
            del active[family]
