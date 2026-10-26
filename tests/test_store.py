from jobhunt.models import JobDetail, JobStub
from jobhunt.store import Store


def stub(n):
    return JobStub(source="s", external_id=str(n), url=f"u{n}", title=f"T{n}", company="C")


def test_avisos_que_desaparecen_quedan_cerrados_y_vuelven_si_reaparecen(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    for n in (1, 2, 3):
        store.upsert_stub(stub(n))
        store.save_detail(stub(n).id, JobDetail(description="d"))
    store.set_status(stub(3).id, "filtered")

    gone = store.mark_gone("s", {stub(1).id})
    assert gone == [stub(2).id]  # los filtrados no se tocan
    assert store.get(stub(2).id)["status"] == "gone"

    store.upsert_stub(stub(2))
    assert store.get(stub(2).id)["status"] == "pending"


def test_recalcular_la_decision_no_toca_el_analisis(tmp_path):
    from jobhunt.models import JobAnalysis
    from jobhunt.policy import Decision

    store = Store(tmp_path / "db.sqlite")
    store.upsert_stub(stub(1))
    analysis = JobAnalysis.model_validate(dict(
        role_family="applied_ai", seniority="senior", years_required_min=None, modality="remote",
        work_location="", remote_accepts_argentina="yes", salary=None, posting_language="en",
        english_required="yes", requirements=[], stack=[], blockers=[], fit_score=80, rationale="r"))
    store.save_analysis(stub(1).id, analysis, Decision("apply", []), "v1")
    store.update_decision(stub(1).id, Decision("skip", ["senior sin años pedidos"]))

    (row,) = store.analyses()
    assert (row["decision"], row["fit_score"], row["rubric_version"]) == ("skip", 80, "v1")
    assert row["decision_reasons"] == '["senior sin años pedidos"]'


def test_volver_a_cargar_un_aviso_corrige_empresa_y_clave_de_duplicado(tmp_path):
    from jobhunt.sources.base import norm_key

    store = Store(tmp_path / "db.sqlite")
    first = JobStub(source="s", external_id="1", url="u1", title="Dev - Acme", company="board.example.com")
    store.upsert_stub(first)
    store.upsert_stub(first.model_copy(update={"title": "Dev", "company": "Acme"}))
    row = store.get(first.id)
    assert (row["title"], row["company"], row["norm_key"]) == ("Dev", "Acme", norm_key("Acme", "Dev"))
