"""Bear flag detector: downward impulse + rising counter-trend channel.

Validated reference (2026-06-01, BTCUSDT 4H):
  impulse 5 candles -3.58%, consolidation 24 candles, conf 0.88.
Uses shared ``detect_flag(..., direction="bear")`` — see config FLAG_* params.
"""
from __future__ import annotations

from typing import Optional

from models import Candle, PatternResult
from patterns.base import PatternDetector, detect_flag


class BearFlagDetector(PatternDetector):
    name = "bear_flag"

    def detect(self, candles: list[Candle], symbol: str) -> Optional[PatternResult]:
        return detect_flag(candles, symbol, direction="bear")
