"""Core data structures shared across the project."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class Candle:
    """A single OHLCV candle.

    ``is_closed`` marks whether the candle is finalized (True) or still forming
    (the current right-most candle on the chart).
    """

    open_time: int  # ms since epoch
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True

    @property
    def body(self) -> float:
        """Absolute body size: |close - open|."""
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        """Full range: high - low (>= 0)."""
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body_ratio(self) -> float:
        """Body size as a fraction of the full range. 0.0 for flat candles."""
        rng = self.range
        if rng <= 0:
            return 0.0
        return self.body / rng

    @property
    def open_dt(self) -> datetime:
        return datetime.fromtimestamp(self.open_time / 1000, tz=timezone.utc)

    @classmethod
    def from_rest_kline(cls, k: list[Any]) -> "Candle":
        """Build from a Binance REST kline array.

        Format: [openTime, open, high, low, close, volume, closeTime, ...].
        REST returns only closed candles.
        """
        return cls(
            open_time=int(k[0]),
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
            is_closed=True,
        )

    @classmethod
    def from_ws_kline(cls, k: dict[str, Any]) -> "Candle":
        """Build from the ``k`` object of a Binance WS kline event."""
        return cls(
            open_time=int(k["t"]),
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            volume=float(k["v"]),
            is_closed=bool(k["x"]),
        )


@dataclass
class PatternResult:
    """Result of a pattern detection.

    ``meta`` carries free-form values used for the Telegram caption and the
    chart annotation (channel lines, support level, touch indices, etc.).
    """

    type: str  # e.g. "BEAR_FLAG_FORMING", "BULLISH_ENGULFING"
    confidence: float  # 0.0 - 1.0
    symbol: str = ""
    # Index references into the candle buffer (closed candles).
    impulse_start_idx: Optional[int] = None
    consolidation_start_idx: Optional[int] = None
    # Channel lines as (slope, intercept) in index/price space.
    channel_top_line: Optional[tuple[float, float]] = None
    channel_bottom_line: Optional[tuple[float, float]] = None
    # Triangle geometry.
    support_level: Optional[float] = None
    resistance_line: Optional[tuple[float, float]] = None
    # Trading context.
    breakout_target: Optional[float] = None
    breakout_level: Optional[float] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def is_engulfing(self) -> bool:
        return self.type in ("BULLISH_ENGULFING", "BEARISH_ENGULFING")
