from __future__ import annotations

import httpx
import pytest

from mapy_mcp.config import Settings
from mapy_mcp.http.client import MapyClient
from mapy_mcp.http.credits import CreditLedger
from mapy_mcp.http.ratelimit import RateLimiter


@pytest.fixture
def settings() -> Settings:
    return Settings(api_key="test-key", base_url="https://api.mapy.com", timeout=5.0)


@pytest.fixture
def ledger() -> CreditLedger:
    return CreditLedger()


@pytest.fixture
async def client(settings: Settings, ledger: CreditLedger):
    http = httpx.AsyncClient(base_url=settings.base_url)
    c = MapyClient(settings, ledger=ledger, limiter=RateLimiter(), client=http)
    try:
        yield c
    finally:
        await http.aclose()
