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
