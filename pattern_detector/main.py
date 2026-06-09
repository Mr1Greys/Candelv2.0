"""Entry point: launch one WebSocket worker per symbol and run detection."""
from __future__ import annotations

import asyncio
import logging
import os
import signal as os_signal
from typing import Optional

import config
from core.state import StateManager
from data.binance_ws import BinanceWSWorker, CandleBuffer
from models import Candle, PatternResult
from patterns.bear_flag import BearFlagDetector
from patterns.bull_flag import BullFlagDetector
from patterns.candle_patterns import (
    detect_bearish_engulfing,
    detect_bullish_engulfing,
)
from patterns.descending_triangle import DescendingTriangleDetector
from signals.chart import render_chart
from signals.telegram import TelegramNotifier, format_caption

logger = logging.getLogger("pattern_detector")

_FLAG_TRIANGLE_DETECTORS = [
    BearFlagDetector(),
    BullFlagDetector(),
    DescendingTriangleDetector(),
]

state = StateManager()
notifier = TelegramNotifier()
_workers: list[BinanceWSWorker] = []
_tasks: list[asyncio.Task] = []
_stop_count = 0


def setup_logging() -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(),
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)
    logging.getLogger("websockets").setLevel(logging.WARNING)


def run_detectors(symbol: str, candles: list[Candle]) -> list[PatternResult]:
    """Run all detectors on the closed candle list and apply combo logic."""
    results: list[PatternResult] = []

    flag_triangle: list[PatternResult] = []
    for det in _FLAG_TRIANGLE_DETECTORS:
        try:
            res = det.detect(candles, symbol)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] detector %s failed", symbol, det.name)
            res = None
        if res is not None:
            flag_triangle.append(res)

    last_idx = len(candles) - 1
    bull_eng = detect_bullish_engulfing(candles, last_idx, symbol)
    bear_eng = detect_bearish_engulfing(candles, last_idx, symbol)

    combo = _combine(flag_triangle, bull_eng, bear_eng, candles, symbol)
    if combo is not None:
        results.append(combo)

    results.extend(flag_triangle)
    # Only send standalone engulfing if it wasn't already folded into a combo.
    if combo is None:
        if bull_eng is not None:
            results.append(bull_eng)
        if bear_eng is not None:
            results.append(bear_eng)

    return results


def _combine(
    flag_triangle: list[PatternResult],
    bull_eng: Optional[PatternResult],
    bear_eng: Optional[PatternResult],
    candles: list[Candle],
    symbol: str,
) -> Optional[PatternResult]:
    """Synthesize a stronger combined signal when patterns coincide."""
    last = candles[-1]
    by_type = {p.type: p for p in flag_triangle}

    # Bearish engulfing confirming a bear-flag breakdown.
    bear_flag = by_type.get("BEAR_FLAG_FORMING")
    if bear_eng is not None and bear_flag is not None and bear_flag.breakout_level:
        if last.close <= bear_flag.breakout_level * 1.001:
            conf = min(0.95, max(bear_flag.confidence, bear_eng.confidence) + 0.1)
            return PatternResult(
                type="BEAR_FLAG_BREAKOUT_CONFIRMED",
                confidence=conf,
                symbol=symbol,
                channel_top_line=bear_flag.channel_top_line,
                channel_bottom_line=bear_flag.channel_bottom_line,
                impulse_start_idx=bear_flag.impulse_start_idx,
                consolidation_start_idx=bear_flag.consolidation_start_idx,
                breakout_level=bear_flag.breakout_level,
                breakout_target=bear_flag.breakout_target,
                meta={
                    **bear_eng.meta,
                    "headline": "BEAR FLAG BREAKOUT CONFIRMED by BEARISH ENGULFING",
                },
            )

    # Bullish engulfing testing descending-triangle support.
    triangle = by_type.get("DESCENDING_TRIANGLE_FORMING")
    if bull_eng is not None and triangle is not None and triangle.support_level:
        if abs(last.low - triangle.support_level) <= triangle.support_level * 0.01:
            conf = min(0.95, max(triangle.confidence, bull_eng.confidence) + 0.1)
            return PatternResult(
                type="TRIANGLE_SUPPORT_TEST_BULLISH_ENGULFING",
                confidence=conf,
                symbol=symbol,
                support_level=triangle.support_level,
                resistance_line=triangle.resistance_line,
                breakout_level=triangle.breakout_level,
                meta={
                    **bull_eng.meta,
                    "window_start": triangle.meta.get("window_start"),
                    "headline": "TRIANGLE SUPPORT TEST + BULLISH ENGULFING",
                },
            )

    return None


