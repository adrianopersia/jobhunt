"""Contrato común de las fuentes.

Una fuente entrega `Listing`s: el aviso mínimo (`stub`) y, si la fuente ya lo trae en el
listado (como las APIs), el detalle. Si no lo trae, el fetch lo pide con `fetch_detail`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from bs4 import BeautifulSoup

from jobhunt.http import PoliteClient
from jobhunt.models import JobDetail, JobStub


@dataclass
class Listing:
    stub: JobStub
    detail: JobDetail | None = None


@dataclass
class FetchContext:
    home: Path
    max_pages: int | None = None
    errors: list[str] = field(default_factory=list)
    complete: bool = True  # False si algo falló: entonces no se marcan avisos como cerrados


class Source(Protocol):
    SOURCE: str

    def iter_jobs(self, client: PoliteClient, ctx: FetchContext) -> Iterator[Listing]: ...

    def fetch_detail(self, client: PoliteClient, stub: JobStub) -> JobDetail: ...


def html_text(html: str | None) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


def norm_key(company: str, title: str) -> str:
    """Clave para detectar el mismo aviso publicado en dos lugares."""
    title = re.sub(r"\([^)]*\)", " ", title.lower())
    title = re.sub(r"\b(remote|remoto|argentina|latam|hybrid|h[ií]brido|ar)\b", " ", title)
    title = re.sub(r"[^a-z0-9]+", " ", title).strip()
    company = re.sub(r"[^a-z0-9]+", "", company.lower())
    return f"{company}|{title}"
