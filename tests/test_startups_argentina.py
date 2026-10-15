"""HTML sintético con la misma estructura que el sitio. No se versionan páginas reales."""

import json

from jobhunt.sources.startups_argentina import parse_detail, parse_listing

LISTING = """
<main>
  <p>Página 1 de 3</p>
  <div class="grid">
    <article class="card">
      <div class="startup-logo"><span>A</span></div>
      <h2><a href="/empleos/acme/1111-aaaa/ai-engineer">AI Engineer</a></h2>
      <p><a href="/startups/acme">Acme</a></p>
      <span>Argentina · remote</span>
    </article>
    <article class="card">
      <h2><a href="/empleos/beta/2222-bbbb/backend-dev">Backend Dev</a></h2>
      <p><a href="/startups/beta">Beta</a></p>
    </article>
    <article class="card"><h2><a href="/startups/gamma">No es un aviso</a></h2></article>
  </div>
</main>
"""

LD = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "AI Engineer",
    "description": "truncada",
    "datePosted": "2026-10-10T16:25:54+00:00",
    "employmentType": "FULL_TIME",
    "jobLocationType": "TELECOMMUTE",
    "applicantLocationRequirements": [{"@type": "Country", "name": "Argentina"}],
}

DETAIL = f"""
<script type="application/ld+json">{json.dumps(LD)}</script>
<main>
  <dl>
    <dt>Ubicación</dt><dd>Argentina</dd>
    <dt>Modalidad</dt><dd>remote</dd>
    <dt>Tipo</dt><dd>Full-time</dd>
  </dl>
  <a href="/guardar">Guardar</a>
  <a href="https://jobs.lever.co/acme/xyz/apply?utm_source=sa">Aplicar</a>
  <div class="job-description"><p>Descripción completa.</p><ul><li>Python</li></ul></div>
</main>
"""


def test_listado_extrae_avisos_y_total_de_paginas():
    stubs, total = parse_listing(LISTING)
    assert total == 3
    assert [s.title for s in stubs] == ["AI Engineer", "Backend Dev"]
    first = stubs[0]
    assert first.id == "startups_argentina:1111-aaaa"
    assert first.company == "Acme"
    assert first.location == "Argentina · remote"
    assert first.url == "https://www.startupsargentina.com/empleos/acme/1111-aaaa/ai-engineer"
    assert stubs[1].location == ""


def test_detalle_prefiere_la_descripcion_completa_del_html():
    detail = parse_detail(DETAIL)
    assert detail.description == "Descripción completa.\nPython"
    assert detail.apply_url.startswith("https://jobs.lever.co/acme/xyz/apply")
    assert detail.posted_at == "2026-10-10T16:25:54+00:00"
    assert detail.modality_raw == "remote"
    assert detail.location_raw == "Argentina"
    assert detail.location_requirements == ["Argentina"]


def test_detalle_sin_html_de_descripcion_usa_el_json_ld():
    detail = parse_detail(DETAIL.replace('class="job-description"', 'class="otra"'))
    assert detail.description == "truncada"
