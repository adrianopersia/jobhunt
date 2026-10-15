"""Respuestas sintéticas con la forma de cada API (verificada contra respuestas reales)."""

from jobhunt.sources import getonbrd, himalayas, jobicy, wwr


def test_getonbrd_concatena_secciones_y_arma_ubicacion():
    job = {"id": "ai-dev-acme", "links": {"public_url": "https://gob/ai-dev-acme"}, "attributes": {
        "title": "AI Developer", "projects": "<p>Agents</p>", "functions": "<li>Build</li>",
        "description": "<li>Python</li>", "remote_modality": "remote_local", "published_at": 1760000000,
        "min_salary": 2000, "max_salary": 2500,
        "company": {"data": {"attributes": {"name": "Acme"}}},
        "seniority": {"data": {"attributes": {"name": "Semi Senior"}}},
        "location_tenants": {"data": [{"attributes": {"name": "Argentina"}}]},
        "location_regions": {"data": [{"attributes": {"name": "South America"}}]},
        "location_cities": {"data": []}}}
    listing = getonbrd.parse(job)
    assert listing.stub.location == "Argentina / South America · remote"
    assert listing.stub.company == "Acme"
    d = listing.detail.description
    assert d.startswith("Agents") and "Python" in d and "Semi Senior" in d and "2000 - 2500" in d


def test_getonbrd_fully_remote_sin_paises_es_mundial():
    job = {"id": "x", "attributes": {"title": "Dev", "remote_modality": "fully_remote"}}
    assert getonbrd.parse(job).stub.location == "Worldwide · remote"


def test_himalayas_restricciones_y_salario():
    job = {"guid": "https://himalayas.app/companies/acme/jobs/ai-engineer", "title": "AI Engineer",
           "companyName": "Acme", "description": "<p>LLMs</p>", "locationRestrictions": ["Argentina", "Chile"],
           "minSalary": 40000, "maxSalary": 60000, "currency": "USD", "salaryPeriod": "annual",
           "pubDate": 1760000000, "applicationLink": "https://himalayas.app/companies/acme/jobs/ai-engineer"}
    listing = himalayas.parse(job)
    assert listing.stub.location == "Argentina / Chile · remote"
    assert listing.stub.external_id == "ai-engineer"
    assert "40000 - 60000 USD annual" in listing.detail.description


def test_jobicy_geo_y_salario_opcional():
    job = {"id": 7, "jobTitle": "Full Stack", "companyName": "Acme", "jobGeo": "LATAM,  USA",
           "jobDescription": "<p>React</p>", "url": "https://jobicy.com/jobs/7", "jobType": ["full-time"]}
    listing = jobicy.parse(job)
    assert listing.stub.location == "LATAM / USA · remote"
    assert "Salary" not in listing.detail.description


def test_wwr_separa_empresa_del_titulo():
    xml = """<rss><channel><item>
      <title>Acme: Backend Engineer</title><region>Anywhere in the World</region>
      <country>🇦🇷 Argentina</country><link>https://weworkremotely.com/remote-jobs/acme-backend</link>
      <pubDate>Mon, 13 Oct 2026 10:00:00 +0000</pubDate>
      <description>&lt;p&gt;Node.js&lt;/p&gt;</description><type>Full-Time</type>
    </item></channel></rss>"""
    [listing] = list(wwr.parse_feed(xml))
    assert (listing.stub.company, listing.stub.title) == ("Acme", "Backend Engineer")
    assert listing.stub.location == "Anywhere in the World / 🇦🇷 Argentina · remote"
    assert listing.detail.description == "Node.js"
