"""Validación estructural del perfil. Atrapa errores de formato que de otro modo pasan en
silencio, como una lista YAML en línea que parte "Firebase (A, B)" en tres items."""

from __future__ import annotations

USES = {"cv", "interview", "pending"}


def validate(profile: dict) -> list[str]:
    errors: list[str] = []
    ids: list[str] = []

    for category, items in (profile.get("skills") or {}).items():
        for skill in items or []:
            if not isinstance(skill, str) or skill.count("(") != skill.count(")"):
                errors.append(f"skills.{category}: item mal formado {skill!r} (¿lista en línea con comas?)")

    groups = [("facts", profile.get("facts") or []), ("projects", profile.get("projects") or [])]
    for exp in profile.get("experience") or []:
        groups.append((f"experience[{exp.get('company')}]", exp.get("achievements") or []))
    for where, items in groups:
        for item in items:
            ids.append(item.get("id", "?"))
            if item.get("use") not in USES:
                errors.append(f"{where}/{item.get('id')}: use inválido {item.get('use')!r}")
            for lang in ("en", "es"):
                if not item.get(lang):
                    errors.append(f"{where}/{item.get('id')}: falta el texto en '{lang}'")

    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        errors.append(f"IDs repetidos: {duplicated}")

    companies = {e.get("company") for e in profile.get("experience") or []}
    for fact in profile.get("facts") or []:
        for company in fact.get("requires_companies") or []:
            if company not in companies:
                errors.append(f"{fact['id']}: requires_companies nombra a {company!r}, que no está en experience")
    return errors
