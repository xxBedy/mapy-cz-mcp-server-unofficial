"""Pasti 3.4 a 3.5 — autentizace hlavičkou a rozlišení 401/403."""

from __future__ import annotations

import httpx
import pytest
import respx

from mapy_mcp.http.credits import COST_GEOCODE
from mapy_mcp.http.errors import MapyError, MissingApiKey
from mapy_mcp.tools.geocode import geocode


@respx.mock
async def test_key_goes_in_header_never_in_url(client):
    route = respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    await geocode(client, "Praha")

    request = route.calls[0].request
    assert request.headers["X-Mapy-Api-Key"] == "test-key"
    assert "test-key" not in str(request.url)
    assert "apikey" not in str(request.url).lower()


@respx.mock
async def test_403_explains_service_not_enabled(client):
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(
            403, json={"detail": [{"msg": "Forbidden"}]}, headers={"X-Correlation-Id": "cid-1"}
        )
    )
    with pytest.raises(MapyError) as exc:
        await geocode(client, "Praha")

    message = str(exc.value)
    assert "geokódování" in message
    assert "povolenou" in message
    assert "cid-1" in message


@respx.mock
async def test_401_tells_user_to_set_the_env_var(client):
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(401, json={"detail": [{"msg": "Unauthorized"}]})
    )
    with pytest.raises(MissingApiKey) as exc:
        await geocode(client, "Praha")
    assert "MAPY_API_KEY" in str(exc.value)


@respx.mock
async def test_422_names_the_bad_parameter(client):
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(
            422,
            json={
                "detail": [
                    {"loc": ["query", "limit"], "msg": "ensure this value is less than 16",
                     "type": "value_error"}
                ]
            },
        )
    )
    with pytest.raises(MapyError) as exc:
        await geocode(client, "Praha")
    assert "limit" in str(exc.value)


@respx.mock
async def test_failed_call_does_not_charge_credits(client):
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(403, json={"detail": [{"msg": "Forbidden"}]})
    )
    with pytest.raises(MapyError):
        await geocode(client, "Praha")
    assert client.ledger.spent == 0.0


@respx.mock
async def test_successful_call_charges_credits(client):
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    await geocode(client, "Praha")
    assert client.ledger.spent == COST_GEOCODE
