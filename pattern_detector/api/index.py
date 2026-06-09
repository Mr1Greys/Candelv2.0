"""Vercel API: health check and daily 1D engulfing cron."""
from __future__ import annotations

import logging
import sys
from http.server import BaseHTTPRequestHandler

from api.cron_handler import run_mode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")


def _is_daily_cron(path: str) -> bool:
    clean = path.split("?", 1)[0].rstrip("/").lower()
    return clean.endswith("/cron") or clean == "/api/cron"


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if _is_daily_cron(self.path):
            run_mode(self, "1d")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"candel-pattern-detector"}')

    def do_POST(self) -> None:
        if _is_daily_cron(self.path):
            run_mode(self, "1d")
            return
        self.send_response(405)
        self.end_headers()
        self.wfile.write(b"Method not allowed")

    def log_message(self, fmt: str, *args) -> None:
        logger.info(fmt, *args)
