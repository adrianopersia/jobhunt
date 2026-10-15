"""Get on Board: API pública v0 (sin auth). La mejor señal para LatAm: filtra por país exacto
y trae seniority y salario. La postulación se hace en Get on Board, con cuenta del candidato.

Salario: la API da `min_salary`/`max_salary` sin moneda ni período; el sitio los muestra como
USD/mes bruto, así que se asume eso y se aclara en la descripción.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from jobhunt.http import PoliteClient
from jobhunt.models import JobDetail, JobStub
from jobhunt.sources.base import FetchContext, Listing, html_text

SOURCE = "getonbrd"
API = "https://www.getonbrd.com/api/v0"
EXPAND = "&".join(f"expand[]={x}" for x in (
    "company", "seniority", "location_tenants", "location_regions", "location_cities"))
QUERIES = [
    f"{API}/categories/programming/jobs?country_code=AR&per_page=120&{EXPAND}",
    f"{API}/categories/machine-learning-ai/jobs?country_code=AR&per_page=120&{EXPAND}",
    f"{API}/categories/mobile-developer/jobs?country_code=AR&per_page=120&{EXPAND}",
    f"{API}/search/jobs?query=developer&remote=true&per_page=120&{EXPAND}",
    f"{API}/search/jobs?query=engineer&remote=true&per_page=120&{EXPAND}",
]
_MODALITY = {"fully_remote": "remote", "remote_local": "remote", "hybrid": "hybrid", "no_remote": "onsite"}


def _names(rel: dict | None) -> list[str]:
    data = (rel or {}).get("data") or []
    data = data if isinstance(data, list) else [data]
    return [d.get("attributes", {}).get("name", "") for d in data if d.get("attributes")]


def parse(job: dict) -> Listing:
    a = job["attributes"]
    places = _names(a.get("location_cities")) + _names(a.get("location_tenants")) + _names(a.get("location_regions"))
    modality = a.get("remote_modality") or ""
    if modality == "fully_remote" and not places:
        places = ["Worldwide"]
    location = " / ".join(dict.fromkeys(p for p in places if p))
    location = f"{location} · {_MODALITY.get(modality, modality)}" if modality else location
    company = (_names(a.get("company")) or [""])[0]
    seniority = (_names(a.get("seniority")) or [""])[0]

    sections = [
        ("", a.get("projects")), (a.get("functions_headline") or "Functions", a.get("functions")),
        (a.get("description_headline") or "Requirements", a.get("description")),
        (a.get("desirable_headline") or "Nice to have", a.get("desirable")),
        (a.get("benefits_headline") or "Benefits", a.get("benefits")),
    ]
    parts = [f"{title}\n{html_text(body)}" if title else html_text(body) for title, body in sections if body]
    if seniority:
        parts.append(f"Seniority (Get on Board): {seniority}")
    if a.get("min_salary") or a.get("max_salary"):
        parts.append(f"Salary (Get on Board, gross USD/month): {a.get('min_salary') or '?'} - {a.get('max_salary') or '?'}")

    url = (job.get("links") or {}).get("public_url", "")
    posted = a.get("published_at")
    stub = JobStub(source=SOURCE, external_id=job["id"], url=url, title=a.get("title", ""),
                   company=company, location=location)
    detail = JobDetail(
        description="\n\n".join(parts), apply_url=url,
        posted_at=datetime.fromtimestamp(posted, UTC).isoformat() if posted else None,
        modality_raw=modality or None, location_raw=location,
        location_requirements=_names(a.get("location_tenants")),
    )
    return Listing(stub, detail)


def iter_jobs(client: PoliteClient, ctx: FetchContext) -> Iterator[Listing]:
    seen: set[str] = set()
    for url in QUERIES:
        page = 1
        while True:
            try:
                data = client.get_json(f"{url}&page={page}")
            except Exception as err:
                ctx.errors.append(f"{url} p{page}: {err}")
                ctx.complete = False
                break
            for job in data.get("data", []):
                if job["id"] not in seen:
                    seen.add(job["id"])
                    yield parse(job)
            if page >= (data.get("meta") or {}).get("total_pages", 1) or page >= 3:
                break
            page += 1


def fetch_detail(client: PoliteClient, stub: JobStub) -> JobDetail:
    raise RuntimeError("Get on Board trae el detalle en el listado.")
