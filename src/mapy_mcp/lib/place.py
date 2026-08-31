"""Převod „místa“ na souřadnice.

Model má v ruce „Praha, Václavské náměstí“, ne dvojici čísel. Kdyby nástroje braly
jen souřadnice, musel by model volat geokódování zvlášť a pak výsledek správně
přepsat do dalšího volání — což je právě ta chvíle, kdy se prohodí lat a lon.
Nástroje proto berou obojí a převod dělá tahle vrstva.
"""

from __future__ import annotations

from typing import Annotated, TypeAlias

from pydantic import Field

from ..config import get_settings
from ..http.client import MapyClient
from ..http.credits import COST_GEOCODE
from ..http.errors import MapyError
from .coords import Coord, swap_warning

PlaceInput: TypeAlias = Annotated[
    str | Coord,
    Field(
        description=(
            "Místo jako text ('Brno, náměstí Svobody', 'Sněžka') nebo přesné souřadnice "
            "{'lat': …, 'lon': …}. Text se geokóduje, což stojí 4 kredity navíc."
        )
    ),
]



def pick_best(query: str, items: list[dict]) -> dict:
    """Vybere z výsledků geokódování ten, který volající nejspíš myslel.

    Geokodér řadí podle vlastní relevance, což u holého názvu obce nemusí sedět:
    na dotaz „Brno“ vrací jako první POI Brněnská přehrada a teprve pak město.
    Pro plánování trasy je to špatně.

    Povyšuje se proto jen přesná shoda názvu, která je **územní celek** (obec, kraj,
    země). To užší pravidlo je tu záměrně: na dotaz „Sněžka“ je přesnou shodou POI
    v Hradci Králové, zatímco hora se jmenuje „Sněžka (1603 m)“ a API ji správně řadí
    první. Kdyby se povyšovala každá přesná shoda, hora by prohrála s restaurací.
    """
    wanted = query.strip().casefold()
    regional_exact = [
        i
        for i in items
        if isinstance(i, dict)
        and str(i.get("name", "")).casefold() == wanted
        and str(i.get("type", "")).startswith("regional")
    ]
    return regional_exact[0] if regional_exact else items[0]


class ResolvedPlace:
    """Bod plus informace o tom, jak se k němu došlo."""

    def __init__(self, coord: Coord, label: str, credits: float, warning: str | None = None):
        self.coord = coord
        self.label = label
        self.credits = credits
        self.warning = warning


async def resolve_place(
    client: MapyClient, place: PlaceInput, *, lang: str | None = None
) -> ResolvedPlace:
    """Text geokóduje, souřadnice propustí. Vrací i varování na možné prohození lat/lon."""
    if isinstance(place, Coord):
        return ResolvedPlace(place, str(place), 0.0, swap_warning(place))

    if isinstance(place, dict):  # pragma: no cover - pojistka pro syrový vstup
        coord = Coord.model_validate(place)
        return ResolvedPlace(coord, str(coord), 0.0, swap_warning(coord))

    query = str(place).strip()
    if not query:
        raise MapyError("Prázdný název místa — zadejte text nebo souřadnice.")

    settings = get_settings()
    # limit=5 stojí stejně jako limit=1 (4 kredity) a dovolí vybrat lepší výsledek.
    payload = await client.get_json(
        "/v1/geocode",
        {"query": query, "limit": 5, "lang": lang or settings.default_lang},
        group="geocode",
        operation="geocode",
        credits=COST_GEOCODE,
    )
    items = payload.get("items") if isinstance(payload, dict) else None
    if not items:
        raise MapyError(
            f"Místo '{query}' se nepodařilo najít. Zkuste přesnější zadání "
            "(např. s obcí nebo krajem), nebo rovnou souřadnice."
        )

    first = pick_best(query, items)
    position = first.get("position") or {}
    coord = Coord(lat=float(position["lat"]), lon=float(position["lon"]))
    label = first.get("name") or query
    location = first.get("location")
    if location:
        label = f"{label}, {location}"
    return ResolvedPlace(coord, label, COST_GEOCODE)


async def resolve_all(
    client: MapyClient, places: list[PlaceInput], *, lang: str | None = None
) -> tuple[list[ResolvedPlace], float, list[str]]:
    """Vyřeší seznam míst a posbírá spotřebu i varování."""
    resolved: list[ResolvedPlace] = []
    credits = 0.0
    warnings: list[str] = []
    for place in places:
        item = await resolve_place(client, place, lang=lang)
        resolved.append(item)
        credits += item.credits
        if item.warning and item.warning not in warnings:
            warnings.append(item.warning)
    return resolved, credits, warnings
