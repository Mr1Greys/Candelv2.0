"""Entry point: WebSocket workers on 4H (flags) and 1D (engulfing)."""
from __future__ import annotations

import asyncio
import logging
import os
import signal as os_signal

import config
from core.detectors import (
    min_candles_required_engulfing,
    min_candles_required_flag,
    run_combo_detectors,
    run_engulfing_detectors,
    run_flag_triangle_detectors,
    timeframe_for_pattern,
)
from core.state import StateManager
from data.binance_ws import BinanceWSWorker, CandleBuffer
from models import Candle, PatternResult
from signals.chart import render_chart
from signals.telegram import TelegramNotifier, format_caption

logger = logging.getLogger("pattern_detector")

state = StateManager()
notifier = TelegramNotifier()
_workers: list[BinanceWSWorker] = []
_tasks: list[asyncio.Task] = []
_stop_count = 0
_buffers_4h: dict[str, list[Candle]] = {}


def setup_logging() -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(),
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)
    logging.getLogger("websockets").setLevel(logging.WARNING)


def _state_key(symbol: str, timeframe: str) -> str:
    return f"{symbol}:{timeframe}"


async def _emit(symbol: str, results: list[PatternResult], candles: list[Candle], tf: str) -> None:
    key = _state_key(symbol, tf)
    for result in results:
        log_detection(symbol, result, candles[-1], tf)
        if not state.should_emit(key, result, candles):
            continue
        caption_tf = result.meta.get("timeframe") or timeframe_for_pattern(result)
        caption = format_caption(result, candles[-1], symbol, timeframe=caption_tf)
        try:
            png = render_chart(candles, result, symbol, timeframe=caption_tf)
            await notifier.send_photo(png, caption)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] failed to render/send chart; sending text", symbol)
            await notifier.send_text(caption)


async def handle_4h_closed(symbol: str, buffer: CandleBuffer) -> None:
    candles = buffer.closed
    if len(candles) < min_candles_required_flag():
        return

    _buffers_4h[symbol] = candles
    state.on_new_candle(_state_key(symbol, config.FLAG_TIMEFRAME), candles)
    results = run_flag_triangle_detectors(symbol, candles)
    await _emit(symbol, results, candles, config.FLAG_TIMEFRAME)


async def handle_1d_closed(symbol: str, buffer: CandleBuffer) -> None:
    candles_1d = buffer.closed
    if len(candles_1d) < min_candles_required_engulfing():
        return

    state.on_new_candle(_state_key(symbol, config.ENGULFING_TIMEFRAME), candles_1d)
    candles_4h = _buffers_4h.get(symbol, [])

    combos = run_combo_detectors(symbol, candles_4h, candles_1d) if candles_4h else []
    engulfing = run_engulfing_detectors(symbol, candles_1d)
    combo_types = {c.type for c in combos}
    standalone = [e for e in engulfing if e.type not in combo_types]
    results = combos + standalone
    await _emit(symbol, results, candles_1d, config.ENGULFING_TIMEFRAME)


def log_detection(symbol: str, result: PatternResult, candle: Candle, tf: str) -> None:
    logger.info(
        "DETECT %s %s | %s | conf=%.2f | price=%.2f | meta=%s",
        symbol,
        tf,
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
        f"Флаги / треугольник: {config.FLAG_TIMEFRAME.upper()}",
        f"Поглощения: {config.ENGULFING_TIMEFRAME.upper()}",
        "",
    ]
    for w in _workers:
        ready = w.buffer.ready()
        lines.append(
            f"• {w.symbol} {w.timeframe}: "
            f"{'готов' if ready else 'загрузка...'} ({len(w.buffer)} свечей)"
        )
    lines.extend(
        [
            "",
            "Сигналы при закрытии свечи на соответствующем таймфрейме.",
            "Confidence >= 50% — иначе сигнал не отправляется.",
        ]
    )
    return "\n".join(lines)


async def amain() -> None:
    setup_logging()
    logger.info(
        "Pattern Detector starting | symbols=%s | flags=%s | engulfing=%s",
        config.SYMBOLS,
        config.FLAG_TIMEFRAME,
        config.ENGULFING_TIMEFRAME,
    )

    await notifier.start()
    notifier.set_status_provider(build_status_text)

    if notifier.enabled:
        ok = await notifier.send_text(
            f"\u2705 Pattern Detector запущен\nПары: {', '.join(config.SYMBOLS)}\n"
            f"Флаги / треугольник: {config.FLAG_TIMEFRAME.upper()}\n"
            f"Поглощения: {config.ENGULFING_TIMEFRAME.upper()}\n\n"
            f"Напиши /start для справки или /status для статуса."
        )
        if ok:
            logger.info("Telegram startup message sent")
        else:
            logger.warning("Telegram startup message failed — см. лог выше")
    else:
        logger.warning("Telegram credentials missing; signals will be logged only.")

    global _workers, _tasks
    _workers = []
    for sym in config.SYMBOLS:
        _workers.append(BinanceWSWorker(sym, handle_4h_closed, config.FLAG_TIMEFRAME))
        _workers.append(BinanceWSWorker(sym, handle_1d_closed, config.ENGULFING_TIMEFRAME))
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
