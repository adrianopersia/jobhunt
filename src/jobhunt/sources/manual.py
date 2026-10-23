"""Avisos que el candidato encuentra por su cuenta (LinkedIn, un referido, un tuit).

Si el link es de Greenhouse, Lever o Ashby, se lee por su API pública y queda con el mismo ID
que tendría desde el board de la empresa. Cualquier otro link se lee como HTML.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from jobhunt.ats import clean_url, html_to_text
from jobhunt.http import PoliteClient
from jobhunt.models import JobDetail, JobStub
from jobhunt.sources import ats_boards
from jobhunt.sources.base import Listing

SOURCE = "manual"

# Sitios cuyo robots.txt no permite leer avisos de forma automática. Para estos, el texto lo
# pega el candidato (`jobhunt add --paste`), o se usa el link al ATS de la empresa si el aviso
# dice "Apply on company website".
NO_FETCH_HOSTS = ("linkedin.com", "indeed.com", "glassdoor.com")


def no_fetch(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == h or host.endswith("." + h) for h in NO_FETCH_HOSTS)


def from_text(text: str, title: str, company: str, url: str = "", location: str = "") -> Listing:
    """Aviso pegado a mano: el texto lo copió el candidato desde el sitio. Si el link es de un
    aviso de LinkedIn, usa el mismo ID que la alerta de email, así completa ese aviso."""
    from jobhunt.sources import linkedin_alerts

    if linkedin_alerts.job_id(url):
        stub = JobStub(source=linkedin_alerts.SOURCE, external_id=linkedin_alerts.job_id(url),
                       url=linkedin_alerts.canonical_url(url), title=title, company=company,
                       location=location)
        return Listing(stub, JobDetail(description=text.strip(), apply_url=stub.url,
                                       location_raw=location or None))
    key = url or f"{company}|{title}"
    stub = JobStub(source=SOURCE, external_id=hashlib.sha1(key.encode()).hexdigest()[:12],
                   url=url, title=title, company=company, location=location)
    return Listing(stub, JobDetail(description=text.strip(), apply_url=url, location_raw=location or None))


def fetch_listing(client: PoliteClient, url: str) -> Listing:
    if no_fetch(url):
        raise PermissionError(
            f"{urlparse(url).netloc} no permite leer avisos de forma automática. Copiá el texto del "
            "aviso a un archivo y usá `jobhunt add --paste <archivo> --title ... --company ... "
            "--url <link>`; si el aviso dice \"Apply on company website\", pasá ese link en su lugar.")
    url = clean_url(url)
    if m := re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)", url):
        slug, job = m.groups()
        data = client.get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job}?content=true")
        return next(ats_boards.parse_greenhouse({"jobs": [data]}, data.get("company_name") or slug, slug))
    if m := re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})", url):
        slug, job = m.groups()
        data = client.get_json(f"https://api.lever.co/v0/postings/{slug}/{job}?mode=json")
        return next(ats_boards.parse_lever([data], slug, slug))
    if m := re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", url):
        slug, job = m.groups()
        data = client.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
        for listing in ats_boards.parse_ashby(data, slug, slug):
            if listing.stub.external_id.endswith(job):
                return listing
        raise ValueError("El aviso no está publicado en el board de Ashby.")

    page = client.get_text(url)
    soup = BeautifulSoup(page, "html.parser")
    meta = lambda prop: (soup.find("meta", property=prop) or {}).get("content")  # noqa: E731
    title = meta("og:title") or (soup.h1.get_text(" ", strip=True) if soup.h1 else "") or (
        soup.title.get_text(strip=True) if soup.title else url)
    company = meta("og:site_name") or urlparse(url).netloc
    stub = JobStub(source=SOURCE, external_id=hashlib.sha1(url.encode()).hexdigest()[:12],
                   url=url, title=title, company=company)
    return Listing(stub, JobDetail(description=html_to_text(page), apply_url=url))
