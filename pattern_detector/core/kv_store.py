"""Optional dedup store backed by Vercel KV / Upstash Redis REST API."""
from __future__ import annotations

import logging
import os

import aiohttp

logger = logging.getLogger(__name__)


class KVStore:
    """Persist signal keys so cron re-runs do not duplicate Telegram messages."""

    def __init__(
        self,
        rest_url: str | None = None,
        rest_token: str | None = None,
    ) -> None:
        self._url = (rest_url or os.getenv("KV_REST_API_URL", "")).rstrip("/")
        self._token = rest_token or os.getenv("KV_REST_API_TOKEN", "")
        self._session: aiohttp.ClientSession | None = None
        self._local: set[str] = set()

    @property
    def enabled(self) -> bool:
        return bool(self._url and self._token)

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def exists(self, key: str) -> bool:
        if key in self._local:
            return True
        if not self.enabled:
            return False
        session = await self._session_get()
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with session.get(f"{self._url}/get/{key}", headers=headers) as resp:
                if resp.status != 200:
                    logger.warning("KV get failed: %s %s", resp.status, await resp.text())
                    return False
                data = await resp.json()
                if data.get("result") is not None:
                    self._local.add(key)
                    return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("KV get error for %s: %s", key, exc)
        return False

    async def set(self, key: str, value: str = "1") -> None:
        self._local.add(key)
        if not self.enabled:
            return
        session = await self._session_get()
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with session.post(
                f"{self._url}/set/{key}/{value}",
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    logger.warning("KV set failed: %s %s", resp.status, await resp.text())
        except Exception as exc:  # noqa: BLE001
            logger.warning("KV set error for %s: %s", key, exc)
