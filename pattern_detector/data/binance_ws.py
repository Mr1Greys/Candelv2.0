"""Binance WebSocket client with an in-memory candle buffer and auto-reconnect."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from typing import Awaitable, Callable, Optional

import aiohttp
import websockets

import config
from data.binance_rest import fetch_klines
from models import Candle

logger = logging.getLogger(__name__)

# Called with (symbol, buffer) every time a candle closes.
OnClosedCandle = Callable[[str, "CandleBuffer"], Awaitable[None]]


class CandleBuffer:
    """Holds the last ``maxlen`` closed candles plus the current forming candle."""

    def __init__(self, maxlen: int = config.BUFFER_SIZE):
        self._closed: deque[Candle] = deque(maxlen=maxlen)
        self.current: Optional[Candle] = None

    def bootstrap(self, candles: list[Candle]) -> None:
        """Replace the closed-candle history (oldest-first)."""
        self._closed.clear()
        for c in candles:
            self._closed.append(c)
        self.current = None

    def update(self, candle: Candle) -> bool:
        """Apply a candle update from the stream.

        Returns True if this update closed a candle (i.e. detection should run).
        """
        if candle.is_closed:
            # Replace the forming candle if it shares the same open_time, then
            # append it as a finalized candle.
            if (
                self._closed
                and self._closed[-1].open_time == candle.open_time
            ):
                # Duplicate close event for an already-stored candle; ignore.
                self.current = None
                return False
            self._closed.append(candle)
            self.current = None
            return True

        # Still forming: keep as context, no detection trigger.
        self.current = candle
        return False

    @property
    def closed(self) -> list[Candle]:
        return list(self._closed)

    def with_current(self) -> list[Candle]:
        """Closed candles plus the current forming candle (if any)."""
        candles = list(self._closed)
        if self.current is not None:
            candles.append(self.current)
        return candles

    def __len__(self) -> int:
        return len(self._closed)

    def ready(self) -> bool:
        return len(self._closed) >= config.CONSOLIDATION_MIN + config.IMPULSE_CANDLES_MIN


class BinanceWSWorker:
    """Maintains a live candle buffer for one symbol and triggers detection."""

    def __init__(
        self,
        symbol: str,
        on_closed: OnClosedCandle,
        timeframe: str = config.FLAG_TIMEFRAME,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.on_closed = on_closed
        self.buffer = CandleBuffer()
        self._stop = asyncio.Event()
        self._ws = None

    async def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep that returns early when ``stop()`` is called."""
        if self._stop.is_set():
            return
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    @property
    def stream_url(self) -> str:
        return f"{config.BINANCE_WS_BASE}/{self.symbol.lower()}@kline_{self.timeframe}"

    async def _bootstrap(self, session: aiohttp.ClientSession) -> None:
        candles = await fetch_klines(self.symbol, interval=self.timeframe, session=session)
        # The last REST candle may still be the in-progress one; keep only closed.
        # REST klines are closed except possibly the final element when it equals
        # the current period. We keep BUFFER_SIZE most recent and let the WS
        # stream re-close the latest as needed.
        self.buffer.bootstrap(candles[-config.BUFFER_SIZE:])
        logger.info(
            "[%s %s] buffer ready: %d closed candles",
            self.symbol,
            self.timeframe,
            len(self.buffer),
        )
        if self.buffer.ready():
            await self.on_closed(self.symbol, self.buffer)

    async def run(self) -> None:
        backoff = 1
        async with aiohttp.ClientSession() as session:
            while not self._stop.is_set():
                try:
                    await self._bootstrap(session)
                    if self._stop.is_set():
                        break
                    async with websockets.connect(
                        self.stream_url,
                        ping_interval=20,
                        ping_timeout=20,
                        close_timeout=5,
                    ) as ws:
                        self._ws = ws
                        logger.info("[%s %s] WS connected", self.symbol, self.timeframe)
                        backoff = 1
                        try:
                            consume_task = asyncio.create_task(self._consume(ws))
                            stop_task = asyncio.create_task(self._stop.wait())
                            done, pending = await asyncio.wait(
                                [consume_task, stop_task],
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            for task in pending:
                                task.cancel()
                                try:
                                    await task
                                except asyncio.CancelledError:
                                    pass
                        finally:
                            self._ws = None
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - resilience over precision
                    if self._stop.is_set():
                        break
                    logger.warning(
                        "[%s] WS error: %s; reconnecting in %ss",
                        self.symbol, exc, backoff,
                    )
                    await self._interruptible_sleep(backoff)
                    backoff = min(backoff * 2, 60)

    async def _consume(self, ws) -> None:
        async for raw in ws:
            if self._stop.is_set():
                break
            try:
                msg = json.loads(raw)
                k = msg.get("k")
                if not k:
                    continue
                candle = Candle.from_ws_kline(k)
                closed = self.buffer.update(candle)
                if closed:
                    logger.debug(
                        "[%s] candle closed @ %s", self.symbol, candle.open_dt
                    )
                    await self.on_closed(self.symbol, self.buffer)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("[%s] failed to process message: %s", self.symbol, exc)

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is None:
            return
        try:
            asyncio.get_running_loop().create_task(ws.close())
        except RuntimeError:
            pass
