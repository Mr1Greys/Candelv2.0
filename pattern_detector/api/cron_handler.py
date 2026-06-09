"""Shared Vercel cron HTTP handler."""
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

logger = logging.getLogger("api.cron")


def authorized(headers) -> bool:
    secret = os.getenv("CRON_SECRET", "").strip()
    if not secret:
        return True
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    return auth == f"Bearer {secret}"


def run_mode(handler: BaseHTTPRequestHandler, mode: str) -> None:
    if not authorized(handler.headers):
        handler.send_response(401)
        handler.end_headers()
        handler.wfile.write(b"Unauthorized")
        return

    from jobs.daily_check import run_daily_check  # noqa: E402

    try:
        summary = asyncio.run(run_daily_check(mode=mode))
        body = json.dumps(summary, ensure_ascii=False).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.end_headers()
        handler.wfile.write(body)
    except Exception as exc:  # noqa: BLE001
        logger.exception("cron failed mode=%s", mode)
        body = json.dumps({"error": str(exc)}).encode("utf-8")
        handler.send_response(500)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(body)


def make_handler(mode: str):
    class CronHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            run_mode(self, mode)

        def do_POST(self) -> None:
            self.do_GET()

        def log_message(self, fmt: str, *args) -> None:
            logger.info(fmt, *args)

    return CronHandler
