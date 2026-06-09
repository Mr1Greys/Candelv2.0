"""Daily pattern check for Vercel Cron (REST-only, no WebSocket)."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

import config
from core.detectors import min_candles_required, run_detectors
from core.kv_store import KVStore
from data.binance_rest import fetch_klines
from models import PatternResult
from signals.chart import render_chart
from signals.telegram import TelegramNotifier, format_caption

logger = logging.getLogger(__name__)


def _dedup_key(symbol: str, result: PatternResult, open_time: int) -> str:
    return f"signal:{symbol}:{result.type}:{open_time}"


async def run_daily_check() -> dict[str, Any]:
    """Fetch 1D candles, run all detectors, send Telegram alerts."""
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

                # REST returns the current in-progress candle as the last element.
                closed = candles[:-1] if len(candles) > 1 else candles

                if len(closed) < min_candles_required():
                    summary["skipped"].append(
                        {
                            "symbol": symbol,
                            "reason": f"not enough candles ({len(closed)})",
                        }
                    )
                    continue

                signal_candle = closed[-1]
                results = run_detectors(symbol, closed)

                if not results:
                    summary["skipped"].append(
                        {"symbol": symbol, "reason": "no patterns detected"}
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

                    dedup_key = _dedup_key(symbol, result, signal_candle.open_time)
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
                    try:
                        png = render_chart(closed, result, symbol)
                        await notifier.send_photo(png, caption)
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "[%s] chart render failed for %s; sending text",
                            symbol,
                            result.type,
                        )
                        await notifier.send_text(caption)

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
