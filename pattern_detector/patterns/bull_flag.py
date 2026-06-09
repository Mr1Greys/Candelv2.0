"""Bull flag detector: upward impulse + falling counter-trend channel.

Mirror of bear flag — same FLAG_* thresholds and ``detect_flag`` logic:
  impulse UP (3–6 green candles), consolidation in a descending channel,
  price still inside channel (not broken out up).
"""
from __future__ import annotations

from typing import Optional

from models import Candle, PatternResult
from patterns.base import PatternDetector, detect_flag


class BullFlagDetector(PatternDetector):
    name = "bull_flag"

    def detect(self, candles: list[Candle], symbol: str) -> Optional[PatternResult]:
        return detect_flag(candles, symbol, direction="bull")
