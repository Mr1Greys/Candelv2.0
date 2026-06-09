"""Configuration: symbols, timeframe, detection thresholds and secrets.

Secrets (Telegram) are read from environment variables, populated from a local
``.env`` file via python-dotenv. Copy ``.env.example`` to ``.env`` and fill it.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Always load .env from the project folder, even if main.py is run elsewhere.
load_dotenv(Path(__file__).resolve().parent / ".env")


def _parse_symbols() -> list[str]:
    raw = os.getenv("SYMBOLS", "").strip()
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


# --------------------------------------------------------------------------- #
# Market / stream
# --------------------------------------------------------------------------- #
SYMBOLS: list[str] = _parse_symbols()
# Flags / triangles: same FLAG_* logic on 1H and 4H; engulfing on 1D.
def _parse_flag_timeframes() -> list[str]:
    raw = os.getenv("FLAG_TIMEFRAMES", "").strip()
    if raw:
        return [t.strip() for t in raw.split(",") if t.strip()]
    legacy = os.getenv("FLAG_TIMEFRAME", "").strip()
    if legacy:
        return [legacy]
    return ["1h", "4h"]


FLAG_TIMEFRAMES: list[str] = _parse_flag_timeframes()
# 4H structure used for combo signals with 1D engulfing.
COMBO_FLAG_TIMEFRAME: str = os.getenv("COMBO_FLAG_TIMEFRAME", "4h").strip() or "4h"
FLAG_TIMEFRAME: str = COMBO_FLAG_TIMEFRAME  # legacy alias
ENGULFING_TIMEFRAME: str = os.getenv("ENGULFING_TIMEFRAME", "1d").strip() or "1d"
# Legacy alias (engulfing TF) — do not use for flag detection.
TIMEFRAME: str = ENGULFING_TIMEFRAME

BUFFER_SIZE: int = _int_env("BUFFER_SIZE", 60)

BINANCE_REST_URL: str = os.getenv(
    "BINANCE_REST_URL",
    "https://data-api.binance.vision/api/v3/klines",
).strip()
BINANCE_WS_BASE: str = os.getenv(
    "BINANCE_WS_BASE",
    "wss://stream.binance.com:9443/ws",
).strip()

# --------------------------------------------------------------------------- #
# Bear / Bull Flag — validated on live data 2026-06-01
#
# Reference detections (4H, sliding-window search):
#   BTCUSDT BEAR_FLAG  conf=0.88  impulse 5c -3.58%  consolidation 24c
#   SOLUSDT BEAR_FLAG  conf=0.89  impulse 3c -4.43%  consolidation 24c
#
# Bear flag: sharp drop (flagpole) + rising consolidation channel, price inside.
# Bull flag: mirror — sharp rise + falling consolidation channel, price inside.
# Both use the same thresholds below and shared logic in patterns/base.py.
# Signal format: chart PNG + caption (see signals/telegram.py).
# --------------------------------------------------------------------------- #
FLAG_IMPULSE_CANDLES_MIN = 3       # min candles in the flagpole
FLAG_IMPULSE_CANDLES_MAX = 6       # max candles in the flagpole (avg ~4)
FLAG_IMPULSE_MOVE_MIN_PCT = 1.5    # min |move| % (open first -> close last)
FLAG_IMPULSE_BODY_MIN_RATIO = 0.55 # body > 55% of range = "strong" candle
FLAG_CONSOLIDATION_MIN = 5         # min consolidation candles (signal from ~12-14+)
FLAG_CONSOLIDATION_MAX = 30        # max consolidation while still forming
FLAG_CHANNEL_WIDTH_MAX_RATIO = 0.4 # channel width < 40% of flagpole size
FLAG_CHANNEL_PARALLEL_TOLERANCE = 5.0  # max angle diff between channel lines (deg)
# Uniform impulse (all red/green): relax strong-body count when |move| >= MIN * this
FLAG_IMPULSE_UNIFORM_MOVE_MULT = 1.5

# Aliases used across the codebase (do not diverge from FLAG_* above)
IMPULSE_CANDLES_MIN = FLAG_IMPULSE_CANDLES_MIN
IMPULSE_CANDLES_MAX = FLAG_IMPULSE_CANDLES_MAX
IMPULSE_MOVE_MIN_PCT = FLAG_IMPULSE_MOVE_MIN_PCT
IMPULSE_BODY_MIN_RATIO = FLAG_IMPULSE_BODY_MIN_RATIO
CONSOLIDATION_MIN = FLAG_CONSOLIDATION_MIN
CONSOLIDATION_MAX = FLAG_CONSOLIDATION_MAX
CHANNEL_WIDTH_MAX_RATIO = FLAG_CHANNEL_WIDTH_MAX_RATIO
CHANNEL_PARALLEL_TOLERANCE = FLAG_CHANNEL_PARALLEL_TOLERANCE

# --------------------------------------------------------------------------- #
# Other pattern thresholds
# --------------------------------------------------------------------------- #
TRIANGLE_CANDLES_MIN = 15     # minimum candles spanned by the triangle
TRIANGLE_CANDLES_MAX = 30     # maximum (avg 20-25)
TRIANGLE_TOUCHES_MIN = 3      # minimum touches of the support level
DESCENDING_HIGHS_MIN = 3      # minimum descending highs (3-4 in screenshots)
TRIANGLE_SUPPORT_FLAT_DEG = 1.5   # support slope tolerance (degrees, ~horizontal)

SUPPORT_LEVEL_TOLERANCE = 0.003   # +/-0.3% for a horizontal level cluster

ATR_PERIOD = 14

# Pivot detection window (candles to the left/right of a local extreme).
PIVOT_LEFT = 2
PIVOT_RIGHT = 2

# --------------------------------------------------------------------------- #
# Engulfing (ported from Pine Script, tuned for 1D)
# --------------------------------------------------------------------------- #
MIN_ENGULFING_BODY_POINTS = _int_env("MIN_ENGULFING_BODY_POINTS", 300)
POINT_VALUE = _float_env("POINT_VALUE", 0.01)
ENGULFING_PREV_CANDLES_MIN = _int_env("ENGULFING_PREV_CANDLES_MIN", 1)
ENGULFING_PREV_CANDLES_MAX = _int_env("ENGULFING_PREV_CANDLES_MAX", 3)
DOJI_BODY_RATIO = _float_env("DOJI_BODY_RATIO", 0.1)

# --------------------------------------------------------------------------- #
# Signalling rules
# --------------------------------------------------------------------------- #
MIN_CONFIDENCE = _float_env("MIN_CONFIDENCE", 0.5)
SIGNAL_COOLDOWN_CANDLES = 10      # min candles between repeat signals of one pattern

# --------------------------------------------------------------------------- #
# Telegram (secrets)
# --------------------------------------------------------------------------- #
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# --------------------------------------------------------------------------- #
# Chart rendering
# --------------------------------------------------------------------------- #
CHART_CANDLES = 40                # how many recent candles to draw (flags / triangles)
CHART_ENGULFING_CANDLES = 12      # tighter zoom for engulfing screenshots

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
LOG_DIR = "logs"
LOG_FILE = "logs/detections.log"


def telegram_enabled() -> bool:
    """True if both Telegram credentials are configured."""
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
