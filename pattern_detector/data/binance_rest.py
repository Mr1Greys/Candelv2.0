"""Bootstrap historical candles via the public Binance REST klines endpoint."""
from __future__ import annotations

import aiohttp

import config
from models import Candle


async def fetch_klines(
    symbol: str,
    interval: str = config.TIMEFRAME,
    limit: int = config.BUFFER_SIZE + 1,
    session: aiohttp.ClientSession | None = None,
) -> list[Candle]:
    """Fetch the latest ``limit`` closed klines for ``symbol``.

    Returns candles oldest-first. No API key required for public market data.
    """
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession()
    try:
        async with session.get(config.BINANCE_REST_URL, params=params) as resp:
            if resp.status >= 400:
                body = await resp.text()
                raise aiohttp.ClientResponseError(
                    resp.request_info,
                    resp.history,
                    status=resp.status,
                    message=f"{symbol} {interval}: {body[:200]}",
                )
            raw = await resp.json()
    finally:
        if owns_session:
            await session.close()

    return [Candle.from_rest_kline(k) for k in raw]
