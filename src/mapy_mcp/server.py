"""Registrace nástrojů, resources a promptů na MCP server.

Tenhle soubor je jen lepidlo — logika žije v tools/ a lib/. Popisy nástrojů jsou
ale součástí návrhu, ne dokumentace: model se podle nich rozhoduje, který nástroj
zavolat a s jakými parametry, takže se v nich uvádí i cena v kreditech a pasti.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError
from pydantic import Field

from . import __version__
from .config import Lang, get_settings
from .http.client import MapyClient
from .http.credits import COST_TIMEZONE, CreditLedger
from .http.errors import MapyError
from .http.ratelimit import RateLimiter
from .lib.coords import Coord
from .lib.markers import Marker, Shape
from .lib.place import PlaceInput
from .lib.shape import (
    ElevationProfileResult,
    ElevationResult,
    GeocodeResult,
    MatrixResult,
    ReverseGeocodeResult,
    RouteResult,
    TimezoneResult,
)
from .resources.content import ATTRIBUTION_DOC, LIMITS_DOC, MAPSETS_DOC
from .tools import elevation as elevation_tools
from .tools import geocode as geocode_tools
from .tools import imagery as imagery_tools
from .tools import routing as routing_tools
from .tools import timezone as timezone_tools

INSTRUCTIONS = """Nástroje pro práci s mapami ČR i světa přes REST API Mapy.com.

Dvě věci, které stojí za pozornost:

1. Nástroje pracující s místem přijímají **text i souřadnice**. `start="Praha"` funguje
   stejně jako `start={"lat": 50.087, "lon": 14.421}`. Text se geokóduje (4 kredity navíc),
   takže když už souřadnice máte, pošlete je.
2. Každé volání stojí kredity. Odhad je v poli `cost` každé odpovědi a souhrn
   za session je v resource `mapy://usage`.

