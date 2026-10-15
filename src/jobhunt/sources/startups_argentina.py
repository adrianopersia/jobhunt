"""Startups Argentina (www.startupsargentina.com).

El listado y cada aviso vienen renderizados del servidor. El detalle trae un JSON-LD
`JobPosting` (fecha, modalidad, ubicación requerida) y la descripción completa en
`div.job-description`; el JSON-LD la trunca, así que la descripción sale del HTML.

robots.txt permite /empleos para agentes genéricos y declara `ai-input=yes`; no se toca /api/.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from jobhunt.http import PoliteClient
from jobhunt.models import JobDetail, JobStub
from jobhunt.sources.base import FetchContext, Listing

SOURCE = "startups_argentina"
BASE = "https://www.startupsargentina.com"
_PAGES_RE = re.compile(r"Página\s+\d+\s+de\s+(\d+)")


def parse_listing(html: str) -> tuple[list[JobStub], int]:
    soup = BeautifulSoup(html, "html.parser")
    stubs = []
    for card in soup.find_all("article"):
        link = card.select_one("h2 a[href^='/empleos/']")
        if not link:
            continue
        parts = link["href"].strip("/").split("/")
        if len(parts) < 4:
            continue
        company = card.select_one("p a")
        location = card.find("span", recursive=False)
        stubs.append(
            JobStub(
                source=SOURCE,
                external_id=parts[2],
                url=urljoin(BASE, link["href"]),
                title=link.get_text(strip=True),
                company=company.get_text(strip=True) if company else parts[1],
                location=location.get_text(" ", strip=True) if location else "",
            )
        )
    match = _PAGES_RE.search(soup.get_text(" "))
    return stubs, int(match.group(1)) if match else 1


def parse_detail(html: str) -> JobDetail:
    soup = BeautifulSoup(html, "html.parser")

    ld: dict = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            ld = data
            break

    meta = {}
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            meta[dt.get_text(strip=True).lower()] = dd.get_text(" ", strip=True)

    body = soup.select_one("div.job-description")
    description = body.get_text("\n", strip=True) if body else ld.get("description", "")

    apply_url = ""
    for a in soup.find_all("a", href=True):
        if a.get_text(strip=True).lower() == "aplicar" and a["href"].startswith("http"):
            apply_url = a["href"]
            break

    countries = [
        c.get("name", "")
        for c in ld.get("applicantLocationRequirements", []) or []
        if isinstance(c, dict)
    ]
    return JobDetail(
        description=description,
        apply_url=apply_url,
        posted_at=ld.get("datePosted"),
        employment_type=ld.get("employmentType") or meta.get("tipo"),
        modality_raw=meta.get("modalidad") or ld.get("jobLocationType"),
        location_raw=meta.get("ubicación"),
        location_requirements=[c for c in countries if c],
    )


def iter_listing(client: PoliteClient, max_pages: int | None = None) -> Iterator[JobStub]:
    page, total = 1, 1
    while page <= total and (max_pages is None or page <= max_pages):
        html = client.get_text(f"{BASE}/empleos?page={page}")
        stubs, total = parse_listing(html)
        yield from stubs
        page += 1


def iter_jobs(client: PoliteClient, ctx: FetchContext) -> Iterator[Listing]:
    ctx.complete = ctx.max_pages is None
    for stub in iter_listing(client, max_pages=ctx.max_pages):
        yield Listing(stub)


def fetch_detail(client: PoliteClient, stub: JobStub) -> JobDetail:
    return parse_detail(client.get_text(stub.url))
