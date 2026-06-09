# Pattern Detector

Realtime detector of chart patterns on Binance 4H candles that sends signals
(with an annotated chart image) to Telegram.

## What it detects

- **Bear Flag** (forming) — downward impulse + rising consolidation channel.
- **Bull Flag** (forming) — upward impulse + falling consolidation channel.
- **Descending Triangle** (forming) — horizontal support + lower highs.
- **Bullish / Bearish Engulfing** — candle patterns ported from a Pine Script
  strategy.
- **Combined signals** — engulfing confirming a flag breakout or a triangle
  support test.

Patterns are detected **while forming** (before completion), evaluated on each
newly closed 4H candle, using the current unclosed candle as extra context.

## Data source

Public Binance market data — no API key required:

- REST `klines` to bootstrap the candle buffer on startup.
- WebSocket `<symbol>@kline_4h` stream for live updates.

## Setup

```bash
cd pattern_detector
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then fill in your Telegram credentials
```

Edit `.env`:

```
TELEGRAM_BOT_TOKEN=123456:ABC-your-bot-token
TELEGRAM_CHAT_ID=123456789
```

- Token: create a bot with [@BotFather](https://t.me/BotFather).
- Chat id: message [@userinfobot](https://t.me/userinfobot) (for a private chat)
  or add the bot to a group and read the chat id.

## Run

```bash
python main.py
```

On startup the service:

1. Loads `.env`.
2. Sends a "started" message to Telegram (sanity check that the token works).
3. Bootstraps 60 closed candles per symbol via REST.
4. Connects the WebSocket and detects on every closed candle.

If `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are empty, the service still runs and
logs detections to `logs/detections.log` — it just skips sending to Telegram.

## Troubleshooting

If matplotlib prints "cache directory is not writable" / Fontconfig warnings,
point it at a writable dir before running:

```bash
export MPLCONFIGDIR="$PWD/.mplcache"
```

These warnings are harmless; charts still render.

## Configuration

All thresholds and the symbol list live in `config.py`
(`SYMBOLS`, `TIMEFRAME`, impulse/consolidation/triangle parameters, confidence
filter, cooldown, etc.).

## Project layout

```
pattern_detector/
├── main.py                  # asyncio workers per symbol
├── config.py                # symbols, timeframe, thresholds, .env loading
├── models.py                # Candle, PatternResult dataclasses
├── data/
│   ├── binance_rest.py      # REST bootstrap of history
│   └── binance_ws.py        # WS client + CandleBuffer + reconnect
├── patterns/
│   ├── base.py
│   ├── bear_flag.py
│   ├── bull_flag.py
│   ├── descending_triangle.py
│   └── candle_patterns.py
├── signals/
│   ├── telegram.py          # async sendMessage / sendPhoto
│   └── chart.py             # matplotlib chart -> PNG bytes
├── core/
│   └── state.py             # dedup / cooldown / invalidation
└── utils/
    ├── pivot.py
    └── regression.py
```

## Notes / scope

- In-memory buffer only (no database).
- No order execution — detection and signalling only.
- No web UI.
