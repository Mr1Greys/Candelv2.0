"""Vercel API: health check and cron jobs (1h/4h flags, 1d engulfing)."""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler

from api.cron_handler import run_mode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

BUILD_VERSION = os.getenv("VERCEL_GIT_COMMIT_SHA", "local")[:7]


def _cron_mode(path: str) -> str | None:
    """Map request path to cron mode. All /api/* routes hit this handler on Vercel."""
    clean = path.split("?", 1)[0].rstrip("/").lower()
    parts = [p for p in clean.split("/") if p]
    if not parts:
        return None

    last = parts[-1]
    if last == "cron":
        return "1d"
    if last == "cron_1h":
        return "1h"
    if last == "cron_4h":
        return "4h"
    if last == "cron_tick":
        return "tick"
    if len(parts) >= 2 and parts[-2] == "cron" and last in ("1h", "4h"):
        return last
    return None


def _health_body() -> bytes:
    import config

    payload = {
        "status": "ok",
        "service": "candel-pattern-detector",
        "version": BUILD_VERSION,
        "flag_timeframes": config.FLAG_TIMEFRAMES,
        "engulfing_timeframe": config.ENGULFING_TIMEFRAME,
        "cron_routes": ["/api/cron_1h", "/api/cron_4h", "/api/cron", "/api/cron_tick"],
    }
    return json.dumps(payload).encode("utf-8")


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        mode = _cron_mode(self.path)
        if mode:
            run_mode(self, mode)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(_health_body())

    def do_POST(self) -> None:
        mode = _cron_mode(self.path)
        if mode:
            run_mode(self, mode)
            return
        self.send_response(405)
        self.end_headers()
        self.wfile.write(b"Method not allowed")

    def do_HEAD(self) -> None:
        mode = _cron_mode(self.path)
        if mode:
            from api.cron_handler import authorized

            self.send_response(401 if not authorized(self.headers) else 200)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        logger.info(fmt, *args)