async def handle_closed_candle(symbol: str, buffer: CandleBuffer) -> None:
    candles = buffer.closed
    if len(candles) < config.CONSOLIDATION_MIN + config.IMPULSE_CANDLES_MIN:
        return

    state.on_new_candle(symbol, candles)
    results = run_detectors(symbol, candles)

    for result in results:
        log_detection(symbol, result, candles[-1])
        if not state.should_emit(symbol, result, candles):
            continue
        caption = format_caption(result, candles[-1], symbol)
        try:
            png = render_chart(candles, result, symbol)
            await notifier.send_photo(png, caption)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] failed to render/send chart; sending text", symbol)
            await notifier.send_text(caption)


def log_detection(symbol: str, result: PatternResult, candle: Candle) -> None:
    logger.info(
        "DETECT %s | %s | conf=%.2f | price=%.2f | meta=%s",
        symbol,
        result.type,
        result.confidence,
        candle.close,
        result.meta,
    )


async def build_status_text() -> str:
    lines = [
        "\U0001F4CA Pattern Detector — статус",
        "",
        f"Пары: {', '.join(config.SYMBOLS)}",
        f"Таймфрейм: {config.TIMEFRAME.upper()}",
        "",
    ]
    for w in _workers:
        ready = w.buffer.ready()
        lines.append(f"• {w.symbol}: {'готов' if ready else 'загрузка...'} ({len(w.buffer)} свечей)")
    lines.extend(
        [
            "",
            f"Сигналы приходят при закрытии каждой {config.TIMEFRAME.upper()} свечи, если найден паттерн.",
            "Confidence >= 50% — иначе сигнал не отправляется.",
        ]
    )
    return "\n".join(lines)


async def amain() -> None:
    setup_logging()
    logger.info("Pattern Detector starting | symbols=%s | tf=%s", config.SYMBOLS, config.TIMEFRAME)

    await notifier.start()
    notifier.set_status_provider(build_status_text)

    if notifier.enabled:
        ok = await notifier.send_text(
            f"\u2705 Pattern Detector запущен\nПары: {', '.join(config.SYMBOLS)}\n"
            f"Таймфрейм: {config.TIMEFRAME.upper()}\n\n"
            f"Напиши /start для справки или /status для статуса."
        )
        if ok:
            logger.info("Telegram startup message sent")
        else:
            logger.warning("Telegram startup message failed — см. лог выше")
    else:
        logger.warning("Telegram credentials missing; signals will be logged only.")

    global _workers, _tasks
    _workers = [BinanceWSWorker(sym, handle_closed_candle) for sym in config.SYMBOLS]
    _tasks = [asyncio.create_task(w.run()) for w in _workers]
    if notifier.enabled:
        _tasks.append(asyncio.create_task(notifier.poll_commands()))

    def _request_stop() -> None:
        global _stop_count
        _stop_count += 1
        if _stop_count >= 2:
            logger.warning("Force exit")
            os._exit(1)
        logger.info("Shutdown requested (Ctrl+C ещё раз — принудительный выход)")
        for w in _workers:
            w.stop()
        notifier.request_stop()
        for task in _tasks:
            if not task.done():
                task.cancel()

    loop = asyncio.get_running_loop()
    for sig in (os_signal.SIGINT, os_signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass  # Windows

    try:
        await asyncio.gather(*_tasks)
    except asyncio.CancelledError:
        pass
    finally:
        await notifier.close()
        logger.info("Pattern Detector stopped")


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
