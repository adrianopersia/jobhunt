from pathlib import Path

import yaml

from jobhunt.profile import validate

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "profile.example.yaml"


def test_el_ejemplo_es_valido():
    assert validate(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))) == []


def test_detecta_lista_en_linea_partida():
    profile = yaml.safe_load("skills:\n  tools: [Git, Firebase (Messaging, Crashlytics), Jira]\n")
    errors = validate(profile)
    assert len(errors) == 2
    assert all("mal formado" in e for e in errors)


def test_detecta_ids_repetidos_use_invalido_y_textos_faltantes():
    profile = {
        "facts": [{"id": "a", "en": "x", "es": "x", "use": "cv"}, {"id": "a", "en": "y", "use": "maybe"}],
    }
    errors = validate(profile)
    assert any("repetidos" in e for e in errors)
    assert any("use inválido" in e for e in errors)
    assert any("'es'" in e for e in errors)


def test_requires_companies_tiene_que_existir():
    profile = {"facts": [{"id": "f", "en": "x", "es": "x", "use": "cv", "requires_companies": ["Nadie"]}],
               "experience": []}
    assert any("Nadie" in e for e in validate(profile))
