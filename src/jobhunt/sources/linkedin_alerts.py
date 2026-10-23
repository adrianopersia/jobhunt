"""Alertas de empleo de LinkedIn, leídas desde los emails que LinkedIn le manda al candidato.

Nunca se pide nada a linkedin.com (su robots.txt no lo permite). Por cada puesto de la alerta:
1. se busca el mismo aviso en el board público de la empresa (Greenhouse, Lever o Ashby), que
   trae la descripción completa y el formulario real;
2. si no aparece, queda como `needs_text`, para que el candidato pegue el texto con
   `jobhunt add --paste ... --url <link de LinkedIn>`.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from jobhunt.http import PoliteClient
from jobhunt.models import AlertJob, JobStub
from jobhunt.sources import ats_boards
from jobhunt.sources.base import Listing, norm_key

SOURCE = "linkedin"
_JOB_ID = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#]*-)?(\d{6,})")
CACHE_TTL = 30 * 86400


def job_id(url: str) -> str | None:
    match = _JOB_ID.search(url)
    return match.group(1) if match else None


def canonical_url(url: str) -> str:
    jid = job_id(url)
    return f"https://www.linkedin.com/jobs/view/{jid}/" if jid else url.split("?")[0]


def stub_for(job: AlertJob) -> JobStub:
    jid = job_id(job.url) or norm_key(job.company, job.title)
    return JobStub(source=SOURCE, external_id=jid, url=canonical_url(job.url),
                   title=job.title, company=job.company, location=job.location)


def slug_candidates(company: str) -> list[str]:
    """Slugs armados con el nombre completo de la empresa (con y sin sufijo legal).
    Nunca una sola palabra: "Zeta Fictional Corp" no puede caer en el board de "Zeta"."""
    all_words = re.findall(r"[a-z0-9]+", company.lower())
    legal = {"inc", "llc", "ltd", "sa", "srl", "corp", "co", "gmbh", "plc"}
    words = [w for w in all_words if w not in legal] or all_words
    candidates = ["".join(words), "-".join(words), "".join(all_words), "-".join(all_words)]
    return list(dict.fromkeys(s for s in candidates if len(s) > 2))


def _title_tokens(title: str) -> set[str]:
    return set(norm_key("", title).split("|", 1)[1].split())


def same_role(a: str, b: str) -> bool:
    """Mismo puesto: mismas palabras en el título, sin contar ubicación ni puntuación.
    Estricto a propósito: "Software Engineer" no es "Software Engineer, Backend"."""
    ta, tb = _title_tokens(a), _title_tokens(b)
    return bool(ta) and ta == tb


class BoardResolver:
    """Encuentra el board de una empresa por nombre, con caché en disco."""

    def __init__(self, client: PoliteClient, home: Path, known_boards: list[dict]):
        self.client = client
        self.path = home / "board_cache.json"
        try:
            self.cache = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}
        for board in known_boards:
            key = norm_key(board["name"], "x").split("|")[0]
            self.cache[key] = {"ats": board["ats"], "slug": board["slug"], "at": time.time()}
        self.listings: dict[str, list[Listing]] = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")

    def _fetch(self, ats: str, slug: str, company: str) -> list[Listing] | None:
        url, parse = ats_boards.FETCHERS[ats]
        try:
            data = self.client.get_json(url.format(slug=slug))
        except Exception:
            return None
        items = list(parse(data, company, slug))
        return items or None

    def board_listings(self, company: str) -> list[Listing]:
        key = norm_key(company, "x").split("|")[0]
        if key in self.listings:
            return self.listings[key]
        entry = self.cache.get(key)
        found: list[Listing] = []
        if entry and entry.get("ats"):
            found = self._fetch(entry["ats"], entry["slug"], company) or []
        elif not entry or time.time() - entry.get("at", 0) > CACHE_TTL:
            for slug in slug_candidates(company):
                for ats in ("greenhouse", "lever", "ashby"):
                    items = self._fetch(ats, slug, company)
                    if items:
                        self.cache[key] = {"ats": ats, "slug": slug, "at": time.time()}
                        found = items
                        break
                if found:
                    break
            else:
                self.cache[key] = {"ats": None, "slug": None, "at": time.time()}
        self.listings[key] = found
        return found

    def resolve(self, job: AlertJob) -> Listing | None:
        for listing in self.board_listings(job.company):
            if same_role(listing.stub.title, job.title):
                return listing
        return None


def ingest(batch, store, prefs, resolver) -> dict:
    """Carga una tanda de alertas en la base. Devuelve un resumen por resultado."""
    from jobhunt.policy import listing_filter_reason

    if not batch.received_from.lower().strip().endswith("linkedin.com"):
        raise ValueError("Las alertas tienen que venir de un remitente @linkedin.com.")
    summary = {"resolved_on_company_board": [], "needs_text": [], "filtered": 0,
               "duplicates": 0, "already_known": 0}
    for job in batch.jobs:
        stub = stub_for(job)
        existing = store.get(stub.id)
        if existing and existing["status"] not in ("listed", "filtered", "needs_text"):
            summary["already_known"] += 1
            continue
        store.upsert_stub(stub)
        if listing_filter_reason(job.title, job.location, prefs):
            store.set_status(stub.id, "filtered")
            summary["filtered"] += 1
            continue
        listing = resolver.resolve(job)
        if listing:
            store.upsert_stub(listing.stub)
            if listing_filter_reason(listing.stub.title, listing.stub.location, prefs):
                store.set_status(listing.stub.id, "filtered")
                store.set_status(stub.id, "filtered")
                summary["filtered"] += 1
                continue
            if store.needs_detail(listing.stub.id):
                store.save_detail(listing.stub.id, listing.detail)
            store.set_status(stub.id, "duplicate")
            summary["resolved_on_company_board"].append(f"{job.company}: {job.title} -> {listing.stub.id}")
        elif store.duplicate_of(stub.id):
            store.set_status(stub.id, "duplicate")
            summary["duplicates"] += 1
        else:
            store.set_status(stub.id, "needs_text")
            summary["needs_text"].append(f"{job.company}: {job.title} | {stub.url}")
        store.commit()
    return summary