Data z API smí být zobrazena jen s atribucí — plné znění je v `mapy://attribution`.
Statické mapy a panoramata ji mají vypálenou v obrázku, ostatní odpovědi nesou pole
`attribution`, které patří k zobrazeným datům.
"""


def create_server() -> MCPServer:
    settings = get_settings()
    ledger = CreditLedger(budget=settings.credit_budget)
    limiter = RateLimiter()

    server = MCPServer(
        name="mapy-cz-unofficial",
        title="Mapy.com (neoficiální)",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/xxBedy/mapy-cz-mcp-server-unofficial",
    )

    def client() -> MapyClient:
        return MapyClient(settings, ledger=ledger, limiter=limiter)

    # ---------------------------------------------------------------- nástroje

    @server.tool(
        title="Najít místo",
        description=(
            "Najde místo, adresu, ulici, obec nebo bod zájmu podle textového dotazu "
            "a vrátí souřadnice. Použijte mode='suggest' pro neúplný nebo rozepsaný "
            "dotaz (našeptávání). Cena 4 kredity."
        ),
    )
    async def mapy_geocode(
        query: Annotated[str, Field(description="Co hledat, např. 'Brno, náměstí Svobody'.")],
        mode: Annotated[
            Literal["search", "suggest"],
            Field(description="'search' pro úplný dotaz, 'suggest' pro rozepsaný."),
        ] = "search",
        limit: Annotated[int, Field(ge=1, le=15, description="Kolik výsledků vrátit.")] = 5,
        types: Annotated[
            list[geocode_tools.EntityType] | None,
            Field(description="Omezí výsledky na vybrané typy entit."),
        ] = None,
        locality: Annotated[
            list[str] | None,
            Field(description="Omezí hledání na oblasti — názvy obcí nebo kódy zemí (cz, sk…)."),
        ] = None,
        near: Annotated[
            Coord | None, Field(description="Upřednostní výsledky poblíž tohoto bodu.")
        ] = None,
        near_precision_m: Annotated[
            float | None, Field(ge=0, description="Poloměr preference kolem 'near' v metrech.")
        ] = None,
        lang: Lang | None = None,
    ) -> GeocodeResult:
        async with client() as c:
            return await geocode_tools.geocode(
                c,
                query,
                mode=mode,
                limit=limit,
                types=types,
                locality=locality,
                near=near,
                near_precision_m=near_precision_m,
                lang=lang,
            )

    @server.tool(
        title="Zjistit adresu podle souřadnic",
        description=(
            "Reverzní geokódování: pro zadané souřadnice vrátí adresu a nadřazené "
            "územní celky (obec, okres, kraj, země). Cena 4 kredity."
        ),
    )
    async def mapy_reverse_geocode(
        lat: Annotated[float, Field(ge=-90, le=90, description="Zeměpisná šířka.")],
        lon: Annotated[float, Field(ge=-180, le=180, description="Zeměpisná délka.")],
        lang: Lang | None = None,
    ) -> ReverseGeocodeResult:
        async with client() as c:
            return await geocode_tools.reverse_geocode(c, lat, lon, lang=lang)

    @server.tool(
        title="Naplánovat trasu",
        description=(
            "Naplánuje trasu mezi dvěma místy, volitelně přes až 15 průjezdních bodů. "
            "Vrací délku, dobu jízdy a úseky. Geometrie se ve výchozím stavu nevrací, "
            "protože je velká — vyžádejte si ji přes geometry='polyline'. "
            "Pro dotaz typu 'kdy mám vyjet' použijte routeType='car_fast_traffic' "
            "spolu s parametrem departure, jinak se doprava neuvažuje. "
            "Cena 4 kredity plus 4 za každé místo zadané textem."
        ),
    )
    async def mapy_route(
        start: PlaceInput,
        end: PlaceInput,
        route_type: Annotated[
            routing_tools.RouteType,
            Field(description="Způsob dopravy. foot_hiking je turistický, bike_mountain terénní."),
        ] = "car_fast",
        via: Annotated[
            list[PlaceInput] | None, Field(max_length=15, description="Průjezdní body v pořadí.")
        ] = None,
        avoid_toll: Annotated[bool, Field(description="Vyhnout se zpoplatněným úsekům.")] = False,
        avoid_highways: Annotated[bool, Field(description="Vyhnout se dálnicím.")] = False,
        departure: Annotated[
            str | None,
            Field(description="Čas odjezdu v ISO 8601. Účinné jen s car_fast_traffic."),
        ] = None,
        geometry: Annotated[
            routing_tools.GeometryChoice,
            Field(description="'none' šetří kontext; 'polyline' je úsporný tvar geometrie."),
        ] = "none",
        lang: Lang | None = None,
    ) -> RouteResult:
        async with client() as c:
            return await routing_tools.route(
                c,
                start,
                end,
                route_type=route_type,
                via=via,
                avoid_toll=avoid_toll,
                avoid_highways=avoid_highways,
                departure=departure,
                geometry=geometry,
                lang=lang,
            )

    @server.tool(
        title="Matice vzdáleností",
        description=(
            "Spočítá vzdálenosti a časy mezi více výchozími a cílovými body najednou — "
            "vhodné na výběr nejbližší pobočky nebo pořadí zastávek. Bez parametru 'ends' "
            "počítá všechny kombinace výchozích bodů mezi sebou. "
            "Nejvýš 100 buněk (např. 10×10), body do 500 km vzdušnou čarou. "
            "Cena zhruba 0,4 kreditu za buňku."
        ),
    )
    async def mapy_route_matrix(
        starts: Annotated[list[PlaceInput], Field(min_length=1, description="Výchozí body.")],
        ends: Annotated[
            list[PlaceInput] | None,
            Field(description="Cílové body. Vynechte pro matici výchozích bodů proti sobě."),
        ] = None,
        route_type: routing_tools.RouteType = "car_fast",
        avoid_toll: bool = False,
        lang: Lang | None = None,
    ) -> MatrixResult:
        async with client() as c:
            return await routing_tools.route_matrix(
                c, starts, ends=ends, route_type=route_type, avoid_toll=avoid_toll, lang=lang
            )

    @server.tool(
        title="Nadmořská výška",
        description=(
            "Vrátí nadmořskou výšku pro až 256 bodů. Body bez dat mají elevation_m=null "
            "a počítají se do data_gaps. Pro profil celé trasy použijte "
            "mapy_elevation_profile, který si vzorkování řeší sám. Cena 4 kredity."
        ),
    )
    async def mapy_elevation(
        points: Annotated[
            list[Coord], Field(min_length=1, max_length=256, description="Body k změření.")
        ],
        lang: Lang | None = None,
    ) -> ElevationResult:
        async with client() as c:
            return await elevation_tools.elevation(c, points, lang=lang)

    @server.tool(
        title="Výškový profil trasy",
        description=(
            "Naplánuje trasu, navzorkuje ji a vrátí převýšení, klesání, nejvyšší "
            "a nejnižší bod a hrubý tvar profilu. Vhodné na turistiku a cyklistiku. "
            "accuracy='fast' stačí na většinu tras (1 měření, ~8 kreditů); "
            "'detailed' vzorkuje hustěji na delších trasách za cenu dalších volání. "
            "Převýšení ze vzorků skutečnou hodnotu spíš podhodnotí."
        ),
    )
    async def mapy_elevation_profile(
        start: PlaceInput,
        end: PlaceInput,
        route_type: Annotated[
            routing_tools.RouteType, Field(description="Výchozí je pěší turistická trasa.")
        ] = "foot_hiking",
        accuracy: Annotated[
            elevation_tools.Accuracy,
            Field(description="'fast' = 1 volání výšky, 'detailed' = až 4 (přesnější, dražší)."),
        ] = "fast",
        lang: Lang | None = None,
    ) -> ElevationProfileResult:
        async with client() as c:
            return await elevation_tools.elevation_profile(
                c, start, end, route_type=route_type, accuracy=accuracy, lang=lang
            )

    @server.tool(
        title="Obrázek mapy",
        description=(
            "Vrátí obrázek mapy, který si můžete prohlédnout. Nejjednodušší použití je "
            "zadat jen markery — výřez si API dopočítá samo, žádný zoom počítat nemusíte. "
            "Alternativně zadejte center + zoom, nebo bbox (dva rohy). "
            "output='file' uloží obrázek na disk místo vložení do konverzace, "
            "output='url' jen sestaví odkaz a nevolá API (zdarma). Cena 4 kredity."
        ),
    )
    async def mapy_static_map(
        center: Annotated[
            Coord | None, Field(description="Střed mapy. Vyžaduje i zoom.")
        ] = None,
        zoom: Annotated[int | None, Field(ge=1, le=19, description="Úroveň přiblížení.")] = None,
        bbox: Annotated[
            list[Coord] | None,
            Field(min_length=2, max_length=2, description="Dva protilehlé rohy výřezu."),
        ] = None,
        markers: Annotated[
            list[Marker] | None, Field(max_length=50, description="Značky na mapě.")
        ] = None,
        shapes: Annotated[
            list[Shape] | None, Field(max_length=20, description="Čáry a plochy na mapě.")
        ] = None,
        width: Annotated[int, Field(ge=10, le=1024)] = 640,
        height: Annotated[int, Field(ge=10, le=1024)] = 480,
        mapset: Annotated[
            imagery_tools.MapSet, Field(description="outdoor je turistická, aerial letecká.")
        ] = "basic",
        scale: Annotated[int, Field(ge=1, le=2, description="2 pro retina displeje.")] = 1,
        image_format: imagery_tools.ImageFormat = "jpg",
        padding: Annotated[int | None, Field(ge=0, le=1024)] = None,
        output: imagery_tools.Output = "image",
        lang: Lang | None = None,
    ) -> list[Image | str]:
        async with client() as c:
            return await imagery_tools.static_map(
                c,
                center=center,
                zoom=zoom,
                bbox=bbox,
                markers=markers,
                shapes=shapes,
                width=width,
                height=height,
                mapset=mapset,
                scale=scale,
                image_format=image_format,
                padding=padding,
                output=output,
                lang=lang,
            )

    @server.tool(
        title="Panorama z místa",
        description=(
            "Vrátí fotografii z ulice v okolí zadaného bodu — užitečné na otázky "
            "„jak to tam vypadá“. Výchozí yaw='point' natočí pohled na zadaný bod; "
            "'auto' se dívá ve směru jízdy mapovacího vozu. Cena 4 kredity."
        ),
    )
    async def mapy_panorama(
        place: Annotated[Coord, Field(description="Místo, na které se chcete podívat.")],
        width: Annotated[int, Field(ge=10, le=1024)] = 640,
        height: Annotated[int, Field(ge=10, le=1024)] = 360,
        radius_m: Annotated[
            float, Field(ge=0, le=100, description="Jak daleko hledat nejbližší snímek.")
        ] = 50.0,
        yaw: Annotated[
            str, Field(description="'point', 'auto', nebo azimut v radiánech (0 = sever).")
        ] = "point",
        pitch: Annotated[float | None, Field(ge=-1.5, le=1.5)] = None,
        fov: Annotated[float | None, Field(ge=0.16, le=1.57)] = None,
        output: imagery_tools.Output = "image",
        lang: Lang | None = None,
    ) -> list[Image | str]:
        async with client() as c:
            return await imagery_tools.panorama(
                c,
                place=place,
                width=width,
                height=height,
                radius_m=radius_m,
                yaw=yaw,
                pitch=pitch,
                fov=fov,
                output=output,
                lang=lang,
            )

    @server.tool(
        title="Časové pásmo",
        description=(
            "Zjistí časové pásmo, místní čas a posun vůči UTC — buď pro souřadnice "
            "(place), nebo pro název IANA pásma (timezone_name, např. 'Europe/Prague'). "
            "Cena 1 kredit."
        ),
    )
    async def mapy_timezone(
        place: Annotated[Coord | None, Field(description="Souřadnice místa.")] = None,
        timezone_name: Annotated[
            str | None, Field(description="Název IANA pásma, např. 'Europe/Prague'.")
        ] = None,
        lang: Lang | None = None,
    ) -> TimezoneResult:
        async with client() as c:
            return await timezone_tools.timezone(
                c, place=place, timezone_name=timezone_name, lang=lang
            )

    # --------------------------------------------------------------- resources

    @server.resource(
        "mapy://attribution",
        name="Atribuce Mapy.com",
        description="Povinné znění atribuce a pravidla zobrazení loga.",
        mime_type="text/markdown",
    )
    def attribution() -> str:
        return ATTRIBUTION_DOC

    @server.resource(
        "mapy://mapsets",
        name="Sady map",
        description="Sady map pro statickou mapu a pro dlaždice — mají různé enumerace.",
        mime_type="text/markdown",
    )
    def mapsets() -> str:
        return MAPSETS_DOC

    @server.resource(
        "mapy://limits",
        name="Limity a ceny",
        description="Limity požadavků, rate limity a ceník v kreditech.",
        mime_type="text/markdown",
    )
    def limits() -> str:
        return LIMITS_DOC

    @server.resource(
        "mapy://usage",
        name="Spotřeba kreditů",
        description="Kolik kreditů spotřebovala tato session. Lokální odhad, ne stav účtu.",
        mime_type="application/json",
    )
    def usage() -> str:
        return json.dumps(ledger.snapshot(), ensure_ascii=False, indent=2)

    @server.resource(
        "mapy://timezones",
        name="Seznam časových pásem",
        description="Všechna IANA časová pásma, která API zná.",
        mime_type="application/json",
    )
    async def timezones() -> str:
        try:
            async with client() as c:
                payload = await c.get_json(
                    "/v1/timezone/list-timezones",
                    {"lang": settings.default_lang},
                    group="timezone",
                    operation="list_timezones",
                    credits=COST_TIMEZONE,
                )
        except MapyError as exc:
            # Bez ResourceError by klient dostal jen generické "Error reading resource".
            raise ResourceError(str(exc)) from exc
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @server.resource(
        "mapy://tilejson/{mapset}",
        name="TileJSON sady map",
        description="Popis dlaždicové sady pro klienta, který renderuje vlastní mapu.",
        mime_type="application/json",
    )
    async def tilejson(mapset: str) -> str:
        allowed = {"basic", "outdoor", "winter", "aerial", "names-overlay"}
        if mapset not in allowed:
            raise ResourceNotFoundError(
                f"Neznámá dlaždicová sada '{mapset}'. Dostupné: {', '.join(sorted(allowed))}. "
                "Pozor, statická mapa má jinou sadu názvů — viz mapy://mapsets."
            )
        try:
            async with client() as c:
                payload = await c.get_json(
                    f"/v1/maptiles/{mapset}/tiles.json",
                    {"lang": settings.default_lang},
                    group="tiles",
                    operation="tilejson",
                    credits=0.0,
                )
        except MapyError as exc:
            raise ResourceError(str(exc)) from exc
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # ----------------------------------------------------------------- prompty

    @server.prompt(
        title="Naplánuj výlet",
        description="Trasa, výškový profil a mapa pro výlet mezi dvěma místy.",
    )
    def naplanuj_vylet(odkud: str, kam: str, zpusob: str = "pěšky") -> str:
        return (
            f"Naplánuj výlet z '{odkud}' do '{kam}' ({zpusob}).\n\n"
            "Postupuj takto:\n"
            "1. Zjisti trasu nástrojem mapy_route s odpovídajícím routeType.\n"
            "2. Pokud jde o pěší nebo cyklo trasu, přidej mapy_elevation_profile "
            "a okomentuj náročnost převýšení.\n"
            "3. Ukaž mapu přes mapy_static_map s markery na začátku a konci "
            "(mapset='outdoor' pro turistiku).\n"
            "4. Shrň délku, čas a náročnost. Uveď atribuci Mapy.com."
        )

    @server.prompt(
        title="Porovnej trasy",
        description="Srovná varianty dopravy mezi dvěma místy.",
    )
    def porovnej_trasy(odkud: str, kam: str) -> str:
        return (
            f"Porovnej způsoby dopravy z '{odkud}' do '{kam}'.\n\n"
            "Zavolej mapy_route pro car_fast, bike_road a foot_fast. "
            "U auta zkus i variantu s avoid_toll=true a porovnej rozdíl. "
            "Výsledky dej do tabulky s délkou a časem a doporuč, co se kdy vyplatí. "
            "Uveď celkovou spotřebu kreditů."
        )

    @server.prompt(
        title="Kde to je",
        description="Najde místo, ukáže mapu a fotku z ulice.",
    )
    def kde_to_je(misto: str) -> str:
        return (
            f"Ukaž mi, kde je '{misto}'.\n\n"
            "1. Najdi místo přes mapy_geocode.\n"
            "2. Ukaž mapu přes mapy_static_map s markerem na nalezeném bodě.\n"
            "3. Zkus i mapy_panorama pro pohled z ulice (yaw='point').\n"
            "4. Popiš, kde to je, a uveď atribuci."
        )

    return server
