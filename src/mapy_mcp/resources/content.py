"""Statické texty resources.

Atribuce je licenční povinnost, ne kosmetika — proto má vlastní resource a proto ji
nese každá ne-obrázková odpověď. Seznam sad map řeší past, že statická mapa
a dlaždice mají jiné enumerace.
"""

from __future__ import annotations

ATTRIBUTION_DOC = """# Atribuce Mapy.com

Použití dat z REST API Mapy.com je podmíněné zobrazením atribuce. Není to doporučení,
je to licenční povinnost — viz https://developer.mapy.com/rest-api-mapy-cz/atribution/.

## Statické mapy a panoramata

Atribuci mají vypálenou přímo v obrázku. Nic dalšího řešit nemusíte.

## Geokódování, plánování, výška, časové zóny

Atribuci musí zobrazit vaše aplikace:

- **Logo Mapy.com** u dat získaných z API. Minimálně 30 px na výšku (zelená varianta 32 px),
  klikatelné na https://mapy.com/. Umístěné blízko dat nebo přímo ve vyhledávacím
  či plánovacím dialogu.
- Doprovodný text typu „Powered by Mapy.com“, „Search by Mapy.com“ nebo „Routing by Mapy.com“.

## Mapové dlaždice

Nad mapou musí být obojí:

- Logo Mapy.com na viditelném místě, stejně velké nebo větší než jakákoli jiná loga nad mapou.
- Textová doložka **„Seznam.cz a.s. a další“** odkazující na https://api.mapy.com/copyright.

## Krátké znění pro strojové použití

    Mapy.com © Seznam.cz a.s. a další — https://api.mapy.com/copyright
"""

MAPSETS_DOC = """# Sady map

Pozor, statická mapa a dlaždice mají **různé** sady. Záměna vede na HTTP 404.

## Statická mapa (`/v1/static/map`, nástroj `mapy_static_map`)

| Sada | Co to je |
|---|---|
| `basic` | Základní mapa |
| `outdoor` | Turistická mapa |
| `aerial` | Letecký snímek |
| `aerial-names-overlay` | Popisky pro překrytí leteckého snímku |
| `winter` | Zimní mapa |

## Dlaždice (`/v1/maptiles/...`, resource `mapy://tilejson/{mapset}`)

| Sada | Poznámka |
|---|---|
| `basic` | Podporuje `@2x` |
| `outdoor` | Podporuje `@2x` |
| `winter` | |
| `aerial` | |
| `names-overlay` | Jmenuje se jinak než u statické mapy (`aerial-names-overlay`) |

Velikost dlaždice je `256` nebo `256@2x`; `@2x` je povolené jen u `basic` a `outdoor`.
Zoom 0 až 20. Parametr `lang` ovlivní jen dlaždice se zoomem ≤ 6.
"""

LIMITS_DOC = """# Limity a ceny

## Limity požadavků

| Operace | Limit |
|---|---|
| Geokódování | `limit` nejvýš 15 výsledků |
| Plánování trasy | nejvýš 15 průjezdních bodů |
| Maticové plánování | nejvýš 100 buněk, body do 500 km vzdušnou čarou |
| Nadmořská výška | nejvýš 256 pozic na volání |
| Statická mapa i panorama | nejvýš 1024 × 1024 px |

## Rate limity (požadavků za sekundu)

| Skupina | Limit |
|---|---|
| Dlaždice | 500 |
| Časové zóny | 300 |
| Geokódování | 100 |
| Plánování, výška, statické obrázky | 30 |

API tyto limity nehlásí v hlavičkách, server si je proto hlídá sám.

## Kredity

| Operace | Kredity |
|---|---|
| Geokódování, našeptávání, reverzní geokódování | 4 |
| Plánování trasy | 4 |
| Statická mapa, panorama | 4 |
| Nadmořská výška | 4 |
| Časová zóna | 1 |
| Dlaždice | 1 za dlaždici |
| Matice 10 × 10 | 40 |

Zdarma je 250 000 kreditů měsíčně v základním tarifu, 10 000 000 ve zvýhodněném.
Cena buňky matice použitá tímto serverem (0,4) je z ceníku odvozená, ne v něm uvedená.
Aktuální ceník: https://developer.mapy.com/cs/cena/
"""
