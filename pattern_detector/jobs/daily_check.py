"""Pattern checks for Vercel Cron (REST-only, split 4H flags / 1D engulfing)."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

import config
from core.detectors import (
    min_candles_required_engulfing,
    min_candles_required_flag,
    run_combo_detectors,
    run_engulfing_detectors,
    run_flag_triangle_detectors,
    timeframe_for_pattern,
)
from core.kv_store import KVStore
from data.binance_rest import fetch_klines
from models import Candle, PatternResult
from signals.chart import render_chart
from signals.telegram import TelegramNotifier, format_caption

logger = logging.getLogger(__name__)

# Standalone flags/triangles must never fire from the daily (1D) cron.
_FLAG_ONLY_TYPES = frozenset(
    {
        "BEAR_FLAG_FORMING",
        "BULL_FLAG_FORMING",
        "DESCENDING_TRIANGLE_FORMING",
    }
)


def _closed_candles(candles: list[Candle]) -> list[Candle]:
    """Drop the in-progress REST kline (last element)."""
    return candles[:-1] if len(candles) > 1 else candles


def _dedup_key(symbol: str, result: PatternResult, open_time: int, timeframe: str) -> str:
    return f"signal:{symbol}:{timeframe}:{result.type}:{open_time}"


async def _fetch_closed(
    symbol: str, interval: str, session: aiohttp.ClientSession
) -> list[Candle]:
    candles = await fetch_klines(symbol, interval=interval, session=session)
    return _closed_candles(candles)


async def _emit_results(
    *,
    symbol: str,
    results: list[PatternResult],
    candles: list[Candle],
    timeframe: str,
    notifier: TelegramNotifier,
    kv: KVStore,
    summary: dict[str, Any],
) -> None:
    signal_candle = candles[-1]
    for result in results:
        if result.confidence < config.MIN_CONFIDENCE:
            summary["skipped"].append(
                {
                    "symbol": symbol,
                    "type": result.type,
                    "timeframe": timeframe,
                    "reason": f"confidence {result.confidence:.2f}",
                }
            )
            continue

        dedup_key = _dedup_key(symbol, result, signal_candle.open_time, timeframe)
        if await kv.exists(dedup_key):
            summary["skipped"].append(
                {
                    "symbol": symbol,
                    "type": result.type,
                    "timeframe": timeframe,
                    "reason": "already sent",
                }
            )
            continue

        if not notifier.enabled:
            summary["skipped"].append(
                {
                    "symbol": symbol,
                    "type": result.type,
                    "timeframe": timeframe,
                    "reason": "telegram not configured",
                }
            )
            continue

        tf = result.meta.get("timeframe") or timeframe_for_pattern(result)
        caption = format_caption(result, signal_candle, symbol, timeframe=tf)
        try:
            png = render_chart(candles, result, symbol, timeframe=tf)
            await notifier.send_photo(png, caption)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] chart failed %s; sending text", symbol, result.type)
            await notifier.send_text(caption)

        await kv.set(dedup_key)
        summary["signals_sent"].append(
            {
                "symbol": symbol,
                "type": result.type,
                "timeframe": tf,
                "confidence": result.confidence,
                "open_time": signal_candle.open_time,
            }
        )
        logger.info("SENT %s %s %s conf=%.2f", symbol, result.type, tf, result.confidence)


async def run_flag_check(timeframe: str) -> dict[str, Any]:
    """Scan flag/triangle patterns on the given timeframe (1h or 4h)."""
    summary: dict[str, Any] = {
        "mode": timeframe,
        "symbols_checked": [],
        "signals_sent": [],
        "skipped": [],
        "errors": [],
    }
    logger.info("flag check: timeframe=%s symbols=%s", timeframe, config.SYMBOLS)
    notifier = TelegramNotifier()
    kv = KVStore()
    await notifier.start()
    try:
        async with aiohttp.ClientSession() as session:
            for symbol in config.SYMBOLS:
                summary["symbols_checked"].append(symbol)
                try:
                    closed = await _fetch_closed(symbol, timeframe, session)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[%s] %s fetch failed", symbol, timeframe)
                    summary["errors"].append({"symbol": symbol, "error": str(exc)})
                    continue

                if len(closed) < min_candles_required_flag():
                    summary["skipped"].append(
                        {
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "reason": "not enough candles",
                        }
                    )
                    continue

                results = run_flag_triangle_detectors(symbol, closed)
                if not results:
                    summary["skipped"].append(
                        {
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "reason": "no patterns detected",
                        }
                    )
                    continue

                await _emit_results(
                    symbol=symbol,
                    results=results,
                    candles=closed,
                    timeframe=timeframe,
                    notifier=notifier,
                    kv=kv,
                    summary=summary,
                )
    finally:
        await kv.close()
        await notifier.close()
    return summary


async def run_1d_check() -> dict[str, Any]:
    """Scan 1D candles for engulfing patterns (and combos with current 4H structure)."""
    summary: dict[str, Any] = {
        "mode": "1d",
        "symbols_checked": [],
        "signals_sent": [],
        "skipped": [],
        "errors": [],
    }
    logger.info(
        "1d check: engulfing=%s combo_flag=%s symbols=%s",
        config.ENGULFING_TIMEFRAME,
        config.COMBO_FLAG_TIMEFRAME,
        config.SYMBOLS,
    )
    notifier = TelegramNotifier()
    kv = KVStore()
    await notifier.start()
    try:
        async with aiohttp.ClientSession() as session:
            for symbol in config.SYMBOLS:
                summary["symbols_checked"].append(symbol)
                try:
                    closed_1d = await _fetch_closed(symbol, config.ENGULFING_TIMEFRAME, session)
                    closed_4h = await _fetch_closed(
                        symbol, config.COMBO_FLAG_TIMEFRAME, session
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[%s] 1d fetch failed", symbol)
                    summary["errors"].append({"symbol": symbol, "error": str(exc)})
                    continue

                if len(closed_1d) < min_candles_required_engulfing():
                    summary["skipped"].append(
                        {"symbol": symbol, "timeframe": "1d", "reason": "not enough candles"}
                    )
                    continue

                combos = run_combo_detectors(symbol, closed_4h, closed_1d)
                engulfing = run_engulfing_detectors(symbol, closed_1d)
                combo_types = {c.type for c in combos}
                standalone = [e for e in engulfing if e.type not in combo_types]
                results = combos + standalone
                blocked = [r.type for r in results if r.type in _FLAG_ONLY_TYPES]
                if blocked:
                    logger.warning("[%s] blocked standalone flag on 1d cron: %s", symbol, blocked)
                results = [r for r in results if r.type not in _FLAG_ONLY_TYPES]

                if not results:
                    summary["skipped"].append(
                        {"symbol": symbol, "timeframe": "1d", "reason": "no patterns detected"}
                    )
                    continue

                await _emit_results(
                    symbol=symbol,
                    results=results,
                    candles=closed_1d,
                    timeframe=config.ENGULFING_TIMEFRAME,
                    notifier=notifier,
                    kv=kv,
                    summary=summary,
                )
    finally:
        await kv.close()
        await notifier.close()
    return summary


async def run_daily_check(mode: str = "1d") -> dict[str, Any]:
    """Dispatch cron: ``1h``/``4h`` flags, ``1d`` engulfing only."""
    logger.info(
        "cron dispatch mode=%s flag_timeframes=%s",
        mode,
        config.FLAG_TIMEFRAMES,
    )
    if mode in config.FLAG_TIMEFRAMES:
        return await run_flag_check(mode)
    if mode == "1d":
        return await run_1d_check()
    raise ValueError(f"unknown cron mode: {mode!r}")
