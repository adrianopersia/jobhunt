"""El perfil de ejemplo versionado tiene que seguir siendo válido para el verificador."""

from pathlib import Path

import yaml

from jobhunt.cv import CvDocument
from jobhunt.grounding import check

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "profile.example.yaml"


def test_un_cv_armado_desde_el_ejemplo_pasa_la_verificacion():
    profile = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    person = profile["person"]
    acme, austral = profile["experience"]
    doc = CvDocument.model_validate({
        "lang": "en",
        "name": person["name"],
        "headline": profile["headlines"]["fullstack"]["en"],
        "contact": [person["email"], person["location"]["en"]],
        "links": person["links"],
        "summary": {"text": "Developer with 4+ years of professional experience, currently at "
                            "Acme Logística, a freight-tracking SaaS.",
                    "source_ids": ["f-years", "f-acme"]},
        "skills": [{"label": "Backend", "items": ["Node.js", "TypeScript", "WebSockets"]}],
        "experience": [
            {"company": acme["company"], "descriptor": acme["descriptor"]["en"],
             "title": acme["title"]["en"], "start": acme["start"],
             "bullets": [{"text": acme["achievements"][0]["en"], "source_ids": ["acme-tracking"]}]},
            {"company": austral["company"], "title": austral["title"]["en"],
             "start": austral["start"], "end": austral["end"],
             "bullets": [{"text": austral["achievements"][0]["en"], "source_ids": ["aus-shop"]}]},
        ],
        "education": [{"degree": profile["education"][0]["degree"]["en"],
                       "school": profile["education"][0]["school"], "years": "2018 - 2022"}],
        "languages": profile["languages"]["en"],
    })
    report = check(doc, profile)
    assert report.ok, report.errors
