"""Candidato y empresas ficticias: este archivo se versiona."""

import copy

import pytest

from jobhunt.cv import CvDocument
from jobhunt.grounding import check, normalize_numbers

PROFILE = {
    "person": {
        "name": "Ana Ejemplo",
        "email": "ana@example.com",
        "phone": "+54 9 341 000-0000",
        "location": {"en": "Rosario, Argentina", "es": "Rosario, Argentina"},
        "links": [{"label": "github.com/ana", "url": "https://github.com/ana"}],
    },
    "facts": [
        {"id": "f-team", "en": "5-person team", "es": "equipo de 5", "use": "cv"},
        {"id": "f-users", "en": "over 2,000 users", "es": "más de 2.000 usuarios", "use": "pending"},
        {"id": "f-years", "en": "4+ years of experience", "es": "más de 4 años", "use": "cv",
         "requires_companies": ["Gamma"]},
    ],
    "experience": [
        {
            "id": "exp-acme", "company": "Acme", "title": {"en": "Developer", "es": "Desarrolladora"},
            "start": "2023-01", "end": None,
            "achievements": [
                {"id": "acme-prs", "en": "Authored 120 of 300 PRs (40%).", "es": "Autora de 120 de 300 PRs (40%).", "use": "cv"},
                {"id": "acme-agents", "en": "Built the coding-agent setup for 3 repos.", "es": "Armé la configuración de agentes de 3 repos.", "use": "cv"},
                {"id": "acme-bench", "en": "Designed a model benchmark.", "es": "Diseñé un benchmark.", "use": "interview"},
            ],
        },
        {
            "id": "exp-beta", "company": "Beta", "title": {"en": "Intern", "es": "Pasante"},
            "start": "2022-01", "end": "2022-06", "status": "pending_confirmation",
            "achievements": [{"id": "beta-x", "en": "Did things.", "es": "Hice cosas.", "use": "cv"}],
        },
    ],
    "projects": [
        {"id": "prj-site", "title": {"en": "Site", "es": "Sitio"}, "en": "(Astro): a site.", "es": "(Astro): un sitio.", "use": "cv"},
    ],
    "skills": {"backend": ["TypeScript", "WebSockets (Socket.IO)"], "ai": ["Claude Code (skills, subagents)"]},
    "headlines": {"main": {"en": "Software Engineer", "es": "Ingeniera de Software"}},
    "education": [{"degree": {"en": "BSc", "es": "Licenciatura"}, "school": "Uni", "years": "2018 - 2022"}],
    "languages": {"en": "Spanish (native)", "es": "Español (nativo)"},
}

BASE = {
    "lang": "en",
    "name": "Ana Ejemplo",
    "headline": "Software Engineer",
    "contact": ["ana@example.com", "Rosario, Argentina"],
    "links": [{"label": "github.com/ana", "url": "https://github.com/ana"}],
    "summary": {"text": "Developer on a 5-person team.", "source_ids": ["f-team"]},
    "skills": [{"label": "Backend", "items": ["TypeScript", "WebSockets", "Claude Code"]}],
    "experience": [{
        "company": "Acme", "title": "Developer", "start": "2023-01", "end": None,
        "bullets": [
            {"text": "Wrote 120 of the 300 merged PRs (40%).", "source_ids": ["acme-prs"]},
            {"text": "Set up coding agents across 3 repositories.", "source_ids": ["acme-agents"]},
        ],
    }],
    "projects": [{"title": "Site", "text": "(Astro): a site.", "source_ids": ["prj-site"]}],
    "education": [{"degree": "BSc", "school": "Uni", "years": "2018 - 2022"}],
    "languages": "Spanish (native)",
}


def doc(**changes):
    data = copy.deepcopy(BASE)
    for path, value in changes.items():
        target = data
        *parents, leaf = path.split("__")
        for key in parents:
            target = target[int(key)] if key.isdigit() else target[key]
        target[int(leaf) if leaf.isdigit() else leaf] = value
    return CvDocument.model_validate(data)


def errors(**changes):
    return check(doc(**changes), PROFILE).errors


def test_cv_fiel_pasa():
    report = check(doc(), PROFILE)
    assert report.ok, report.errors


def test_normaliza_separadores_de_miles():
    assert normalize_numbers("4,515 y 4.515 y 4515") == {"4515"}


def test_numero_inventado_falla():
    errs = errors(experience__0__bullets__0__text="Wrote 150 of the 300 merged PRs (50%).")
    assert any("150" in e and "50" in e for e in errs)


@pytest.mark.parametrize("source_id,motivo", [
    ("no-existe", "no existe"),
    ("acme-bench", "solo para entrevista"),
    ("f-users", "no está confirmado"),
])
def test_fuentes_no_usables(source_id, motivo):
    errs = errors(experience__0__bullets__1__source_ids=[source_id])
    assert any(motivo in e for e in errs)


def test_logro_bajo_otro_empleador_falla():
    data = copy.deepcopy(BASE)
    data["experience"].append({
        "company": "Beta", "title": "Intern", "start": "2022-01", "end": "2022-06",
        "bullets": [{"text": "Set up coding agents across 3 repositories.", "source_ids": ["acme-agents"]}],
    })
    errs = check(CvDocument.model_validate(data), PROFILE).errors
    assert any("es de Acme, no de Beta" in e for e in errs)
    assert any("Beta: experiencia sin confirmar" in e for e in errs)


def test_titulo_y_fechas_tienen_que_coincidir():
    assert any("título" in e for e in errors(experience__0__title="Senior Developer"))
    assert any("fechas" in e for e in errors(experience__0__start="2022-01"))


def test_skill_inventada_falla():
    errs = errors(skills__0__items=["TypeScript", "Kubernetes"])
    assert errs == ["skill que no está en el perfil: 'Kubernetes'"]


def test_contacto_ajeno_falla():
    assert any("contacto" in e for e in errors(contact=["otra@example.com"]))


def test_multiplicador_de_productividad_falla():
    errs = errors(summary__text="Developer on a 5-person team who ships 2x faster with AI.")
    assert any("multiplicador" in e for e in errs)


def test_resumen_con_numero_sin_fuente_falla():
    errs = errors(summary__text="Developer with 4 years on a 5-person team.")
    assert any("resumen" in e and "4" in e for e in errs)


def test_hecho_que_exige_un_empleador_ausente_falla():
    errs = errors(summary__text="Developer with 4+ years on a 5-person team.",
                  summary__source_ids=["f-team", "f-years"])
    assert any("f-years" in e and "Gamma" in e for e in errs)


def test_titular_inventado_falla():
    assert any("titular" in e for e in errors(headline="Senior AI Engineer"))


def test_educacion_e_idiomas_tienen_que_coincidir():
    assert any("educación" in e for e in errors(education__0__degree="MSc"))
    assert any("idiomas" in e for e in errors(languages="Spanish (native), English (C2)"))
