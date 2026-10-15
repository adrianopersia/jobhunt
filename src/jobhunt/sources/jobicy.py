"""Jobicy: API pública de empleos remotos, filtrada por Argentina del lado del servidor
(devuelve Argentina, LATAM y Anywhere). Términos: dar crédito con link y no más de un pase
automático por hora."""

from __future__ import annotations

from collections.abc import Iterator

from jobhunt.http import PoliteClient
from jobhunt.models import JobDetail, JobStub
from jobhunt.sources.base import FetchContext, Listing, html_text

SOURCE = "jobicy"
URL = "https://jobicy.com/api/v2/remote-jobs?count=100&geo=argentina"


def parse(job: dict) -> Listing:
    geo = " / ".join(p.strip() for p in (job.get("jobGeo") or "").split(",") if p.strip())
    location = f"{geo or 'Anywhere'} · remote"
    description = html_text(job.get("jobDescription"))
    if job.get("salaryMin") or job.get("salaryMax"):
        description += (f"\n\nSalary (Jobicy): {job.get('salaryMin') or '?'} - {job.get('salaryMax') or '?'} "
                        f"{job.get('salaryCurrency') or ''} {job.get('salaryPeriod') or ''}")
    if job.get("jobLevel"):
        description += f"\nLevel (Jobicy): {job['jobLevel']}"
    stub = JobStub(source=SOURCE, external_id=str(job["id"]), url=job.get("url", ""),
                   title=job.get("jobTitle", ""), company=job.get("companyName", ""), location=location)
    detail = JobDetail(description=description, apply_url=job.get("url", ""), posted_at=job.get("pubDate"),
                       employment_type=", ".join(job.get("jobType") or []) or None,
                       modality_raw="remote", location_raw=location)
    return Listing(stub, detail)


def iter_jobs(client: PoliteClient, ctx: FetchContext) -> Iterator[Listing]:
    data = client.get_json(URL)
    for job in data.get("jobs") or []:
        yield parse(job)
    ctx.complete = False  # ventana de 7 días: que no aparezca no significa que se cerró


def fetch_detail(client: PoliteClient, stub: JobStub) -> JobDetail:
    raise RuntimeError("Jobicy trae el detalle en el listado.")
