"""Ad-hoc smoke test: synthetic detectors + chart render + live REST run.

Not part of the service. Run: python smoke_test.py
"""
from __future__ import annotations

import asyncio

from models import Candle
from patterns.candle_patterns import detect_bearish_engulfing, detect_bullish_engulfing
from patterns.bear_flag import BearFlagDetector
from patterns.bull_flag import BullFlagDetector
from patterns.descending_triangle import DescendingTriangleDetector
from signals.chart import render_chart


def C(t, o, h, l, c, v=100.0, closed=True):
    return Candle(open_time=t * 4 * 3600 * 1000, open=o, high=h, low=l, close=c, volume=v, is_closed=closed)


def test_bullish_engulfing_one_prev():
    """Classic engulfing: one bearish candle then bullish engulfing (like the screenshot)."""
    candles = [
        C(0, 100, 101, 99, 100.5),   # bullish context before the drop
        C(1, 100.5, 101, 95, 95.5),  # single bearish before engulfing
        C(2, 95.0, 101, 94.5, 101.0),  # bullish engulfing (closes above prev open)
    ]
    res = detect_bullish_engulfing(candles, len(candles) - 1, "BTCUSDT")
    assert res is not None, "bullish engulfing (1 prev) not detected"
    assert res.meta["prev_bearish"] == 1
    print("OK bullish engulfing (1 prev):", res.meta, "conf", res.confidence)


def test_bullish_engulfing():
    candles = [
        C(0, 100, 101, 99, 99.5),
        C(1, 99.5, 100, 95, 95.5),   # bearish
        C(2, 95.5, 96, 92, 92.5),    # bearish
        C(3, 92.0, 100, 91.5, 99.0), # bullish engulfing (big body $7 = 700 pts)
    ]
    res = detect_bullish_engulfing(candles, len(candles) - 1, "BTCUSDT")
    assert res is not None, "bullish engulfing not detected"
    assert res.type == "BULLISH_ENGULFING"
    assert res.meta["prev_bearish"] == 3
    print("OK bullish engulfing (2 prev):", res.meta, "conf", res.confidence)
    return candles, res


def test_bearish_engulfing():
    candles = [
        C(0, 100, 101, 99, 100.5),
        C(1, 100.5, 105, 100, 104.5),  # bullish
        C(2, 104.5, 108, 104, 107.5),  # bullish
        C(3, 108, 108.5, 100, 100.5),  # bearish engulfing
    ]
    res = detect_bearish_engulfing(candles, len(candles) - 1, "BTCUSDT")
    assert res is not None, "bearish engulfing not detected"
    print("OK bearish engulfing:", res.meta, "conf", res.confidence)


def build_bear_flag():
    candles = []
    t = 0
    # baseline
    for i in range(6):
        candles.append(C(t, 1000, 1002, 998, 1000)); t += 1
    # impulse down: 4 strong red candles ~ -4%
    price = 1000.0
    for i in range(4):
        o = price
        c = price - 11
        candles.append(C(t, o, o + 1, c - 1, c, v=300)); t += 1
        price = c
    # rising channel consolidation (8 candles), small bodies, drifting up
    base = price
    for i in range(8):
        o = base + i * 1.2
        c = o + 0.5
        candles.append(C(t, o - 0.5, c + 0.5, o - 1.0, c, v=80)); t += 1
    return candles


def build_bull_flag():
    """Mirror of build_bear_flag: impulse up + falling consolidation channel."""
    candles = []
    t = 0
    for i in range(6):
        candles.append(C(t, 1000, 1002, 998, 1000)); t += 1
    price = 1000.0
    for i in range(4):
        o = price
        c = price + 11
        candles.append(C(t, o - 1, c + 1, o - 0.5, c, v=300)); t += 1
        price = c
    base = price
    for i in range(8):
        o = base - i * 1.2
        c = o - 0.5
        candles.append(C(t, o + 0.5, o + 1.0, c - 0.5, c, v=80)); t += 1
    return candles


def test_flags_triangle_no_crash():
    bear = build_bear_flag()
    bull = build_bull_flag()
    bear_res = BearFlagDetector().detect(bear, "BTCUSDT")
    bull_res = BullFlagDetector().detect(bull, "BTCUSDT")
    assert bear_res is not None, "bear flag synthetic must detect"
    assert bull_res is not None, "bull flag synthetic must detect (mirror)"
    print(f"  bear_flag: HIT {bear_res.type} conf={bear_res.confidence:.2f}")
    print(f"  bull_flag: HIT {bull_res.type} conf={bull_res.confidence:.2f}")
    tri = DescendingTriangleDetector().detect(bear, "BTCUSDT")
    print(f"  descending_triangle: {'HIT ' + tri.type if tri else 'none'}")
    return bear


async def test_live_rest():
    from data.binance_rest import fetch_klines
    try:
        candles = await fetch_klines("BTCUSDT")
    except Exception as exc:  # noqa: BLE001
        print("SKIP live REST (network):", exc)
        return
    print(f"OK live REST: {len(candles)} candles, last close={candles[-1].close}")
    from main import run_detectors
    results = run_detectors("BTCUSDT", candles)
    print(f"  live detectors -> {[r.type for r in results] or 'no patterns right now'}")


def main():
    test_bullish_engulfing_one_prev()
    candles, eng = test_bullish_engulfing()
    test_bearish_engulfing()
    test_flags_triangle_no_crash()

    png = render_chart(candles, eng, "BTCUSDT")
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "chart is not a PNG"
    print(f"OK chart render: {len(png)} bytes PNG")

    asyncio.run(test_live_rest())
    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
