# Mapy.com MCP Server (neoficiální)

MCP server nad [REST API Mapy.com](https://developer.mapy.com/cs/rest-api/) — geokódování, plánování tras,
maticové plánování, nadmořská výška, výškový profil trasy, statické mapy, panoramata a časové zóny.

> **Neoficiální projekt.** Není produktem ani službou Seznam.cz a.s. Mapová data © Seznam.cz a.s. a další.

Návrh a rozbor API včetně zjištěných pastí je v [DESIGN.md](DESIGN.md).

## Instalace

Potřebujete API klíč z [developer.mapy.com](https://developer.mapy.com/account/). V portálu musí být pro klíč
povolené služby, které chcete používat — jinak API vrací `403` i s platným klíčem.

### Claude Code

```bash
claude mcp add mapy --env MAPY_API_KEY=váš_klíč -- uvx mapy-cz-mcp-server-unofficial
```

### Claude Desktop

```json
{
  "mcpServers": {
    "mapy": {
      "command": "uvx",
      "args": ["mapy-cz-mcp-server-unofficial"],
      "env": { "MAPY_API_KEY": "váš_klíč" }
    }
  }
}
```

## Nástroje

| Nástroj | Co dělá | Kredity |
|---|---|---|
| `mapy_geocode` | Najde místo podle názvu nebo adresy (`mode="suggest"` pro našeptávání) | 4 |
| `mapy_reverse_geocode` | Zjistí adresu a regionální strukturu pro souřadnice | 4 |
| `mapy_route` | Naplánuje trasu mezi místy, volitelně přes průjezdní body | 4 + geokódování |
| `mapy_route_matrix` | Matice vzdáleností a časů mezi více body (max 100 buněk) | ~0,4 / buňku |
| `mapy_elevation` | Nadmořská výška pro až 256 bodů | 4 |
| `mapy_elevation_profile` | Výškový profil trasy: převýšení, klesání, sparkline | 8+ |
| `mapy_static_map` | Obrázek mapy s markery a tvary — model ho vidí | 4 |
| `mapy_panorama` | Panoramatický snímek z místa | 4 |
| `mapy_timezone` | Časové pásmo, místní čas a posun | 1 |

Všechny nástroje pracující se souřadnicemi přijímají **název místa i souřadnice**:
`start="Praha"` funguje stejně jako `start={"lat": 50.087, "lon": 14.421}`.

## Resources

| URI | Obsah |
|---|---|
| `mapy://attribution` | Povinné znění atribuce a pravidla zobrazení loga |
| `mapy://mapsets` | Sady map pro statickou mapu a pro dlaždice |
| `mapy://timezones` | Seznam IANA časových pásem |
| `mapy://tilejson/{mapset}` | TileJSON pro klienta renderujícího vlastní mapu |
| `mapy://usage` | Kredity spotřebované v této session |

## Prompty

`naplanuj-vylet`, `porovnej-trasy`, `kde-to-je`.

## Konfigurace

| Proměnná | Default | Význam |
|---|---|---|
| `MAPY_API_KEY` | — | API klíč (povinný pro volání, ne pro start serveru) |
| `MAPY_DEFAULT_LANG` | `cs` | Jazyk odpovědí |
| `MAPY_CREDIT_BUDGET` | — | Strop kreditů na session; po překročení nástroje odmítnou volat |
| `MAPY_BASE_URL` | `https://api.mapy.com` | Základní URL API |
| `MAPY_TIMEOUT` | `20.0` | Timeout požadavku v sekundách |
| `MAPY_IMAGE_DIR` | dočasný adresář | Kam ukládat obrázky při `output="file"` |

Klíč se posílá **výhradně v hlavičce** `X-Mapy-Api-Key`, nikdy v URL — nedostane se tak do logů ani historie.

## Atribuce

Použití dat z API je podmíněné [zobrazením atribuce](https://developer.mapy.com/rest-api-mapy-cz/atribution/).
Statické mapy a panoramata mají atribuci vypálenou v obrázku. U geokódování a plánování ji musí zobrazit
vaše aplikace — každá ne-obrázková odpověď proto nese pole `attribution` a plné znění je v resource
`mapy://attribution`.

## Vývoj

```bash
uv sync --extra dev
uv run pytest                    # kontraktní testy, nespotřebují kredity
uv run ruff check src tests
uv run python -m mapy_mcp        # spuštění na stdio
```

Testy běží proti uloženým fixtures přes `respx`, takže nepotřebují API klíč ani nespotřebovávají kredity.

## Licence

MIT — viz [LICENSE](LICENSE). Licence se vztahuje na kód tohoto serveru, ne na mapová data,
která podléhají [podmínkám Mapy.com](https://developer.mapy.com/terms-and-conditions/).
