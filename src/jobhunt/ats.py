"""Descripción del aviso tomada del ATS de la empresa, para cuando el agregador no la tiene."""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup

from jobhunt.http import PoliteClient
from jobhunt.policy import detect_ats

MIN_CHARS = 300


def clean_url(url: str) -> str:
    """Saca query y fragmento (UTMs de referido) antes de pedir la página."""
    parts = urlparse(url)
    return urlunparse(parts._replace(query="", fragment=""))


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()
    root = soup.find("main") or soup.body or soup
    return root.get_text("\n", strip=True)


def _bamboohr(client: PoliteClient, url: str) -> str:
    match = re.search(r"/careers/(\d+)", url)
    if not match:
        return ""
    host = urlparse(url).netloc
    data = client.get_json(f"https://{host}/careers/{match.group(1)}/detail")
    opening = (data.get("result") or {}).get("jobOpening") or {}
    return html_to_text(opening.get("description") or "")


def fetch_description(client: PoliteClient, apply_url: str) -> str:
    """Texto del aviso desde el ATS, o "" si no se puede obtener sin un navegador."""
    if not apply_url:
        return ""
    url = clean_url(apply_url)
    if detect_ats(url) == "bamboohr":
        text = _bamboohr(client, url)
    else:
        text = html_to_text(client.get_text(url))
    return text if len(text) >= MIN_CHARS else ""
