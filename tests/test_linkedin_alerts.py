import pytest

from jobhunt.models import AlertBatch, AlertJob, Preferences
from jobhunt.sources import linkedin_alerts as li
from jobhunt.sources.manual import from_text
from jobhunt.store import Store

PREFS = Preferences(home_city_keywords=["rosario"], title_include=["engineer", "developer"],
                    title_exclude=["manager"], remote_region_ok=["argentin"], remote_region_block=[r"\busa\b"])


def test_id_y_link_canonico():
    assert li.job_id("https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=abc") == "4012345678"
    assert li.job_id("https://ar.linkedin.com/jobs/view/ai-engineer-at-acme-4012345678") == "4012345678"
    assert li.canonical_url("https://www.linkedin.com/comm/jobs/view/4012345678/?x=1") == \
        "https://www.linkedin.com/jobs/view/4012345678/"


def test_slugs_y_titulos():
    assert li.slug_candidates("Acme Labs Inc.") == ["acmelabs", "acme-labs", "acmelabsinc", "acme-labs-inc"]
    assert "zeta" not in li.slug_candidates("Zeta Fictional Corp")
    assert li.same_role("Senior AI Engineer (Remote, LATAM)", "Senior AI Engineer")
    assert not li.same_role("Software Engineer", "Software Engineer, Backend")
    assert not li.same_role("AI Engineer", "Account Executive")


class FakeClient:
    """Solo existe el board de Greenhouse de 'acme' (y uno de otra empresa, 'zeta')."""

    def __init__(self):
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        if "/boards/zeta/" in url:
            return {"jobs": [{"id": 9, "title": "Backend Developer", "location": {"name": "Argentina"},
                              "absolute_url": "https://job-boards.greenhouse.io/zeta/jobs/9", "content": ""}]}
        if "greenhouse" in url and "/boards/acme/" in url:
            return {"jobs": [{"id": 7, "title": "AI Engineer", "location": {"name": "Argentina, Remote"},
                              "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/7",
                              "content": "&lt;p&gt;LLMs&lt;/p&gt;"}]}
        raise RuntimeError("404")


def batch(*jobs, sender="jobalerts-noreply@linkedin.com"):
    return AlertBatch(received_from=sender, jobs=list(jobs))


def test_ingesta_resuelve_en_el_board_o_pide_texto(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    resolver = li.BoardResolver(FakeClient(), tmp_path, known_boards=[])
    found = AlertJob(title="AI Engineer", company="Acme", location="Argentina (Remote)",
                     url="https://www.linkedin.com/comm/jobs/view/4000000001/")
    missing = AlertJob(title="Backend Developer", company="Zeta Fictional Corp", location="Argentina",
                       url="https://www.linkedin.com/comm/jobs/view/4000000002/")
    filtered = AlertJob(title="Engineering Manager", company="Acme", location="Argentina",
                        url="https://www.linkedin.com/comm/jobs/view/4000000003/")
    summary = li.ingest(batch(found, missing, filtered), store, PREFS, resolver)

    assert summary["filtered"] == 1
    assert store.get("ats_boards:greenhouse-acme-7")["status"] == "pending"
    assert store.get("linkedin:4000000001")["status"] == "duplicate"
    assert store.get("linkedin:4000000002")["status"] == "needs_text"

    # El texto pegado a mano completa el mismo aviso de la alerta.
    assert store.get("ats_boards:greenhouse-zeta-9") is None  # no cayó en el board de otra empresa
    pasted = from_text("Buscamos backend...", "Backend Developer", "Zeta Fictional Corp",
                       url="https://www.linkedin.com/jobs/view/4000000002/?utm=x")
    assert pasted.stub.id == "linkedin:4000000002"


def test_el_board_encontrado_queda_en_cache(tmp_path):
    client = FakeClient()
    resolver = li.BoardResolver(client, tmp_path, known_boards=[])
    resolver.board_listings("Acme")
    resolver.save()
    again = li.BoardResolver(FakeClient(), tmp_path, known_boards=[])
    assert again.cache["acme"]["slug"] == "acme"


def test_solo_acepta_alertas_de_linkedin(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    with pytest.raises(ValueError):
        li.ingest(batch(sender="otro@ejemplo.com"), store, PREFS, li.BoardResolver(FakeClient(), tmp_path, []))


def test_descartar_avisos_que_esperan_texto(tmp_path, capsys):
    from argparse import Namespace

    from jobhunt.cli import cmd_linkedin_dismiss
    from jobhunt.models import JobStub
    from jobhunt.store import Store

    store = Store(tmp_path / "db.sqlite")
    for n in ("111111", "222222", "333333"):
        store.upsert_stub(JobStub(source="linkedin", external_id=n, url=f"https://www.linkedin.com/jobs/view/{n}/",
                                  title="Dev", company="Acme"))
        store.set_status(f"linkedin:{n}", "needs_text")
    cmd_linkedin_dismiss(Namespace(refs=["https://www.linkedin.com/jobs/view/111111/?trk=x"], closed=True), store)
    cmd_linkedin_dismiss(Namespace(refs=["linkedin:222222", "linkedin:999999"], closed=False), store)

    assert [store.get(f"linkedin:{n}")["status"] for n in ("111111", "222222", "333333")] == [
        "gone", "filtered", "needs_text"]
    assert "999999" in capsys.readouterr().out
