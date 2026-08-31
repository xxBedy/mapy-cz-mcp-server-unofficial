"""HTTP klient pro REST API Mapy.com.

Klíč se posílá výhradně v hlavičce X-Mapy-Api-Key. Query parametr by fungoval taky,
ale dokumentace si u jeho názvu protiřečí (commons uvádí `apiKey`, služby `apikey`,
a query parametry jsou case-sensitive) a hlavně by klíč skončil v logu i v historii.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from ..config import Settings, get_settings
from .credits import CreditLedger
from .errors import MapyError, MissingApiKey
from .ratelimit import RateLimiter

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3

# Lidský název služby do chybové hlášky u 403 — musí odpovídat tomu,
# co uživatel vidí v portálu při povolování služeb.
SERVICE_NAMES: dict[str, str] = {
    "geocode": "geokódování",
    "routing": "plánování tras",
    "elevation": "nadmořská výška",
    "static": "statické mapy",
    "timezone": "časové zóny",
    "tiles": "mapové dlaždice",
}


class MapyClient:
    """Tenký asynchronní klient nad httpx s hlídáním limitů a kreditů."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        ledger: CreditLedger | None = None,
        limiter: RateLimiter | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.ledger = ledger or CreditLedger(budget=self.settings.credit_budget)
        self.limiter = limiter or RateLimiter()
        self._client = client
        self._owns_client = client is None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.base_url,
                timeout=self.settings.timeout,
                follow_redirects=True,
                headers={"User-Agent": "mapy-cz-mcp-server-unofficial"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> MapyClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _headers(self) -> dict[str, str]:
        if not self.settings.api_key:
            raise MissingApiKey()
        return {"X-Mapy-Api-Key": self.settings.api_key}

    async def _request(
        self,
        path: str,
        params: dict[str, Any],
        *,
        group: str,
        operation: str,
        credits: float,
    ) -> httpx.Response:
        headers = self._headers()
        self.ledger.check(credits)
        await self.limiter.acquire(group)

        client = await self._http()
        clean = {k: v for k, v in params.items() if v is not None}

        last_error: MapyError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await client.get(path, params=clean, headers=headers)
            except httpx.TimeoutException as exc:
                last_error = MapyError(
                    f"Vypršel časový limit požadavku na {path} po {self.settings.timeout} s."
                )
                if attempt == MAX_ATTEMPTS:
                    raise last_error from exc
                await self._backoff(attempt)
                continue
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
                # Výpadky spojení bývají přechodné (proxy, DNS, reset), zkusí se znovu.
                if attempt == MAX_ATTEMPTS:
                    raise self._connection_error(exc) from exc
                await self._backoff(attempt)
                continue
            except httpx.HTTPError as exc:
                raise self._connection_error(exc) from exc

            if response.status_code < 400:
                # Kredity se účtují až za odpověď, kterou API skutečně vydalo.
                self.ledger.record(operation, credits)
                return response

            if response.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                await self._backoff(attempt)
                continue

            raise self._translate(response, group)

        raise last_error or MapyError(f"Požadavek na {path} se nepodařilo dokončit.")

    def _connection_error(self, exc: Exception) -> MapyError:
        # ConnectError bývá bez textu — samotné "selhalo: " uživateli nic neřekne.
        reason = str(exc).strip() or type(exc).__name__
        return MapyError(
            self.settings.redact(
                f"Spojení s API Mapy.com selhalo ({reason}). "
                "Zkontrolujte síť, proxy a dostupnost api.mapy.com."
            )
        )

    @staticmethod
    async def _backoff(attempt: int) -> None:
        delay = (2 ** (attempt - 1)) * 0.5
        await asyncio.sleep(delay + random.uniform(0, 0.25))

    def _translate(self, response: httpx.Response, group: str) -> MapyError:
        from .errors import translate

        try:
            payload: object = response.json()
        except ValueError:
            payload = None
        return translate(
            response.status_code,
            payload,
            service=SERVICE_NAMES.get(group, group),
            correlation_id=response.headers.get("X-Correlation-Id"),
        )

    async def get_json(
        self,
        path: str,
        params: dict[str, Any],
        *,
        group: str,
        operation: str,
        credits: float,
    ) -> Any:
        response = await self._request(
            path, params, group=group, operation=operation, credits=credits
        )
        try:
            return response.json()
        except ValueError as exc:
            raise MapyError(f"API vrátilo odpověď, která není JSON ({path}).") from exc

    async def get_bytes(
        self,
        path: str,
        params: dict[str, Any],
        *,
        group: str,
        operation: str,
        credits: float,
    ) -> tuple[bytes, str]:
        """Vrátí obsah a MIME typ — pro obrázkové endpointy."""
        response = await self._request(
            path, params, group=group, operation=operation, credits=credits
        )
        mime = response.headers.get("Content-Type", "image/png").split(";")[0].strip()
        return response.content, mime

    def build_url(self, path: str, params: dict[str, Any]) -> str:
        """Sestaví URL bez klíče — pro output='url'. Klíč si doplní volající."""
        clean = {k: v for k, v in params.items() if v is not None}
        return str(httpx.URL(self.settings.base_url).join(path).copy_merge_params(clean))
