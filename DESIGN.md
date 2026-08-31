# Návrh MCP serveru pro REST API Mapy.com

> Neoficiální MCP server. Není produktem Seznam.cz a.s.
>
> Podklad: 7 OpenAPI specifikací stažených z `https://api.mapy.com/v1/docs/{commons,geocode,routing,elevation,maptiles,static,timezone}/openapi.{json,yaml}`,
> doplněno o [funkce](https://developer.mapy.com/cs/rest-api/funkce/), [ceník](https://developer.mapy.com/cs/cena/)
> a [pravidla atribuce](https://developer.mapy.com/rest-api-mapy-cz/atribution/). Ověřeno proti živému API (chybové odpovědi).

---

## 1. Shrnutí

API Mapy.com má **13 endpointů v 6 doménách**. Návrh je nemapuje 1:1 — mapuje je na **9 nástrojů, 5 resources a 3 prompty**,
protože přímý překlad REST → MCP naráží na čtyři věci, které pro LLM klienta neplatí:

| REST předpoklad | Realita LLM klienta | Důsledek pro návrh |
|---|---|---|
| Klient zná souřadnice | Model má „Praha, Václavák" | Nástroje přijímají **název i souřadnice** (§5.1) |
| Klient chce plnou odpověď | Geometrie trasy = desítky tisíc tokenů | **Tvarování odpovědí**, geometrie default vypnutá (§7) |
| Klient skládá dlaždice | Model dlaždice nesloží | Maptiles **není nástroj**, ale resource (§4.3) |
| Volání je zdarma | 4 kredity/volání, matice 40 | **Účtování kreditů + rozpočtový strop** (§6.4) |

Nejvyšší přidaná hodnota nad tenkým wrapperem: **statická mapa jako `ImageContent`** (model mapu skutečně *vidí*)
a **výškový profil trasy** (`route` → převzorkování → `elevation` → statistika), což je kompozice, kterou API samo nenabízí.

---

## 2. Co API skutečně umí

Ověřeno ze specifikací, ne z marketingu. Base URL `https://api.mapy.com` (alias `https://api.mapy.cz`).

| # | Endpoint | Účel | Limit v požadavku | Rate limit |
|---|---|---|---|---|
| 1 | `GET /v1/geocode` | Dopředné geokódování | `limit` ≤ 15 | 100/s |
| 2 | `GET /v1/suggest` | Našeptávání (neúplné dotazy) | `limit` ≤ 15 | 100/s |
| 3 | `GET /v1/rgeocode` | Reverzní geokódování | — | 100/s ¹ |
| 4 | `GET /v1/routing/route` | Trasa A→B | ≤ 15 průjezdních bodů | 30/s |
| 5 | `GET /v1/routing/matrix-m` | Matice N×M | **≤ 100 buněk**, ≤ 500 km vzdušně | 30/s |
| 6 | `GET /v1/elevation` | Nadmořská výška | **≤ 256 pozic** | 30/s |
| 7 | `GET /v1/static/map` | Statická mapa (obrázek) | ≤ 1024×1024 px | 30/s |
| 8 | `GET /v1/static/pano` | Statická panorama (obrázek) | ≤ 1024×1024 px | 30/s |
| 9 | `GET /v1/timezone/coordinate` | Časové pásmo dle souřadnic | — | 300/s |
| 10 | `GET /v1/timezone/timezone` | Info o IANA pásmu | — | 300/s |
| 11 | `GET /v1/timezone/list-timezones` | Seznam IANA pásem | — | 300/s |
| 12 | `GET /v1/maptiles/{mapset}/{tileSize}/{z}/{x}/{y}` | Mapová dlaždice | z ≤ 20 | 500/s |
| 13 | `GET /v1/maptiles/{mapset}/tiles.json` | TileJSON popis sady | — | 100/s |

¹ Specifikace si u `rgeocode` v jedné větě protiřečí („200 requests per second… 100 requests per second"). Návrh počítá s konzervativními 100/s.

**Enumerace, které se opakují napříč API:**

- `lang`: `cs, de, el, en, es, fr, it, nl, pl, pt, ru, sk, tr, uk` (default `cs`)
- `routeType`: `car_fast, car_fast_traffic, car_short, foot_fast, foot_hiking, bike_road, bike_mountain`
- `mapset` (statická mapa): `basic, outdoor, aerial, aerial-names-overlay, winter`
- `mapset` (dlaždice): `basic, outdoor, winter, aerial, names-overlay` — **pozor, jiná sada než u statické mapy**
- typy entit: `regional{,.country,.region,.municipality,.municipality_part,.street,.address}, poi, coordinate`

---

## 3. Pasti zjištěné rešerší

Tohle je jádro návrhu — každá past má v §5–§7 konkrétní protiopatření.

### 3.1 Pořadí souřadnic je `lon,lat`

Celé API používá **longitude první**. LLM téměř vždy píše `lat,lon` (protože tak se to říká česky i anglicky). Bez obrany
skončí trasa „Praha → Brno" uprostřed Indického oceánu a odpověď bude vypadat validně.

**Protiopatření:** schémata nástrojů **nikdy nepřijímají pole `[x, y]`**, jen pojmenovaná pole `lat` / `lon`.
Převod do pořadí API je v jediné funkci `to_api_coord()`. Navíc heuristika: pokud bod padne mimo pevninu, ale po prohození
padne do ČR/SK, vrátí se ve výsledku `warnings: ["possible_lat_lon_swap"]` — **nikdy tichá autokorekce**.

### 3.2 Matice vrací chybové kódy jako čísla

`matrix-m` nevrací HTTP chybu pro nedosažitelnou buňku, vrací `{"length": -3, "duration": -3}`.
Kdo to nezná, sečte `-3` do součtu vzdáleností.

| Hodnota | Význam |
|---|---|
| `-1` | obecná chyba |
| `-2` | body příliš daleko od sebe (limit 500 km vzdušně) |
| `-3` | bod nenalezen — příliš daleko od silniční sítě |
| `-4` | interní timeout služby |

**Protiopatření:** mapování na `{ unreachable: true, reason: "too_far_from_network" }`, záporné hodnoty se nikdy nepropíší ven.

### 3.3 Elevation má sentinel `-100000.0`

Místo bez dat vrací `-100000.0`, ne `null`. V profilu trasy to znamená pokles o 100 km.

**Protiopatření:** filtrovat na `null` + `dataGaps: n` v souhrnu.

### 3.4 Dokumentace si protiřečí u názvu API klíče

`commons/openapi.yaml` uvádí query parametr `apiKey` a hlavičku `X-MAPY-API-KEY`.
Všech šest ostatních specifikací uvádí `apikey` (malá písmena) a `X-Mapy-Api-Key`.
Hlavičky jsou case-insensitive, **query parametry ne**.

**Protiopatření:** posílat **výhradně hlavičku** `X-Mapy-Api-Key`. Zároveň to řeší únik klíče do logů, historie a `X-Correlation-Id` reportů.

### 3.5 `401` a `403` znamenají různé věci

Ověřeno živě proti API:

```
bez klíče        → 401 {"detail":[{"msg":"Unauthorized"}]}
neplatný klíč    → 403 {"detail":[{"msg":"Forbidden"}]}
```

Podle `commons` má `403` **dvě různé příčiny**: `„Api key not valid"` a `„Service not allowed for api key"` —
tedy klíč je v pořádku, ale daná služba pro něj není v portálu zapnutá. To je nejčastější onboarding problém a generická
hláška „Forbidden" uživatele nikam nedovede.

**Protiopatření:** mapování na akční hlášky (§6.3).

### 3.6 Rate limit se nedá číst z odpovědi

API nevrací `X-RateLimit-*` ani `Retry-After`. Klient musí limity znát dopředu a hlídat si je sám (§6.2).

### 3.7 Geometrie trasy je token bomba

GeoJSON `LineString` pro Praha→Brno má tisíce bodů. Jedno volání může vyčerpat celé kontextové okno.

**Protiopatření:** `geometry: "none"` jako **default** (§7).

---

## 4. Povrch serveru

### 4.1 Nástroje (9)

| Nástroj | Endpoint(y) | Vrací |
|---|---|---|
| `mapy_geocode` | `/v1/geocode` + `/v1/suggest` (přes `mode`) | text/JSON |
| `mapy_reverse_geocode` | `/v1/rgeocode` | text/JSON |
| `mapy_route` | `/v1/routing/route` (+ geocode pro názvy) | text/JSON |
| `mapy_route_matrix` | `/v1/routing/matrix-m` (+ geocode) | text/JSON |
| `mapy_elevation` | `/v1/elevation` | text/JSON |
| `mapy_elevation_profile` | `route` → `elevation` **(kompozice)** | text/JSON |
| `mapy_static_map` | `/v1/static/map` | **obrázek** + text |
| `mapy_panorama` | `/v1/static/pano` | **obrázek** + text |
| `mapy_timezone` | `/v1/timezone/coordinate` + `/timezone` | text/JSON |

**Sloučení `geocode` + `suggest`:** mají identickou sadu parametrů a liší se jen tolerancí k neúplnému dotazu.
Dva nástroje by model nutily volit mezi téměř identickými popisy. Jeden nástroj s `mode: "search" | "suggest"` (default `search`).

**Proč není nástroj pro `list-timezones`:** vrací ~420 řetězců. Jako nástroj zabírá kontext při každém volání; jako resource se načte jen když je potřeba.

### 4.2 Kompozitní nástroj `mapy_elevation_profile`

Jediná věc v návrhu, kterou API samo nenabízí, a zároveň nejsilnější use-case (turistika, cyklo):

```
1. route(start, end, routeType: foot_hiking, geometry: polyline6)
2. dekódovat polyline → N bodů (typicky 2 000–20 000)
3. převzorkovat na ekvidistantních ≤ 256 bodů
4. elevation(těch 256 bodů)
5. spočítat: min, max, převýšení ↑, klesání ↓, sparkline profilu
```

**Poctivá výhrada, která patří do popisu nástroje:** převýšení počítané ze 256 vzorků na 80km trase
systematicky **podhodnocuje** skutečné převýšení (zahladí se lokální vlny). Proto parametr
`accuracy: "fast" | "detailed"`, kde `detailed` rozdělí trasu na segmenty po 256 bodech a udělá víc volání —
trasa s 1 000 body = 4 volání = **16 kreditů místo 4**. Cena je vidět dopředu v popisu nástroje i ve výsledku.

### 4.3 Resources (5)

| URI | Obsah | Proč resource a ne nástroj |
|---|---|---|
| `mapy://attribution` | Povinné znění, logo, odkazy | Statické, potřeba při každém zobrazení dat |
| `mapy://mapsets` | Sady map + kde platí která enumerace | Statické, řeší past §2 |
| `mapy://timezones` | ~420 IANA pásem | Velké, zřídka potřebné |
| `mapy://tilejson/{mapset}` | TileJSON (šablona) | Pro klienta, který renderuje mapu |
| `mapy://usage` | Kredity spotřebované v session | Živý stav, ne akce |

### 4.4 Prompty (3)

`naplanuj-vylet` (geocode → route → elevation_profile → static_map),
`porovnej-trasy` (matice variant dopravy),
`kde-to-je` (geocode → static_map → panorama).

---

## 5. Ergonomie nástrojů

### 5.1 Místo místo souřadnic

Klíčové rozhodnutí. Nástroje pracující s body přijímají sjednocený typ:

```python
class Coord(BaseModel):
    lat: float = Field(ge=-90, le=90, description="Zeměpisná šířka")
    lon: float = Field(ge=-180, le=180, description="Zeměpisná délka")

Place = Annotated[
    str | Coord,
    Field(description='Název místa ("Brno, náměstí Svobody") nebo souřadnice'),
]
```

`resolve_place()` řetězec geokóduje (+4 kredity, uvedeno ve výsledku), `Coord` propustí. Model tak zvládne
„naplánuj trasu z Prahy do Brna" jedním voláním místo tří.

Pydantic tu dělá dvě věci najednou: odvodí JSON schéma nástroje ze signatury (nemusí se psát ručně)
a zároveň je to runtime validace vstupu od modelu — což je přesně vrstva, kde se zachytí past §3.1.

### 5.2 Statická mapa: nulová matematika

API umí viewport **dopočítat z markerů**. Nástroj toho využívá: `zoom` je volitelný a bez `center` se
viewport nafitne na markery. Běžný případ „ukaž mapu s těmito body" nevyžaduje žádný výpočet zoomu ani bboxu.

Markery a tvary mají netriviální řetězcovou syntaxi (`color:red;size:large;label:AB;14.42,50.08`).
Nástroj bere strukturovaná data a řetězec sestaví sám:

```python
class Marker(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str | None = Field(None, max_length=2)
    color: str | None = None                      # název barvy nebo #RRGGBB(AA)
    size: Literal["small", "normal", "large"] | None = None

# v signatuře nástroje:
markers: Annotated[list[Marker], Field(max_length=50)] | None = None
```

Pozn.: markery s **různým** nastavením musí jít do samostatných opakovaných parametrů `markers`,
ne do jednoho seznamu — builder je proto seskupuje podle stylu.

### 5.3 Obrázky do kontextu

`mapy_static_map` a `mapy_panorama` vracejí `Image(data=..., format="jpeg")` z `mcp.server.mcpserver`,
což SDK převede na `ImageContent`. Model mapu vidí.
Rozpočet kontextu ale rozhoduje: **default 640×480 `jpg`** (≈ 60–120 kB base64), ne API maximum 1024×1024 `png` @2x.
Parametr `output: "image" | "file" | "url"` — `file` uloží na disk a vrátí cestu (pro velké výstupy),
`url` vrátí jen sestavené URL (nula kreditů, nula tokenů, ale klíč v URL — proto **ne default**).

### 5.4 Trasa

```python
@server.tool()
async def mapy_route(
    start: Place,
    end: Place,
    route_type: RouteType = "car_fast",
    via: Annotated[list[Place], Field(max_length=15)] | None = None,   # limit API
    avoid_toll: bool = False,
    avoid_highways: bool = False,
    departure: datetime | None = None,                # jen pro car_fast_traffic
    geometry: Literal["none", "polyline", "geojson"] = "none",
) -> RouteSummary: ...
```

Návratový typ je Pydantic model, takže SDK vedle textu vydá i strukturovaný výstup — tvarování z §7
se tím dělá deklarativně v modelu, ne ručním serializováním.

`departure` + `car_fast_traffic` je jediná cesta k dotazu „kdy mám vyjet" — v popisu nástroje to musí být explicitně,
jinak model sáhne po `car_fast` a dopravu ignoruje.

---

## 6. Průřezové vrstvy

### 6.1 Autentizace

`MAPY_API_KEY` z prostředí, posílá se **jen jako hlavička** `X-Mapy-Api-Key` (§3.4).
Klíč se redaguje ve všech logách i chybových hláškách. Chybí-li klíč, server nastartuje a nástroje vrátí
instruktážní chybu s odkazem na registraci — server se nesmí zhroutit při startu, jinak klient hlásí jen „MCP server failed".

### 6.2 Rate limiting

Token bucket per skupina endpointů (30/s statika+routing+elevation, 100/s geokódování, 300/s timezone, 500/s dlaždice).
API limity nehlásí (§3.6), takže se hlídají lokálně. Na `429`/`503` exponenciální backoff s jitterem, max 3 pokusy;
`4xx` kromě `429` se neopakují.

### 6.3 Chyby

| Stav | Hláška pro uživatele |
|---|---|
| `401` | „Chybí API klíč. Nastavte `MAPY_API_KEY` — klíč získáte na developer.mapy.com/account." |
| `403` | „Klíč je neplatný, **nebo služba `{service}` není pro tento klíč povolena** — zkontrolujte projekt v portálu." |
| `404` + `errorCode: 7` | „Bod leží mimo síť pro `{routeType}` — zkuste jiný typ dopravy nebo bližší bod." |
| `404` + `errorCode: 9` | „Body nejsou spojené zvoleným způsobem dopravy (např. jiný kontinent)." |
| `422` | Parsovat `detail[].loc` a ukázat, **který parametr** je špatně. |

Ke každé chybě se přikládá `X-Correlation-Id` — Mapy.com ho vyžadují při reportu problému.

### 6.4 Kredity

Každý nástroj vrací v metadatech odhad ceny; server drží kumulativní součet session a volitelný strop
`MAPY_CREDIT_BUDGET` (při překročení nástroje odmítnou volat a řeknou proč).

| Operace | Kredity |
|---|---|
| geocode / suggest / rgeocode | 4 |
| routing | 4 |
| static map / panorama | 4 |
| elevation | 4 |
| timezone | 1 |
| dlaždice | 1 / dlaždice |
| matice 10×10 | 40 |

Zdroj: [ceník Mapy.com](https://developer.mapy.com/cs/cena/). Free tier 250 000 kreditů/měsíc (základní tarif),
10 000 000 pro zvýhodněný. Cena matice na buňku je z ceníku **odvozená** (40 / 100 = 0,4) — odhad se označuje jako přibližný,
dokud ho nepotvrdí kalkulačka.

### 6.5 Atribuce

Není to kosmetika, je to **licenční povinnost** a wrappery ji rutinně vynechávají. Statická mapa i panorama si atribuci
vypalují do obrázku samy. U geokódování a plánování ale musí atribuci zobrazit aplikace: logo Mapy.com u dat
(min. 30 px, klikatelné na `https://mapy.com/`) a text „Seznam.cz a.s. a další" odkazující na `https://api.mapy.com/copyright`.

Proto každá **ne-obrázková** odpověď nese pole `attribution` a existuje resource `mapy://attribution` s plným zněním.

---

## 7. Ekonomika tokenů

Vrstva, která rozhoduje o použitelnosti víc než cokoli jiného. Syrové odpovědi API jsou pro kontext příliš velké.

| Nástroj | Syrově | Po tvarování | Jak |
|---|---|---|---|
| `route` (Praha→Brno) | ~180 kB GeoJSON | ~200 B | `geometry: "none"` default; jen délka, čas, úseky |
| `geocode` (limit 5) | ~8 kB | ~800 B | bez `bbox`, `regionalStructure` zploštěná na `"Praha, Hlavní město Praha, Česko"` |
| `elevation` (256 bodů) | ~14 kB | ~300 B | statistika + sparkline místo pole bodů (`raw: true` vrátí vše) |
| `matrix` (10×10) | ~4 kB | ~2 kB | zachovat, ale zaokrouhlit; `-3` → `unreachable` |

Pravidlo: **default je souhrn, detail na vyžádání.** Každý nástroj má `raw: boolean` pro plnou odpověď.
`polyline6` se preferuje před `geojson` všude, kde geometrie skutečně musí projít (≈ 10× úspornější).

---

## 8. Architektura

### 8.1 Volba jazyka

**Python ≥ 3.10, oficiální SDK `mcp` 2.x, `pydantic`, `httpx`.** Transport `stdio` (default) + volitelně
streamable HTTP. Distribuce přes `uvx mapy-cz-mcp-server-unofficial`.

Rozvaha (ověřeno proti registrům 30. 8. 2026): obě oficiální SDK jsou plnohodnotná, ale `mcp` 2.1.1 (PyPI,
25. 8. 2026) je na novějším majoru a vydává rychleji než `@modelcontextprotocol/sdk` 1.30.0 (npm, 27. 7. 2026).
Rozhodly dvě věci:

- **Pydantic odvodí schéma nástroje ze signatury.** Proti ručně psanému zodu je to méně kódu na stejnou věc
  a zároveň runtime validace vstupu od modelu — tedy přesně ta vrstva, kde se chytá past §3.1.
- **Distribuce je nerozhodně.** `uvx` je v konfigurech MCP klientů stejně standardní zápis jako `npx`,
  takže argument, který by jinak mluvil pro TypeScript, tu nehraje.

Poctivá poznámka k tomu, co *nerozhodlo*: nabízelo se sáhnout po `shapely`/`pyproj`/`numpy` na geometrii z §4.2.
Při bližším pohledu je to ale ~100 řádků kódu tak či tak a u nástroje instalovaného přes `uvx` váží tyhle
závislosti víc, než přinesou. **Geometrie bude čistý Python bez těžkých závislostí.**

> **Past SDK, ne API.** V `mcp` 2.x byla třída `FastMCP` přejmenována na `MCPServer`
> (`from mcp.server.mcpserver import MCPServer`). Starý import `from mcp.server.fastmcp import FastMCP`
> je v1 API a dnes padá s `ModuleNotFoundError`, které odkazuje na migrační guide. Většina tutoriálů
> ukazuje ještě starý tvar. Pozor i na jmennou kolizi: balík **`fastmcp`** na PyPI (3.4.7, PrefectHQ)
> je samostatný framework, ne oficiální SDK — tenhle projekt ho nepoužívá.

### 8.2 Rozvržení

```
src/mapy_mcp/
  __main__.py           # entry point, volba transportu, graceful start bez klíče
  server.py             # MCPServer(...), registrace @server.tool/resource/prompt
  config.py             # pydantic-settings, redakce klíče
  http/
    client.py           # httpx.AsyncClient: hlavička, timeout, retry, correlation id
    errors.py           # HTTP + errorCode → akční hlášky (§6.3)
    ratelimit.py        # token bucket per skupina (§6.2)
    credits.py          # účtování + strop (§6.4)
  tools/                # 9 nástrojů, každý = signatura + handler + návratový model
  resources/            # 5 resources
  prompts/              # 3 prompty
  lib/
    coords.py           # to_api_coord(), validace, detekce prohození (§3.1)
    place.py            # resolve_place(): název | souřadnice → souřadnice (§5.1)
    polyline.py         # dekódování polyline / polyline6
    resample.py         # geometrie → ≤ 256 ekvidistantních bodů (§4.2)
    markers.py          # strukturovaná data → řetězcová syntaxe (§5.2)
    shape.py            # návratové Pydantic modely (§7)
pyproject.toml          # [project.scripts] mapy-cz-mcp-server-unofficial
```

Klíčová vlastnost rozvržení: **pořadí souřadnic žije jen v `coords.py`**, tvarování odpovědí jen v `shape.py`.
Nejnebezpečnější třída chyb je tak omezená na jeden soubor s vlastními testy.

---

## 9. Testování a CI

- **Kontraktní testy** proti uloženým fixtures (`pytest` + `respx`) — bez spotřeby kreditů, běží na každý push.
- **Hlídač driftu API:** CI job stáhne všech 7 OpenAPI specifikací a porovná je s uloženým snapshotem.
  Změna v API = failnutý build s diffem. Specifikace jsou veřejně dostupné, takže to stojí jeden `curl` — nečekat, až se něco rozbije v produkci.
- **Smoke test** s reálným klíčem (`uv run smoke`, ~30 kreditů) — ruční / nightly, ne v PR.
- **Cílené testy pastí:** prohození lat/lon, `-100000.0` v elevation, `-3` v matici, `403` s nezapnutou službou.

---

## 10. Otevřené otázky

1. **Jazyk odpovědí** — držet `lang: cs` (default API) i pro anglicky vedenou konverzaci, nebo odvodit z dotazu? Návrh: `MAPY_DEFAULT_LANG`, default `cs`.
2. **Cena buňky matice** — ověřit odvozených 0,4 kreditu proti [kalkulačce](https://developer.mapy.com/cs/cena/cenova-kalkulacka/).
3. **`mapy://usage` vs. nástroj** — session-lokální počítadlo neodpovídá reálné spotřebě účtu (API zůstatek nevystavuje). Zvážit, zda to nepřiznat přímo v popisu resource, aby model nevydával odhad za fakt.
4. **Panorama `yaw: "point"`** — namířit pohled na zadaný bod je pro „ukaž mi ten dům" lepší default než `auto` (směr jízdy auta). Chce ověřit na reálných datech.

---

## 11. Milníky

| Fáze | Obsah | Stav |
|---|---|---|
| **M1 — kostra** | `client.py`, `errors.py`, `coords.py`, `mapy_geocode`, `mapy_reverse_geocode` | hotovo |
| **M2 — jádro** | `mapy_route`, `mapy_elevation`, `mapy_timezone`, `shape.py`, kredity | hotovo |
| **M3 — vizuál** | `mapy_static_map`, `mapy_panorama`, `markers.py`, atribuce | hotovo |
| **M4 — kompozice** | `mapy_route_matrix`, `mapy_elevation_profile`, `resample.py`, prompty | hotovo |
| **M5 — vydání** | hlídač driftu, README, publikace na PyPI | hotovo mimo samotnou publikaci ¹ |

¹ Publikace na PyPI vyžaduje jednorázové nastavení Trusted Publishing na straně PyPI a GitHubu,
což nejde udělat z repozitáře — postup je v README, sekci Vydání. Workflow `release.yml` je
připravené a spustí se tagem `v*`.

---

## 12. Co se ukázalo až při implementaci

Tři věci, které rešerše specifikací odhalit nemohla — vyplavaly z volání živého API.

### 12.1 Geokodér řadí POI nad obec

Na dotaz `Brno` vrací API jako první bod zájmu **Brněnská přehrada** a teprve druhé
je město. Trasa „Praha → Brno“ tak vedla k přehradě. Řeší to `pick_best()` v `place.py`:
povyšuje se přesná shoda názvu, ale **jen když je to územní celek**.

To zúžení je podstatné. První, širší verze pravidla povyšovala každou přesnou shodu
a rozbila dotaz `Sněžka`: přesnou shodou je totiž POI v Hradci Králové, zatímco hora
se jmenuje `Sněžka (1603 m)` a API ji správně řadí první. Obě situace teď kryje test.

### 12.2 Chyby v resources potřebují `ResourceError`

MCP SDK zabalí libovolnou výjimku z resource handleru do `UnexpectedResourceError`
a klientovi pošle jen generické „Error creating resource from template“. Pečlivě
napsaná hláška se tím ztratí. Resources proto vyhazují `ResourceError`,
respektive `ResourceNotFoundError`, které SDK propustí i s textem.

### 12.3 Výpadky spojení se vyplatí opakovat

Retry původně pokrýval jen HTTP stavy a timeouty. Přechodné `ConnectError`
(proxy, DNS, reset) přitom spolehlivě projdou na druhý pokus, takže patří
do stejné smyčky. `ConnectError` navíc bývá bez textu — hláška proto doplňuje
aspoň typ výjimky, jinak uživatel čte jen „spojení selhalo: “.

### 12.4 Otisk API musí rozbalit `$ref` dřív, než sáhne na jméno

Hlídač driftu z §9 nejdřív bral jméno parametru z nerozbaleného zápisu.
Parametry zadané přes `$ref` tak spadly pod společný klíč `"None"` a vzájemně
se přepsaly — u `maptiles`, kde se takhle sdílí `mapset` i `lang`, otisk oba
parametry ztratil a jejich změnu by nikdy nenahlásil. Hlídač, který mlčí,
je horší než žádný. Chybu odhalil test na rozbalování referencí, ne čtení kódu.
