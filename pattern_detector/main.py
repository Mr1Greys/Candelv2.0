"""Entry point: launch one WebSocket worker per symbol and run detection."""
from __future__ import annotations

import asyncio
import logging
import os
import signal as os_signal
import config
from core.detectors import min_candles_required, run_detectors
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


def setup_logging() -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(),
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)
    logging.getLogger("websockets").setLevel(logging.WARNING)


async def handle_closed_candle(symbol: str, buffer: CandleBuffer) -> None:
    candles = buffer.closed
    if len(candles) < min_candles_required():
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
