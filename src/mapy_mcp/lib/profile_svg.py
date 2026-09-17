"""Vykreslení výškového profilu trasy jako SVG — bez grafické knihovny.

Server běží jen na mcp/pydantic/httpx, takže se stringová geometrie skládá ručně,
stejně jako markery a tvary pro statickou mapu. Vstup jsou dvě rovnoběžné řady:
vzdálenost po trase (km) a výška (m). Křivka se před kreslením vyhladí klouzavým
průměrem, protože vzorky z výškového API bývají zubaté.
"""

from __future__ import annotations

from math import floor, log10

# Barvy ladí s designem itineráře: tmavě zelená linie, světlá výplň, červený vrchol.
_AREA_FILL = "#2e7d32"
_LINE = "#1b5e20"
_PEAK = "#c62828"
_GRID_Y = "#e7e2d5"
_GRID_X = "#f0ece1"
_LABEL = "#8a8577"
_UNIT = "#b0aa9a"
_BG = "#ffffff"

_MAX_PLOT_POINTS = 300


def nice_step(x: float) -> float:
    """Hezky zaokrouhlený krok osy: 1/2/2.5/5×10^n, který pokryje rozsah ``x``."""
    if x <= 0:
        return 1.0
    magnitude = 10 ** floor(log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if m * magnitude >= x:
            return m * magnitude
    return 10 * magnitude


def moving_average(values: list[float], window: int) -> list[float]:
    """Klouzavý průměr s okénkem ``±window``. Zahladí zuby, tvar zachová."""
    if window < 1 or len(values) <= 2:
        return list(values)
    n = len(values)
    out: list[float] = []
    for i in range(n):
        lo = max(0, i - window)
        hi = min(n, i + window + 1)
        segment = values[lo:hi]
        out.append(sum(segment) / len(segment))
    return out


def _esc(text: str) -> str:
    """Ošetří text pro vložení do SVG (title je od uživatele)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_profile_svg(
    distances_km: list[float],
    elevations_m: list[float],
    *,
    width: int = 1000,
    height: int = 300,
    title: str | None = None,
    attribution: str = "Mapy.com © Seznam.cz a.s. a další",
) -> str:
    """Sestaví SVG výškového profilu. Očekává aspoň dva body a stejně dlouhé řady.

    ``distances_km`` je kumulativní vzdálenost po trase, ``elevations_m`` výška.
    """
    if len(distances_km) < 2 or len(distances_km) != len(elevations_m):
        raise ValueError("Profil potřebuje aspoň dva body a shodně dlouhé řady.")

    # Vyhlazení; okénko roste s počtem vzorků, ať je efekt podobný na krátkých i dlouhých.
    window = max(1, len(elevations_m) // 60)
    smooth = moving_average(elevations_m, window)

    left, right = 58, 18
    top = 40 if title else 22
    bottom = 48  # místo na popisky osy X a vypálenou atribuci
    plot_w = width - left - right
    plot_h = height - top - bottom

    dmax = distances_km[-1] or 1.0
    emin, emax = min(smooth), max(smooth)
    ystep = nice_step((emax - emin) / 4 or 1.0)
    y0 = floor(emin / ystep) * ystep
    y1 = -(-emax // ystep) * ystep  # ceil(emax/ystep)*ystep bez importu
    if y1 <= y0:
        y1 = y0 + ystep
    xstep = nice_step(dmax / 6)

    def x_of(km: float) -> float:
        return left + plot_w * (km / dmax)

    def y_of(m: float) -> float:
        return top + plot_h * (1 - (m - y0) / (y1 - y0))

    # Kreslí se vyhlazená řada, kvůli velikosti stringu navzorkovaná na ~300 bodů.
    n = len(smooth)
    stride = max(1, n // _MAX_PLOT_POINTS)
    idx = list(range(0, n, stride))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    line_pts = " ".join(f"{x_of(distances_km[i]):.1f},{y_of(smooth[i]):.1f}" for i in idx)
    area_pts = f"{x_of(0):.1f},{y_of(y0):.1f} {line_pts} {x_of(dmax):.1f},{y_of(y0):.1f}"

    # Vrchol: pozice podle skutečného maxima, tečka sedí na vyhlazené linii.
    imax = max(range(n), key=lambda i: elevations_m[i])
    peak_x, peak_y = x_of(distances_km[imax]), y_of(smooth[imax])
    peak_label = f"{int(round(elevations_m[imax]))} m"

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" font-family="sans-serif">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{_BG}"/>',
    ]

    # Vodorovné gridlines + popisky výšky
    yv = y0
    while yv <= y1 + 1e-6:
        yy = y_of(yv)
        parts.append(
            f'<line x1="{left}" y1="{yy:.1f}" x2="{width - right}" y2="{yy:.1f}" '
            f'stroke="{_GRID_Y}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 8}" y="{yy + 4:.1f}" text-anchor="end" font-size="15" '
            f'fill="{_LABEL}">{int(round(yv))}</text>'
        )
        yv += ystep

    # Svislé gridlines + popisky vzdálenosti
    xv = 0.0
    while xv <= dmax + 1e-6:
        xx = x_of(xv)
        parts.append(
            f'<line x1="{xx:.1f}" y1="{top}" x2="{xx:.1f}" y2="{height - bottom}" '
            f'stroke="{_GRID_X}" stroke-width="1"/>'
        )
        label = f"{xv:.0f}" if xstep >= 1 else f"{xv:.1f}"
        parts.append(
            f'<text x="{xx:.1f}" y="{height - bottom + 20:.1f}" text-anchor="middle" '
            f'font-size="15" fill="{_LABEL}">{label}</text>'
        )
        xv += xstep

    # Jednotky os
    parts.append(
        f'<text x="{left - 8}" y="{top - 8:.1f}" text-anchor="end" font-size="13" '
        f'fill="{_UNIT}">m n.m.</text>'
    )
    parts.append(
        f'<text x="{width - right}" y="{height - bottom + 20:.1f}" text-anchor="end" '
        f'font-size="13" fill="{_UNIT}">km</text>'
    )

    # Plocha + linie
    parts.append(f'<polygon points="{area_pts}" fill="{_AREA_FILL}" fill-opacity="0.16"/>')
    parts.append(
        f'<polyline points="{line_pts}" fill="none" stroke="{_LINE}" '
        f'stroke-width="2.6" stroke-linejoin="round"/>'
    )

    # Vrchol
    parts.append(f'<circle cx="{peak_x:.1f}" cy="{peak_y:.1f}" r="4.5" fill="{_PEAK}"/>')
    parts.append(
        f'<text x="{peak_x:.1f}" y="{peak_y - 10:.1f}" text-anchor="middle" font-size="15" '
        f'font-weight="700" fill="{_PEAK}">{peak_label}</text>'
    )

    # Titulek
    if title:
        parts.append(
            f'<text x="{left}" y="24" font-size="17" font-weight="700" fill="#333333">'
            f"{_esc(title)}</text>"
        )

    # Vypálená atribuce — data z API se smí zobrazit jen s ní.
    parts.append(
        f'<text x="{width - right}" y="{height - 6}" text-anchor="end" font-size="11" '
        f'fill="{_UNIT}">{_esc(attribution)}</text>'
    )

    parts.append("</svg>")
    return "\n".join(parts)
