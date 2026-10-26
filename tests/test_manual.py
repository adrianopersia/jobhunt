import pytest

from jobhunt.sources.manual import fetch_listing, from_text, no_fetch


@pytest.mark.parametrize("url,blocked", [
    ("https://www.linkedin.com/jobs/view/1234567890/", True),
    ("https://ar.linkedin.com/jobs/view/ai-engineer-at-acme-123", True),
    ("https://ar.indeed.com/viewjob?jk=abc", True),
    ("https://jobs.lever.co/acme/123", False),
    ("https://notlinkedin.com/jobs/1", False),
])
def test_sitios_que_no_se_leen_automaticamente(url, blocked):
    assert no_fetch(url) is blocked


def test_link_de_linkedin_no_hace_ningun_request():
    class Boom:
        def get_text(self, url):
            raise AssertionError("no debería pedir nada")
        get_json = get_text

    with pytest.raises(PermissionError, match="--paste"):
        fetch_listing(Boom(), "https://www.linkedin.com/jobs/view/1/")


def test_aviso_pegado_a_mano():
    listing = from_text("  Buscamos AI Engineer...\\n", "AI Engineer", "Acme",
                        url="https://www.linkedin.com/jobs/view/1/", location="Argentina · remote")
    assert listing.stub.source == "manual"
    assert listing.stub.location == "Argentina · remote"
    assert listing.detail.description.startswith("Buscamos")
    assert listing.detail.apply_url.endswith("/view/1/")
    again = from_text("otro texto", "AI Engineer", "Acme", url="https://www.linkedin.com/jobs/view/1/")
    assert again.stub.id == listing.stub.id  # mismo link, mismo aviso


def test_aviso_de_workable_por_su_api_publica():
    job = {"title": "Full-Stack Developer", "remote": True, "workplace": "remote", "type": "full",
           "published": "2026-01-10T00:00:00.000Z",
           "description": "<p>Build web products.</p>", "requirements": "<ul><li>3+ years of React</li></ul>",
           "benefits": "<p>Remote</p>",
           "locations": [{"city": "Tbilisi", "country": "Georgia", "hidden": False},
                         {"city": "", "country": "Argentina", "hidden": False},
                         {"city": "", "country": "Oculto", "hidden": True}]}

    class Fake:
        def __init__(self):
            self.urls = []

        def get_json(self, url):
            self.urls.append(url)
            return {"name": "Acme Apps"} if url.endswith("/accounts/acmeapps") else job

    client = Fake()
    listing = fetch_listing(client, "https://apply.workable.com/acmeapps/j/AB12CD34EF/?utm_source=x")
    assert client.urls == ["https://apply.workable.com/api/v2/accounts/acmeapps/jobs/AB12CD34EF",
                           "https://apply.workable.com/api/v1/accounts/acmeapps"]
    assert (listing.stub.company, listing.stub.title) == ("Acme Apps", "Full-Stack Developer")
    assert listing.stub.location == "Tbilisi, Georgia / Argentina · remote"
    assert listing.detail.location_requirements == ["Georgia", "Argentina"]
    assert "3+ years of React" in listing.detail.description and "Requirements" in listing.detail.description
    assert listing.detail.apply_url == "https://apply.workable.com/acmeapps/j/AB12CD34EF/"
