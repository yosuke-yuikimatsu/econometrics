from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class FetchResult:
    url: str
    status_code: int
    text: str
    content_type: str | None
    final_url: str


class RateLimiter:
    def __init__(self, rate_per_second: float) -> None:
        self.min_interval = 1.0 / max(rate_per_second, 0.1)
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_at = now + self.min_interval


class AsyncFetcher:
    def __init__(self) -> None:
        limits = httpx.Limits(max_connections=settings.http_max_connections, max_keepalive_connections=settings.http_max_keepalive_connections)
        timeout = httpx.Timeout(
            timeout=settings.http_timeout_seconds,
            connect=settings.http_connect_timeout_seconds,
            read=settings.http_read_timeout_seconds,
        )
        self.client = httpx.AsyncClient(
            headers={'User-Agent': settings.user_agent},
            follow_redirects=True,
            timeout=timeout,
            limits=limits,
            http2=True,
        )
        self.global_sem = asyncio.Semaphore(settings.http_max_concurrency)
        self.host_sem = asyncio.Semaphore(settings.http_per_host_concurrency)
        self.rate = RateLimiter(settings.http_rps_limit)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def fetch_one(self, url: str) -> FetchResult:
        async with self.global_sem, self.host_sem:
            await self.rate.acquire()
            response = await self.client.get(url)
            response.raise_for_status()
            return FetchResult(
                url=url,
                status_code=response.status_code,
                text=response.text,
                content_type=response.headers.get('content-type'),
                final_url=str(response.url),
            )

    async def fetch_many(self, urls: Iterable[str]) -> list[FetchResult]:
        tasks = [asyncio.create_task(self.fetch_one(url)) for url in urls]
        results: list[FetchResult] = []
        for task in asyncio.as_completed(tasks):
            results.append(await task)
        return results
