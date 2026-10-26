import pytest

from jobhunt.models import JobAnalysis, Preferences
from jobhunt.policy import company_excluded, decide, detect_ats, listing_filter_reason, monthly_usd, too_old


@pytest.fixture
def prefs():
    return Preferences(
        home_city_keywords=["rosario"],
        salary_floor_usd_month=1500,
        fx_to_usd={"ARS": 1000},
        max_years_required=5,
        excluded_role_families=["ml_research"],
        title_include=[r"\b(ai|llm)\b", "full[- ]?stack", "member of technical staff"],
        title_exclude=[r"(?<!technical )\bstaff\b", "manager"],
        excluded_companies=[r"^Acme Outsourcing\b"],
    )


def analysis(**overrides):
    base = dict(
        role_family="applied_ai", seniority="semi_senior", years_required_min=3,
        modality="remote", work_location="", remote_accepts_argentina="yes",
        salary=None, posting_language="en", english_required="yes",
        requirements=[], stack=["TypeScript"], blockers=[], fit_score=80,
        rationale="Encaja.",
    )
    base.update(overrides)
    return JobAnalysis.model_validate(base)


@pytest.mark.parametrize("title,location,expected", [
    ("AI Engineer", "Argentina · remote", None),
    ("Fullstack Developer", "Rosario · Híbrido", None),
    ("Fullstack Developer", "Córdoba · hybrid", "híbrido o presencial fuera de la ciudad"),
    ("AI Engineer", "Buenos Aires / Remote · hybrid", None),
    ("Staff AI Engineer", "Argentina · remote", "título excluido"),
    ("Member of Technical Staff, Fullstack", "Argentina · remote", None),
    ("Account Executive", "Argentina · remote", "título fuera del objetivo"),
])
def test_filtro_de_listado(prefs, title, location, expected):
    assert listing_filter_reason(title, location, prefs) == expected


def test_empresa_excluida_se_descarta_sin_analizar(prefs):
    assert listing_filter_reason("AI Engineer", "Worldwide · remote", prefs, "Acme Outsourcing") == "empresa excluida"
    assert listing_filter_reason("AI Engineer", "Worldwide · remote", prefs, "Acme Labs") is None
    assert company_excluded("acme outsourcing inc.", prefs)


@pytest.mark.parametrize("url,ats", [
    ("https://jobs.lever.co/acme/123/apply?utm_source=x", "lever"),
    ("https://job-boards.greenhouse.io/acme/jobs/1", "greenhouse"),
    ("https://jobs.ashbyhq.com/acme/abc", "ashby"),
    ("https://acme.bamboohr.com/careers/1", "bamboohr"),
    ("https://acme.com/careers", "other"),
    ("", "unknown"),
])
def test_detecta_ats(url, ats):
    assert detect_ats(url) == ats


def test_convierte_salario_a_usd_mensual(prefs):
    anual_usd = analysis(salary={"min": 36000, "max": 48000, "currency": "USD", "period": "year"})
    assert monthly_usd(anual_usd, prefs) == pytest.approx(4000)
    pesos = analysis(salary={"min": None, "max": 2_000_000, "currency": "ARS", "period": "month"})
    assert monthly_usd(pesos, prefs) == pytest.approx(2000)
    sin_cambio = analysis(salary={"max": 100, "currency": "EUR", "period": "hour"})
    assert monthly_usd(sin_cambio, prefs) is None


def test_aplica_si_supera_el_umbral(prefs):
    assert decide(analysis(), prefs).decision == "apply"
    assert decide(analysis(fit_score=60), prefs).decision == "maybe"
    assert decide(analysis(fit_score=30), prefs).decision == "skip"


@pytest.mark.parametrize("overrides,motivo", [
    ({"modality": "hybrid", "work_location": "Córdoba"}, "fuera de la ciudad"),
    ({"remote_accepts_argentina": "no"}, "no acepta Argentina"),
    ({"years_required_min": 7}, "7+ años"),
    ({"role_family": "ml_research"}, "familia de rol excluida"),
    ({"salary": {"max": 1000, "currency": "USD", "period": "month"}}, "debajo del piso"),
])
def test_condiciones_duras_descartan_aunque_el_puntaje_sea_alto(prefs, overrides, motivo):
    result = decide(analysis(fit_score=95, **overrides), prefs)
    assert result.decision == "skip"
    assert any(motivo in r for r in result.reasons)


def test_hibrido_en_la_ciudad_propia_pasa(prefs):
    assert decide(analysis(modality="hybrid", work_location="Rosario, Santa Fe"), prefs).decision == "apply"


def test_salario_sin_tipo_de_cambio_no_descarta_pero_avisa(prefs):
    result = decide(analysis(salary={"max": 900, "currency": "EUR", "period": "month"}), prefs)
    assert result.decision == "apply"
    assert any("sin tipo de cambio" in r for r in result.reasons)


def test_esquema_rechaza_campos_inventados():
    with pytest.raises(ValueError):
        analysis(score_extra=1)


def test_avisos_viejos(prefs):
    from datetime import UTC, datetime
    today = datetime(2026, 10, 15, tzinfo=UTC)
    assert too_old("2024-05-01T00:00:00+00:00", prefs, today)
    assert not too_old("2026-10-01T00:00:00Z", prefs, today)
    assert not too_old(None, prefs, today)
    assert not too_old("2026-09-01", prefs, today)  # sin zona horaria, 44 días
