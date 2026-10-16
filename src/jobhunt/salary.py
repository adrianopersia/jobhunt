"""Recomendación salarial determinista: ni tan ambiciosa ni tan baja.

Parte de una banda: la que publica el aviso, si la hay; si no, la referencia de mercado de las
preferencias según quién paga (empresa local o del exterior). Dentro de la banda se ubica entre
el 35% y el 65% según el puntaje de encaje. Nunca queda por debajo del piso del candidato.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import quantiles

from jobhunt.models import JobAnalysis, Preferences, SalaryBand
from jobhunt.policy import monthly_usd_amount


@dataclass
class Suggestion:
    ask: int
    low: int
    high: int
    band: tuple[int, int]
    source: str
    rationale: str


def _round(value: float, step: int = 100) -> int:
    return int(value / step + 0.5) * step


def position_for(fit_score: int) -> float:
    """Encaje 50 → 35% de la banda; 90 o más → 65%."""
    return 0.35 + 0.30 * min(max((fit_score - 50) / 40, 0.0), 1.0)


def market_band(market: str, prefs: Preferences) -> tuple[SalaryBand, str]:
    ref = prefs.salary_reference
    if market == "local" and ref.local:
        return ref.local, "referencia de mercado para empresa local"
    if market == "foreign" and ref.foreign:
        return ref.foreign, "referencia de mercado para empresa del exterior"
    if ref.local and ref.foreign:
        # Sin saber quién paga: el tramo entre el techo local y el piso del exterior.
        band = SalaryBand(min=ref.local.max, max=ref.foreign.min,
                          source=f"{ref.local.source} / {ref.foreign.source}")
        return band, "entre el techo local y el piso del exterior (no está claro quién paga)"
    raise ValueError("Falta salary_reference en las preferencias.")


MIN_DATA_POINTS = 8


def data_band(points: list[float]) -> SalaryBand | None:
    """Percentiles 25–75 de avisos comparables con salario publicado, si hay suficientes."""
    if len(points) < MIN_DATA_POINTS:
        return None
    q1, _, q3 = quantiles(points, n=4)
    return SalaryBand(min=q1, max=q3, source=f"avisos comparables con salario publicado (n={len(points)})")


def suggest(analysis: JobAnalysis, prefs: Preferences, market: str | None = None,
            observed: SalaryBand | None = None) -> Suggestion:
    market = market or analysis.employer_market
    posted = analysis.salary
    lo = hi = None
    if posted and posted.min is not None and posted.max is not None:
        lo = monthly_usd_amount(posted.min, posted.currency, posted.period, prefs)
        hi = monthly_usd_amount(posted.max, posted.currency, posted.period, prefs)
    if lo is not None and hi is not None and hi > lo:
        source = "banda publicada en el aviso"
    elif observed is not None:
        lo, hi, source = observed.min, observed.max, observed.source
    else:
        band, source = market_band(market, prefs)
        lo, hi = band.min, band.max
        source = f"{source} ({band.source})"

    pos = position_for(analysis.fit_score)
    if posted and posted.location_adjusted and source == "banda publicada en el aviso":
        # La banda es para el país de la empresa: desde Argentina, anclar cerca del piso.
        pos = 0.10
        source += ", ajustable por ubicación"
    floor = prefs.salary_floor_usd_month or 0
    ask = max(_round(lo + (hi - lo) * pos), _round(floor))
    low = max(_round(lo + (hi - lo) * max(pos - 0.15, 0.0)), _round(floor))
    high = max(_round(lo + (hi - lo) * (pos + 0.15)), ask)
    rationale = (
        f"Banda USD {lo:,.0f}–{hi:,.0f}/mes ({source}). Con encaje {analysis.fit_score}, "
        f"la propuesta queda al {pos:.0%} de la banda: sin pedir el techo cuando hay huecos, "
        f"y sin regalar el piso cuando el perfil cubre lo que piden."
    )
    if pos == 0.10:
        rationale += " Como la banda se ajusta por ubicación, se ancla cerca del piso."
    return Suggestion(ask, low, high, (round(lo), round(hi)), source, rationale)
