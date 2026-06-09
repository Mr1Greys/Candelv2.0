# CandelV2.0

Pattern Detector for crypto: finds **Bullish / Bearish Engulfing** on Binance **1D** candles and sends annotated chart screenshots to Telegram.

## Repository layout

```
CandelV2.0/
  pattern_detector/   # Python service (local bot + Vercel Cron)
  README.md
```

## Local run (24/7 WebSocket bot)

```bash
cd pattern_detector
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
export MPLCONFIGDIR="$PWD/.mplcache"
python main.py
```

## Vercel Cron (production, daily check)

Vercel runs a serverless function **every day at 00:05 UTC** — after the daily candle closes — checks all patterns and sends Telegram photos.

### 1. Connect GitHub

Repository: https://github.com/Mr1Greys/Candelv2.0.git

### 2. Import project in Vercel

| Setting | Value |
|---------|-------|
| Root Directory | **`pattern_detector`** (обязательно — иначе `api/cron.py` не найдётся) |
| Framework Preset | Other |
| Build Command | *(empty)* |
| Output Directory | *(empty)* |
| Install Command | `pip install -r requirements.txt` *(или оставить пустым — задано в vercel.json)* |

### 3. Environment variables

**Required**

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your chat ID |

**Recommended**

| Variable | Default |
|----------|---------|
| `BINANCE_REST_URL` | `https://data-api.binance.vision/api/v3/klines` |
| `FLAG_TIMEFRAMES` | `1h,4h` (флаги и треугольник) |
| `COMBO_FLAG_TIMEFRAME` | `4h` (для комбо с 1D поглощением) |
| `ENGULFING_TIMEFRAME` | `1d` (поглощения) |
| `SYMBOLS` | `BTCUSDT,ETHUSDT,SOLUSDT` |
| `MPLCONFIGDIR` | `/tmp` |

**Auto (Vercel)**

| Variable | Description |
|----------|-------------|
| `CRON_SECRET` | Create manually: `openssl rand -hex 32` — add in Environment Variables |

**Dedup (recommended)**

Create **Storage → KV** in Vercel and link it to the project. Vercel injects:

| Variable | Description |
|----------|-------------|
| `KV_REST_API_URL` | Upstash REST URL |
| `KV_REST_API_TOKEN` | Upstash REST token |

Without KV, duplicate Telegram messages are possible if the cron endpoint is triggered twice for the same day.

**Optional thresholds**

| Variable | Default |
|----------|---------|
| `MIN_CONFIDENCE` | `0.5` |
| `ENGULFING_PREV_CANDLES_MIN` | `1` |
| `ENGULFING_PREV_CANDLES_MAX` | `3` |
| `MIN_ENGULFING_BODY_POINTS` | `300` |

### 4. Deploy / sync with GitHub

After each `git push` to `main`, Vercel must create a **new** deployment. **"Redeploy" on an old deployment republishes the same old code** — it does not pull from GitHub.

**Check production version:** open `https://candelv2-0.vercel.app/api`

- **Stale (bad):** `{"status":"ok","service":"candel-pattern-detector"}` only
- **Current (good):** includes `"version"`, `"flag_timeframes": ["1h","4h"]`, `"cron_routes"`

**If pushes are not deploying:**

1. Vercel → **Settings → Git** → disconnect and reconnect `Mr1Greys/Candelv2.0`
2. **Root Directory** must be `pattern_detector`
3. **Deployments → Create Deployment** → `main` → latest commit
4. **Gold:** use `PAXGUSDT` in `SYMBOLS` (Binance spot has no `XAUUSDT`)

### 5. Enable Cron Jobs

Cron is defined in [`pattern_detector/vercel.json`](pattern_detector/vercel.json):

- `/api/cron_1h` — `5 * * * *` (флаги и треугольник, каждый час)
- `/api/cron_4h` — `5 */4 * * *` (флаги и треугольник, каждые 4 часа)
- `/api/cron` — `5 0 * * *` (поглощения, ежедневно 00:05 UTC)

On Hobby the function timeout is 10s — chart rendering for 3 pairs may time out; Vercel Pro gives up to 60s (configure `functions` in `vercel.json` after the first successful deploy).

### 6. Manual test

```bash
curl -H "Authorization: Bearer $CRON_SECRET" \
  https://<your-app>.vercel.app/api/cron
```

Response is JSON with `signals_sent`, `skipped`, and `errors`.

### Vercel vs local bot

| Feature | Vercel Cron | Local `main.py` |
|---------|-------------|-----------------|
| Engulfing 1D | Yes (daily `/api/cron`) | Yes |
| Flags / Triangle | Yes (1H + 4H crons) | Yes (1H + 4H) |
| Combo signals | Yes (daily) | Yes |
| Chart + Telegram | Yes | Yes |
| `/start`, `/status` | No | Yes |
| WebSocket realtime | No | Yes |

## License

Private project.
