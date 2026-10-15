"""We Work Remotely: feeds RSS por categoría. Pide atribución con link al aviso.
El título viene como "Empresa: Puesto". La región sola no es confiable; se suma la lista de
países del item a la ubicación para que el filtro de región vea las dos cosas."""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from email.utils import parsedate_to_datetime

from jobhunt.http import PoliteClient
from jobhunt.models import JobDetail, JobStub
from jobhunt.sources.base import FetchContext, Listing, html_text

SOURCE = "wwr"
FEEDS = [
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
]


def parse_feed(xml: str) -> Iterator[Listing]:
    for item in ET.fromstring(xml).iter("item"):
        get = lambda tag: (item.findtext(tag) or "").strip()  # noqa: E731
        company, _, title = get("title").partition(": ")
        if not title:
            company, title = "", company
        countries = get("country")
        location = " / ".join(x for x in (get("region"), countries) if x) or "Anywhere"
        link = get("link") or get("guid")
        try:
            posted = parsedate_to_datetime(get("pubDate")).isoformat()
        except (TypeError, ValueError):
            posted = None
        stub = JobStub(source=SOURCE, external_id=link.rstrip("/").rsplit("/", 1)[-1], url=link,
                       title=title, company=company, location=f"{location} · remote")
        detail = JobDetail(description=html_text(html.unescape(get("description"))), apply_url=link,
                           posted_at=posted, employment_type=get("type") or None,
                           modality_raw="remote", location_raw=location)
        yield Listing(stub, detail)


def iter_jobs(client: PoliteClient, ctx: FetchContext) -> Iterator[Listing]:
    seen: set[str] = set()
    for feed in FEEDS:
        try:
            xml = client.get_text(feed)
        except Exception as err:
            ctx.errors.append(f"{feed}: {err}")
            ctx.complete = False
            continue
        for listing in parse_feed(xml):
            if listing.stub.id not in seen:
                seen.add(listing.stub.id)
                yield listing


def fetch_detail(client: PoliteClient, stub: JobStub) -> JobDetail:
    raise RuntimeError("WWR trae el detalle en el feed.")
