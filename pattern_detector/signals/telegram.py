"""Async Telegram delivery: text messages, chart photos and basic commands."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

import aiohttp

import config
from models import Candle, PatternResult

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"

WELCOME_TEXT = (
    "\U0001F44B Pattern Detector\n\n"
    f"Я мониторю BTC / ETH / SOL и присылаю сигналы:\n"
    f"• Bear / Bull Flag + треугольник — {', '.join(t.upper() for t in config.FLAG_TIMEFRAMES)}\n"
    f"• Bullish / Bearish Engulfing — {config.ENGULFING_TIMEFRAME.upper()}\n\n"
    "Сигнал = картинка графика + описание.\n"
    "Кнопок нет — только автоматические уведомления.\n\n"
    "Команды:\n"
    "/status — статус мониторинга\n"
    "/start — это сообщение"
)

StatusProvider = Callable[[], Awaitable[str]]


def _fmt_price(value: float) -> str:
    return f"{value:,.2f}"


def format_caption(
    pattern: PatternResult,
    candle: Candle,
    symbol: str,
    timeframe: str | None = None,
) -> str:
    """Build the human-readable signal text for a pattern."""
    tf = (timeframe or config.FLAG_TIMEFRAME).upper()
    price = _fmt_price(candle.close)
    when = candle.open_dt.strftime("%Y-%m-%d %H:%M UTC")
    conf = f"{round(pattern.confidence * 100)}%"
    m = pattern.meta

    if pattern.type == "BEAR_FLAG_FORMING":
        return (
            f"\U0001F534 BEAR FLAG FORMING | {symbol} | {tf}\n\n"
            f"Флагшток: {m.get('move_pct')}% за {m.get('impulse_candles')} свечей\n"
            f"Консолидация: {m.get('consolidation_candles')} свечей, "
            f"канал {m.get('channel_angle')}°\n"
            f"Confidence: {conf}\n\n"
            f"Текущая цена: {price}\n"
            f"Цель при пробое: {_fmt_price(pattern.breakout_target)}\n"
            f"Уровень пробоя: {_fmt_price(pattern.breakout_level)} (нижняя граница канала)\n\n"
            f"Время: {when}"
        )

    if pattern.type == "BULL_FLAG_FORMING":
        return (
            f"\U0001F7E2 BULL FLAG FORMING | {symbol} | {tf}\n\n"
            f"Флагшток: +{m.get('move_pct')}% за {m.get('impulse_candles')} свечей\n"
            f"Консолидация: {m.get('consolidation_candles')} свечей, "
            f"канал {m.get('channel_angle')}°\n"
            f"Confidence: {conf}\n\n"
            f"Текущая цена: {price}\n"
            f"Цель при пробое: {_fmt_price(pattern.breakout_target)}\n"
            f"Уровень пробоя: {_fmt_price(pattern.breakout_level)} (верхняя граница канала)\n\n"
            f"Время: {when}"
        )

    if pattern.type == "DESCENDING_TRIANGLE_FORMING":
        return (
            f"\U0001F53B DESCENDING TRIANGLE FORMING | {symbol} | {tf}\n\n"
            f"Поддержка: {_fmt_price(pattern.support_level)} "
            f"({m.get('support_touches')} касаний)\n"
            f"Нисходящих максимумов: {m.get('descending_highs')}\n"
            f"До схождения: ~{m.get('apex_in_candles')} свечей\n"
            f"Confidence: {conf}\n\n"
            f"Текущая цена: {price}\n"
            f"Уровень пробоя: {_fmt_price(pattern.breakout_level)} (поддержка)\n\n"
            f"Время: {when}"
        )

    if pattern.type == "BULLISH_ENGULFING":
        return (
            f"\U0001F7E2 BULLISH ENGULFING | {symbol} | {tf}\n\n"
            f"Поглощение: тело {m.get('body_points')} пунктов "
            f"(${m.get('body_usd')})\n"
            f"Предыдущих медвежьих свечей: {m.get('prev_bearish')}\n"
            f"Тело поглощает: {m.get('engulf_pct')}% предыдущей свечи\n"
            f"Confidence: {conf}\n\n"
            f"Текущая цена: {price}\n"
            f"Время: {when}"
        )

    if pattern.type == "BEARISH_ENGULFING":
        return (
            f"\U0001F534 BEARISH ENGULFING | {symbol} | {tf}\n\n"
            f"Поглощение: тело {m.get('body_points')} пунктов "
            f"(${m.get('body_usd')})\n"
            f"Предыдущих бычьих свечей: {m.get('prev_bullish')}\n"
            f"Тело поглощает: {m.get('engulf_pct')}% предыдущей свечи\n"
            f"Confidence: {conf}\n\n"
            f"Текущая цена: {price}\n"
            f"Время: {when}"
        )

    # Combined / fallback.
    headline = m.get("headline", pattern.type)
    return (
        f"\u26A1 {headline} | {symbol} | {tf}\n\n"
        f"Confidence: {conf}\n\n"
        f"Текущая цена: {price}\n"
        f"Время: {when}"
    )


class TelegramNotifier:
    """Thin async wrapper over the Telegram Bot API."""

    def __init__(
        self,
        token: str = config.TELEGRAM_BOT_TOKEN,
        chat_id: str = config.TELEGRAM_CHAT_ID,
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self._session: aiohttp.ClientSession | None = None
        self._update_offset = 0
        self._status_provider: Optional[StatusProvider] = None
        self._poll_stop = asyncio.Event()

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    async def start(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        self._poll_stop.set()
        if self._session is not None:
            await self._session.close()
            self._session = None

    def request_stop(self) -> None:
        """Signal the command polling loop to exit."""
        self._poll_stop.set()

    def set_status_provider(self, provider: StatusProvider) -> None:
        self._status_provider = provider

    async def send_text(self, text: str, chat_id: str | None = None) -> bool:
        """Send a text message. Returns True on success."""
        target = chat_id or self.chat_id
        if not self.token or not target:
            logger.info("[telegram disabled] %s", text.replace("\n", " | "))
            return False
        await self.start()
        url = _API.format(token=self.token, method="sendMessage")
        payload = {"chat_id": target, "text": text}
        try:
            async with self._session.post(url, data=payload) as resp:
                body = await resp.text()
                if resp.status != 200:
                    self._log_send_error(resp.status, body)
                    return False
                return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram sendMessage error: %s", exc)
            return False

    def _log_send_error(self, status: int, body: str) -> None:
        logger.warning("Telegram API failed: %s %s", status, body)
        if "chat not found" in body.lower():
            logger.warning(
                "Подсказка: открой бота @Pattern_Detectorbot в Telegram, "
                "нажми Start (/start), затем перезапусти python main.py"
            )

    async def send_photo(self, png: bytes, caption: str) -> None:
        if not self.enabled:
            logger.info("[telegram disabled] PHOTO: %s", caption.replace("\n", " | "))
            return
        await self.start()
        url = _API.format(token=self.token, method="sendPhoto")
        form = aiohttp.FormData()
        form.add_field("chat_id", self.chat_id)
        form.add_field("caption", caption)
        form.add_field("photo", png, filename="signal.png", content_type="image/png")
        try:
            async with self._session.post(url, data=form) as resp:
                body = await resp.text()
                if resp.status != 200:
                    self._log_send_error(resp.status, body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram sendPhoto error: %s", exc)

    async def poll_commands(self) -> None:
        """Background loop: reply to /start and /status from the configured chat."""
        if not self.enabled:
            return
        await self.start()
        logger.info("Telegram command polling started")
        while not self._poll_stop.is_set():
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Telegram poll error: %s", exc)
            try:
                await asyncio.wait_for(self._poll_stop.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass

    async def _poll_once(self) -> None:
        url = _API.format(token=self.token, method="getUpdates")
        params = {
            "offset": self._update_offset,
            "timeout": 0,
            "allowed_updates": '["message"]',
        }
        async with self._session.get(url, params=params) as resp:
            data = await resp.json()
        if not data.get("ok"):
            return
        for update in data.get("result", []):
            self._update_offset = update["update_id"] + 1
            msg = update.get("message") or {}
            chat = msg.get("chat", {})
            chat_id = str(chat.get("id", ""))
            if chat_id != self.chat_id:
                continue
            text = (msg.get("text") or "").strip()
            if text.startswith("/start"):
                await self.send_text(WELCOME_TEXT, chat_id=chat_id)
            elif text.startswith("/status"):
                status = (
                    await self._status_provider()
                    if self._status_provider
                    else "Мониторинг активен."
                )
                await self.send_text(status, chat_id=chat_id)
