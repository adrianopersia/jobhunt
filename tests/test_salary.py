import pytest

from jobhunt.models import JobAnalysis, Preferences
from jobhunt.salary import data_band, position_for, suggest

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


def test_con_datos_suficientes_usa_la_banda_observada():
    assert data_band([2000.0] * 7) is None
    band = data_band([1800, 2000, 2100, 2200, 2400, 2500, 2600, 3000])
    s = suggest(analysis(fit=70, market="local"), PREFS, observed=band)
    assert s.source.startswith("avisos comparables")
    assert band.min < s.ask < band.max


def test_la_banda_del_aviso_le_gana_a_los_datos():
    band = data_band([1000] * 10)
    s = suggest(analysis(fit=70, salary={"min": 3000, "max": 4500, "currency": "USD", "period": "month"}),
                PREFS, observed=band)
    assert s.source == "banda publicada en el aviso"


def test_calibracion_solo_con_salarios_regionales(tmp_path):
    from jobhunt.cli import _salary_points
    from jobhunt.models import JobDetail, JobStub
    from jobhunt.policy import Decision
    from jobhunt.store import Store

    store = Store(tmp_path / "db.sqlite")
    cases = [("getonbrd", "1", 3000, "yes"), ("wwr", "2", 15000, "yes"), ("getonbrd", "3", 2500, "no")]
    for source, ext, amount, accepts in cases:
        stub = JobStub(source=source, external_id=ext, url="u", title=f"Dev {ext}", company="C")
        store.upsert_stub(stub)
        store.save_detail(stub.id, JobDetail(description="d"))
        a = analysis(fit=70, market="foreign",
                     salary={"min": amount, "max": amount, "currency": "USD", "period": "month"})
        a = a.model_copy(update={"remote_accepts_argentina": accepts})
        store.save_analysis(stub.id, a, Decision("apply", []), "v")
    points = _salary_points(store, PREFS)
    assert points == {("foreign", "semi_senior"): [3000.0]}  # wwr (EE.UU.) y el que no acepta Argentina, afuera
