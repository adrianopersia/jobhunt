from jobhunt.models import JobDetail, JobStub, Preferences
from jobhunt.policy import listing_filter_reason
from jobhunt.sources.ats_boards import parse_ashby, parse_greenhouse, parse_lever
from jobhunt.sources.base import norm_key
from jobhunt.store import Store


def test_greenhouse_desescapa_el_html_del_contenido():
    data = {"jobs": [{"id": 1, "title": "AI Engineer", "location": {"name": "Argentina, Remote"},
                      "absolute_url": "https://x/1", "updated_at": "2026-10-01",
                      "content": "&lt;p&gt;Build &lt;b&gt;agents&lt;/b&gt;&lt;/p&gt;"}]}
    [listing] = parse_greenhouse(data, "Acme", "acme")
    assert listing.stub.id == "ats_boards:greenhouse-acme-1"
    assert listing.detail.description == "Build\nagents"


def test_lever_arma_ubicacion_con_modalidad_y_salario_en_la_descripcion():
    data = [{"id": "a", "text": "Backend Dev", "hostedUrl": "h", "applyUrl": "h/apply",
             "categories": {"location": "Buenos Aires", "commitment": "Full-time"},
             "workplaceType": "hybrid", "descriptionPlain": "Intro",
             "lists": [{"text": "Requirements", "content": "<li>Node</li>"}],
             "salaryRange": {"min": 2000, "max": 3000, "currency": "USD", "interval": "per-month-salary"},
             "createdAt": 1760000000000}]
    [listing] = parse_lever(data, "Acme", "acme")
    assert listing.stub.location == "Buenos Aires · hybrid"
    assert "Requirements\nNode" in listing.detail.description
    assert "2000-3000 USD" in listing.detail.description


def test_ashby_omite_no_listados_y_marca_remoto():
    data = {"jobs": [
        {"id": "1", "title": "FDE", "location": "Argentina", "secondaryLocations": [{"location": "Chile"}],
         "isRemote": True, "descriptionPlain": "x", "jobUrl": "j", "applyUrl": "j/app"},
        {"id": "2", "title": "Hidden", "isListed": False},
    ]}
    listings = list(parse_ashby(data, "Acme", "acme"))
    assert [l.stub.title for l in listings] == ["FDE"]
    assert listings[0].stub.location == "Argentina / Chile · remote"


def test_region_bloqueada_salvo_que_nombre_una_aceptable():
    prefs = Preferences(home_city_keywords=["rosario"], title_include=["engineer"], title_exclude=[],
                        remote_region_ok=["argentin", r"\blatam\b"], remote_region_block=[r"\b(usa|brazil)\b"])
    assert listing_filter_reason("Engineer", "USA · remote", prefs) == "restringido a otra región"
    assert listing_filter_reason("Engineer", "Brazil / Argentina · remote", prefs) is None
    assert listing_filter_reason("Engineer", "Remote", prefs) is None


def test_norm_key_ignora_ubicacion_y_puntuacion():
    assert norm_key("Acme Inc.", "Senior Engineer (Argentina) - Remote") == norm_key("ACME inc", "Senior Engineer")


def test_mismo_aviso_en_dos_fuentes_es_duplicado(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    a = JobStub(source="s1", external_id="1", url="u", title="AI Engineer", company="Acme")
    b = JobStub(source="s2", external_id="9", url="v", title="AI Engineer (LATAM)", company="ACME")
    store.upsert_stub(a)
    store.save_detail(a.id, JobDetail(description="d"))
    store.upsert_stub(b)
    assert store.duplicate_of(b.id) == a.id


def test_prioridad_de_titulos():
    from jobhunt.policy import title_priority
    prefs = Preferences(home_city_keywords=["x"], title_include=["."], title_exclude=[],
                        priority_title=[r"\bai\b"], deprioritize_title=[r"\bsenior\b"])
    assert title_priority("AI Engineer", prefs) == 2
    assert title_priority("Backend Engineer", prefs) == 1
    assert title_priority("Senior AI Engineer", prefs) == 1
    assert title_priority("Senior Backend Engineer", prefs) == 0


def test_duplicados_dentro_de_la_misma_corrida(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    a = JobStub(source="s", external_id="1", url="u", title="Mobile Engineer (Argentina)", company="Acme")
    b = JobStub(source="s", external_id="2", url="v", title="Mobile Engineer (Latin America)", company="Acme")
    store.upsert_stub(a)
    store.set_status(a.id, "listed")
    store.upsert_stub(b)
    assert store.duplicate_of(b.id) == a.id
