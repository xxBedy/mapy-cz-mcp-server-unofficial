"""Časové zóny podle souřadnic nebo podle názvu IANA pásma."""

from __future__ import annotations

from ..config import Lang, get_settings
from ..http.client import MapyClient
from ..http.credits import COST_TIMEZONE
from ..http.errors import MapyError
from ..lib.coords import Coord, swap_warning
from ..lib.shape import Cost, TimezoneResult


async def timezone(
    client: MapyClient,
    *,
    place: Coord | None = None,
    timezone_name: str | None = None,
    lang: Lang | None = None,
) -> TimezoneResult:
    if place is None and not timezone_name:
        raise MapyError("Zadejte buď souřadnice (place), nebo název pásma (timezone_name).")

    settings = get_settings()
    language = lang or settings.default_lang
    warnings: list[str] = []

    if timezone_name:
        path = "/v1/timezone/timezone"
        params: dict[str, object] = {"timezone": timezone_name, "lang": language}
    else:
        assert place is not None
        path = "/v1/timezone/coordinate"
        params = {"lon": place.lon, "lat": place.lat, "lang": language}
        w = swap_warning(place)
        if w:
            warnings.append(w)

    payload = await client.get_json(
        path, params, group="timezone", operation="timezone", credits=COST_TIMEZONE
    )
    info = payload.get("timezone") if isinstance(payload, dict) else None
    if not isinstance(info, dict):
        raise MapyError("API vrátilo odpověď bez údajů o časovém pásmu.")

    return TimezoneResult(
        timezone=info.get("timezoneName", ""),
        local_time=info.get("currentLocalTime", ""),
        utc_time=info.get("currentUtcTime", ""),
        utc_offset_s=int(info.get("currentUtcOffsetSeconds") or 0),
        abbreviation=info.get("currentTimeAbbreviation", ""),
        standard_abbreviation=info.get("standardTimeAbbreviation"),
        has_dst=bool(info.get("hasDst")),
        dst_active=bool(info.get("isDstActive")),
        warnings=warnings,
        cost=Cost(credits=COST_TIMEZONE, session_total=round(client.ledger.spent, 1)),
    )
