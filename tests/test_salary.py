import pytest

from jobhunt.models import JobAnalysis, Preferences
from jobhunt.salary import position_for, suggest

PREFS = Preferences(
    home_city_keywords=["rosario"], salary_floor_usd_month=1500, fx_to_usd={"ARS": 1000},
    salary_reference={
        "local": {"min": 1700, "max": 2300, "source": "encuesta"},
        "foreign": {"min": 2900, "max": 4600, "source": "guía"},
    },
    title_include=["x"], title_exclude=[],
)


def analysis(fit=70, market="unclear", salary=None):
    return JobAnalysis.model_validate(dict(
        role_family="applied_ai", seniority="semi_senior", years_required_min=3,
        modality="remote", work_location="", remote_accepts_argentina="yes", salary=salary,
        employer_market=market, posting_language="en", english_required="yes",
        requirements=[], stack=[], blockers=[], fit_score=fit, rationale="r",
    ))


@pytest.mark.parametrize("fit,pos", [(40, 0.35), (50, 0.35), (70, 0.50), (90, 0.65), (100, 0.65)])
def test_posicion_en_la_banda_segun_encaje(fit, pos):
    assert position_for(fit) == pytest.approx(pos)


def test_usa_la_banda_publicada_si_existe():
    s = suggest(analysis(fit=70, salary={"min": 3000, "max": 4500, "currency": "USD", "period": "month"}), PREFS)
    assert s.source == "banda publicada en el aviso"
    assert (s.ask, s.low, s.high) == (3800, 3500, 4000)


def test_banda_anual_y_usdt_se_normalizan():
    s = suggest(analysis(fit=70, salary={"min": 36000, "max": 54000, "currency": "USDT", "period": "year"}), PREFS)
    assert s.band == (3000, 4500)


def test_sin_banda_usa_la_referencia_del_mercado_que_paga():
    assert suggest(analysis(fit=86, market="local"), PREFS).ask == 2100
    assert suggest(analysis(fit=86, market="foreign"), PREFS).ask == 4000


def test_sin_saber_quien_paga_usa_el_tramo_intermedio():
    s = suggest(analysis(fit=70, market="unclear"), PREFS)
    assert s.band == (2300, 2900)
    assert s.ask == 2600


def test_nunca_por_debajo_del_piso():
    prefs = PREFS.model_copy(update={"salary_floor_usd_month": 2500})
    s = suggest(analysis(fit=50, market="local"), prefs)
    assert s.ask == 2500 and s.low == 2500
