"""Vercel Cron entrypoint: daily 1D pattern check (flags, triangle, engulfing)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

# pattern_detector root (api/cron/index.py -> up 3 levels)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("MPLCONFIGDIR", "/tmp")

from jobs.daily_check import run_daily_check  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api.cron")


def _authorized(headers) -> bool:
    secret = os.getenv("CRON_SECRET", "").strip()
    if not secret:
        return True
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    return auth == f"Bearer {secret}"


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not _authorized(self.headers):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        try:
            summary = asyncio.run(run_daily_check())
            body = json.dumps(summary, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # noqa: BLE001
            logger.exception("cron failed")
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self) -> None:
        self.do_GET()

    def log_message(self, fmt: str, *args) -> None:
        logger.info(fmt, *args)
