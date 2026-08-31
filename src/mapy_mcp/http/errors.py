"""Převod HTTP chyb API Mapy.com na akční hlášky.

Generické „Forbidden“ uživatele nikam nedovede. Nejčastější příčina 403 přitom není
neplatný klíč, ale služba nezapnutá pro daný klíč v portálu — a to je opravitelné.
"""

from __future__ import annotations

# Chybové kódy plánovače, viz popis /v1/routing/route v OpenAPI.
ROUTING_ERROR_HINTS: dict[int, str] = {
    7: (
        "Některý bod leží mimo dostupnou síť pro zvolený typ dopravy. "
        "Zkuste jiný routeType nebo bod blíž k cestě."
    ),
    9: (
        "Body nejsou zvoleným způsobem dopravy propojené — typicky jiný kontinent "
        "nebo oblast bez spojení."
    ),
}

# Sentinelové hodnoty v maticovém plánovači. Nejsou to délky, jsou to chyby.
MATRIX_ERRORS: dict[int, str] = {
    -1: "general_error",
    -2: "too_far_apart",
    -3: "too_far_from_network",
    -4: "service_timeout",
}

MATRIX_ERROR_LABELS: dict[str, str] = {
    "general_error": "obecná chyba plánovače",
    "too_far_apart": "body jsou od sebe dál než 500 km vzdušnou čarou",
    "too_far_from_network": "bod je příliš daleko od silniční sítě",
    "service_timeout": "plánovač nestihl trasu spočítat",
}


class MapyError(Exception):
    """Chyba volání API Mapy.com přeložená do srozumitelné hlášky."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        correlation_id: str | None = None,
        service: str | None = None,
    ) -> None:
        self.status = status
        self.correlation_id = correlation_id
        self.service = service
        parts = [message]
        if correlation_id:
            parts.append(f"(X-Correlation-Id: {correlation_id} — uveďte při reportu na Mapy.com)")
        super().__init__(" ".join(parts))


class MissingApiKey(MapyError):
    def __init__(self) -> None:
        super().__init__(
            "Chybí API klíč. Nastavte proměnnou prostředí MAPY_API_KEY — klíč získáte "
            "registrací na https://developer.mapy.com/account/."
        )


class CreditBudgetExceeded(MapyError):
    def __init__(self, spent: float, budget: int, needed: float) -> None:
        super().__init__(
            f"Rozpočet kreditů pro tuto session je vyčerpán: spotřebováno {spent:.1f} "
            f"z {budget}, tato operace by stála dalších {needed:.1f}. "
            "Zvyšte MAPY_CREDIT_BUDGET, nebo strop odstraňte."
        )


def _detail_messages(payload: object) -> list[str]:
    """Vytáhne msg z odpovědi tvaru {"detail": [{"msg": ...}]}."""
    if not isinstance(payload, dict):
        return []
    detail = payload.get("detail")
    if not isinstance(detail, list):
        return []
    out: list[str] = []
    for item in detail:
        if isinstance(item, dict) and isinstance(item.get("msg"), str):
            out.append(item["msg"])
    return out


def _routing_error_codes(payload: object) -> list[int]:
    if not isinstance(payload, dict):
        return []
    detail = payload.get("detail")
    if not isinstance(detail, list):
        return []
    return [
        i["errorCode"]
        for i in detail
        if isinstance(i, dict) and isinstance(i.get("errorCode"), int)
    ]


def _validation_message(payload: object) -> str | None:
    """Z 422 vytáhne, který parametr je špatně."""
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if not isinstance(detail, list) or not detail:
        return None
    problems: list[str] = []
    for item in detail:
        if not isinstance(item, dict):
            continue
        loc = item.get("loc")
        msg = item.get("msg", "neplatná hodnota")
        if isinstance(loc, list) and loc:
            name = ".".join(str(p) for p in loc if p != "query")
            problems.append(f"{name}: {msg}")
        else:
            problems.append(str(msg))
    return "; ".join(problems) if problems else None


def translate(
    status: int, payload: object, *, service: str, correlation_id: str | None
) -> MapyError:
    """Přeloží HTTP odpověď na MapyError s hláškou, se kterou se dá něco dělat."""
    msgs = _detail_messages(payload)

    if status == 401:
        return MissingApiKey()

    if status == 403:
        return MapyError(
            f"API klíč byl odmítnut pro službu '{service}'. Buď je klíč neplatný, "
            f"nebo — a to je častější — nemá tuto službu povolenou. Zkontrolujte projekt "
            f"na https://developer.mapy.com/account/ a ověřte, že je '{service}' zapnutá.",
            status=status,
            correlation_id=correlation_id,
            service=service,
        )

    if status == 404:
        for code in _routing_error_codes(payload):
            hint = ROUTING_ERROR_HINTS.get(code)
            if hint:
                return MapyError(
                    hint, status=status, correlation_id=correlation_id, service=service
                )
        detail = "; ".join(msgs) if msgs else "Data nenalezena."
        return MapyError(detail, status=status, correlation_id=correlation_id, service=service)

    if status in (400, 422):
        problem = _validation_message(payload)
        if problem:
            return MapyError(
                f"API odmítlo parametry — {problem}",
                status=status,
                correlation_id=correlation_id,
                service=service,
            )
        detail = "; ".join(msgs) if msgs else "Neplatné parametry požadavku."
        return MapyError(detail, status=status, correlation_id=correlation_id, service=service)

    if status == 429:
        return MapyError(
            "Překročen rate limit API Mapy.com. Server opakoval pokus s odstupem, ale "
            "limit stále platí — zpomalte tempo volání.",
            status=status,
            correlation_id=correlation_id,
            service=service,
        )

    if status >= 500:
        detail = "; ".join(msgs) if msgs else "Server Mapy.com hlásí chybu."
        return MapyError(
            f"{detail} (HTTP {status})",
            status=status,
            correlation_id=correlation_id,
            service=service,
        )

    detail = "; ".join(msgs) if msgs else f"Neočekávaná odpověď HTTP {status}."
    return MapyError(detail, status=status, correlation_id=correlation_id, service=service)
