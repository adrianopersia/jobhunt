"""Himalayas: API pública de empleos remotos. Términos: uso personal permitido, la postulación
va por `applicationLink` y hay que dar crédito a Himalayas como fuente (ver README)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import quote

from jobhunt.http import PoliteClient
from jobhunt.models import JobDetail, JobStub
from jobhunt.sources.base import FetchContext, Listing, html_text

SOURCE = "himalayas"
QUERIES = ["ai engineer", "llm", "full stack", "backend engineer", "typescript", "flutter"]
PAGES = 2


def parse(job: dict) -> Listing:
    regions = job.get("locationRestrictions") or []
    regions = [r if isinstance(r, str) else r.get("name", "") for r in regions]
    location = f"{' / '.join(regions) if regions else 'Worldwide'} · remote"
    description = html_text(job.get("description"))
    if job.get("minSalary") or job.get("maxSalary"):
        description += (f"\n\nSalary (Himalayas): {job.get('minSalary') or '?'} - {job.get('maxSalary') or '?'} "
                        f"{job.get('currency') or ''} {job.get('salaryPeriod') or ''}")
    if job.get("seniority"):
        description += f"\nSeniority (Himalayas): {', '.join(job['seniority'])}"
    posted = job.get("pubDate")
    url = job.get("applicationLink") or job.get("guid", "")
    stub = JobStub(source=SOURCE, external_id=str(job.get("guid", url)).rstrip("/").rsplit("/", 1)[-1],
                   url=url, title=job.get("title", ""), company=job.get("companyName", ""), location=location)
    detail = JobDetail(
        description=description, apply_url=url,
        posted_at=datetime.fromtimestamp(posted, UTC).isoformat() if isinstance(posted, (int, float)) else posted,
        employment_type=job.get("employmentType"), modality_raw="remote", location_raw=location,
        location_requirements=regions,
    )
    return Listing(stub, detail)


def iter_jobs(client: PoliteClient, ctx: FetchContext) -> Iterator[Listing]:
    seen: set[str] = set()
    for query in QUERIES:
        for page in range(1, PAGES + 1):
            url = f"https://himalayas.app/jobs/api/search?q={quote(query)}&country=AR&sort=recent&page={page}"
            try:
                data = client.get_json(url)
            except Exception as err:
                ctx.errors.append(f"{query} p{page}: {err}")
                ctx.complete = False
                break
            jobs = data.get("jobs") or []
            for job in jobs:
                listing = parse(job)
                if listing.stub.id not in seen:
                    seen.add(listing.stub.id)
                    yield listing
            if not jobs:
                break
    # La búsqueda devuelve una muestra por relevancia, no el universo: no se marcan cerrados.
    ctx.complete = False


def fetch_detail(client: PoliteClient, stub: JobStub) -> JobDetail:
    raise RuntimeError("Himalayas trae el detalle en el listado.")
