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


def fetch_listing(client: PoliteClient, url: str) -> Listing:
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
