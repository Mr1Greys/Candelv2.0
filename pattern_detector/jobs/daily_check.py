"""Daily engulfing check for Vercel Cron (REST-only, no WebSocket)."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

import config
from core.kv_store import KVStore
from data.binance_rest import fetch_klines
from models import Candle, PatternResult
from patterns.candle_patterns import detect_bearish_engulfing, detect_bullish_engulfing
from signals.chart import render_chart
from signals.telegram import TelegramNotifier, format_caption

logger = logging.getLogger(__name__)


def detect_engulfing_only(symbol: str, candles: list[Candle]) -> list[PatternResult]:
    """Run bullish/bearish engulfing detectors on the last closed candle."""
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


async def run_daily_check() -> dict[str, Any]:
    """Fetch 1D candles, detect engulfing on last closed day, send Telegram alerts."""
    summary: dict[str, Any] = {
        "symbols_checked": [],
        "signals_sent": [],
        "skipped": [],
        "errors": [],
    }

    notifier = TelegramNotifier()
    kv = KVStore()
    await notifier.start()

    try:
        async with aiohttp.ClientSession() as session:
            for symbol in config.SYMBOLS:
                summary["symbols_checked"].append(symbol)
                try:
                    candles = await fetch_klines(symbol, session=session)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[%s] fetch failed", symbol)
                    summary["errors"].append({"symbol": symbol, "error": str(exc)})
                    continue

                if len(candles) < 2:
                    summary["skipped"].append(
                        {"symbol": symbol, "reason": "not enough candles"}
                    )
                    continue

                # REST returns the current in-progress candle as the last element.
                closed = candles[:-1]
                signal_candle = closed[-1]
                results = detect_engulfing_only(symbol, closed)

                if not results:
                    summary["skipped"].append(
                        {"symbol": symbol, "reason": "no engulfing pattern"}
                    )
                    continue

                for result in results:
                    if result.confidence < config.MIN_CONFIDENCE:
                        summary["skipped"].append(
                            {
                                "symbol": symbol,
                                "type": result.type,
                                "reason": f"confidence {result.confidence:.2f}",
                            }
                        )
                        continue

                    dedup_key = f"engulf:{symbol}:{signal_candle.open_time}:{result.type}"
                    if await kv.exists(dedup_key):
                        summary["skipped"].append(
                            {
                                "symbol": symbol,
                                "type": result.type,
                                "reason": "already sent",
                            }
                        )
                        continue

                    if not notifier.enabled:
                        summary["skipped"].append(
                            {
                                "symbol": symbol,
                                "type": result.type,
                                "reason": "telegram not configured",
                            }
                        )
                        continue

                    caption = format_caption(result, signal_candle, symbol)
                    png = render_chart(closed, result, symbol)
                    await notifier.send_photo(png, caption)
                    await kv.set(dedup_key)
                    summary["signals_sent"].append(
                        {
                            "symbol": symbol,
                            "type": result.type,
                            "confidence": result.confidence,
                            "open_time": signal_candle.open_time,
                        }
                    )
                    logger.info(
                        "SENT %s %s conf=%.2f open_time=%s",
                        symbol,
                        result.type,
                        result.confidence,
                        signal_candle.open_time,
                    )
    finally:
        await kv.close()
        await notifier.close()

    return summary
