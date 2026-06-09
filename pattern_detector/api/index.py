"""Vercel API entrypoint: health check and /api/cron daily pattern scan."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("MPLCONFIGDIR", "/tmp")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")


def _cron_mode(path: str) -> str | None:
    clean = path.split("?", 1)[0].rstrip("/")
    if clean.endswith("/cron/4h"):
        return "4h"
    if clean.endswith("/cron") or clean == "/api/cron":
        return "1d"
    return None


def _authorized(headers) -> bool:
    secret = os.getenv("CRON_SECRET", "").strip()
    if not secret:
        return True
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    return auth == f"Bearer {secret}"


def _handle_cron(handler: BaseHTTPRequestHandler) -> None:
    if not _authorized(handler.headers):
        handler.send_response(401)
        handler.end_headers()
        handler.wfile.write(b"Unauthorized")
        return

    from jobs.daily_check import run_daily_check  # noqa: E402

    mode = _cron_mode(handler.path) or "1d"
    try:
        summary = asyncio.run(run_daily_check(mode=mode))
        body = json.dumps(summary, ensure_ascii=False).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.end_headers()
        handler.wfile.write(body)
    except Exception as exc:  # noqa: BLE001
        logger.exception("cron failed")
        body = json.dumps({"error": str(exc)}).encode("utf-8")
        handler.send_response(500)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(body)


def _handle_health(handler: BaseHTTPRequestHandler) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(b'{"status":"ok","service":"candel-pattern-detector"}')


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if _cron_mode(self.path):
            _handle_cron(self)
        else:
            _handle_health(self)

    def do_POST(self) -> None:
        if _cron_mode(self.path):
            _handle_cron(self)
        else:
            self.send_response(405)
            self.end_headers()
            self.wfile.write(b"Method not allowed")

    def log_message(self, fmt: str, *args) -> None:
        logger.info(fmt, *args)
