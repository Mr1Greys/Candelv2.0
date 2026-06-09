"""Render an annotated candlestick chart to PNG bytes (pure matplotlib)."""
from __future__ import annotations

import io
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # headless backend, no display needed
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

import config  # noqa: E402
from models import Candle, PatternResult  # noqa: E402
from utils.regression import price_at_index  # noqa: E402

_UP = "#26a69a"
_DOWN = "#ef5350"
_LINE = "#2962ff"
_LINE2 = "#ff6d00"
_HILITE = "#ffd54f"


def render_chart(
    candles: list[Candle],
    pattern: PatternResult,
    symbol: str,
    timeframe: str | None = None,
) -> bytes:
    """Draw the last ``CHART_CANDLES`` candles with pattern overlays.

    ``candles`` is the closed-candle list (oldest-first). Pattern indices are
    absolute into this list, so we use the absolute index as the x coordinate.
    """
    n = len(candles)
    view = (
        config.CHART_ENGULFING_CANDLES
        if pattern.is_engulfing()
        else config.CHART_CANDLES
    )
    x_start = max(0, n - view)

    fig, ax = plt.subplots(figsize=(11, 6), dpi=110)

    for i in range(x_start, n):
        c = candles[i]
        color = _UP if c.close >= c.open else _DOWN
        # Wick
        ax.plot([i, i], [c.low, c.high], color=color, linewidth=0.8, zorder=2)
        # Body
        lower = min(c.open, c.close)
        height = max(abs(c.close - c.open), (c.high - c.low) * 0.001)
        ax.add_patch(
            Rectangle(
                (i - 0.3, lower),
                0.6,
                height,
                facecolor=color,
                edgecolor=color,
                zorder=3,
            )
        )

    _overlay_pattern(ax, candles, pattern, x_start, n)

    ax.set_xlim(x_start - 1, n)
    tf = (timeframe or config.FLAG_TIMEFRAME).upper()
    title = f"{pattern.type}  |  {symbol}  |  {tf}"
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.grid(True, alpha=0.2)
    ax.set_ylabel("Price (USDT)")
    ax.set_xticks([])

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _overlay_pattern(
    ax, candles: list[Candle], pattern: PatternResult, x_start: int, n: int
) -> None:
    last_idx = n - 1

    # Flag channel lines.
    if pattern.channel_top_line and pattern.channel_bottom_line:
        cons_start = pattern.consolidation_start_idx or x_start
        xs = list(range(cons_start, n))
        top = [price_at_index(*pattern.channel_top_line, x) for x in xs]
        bot = [price_at_index(*pattern.channel_bottom_line, x) for x in xs]
        ax.plot(xs, top, color=_LINE, linewidth=1.6, label="Channel top")
        ax.plot(xs, bot, color=_LINE2, linewidth=1.6, label="Channel bottom")
        if pattern.impulse_start_idx is not None:
            _mark_impulse(ax, candles, pattern.impulse_start_idx, cons_start)

    # Triangle: support + resistance.
    if pattern.support_level is not None:
        win_start = pattern.meta.get("window_start", x_start)
        ax.hlines(
            pattern.support_level,
            win_start,
            n - 1,
            color=_LINE2,
            linewidth=1.6,
            label="Support",
        )
        if pattern.resistance_line is not None:
            xs = list(range(win_start, n))
            res = [price_at_index(*pattern.resistance_line, x) for x in xs]
            ax.plot(xs, res, color=_LINE, linewidth=1.6, label="Resistance")

    # Engulfing: highlight engulfing candle + preceding opposite candles.
    idx = pattern.meta.get("idx")
    if pattern.is_engulfing() and isinstance(idx, int) and 0 <= idx < n:
        prev_count = pattern.meta.get("prev_bearish") or pattern.meta.get("prev_bullish") or 1
        for k in range(1, int(prev_count) + 1):
            pi = idx - k
            if pi < 0:
                break
            pc = candles[pi]
            ax.add_patch(
                Rectangle(
                    (pi - 0.45, pc.low),
                    0.9,
                    max(pc.high - pc.low, 1e-9),
                    facecolor="none",
                    edgecolor="#90a4ae",
                    linewidth=1.2,
                    linestyle="--",
                    zorder=4,
                )
            )
        c = candles[idx]
        ax.add_patch(
            Rectangle(
                (idx - 0.45, c.low),
                0.9,
                max(c.high - c.low, 1e-9),
                facecolor="none",
                edgecolor=_HILITE,
                linewidth=2.5,
                zorder=5,
            )
        )

    # Breakout target / level reference lines.
    if pattern.breakout_level is not None:
        ax.axhline(pattern.breakout_level, color="#90a4ae", linewidth=0.8, linestyle="--")
    if pattern.breakout_target is not None:
        ax.axhline(pattern.breakout_target, color="#90a4ae", linewidth=0.8, linestyle=":")

    handles, labels = ax.get_legend_handles_labels()
    if labels:
        ax.legend(loc="best", fontsize=8, framealpha=0.6)


def _mark_impulse(ax, candles: list[Candle], imp_start: int, cons_start: int) -> None:
    """Shade the flagpole span lightly."""
    if cons_start <= imp_start:
        return
    ax.axvspan(imp_start - 0.5, cons_start - 0.5, color="#b0bec5", alpha=0.12)
