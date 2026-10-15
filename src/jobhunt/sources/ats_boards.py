"""Boards públicos de empresas en Greenhouse, Lever y Ashby.

Son APIs pensadas para que cualquiera muestre los avisos de la empresa: traen la descripción
completa en el listado, así que no hace falta un request por aviso. La lista de empresas vive
en `private/boards.yaml` (ejemplo en `examples/boards.example.yaml`).
"""

from __future__ import annotations

import html
from collections.abc import Iterator
from datetime import UTC, datetime

import yaml

from jobhunt.http import PoliteClient
from jobhunt.models import JobDetail, JobStub
from jobhunt.sources.base import FetchContext, Listing, html_text

SOURCE = "ats_boards"


def _iso_from_ms(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat() if ms else None


def parse_greenhouse(data: dict, company: str, slug: str) -> Iterator[Listing]:
    for job in data.get("jobs", []):
        location = (job.get("location") or {}).get("name", "")
        stub = JobStub(source=SOURCE, external_id=f"greenhouse-{slug}-{job['id']}",
                       url=job.get("absolute_url", ""), title=job.get("title", ""),
                       company=company, location=location)
        detail = JobDetail(
            description=html_text(html.unescape(job.get("content") or "")),
            apply_url=job.get("absolute_url", ""), posted_at=job.get("updated_at"),
            location_raw=location,
        )
        yield Listing(stub, detail)


def parse_lever(data: list, company: str, slug: str) -> Iterator[Listing]:
    for job in data:
        cats = job.get("categories") or {}
        workplace = job.get("workplaceType") or ""
        locations = cats.get("allLocations") or [cats.get("location", "")]
        location = " / ".join(l for l in locations if l)
        location = f"{location} · {workplace}" if workplace else location
        parts = [job.get("descriptionPlain") or ""]
        for block in job.get("lists") or []:
            parts.append(block.get("text", ""))
            parts.append(html_text(block.get("content")))
        parts.append(job.get("additionalPlain") or "")
        salary = job.get("salaryRange") or {}
        if salary.get("min"):
            parts.append(f"Salary range: {salary.get('min')}-{salary.get('max')} "
                         f"{salary.get('currency', '')} per {salary.get('interval', '')}")
        stub = JobStub(source=SOURCE, external_id=f"lever-{slug}-{job['id']}",
                       url=job.get("hostedUrl", ""), title=job.get("text", ""),
                       company=company, location=location)
        detail = JobDetail(
            description="\n".join(p for p in parts if p).strip(),
            apply_url=job.get("applyUrl") or job.get("hostedUrl", ""),
            posted_at=_iso_from_ms(job.get("createdAt")),
            employment_type=cats.get("commitment"), modality_raw=workplace or None,
            location_raw=location,
        )
        yield Listing(stub, detail)


def parse_ashby(data: dict, company: str, slug: str) -> Iterator[Listing]:
    for job in data.get("jobs", []):
        if job.get("isListed") is False:
            continue
        places = [job.get("location") or ""] + [
            s.get("location", "") for s in job.get("secondaryLocations") or []]
        workplace = "remote" if job.get("isRemote") else (job.get("workplaceType") or "")
        location = " / ".join(p for p in places if p)
        location = f"{location} · {workplace}" if workplace else location
        description = job.get("descriptionPlain") or html_text(job.get("descriptionHtml"))
        comp = (job.get("compensation") or {}).get("compensationTierSummary")
        if comp:
            description += f"\nCompensation: {comp}"
        stub = JobStub(source=SOURCE, external_id=f"ashby-{slug}-{job['id']}",
                       url=job.get("jobUrl", ""), title=job.get("title", ""),
                       company=company, location=location)
        detail = JobDetail(
            description=description, apply_url=job.get("applyUrl") or job.get("jobUrl", ""),
            posted_at=job.get("publishedAt"), employment_type=job.get("employmentType"),
            modality_raw=workplace or None, location_raw=location,
        )
        yield Listing(stub, detail)


FETCHERS = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", parse_greenhouse),
    "lever": ("https://api.lever.co/v0/postings/{slug}?mode=json", parse_lever),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true", parse_ashby),
}


def load_boards(ctx: FetchContext) -> list[dict]:
    path = ctx.home / "boards.yaml"
    if not path.is_file():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def iter_jobs(client: PoliteClient, ctx: FetchContext) -> Iterator[Listing]:
    for board in load_boards(ctx):
        url, parse = FETCHERS[board["ats"]]
        try:
            data = client.get_json(url.format(slug=board["slug"]))
        except Exception as err:
            ctx.errors.append(f"{board['name']} ({board['ats']}/{board['slug']}): {err}")
            ctx.complete = False
            continue
        yield from parse(data, board["name"], board["slug"])


def fetch_detail(client: PoliteClient, stub: JobStub) -> JobDetail:
    raise RuntimeError("Los boards traen el detalle en el listado.")
