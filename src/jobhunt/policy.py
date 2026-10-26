"""Reglas deterministas. El LLM extrae y puntúa; la decisión de descartar por condiciones
duras (ubicación, salario, años) se toma acá, con reglas que se pueden testear."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from jobhunt.models import JobAnalysis, Modality, Preferences, Seniority

_ATS_HOSTS = {
    "jobs.lever.co": "lever",
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.ashbyhq.com": "ashby",
    "apply.workable.com": "workable",
    "www.linkedin.com": "linkedin",
    "linkedin.com": "linkedin",
    "www.getonbrd.com": "getonbrd",
    "docs.google.com": "google_forms",
    "forms.gle": "google_forms",
}
_PERIOD_TO_MONTH = {"month": 1.0, "year": 1 / 12, "hour": 160.0}


def detect_ats(apply_url: str) -> str:
    host = urlparse(apply_url).netloc.lower()
    if not host:
        return "unknown"
    if host in _ATS_HOSTS:
        return _ATS_HOSTS[host]
    if host.endswith(".bamboohr.com"):
        return "bamboohr"
    if host.endswith(".recruitee.com"):
        return "recruitee"
    if "myworkdayjobs" in host:
        return "workday"
    return "other"


_ON_SITE_RE = re.compile(r"hybrid|h[ií]brido|onsite|on-site|presencial", re.IGNORECASE)
_REMOTE_RE = re.compile(r"remot", re.IGNORECASE)


def company_excluded(company: str, prefs: Preferences) -> bool:
    return any(re.search(p, company, re.IGNORECASE) for p in prefs.excluded_companies)


def listing_filter_reason(title: str, location: str, prefs: Preferences, company: str = "") -> str | None:
    """Motivo para descartar un aviso solo con lo que muestra el listado, o None si pasa.
    Es barato y conservador: ante la duda deja pasar y decide el análisis completo."""
    if company_excluded(company, prefs):
        return "empresa excluida"
    if any(re.search(p, title, re.IGNORECASE) for p in prefs.title_exclude):
        return "título excluido"
    if not any(re.search(p, title, re.IGNORECASE) for p in prefs.title_include):
        return "título fuera del objetivo"
    if _ON_SITE_RE.search(location) and not _REMOTE_RE.search(location):
        if not any(k.lower() in location.lower() for k in prefs.home_city_keywords):
            return "híbrido o presencial fuera de la ciudad"
    if any(re.search(p, location, re.IGNORECASE) for p in prefs.remote_region_block):
        home = any(k.lower() in location.lower() for k in prefs.home_city_keywords)
        if not home and not any(re.search(p, location, re.IGNORECASE) for p in prefs.remote_region_ok):
            return "restringido a otra región"
    return None


def too_old(posted_at: str | None, prefs: Preferences, today=None) -> bool:
    from datetime import UTC, datetime

    if not posted_at or prefs.max_posting_age_days is None:
        return False
    try:
        posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=UTC)
    now = today or datetime.now(UTC)
    return (now - posted).days > prefs.max_posting_age_days


def title_priority(title: str, prefs: Preferences) -> int:
    """2: prioritario y no despriorizado; 1: uno de los dos; 0: despriorizado y no prioritario."""
    boost = any(re.search(p, title, re.IGNORECASE) for p in prefs.priority_title)
    demote = any(re.search(p, title, re.IGNORECASE) for p in prefs.deprioritize_title)
    return int(boost) + int(not demote)


_USD_LIKE = {"USD", "USDT", "USDC"}


def monthly_usd_amount(amount: float, currency: str, period: str, prefs: Preferences) -> float | None:
    currency = currency.upper()
    rate = 1.0 if currency in _USD_LIKE else prefs.fx_to_usd.get(currency)
    if rate is None:
        return None
    return amount * _PERIOD_TO_MONTH[period] / rate


def monthly_usd(analysis: JobAnalysis, prefs: Preferences) -> float | None:
    salary = analysis.salary
    if not salary:
        return None
    amount = salary.max if salary.max is not None else salary.min
    if amount is None:
        return None
    return monthly_usd_amount(amount, salary.currency, salary.period, prefs)


@dataclass
class Decision:
    decision: str  # apply | maybe | skip
    reasons: list[str]


def decide(analysis: JobAnalysis, prefs: Preferences) -> Decision:
    hard: list[str] = []
    notes: list[str] = []

    if analysis.role_family in prefs.excluded_role_families:
        hard.append(f"familia de rol excluida: {analysis.role_family}")

    if analysis.modality in (Modality.HYBRID, Modality.ONSITE):
        place = analysis.work_location.lower()
        if not any(k.lower() in place for k in prefs.home_city_keywords):
            hard.append(f"{analysis.modality} fuera de la ciudad: {analysis.work_location or '?'}")
    elif analysis.modality == Modality.REMOTE:
        if not prefs.remote_ok:
            hard.append("remoto no aceptado")
        elif analysis.remote_accepts_argentina == "no":
            hard.append("remoto que no acepta Argentina")
        elif analysis.remote_accepts_argentina == "unclear":
            notes.append("no está claro si el remoto acepta Argentina")
    else:
        notes.append("modalidad no especificada")

    years = analysis.years_required_min
    senior = analysis.seniority in (Seniority.SENIOR, Seniority.STAFF_PLUS)
    if years is not None and years > prefs.max_years_required:
        hard.append(f"pide {years}+ años")
    elif senior and prefs.max_years_required_senior is not None:
        if years is None:
            hard.append("senior sin años pedidos (suele ser 4+)")
        elif years > prefs.max_years_required_senior:
            hard.append(f"senior que pide {years}+ años")

    if prefs.salary_floor_usd_month is not None and analysis.salary:
        usd = monthly_usd(analysis, prefs)
        if usd is None:
            notes.append(f"salario en {analysis.salary.currency} sin tipo de cambio configurado")
        elif usd < prefs.salary_floor_usd_month:
            hard.append(f"salario ~{usd:.0f} USD/mes, debajo del piso")

    if hard:
        return Decision("skip", hard + notes)
    if analysis.fit_score >= prefs.apply_threshold:
        return Decision("apply", notes)
    if analysis.fit_score >= prefs.maybe_threshold:
        return Decision("maybe", notes)
    return Decision("skip", [f"puntaje {analysis.fit_score} bajo el umbral"] + notes)
