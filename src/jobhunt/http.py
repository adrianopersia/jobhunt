"""Cliente HTTP lento a propósito: un request por vez, pausa fija y reintentos con backoff."""

from __future__ import annotations

import time

import httpx

USER_AGENT = "jobhunt/0.1 (personal job search; one request at a time)"


class PoliteClient:
    def __init__(self, delay_s: float = 1.5, retries: int = 3, timeout_s: float = 20.0):
        self.delay_s = delay_s
        self.retries = retries
        self._last = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_s,
            follow_redirects=True,
        )

    def get_text(self, url: str) -> str:
        return self._get(url).text

    def get_json(self, url: str):
        return self._get(url, headers={"Accept": "application/json"}).json()

    def _get(self, url: str, headers: dict | None = None) -> httpx.Response:
        for attempt in range(self.retries + 1):
            wait = self.delay_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                response = self._client.get(url, headers=headers)
            except httpx.TransportError:  # conexión cortada o timeout: se reintenta igual que un 5xx
                if attempt < self.retries:
                    time.sleep(self.delay_s * 2 ** (attempt + 1))
                    continue
                raise
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.retries:
                    time.sleep(self.delay_s * 2 ** (attempt + 1))
                    continue
            response.raise_for_status()
            return response
        raise RuntimeError("inalcanzable")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
