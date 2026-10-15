"""Documento de CV y su render a PDF.

`CvDocument` es lo que produce el agente cv-tailor: cada bullet y el resumen llevan los IDs
del perfil de donde salen, para poder verificar que nada se inventó. El render es HTML con
Jinja más Chrome headless, así el PDF tiene texto real en una sola columna (lo que mejor
leen los ATS).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict, Field

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"

LABELS = {
    "en": {"summary": "Summary", "skills": "Skills", "experience": "Professional Experience",
           "projects": "Projects", "education": "Education", "languages": "Languages",
           "present": "Present"},
    "es": {"summary": "Perfil", "skills": "Habilidades", "experience": "Experiencia Profesional",
           "projects": "Proyectos", "education": "Educación", "languages": "Idiomas",
           "present": "Actualidad"},
}
MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "es": ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"],
}


class Grounded(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    source_ids: list[str] = Field(min_length=1, description="IDs del perfil que respaldan el texto")


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    url: str


class SkillLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    items: list[str]


class Role(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str
    descriptor: str | None = None
    title: str
    start: str = Field(pattern=r"^\d{4}-\d{2}$")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    bullets: list[Grounded]


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    text: str
    links: list[str] = []
    source_ids: list[str] = Field(min_length=1)


class Education(BaseModel):
    model_config = ConfigDict(extra="forbid")
    degree: str
    school: str
    years: str
    status: str | None = None


class CvDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lang: Literal["en", "es"]
    name: str
    headline: str
    contact: list[str]
    links: list[Link]
    summary: Grounded
    skills: list[SkillLine]
    experience: list[Role]
    projects: list[Project] = []
    education: list[Education]
    languages: str


def format_period(start: str, end: str | None, lang: str) -> str:
    def month(value: str) -> str:
        year, mon = value.split("-")
        return f"{MONTHS[lang][int(mon) - 1]} {year}"

    return f"{month(start)} - {month(end) if end else LABELS[lang]['present']}"


def render_html(doc: CvDocument) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"])
    )
    env.filters["period"] = lambda role: format_period(role.start, role.end, doc.lang)
    return env.get_template("cv.html.j2").render(doc=doc, labels=LABELS[doc.lang])


def find_chrome() -> str:
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        if path := shutil.which(name):
            return path
    raise RuntimeError("No encontré Chrome ni Chromium para generar el PDF.")


def page_count(pdf: Path) -> int:
    data = pdf.read_bytes()
    return len(re.findall(rb"/Type\s*/Page(?!s)", data))


def render_pdf(doc: CvDocument, out: Path) -> int:
    """Genera el PDF y devuelve la cantidad de páginas."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / "cv.html"
        html.write_text(render_html(doc), encoding="utf-8")
        subprocess.run(
            [find_chrome(), "--headless", "--disable-gpu", "--no-pdf-header-footer",
             f"--user-data-dir={tmp}/profile", f"--print-to-pdf={out.resolve()}",
             html.as_uri()],
            check=True, capture_output=True,
        )
    return page_count(out)
