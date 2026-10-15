"""Verificación determinista de que un CvDocument no inventa nada respecto del perfil.

Chequea lo que se puede chequear sin un LLM:
- cada texto cita IDs que existen y se pueden usar en un CV (`use: cv`, experiencia confirmada);
- cada bullet cita logros del mismo empleador bajo el que aparece;
- cada número del texto aparece en las fuentes citadas;
- cada skill existe en el perfil;
- si un hecho exige que figuren ciertos empleadores (ej. los años de experiencia), figuran;
- los datos de contacto, el titular, la educación y los idiomas son los del perfil;
- nada de `not_claimable` aparece en el texto.

Lo que no se puede chequear así (si una frase reformulada dice algo que la fuente no dice)
queda para el eval con LLM-juez.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobhunt.cv import CvDocument

_NUMBER_RE = re.compile(r"\d[\d.,]*")


def normalize_numbers(text: str) -> set[str]:
    """'4,515', '4.515' y '4515' son el mismo número; '1.5' queda como '15' a propósito:
    alcanza con que los dígitos coincidan para atrapar números inventados."""
    return {re.sub(r"[.,]", "", m).lstrip("0") or "0" for m in _NUMBER_RE.findall(text)}


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class ProfileIndex:
    def __init__(self, profile: dict):
        self.profile = profile
        self.items: dict[str, dict] = {}
        self.owner: dict[str, str] = {}
        for exp in profile.get("experience", []):
            for item in exp.get("achievements", []):
                self.items[item["id"]] = {**item, "_pending": exp.get("status") == "pending_confirmation"}
                self.owner[item["id"]] = exp["company"]
        for item in profile.get("facts", []) + profile.get("projects", []):
            self.items[item["id"]] = {**item, "_pending": False}
        self.skills = [s for items in profile.get("skills", {}).values() for s in items]

    def source_text(self, ids: list[str]) -> str:
        parts = []
        for i in ids:
            item = self.items.get(i, {})
            parts += [item.get("en", ""), item.get("es", "")]
            title = item.get("title")
            if isinstance(title, dict):
                parts += list(title.values())
        return "\n".join(parts)

    def skill_exists(self, name: str) -> bool:
        wanted = name.strip().lower()
        for skill in self.skills:
            s = skill.lower()
            if wanted == s or wanted == s.split(" (")[0]:
                return True
        return False


def _check_sources(where: str, ids: list[str], text: str, idx: ProfileIndex, rep: Report,
                   company: str | None = None) -> None:
    for i in ids:
        item = idx.items.get(i)
        if item is None:
            rep.errors.append(f"{where}: cita '{i}', que no existe en el perfil")
            continue
        if item.get("use") == "interview":
            rep.errors.append(f"{where}: cita '{i}', que es solo para entrevista")
        elif item.get("use") != "cv":
            rep.errors.append(f"{where}: cita '{i}', que no está confirmado para usar en un CV")
        if item["_pending"]:
            rep.errors.append(f"{where}: cita '{i}', de una experiencia sin confirmar")
        if company and i in idx.owner and idx.owner[i] != company:
            rep.errors.append(f"{where}: cita '{i}', que es de {idx.owner[i]}, no de {company}")
    missing = normalize_numbers(text) - normalize_numbers(idx.source_text(ids))
    if missing:
        rep.errors.append(f"{where}: números que no están en las fuentes citadas: {sorted(missing)}")


def check(doc: CvDocument, profile: dict) -> Report:
    idx = ProfileIndex(profile)
    rep = Report()
    person = profile["person"]

    if doc.name != person["name"]:
        rep.errors.append(f"nombre distinto al del perfil: {doc.name!r}")
    for value in doc.contact:
        known = [person["email"], person["phone"], *person["location"].values()]
        if value not in known:
            rep.errors.append(f"dato de contacto que no está en el perfil: {value!r}")
    known_links = {link["url"] for link in person.get("links", [])}
    for link in doc.links:
        if link.url not in known_links:
            rep.errors.append(f"link que no está en el perfil: {link.url}")

    headlines = [h.get(doc.lang) for h in profile.get("headlines", {}).values()]
    if doc.headline not in headlines:
        rep.errors.append(f"titular que no está entre los del perfil: {doc.headline!r}")
    degrees = {(e["degree"][doc.lang], e["school"]) for e in profile.get("education", [])}
    for edu in doc.education:
        if (edu.degree, edu.school) not in degrees:
            rep.errors.append(f"educación que no está en el perfil: {edu.degree!r}")
    if doc.languages != profile.get("languages", {}).get(doc.lang):
        rep.errors.append("idiomas distintos a los del perfil")

    _check_sources("resumen", doc.summary.source_ids, doc.summary.text, idx, rep)

    experiences = {exp["company"]: exp for exp in profile.get("experience", [])}
    seen: set[str] = set()
    for role in doc.experience:
        exp = experiences.get(role.company)
        if exp is None:
            rep.errors.append(f"empleador que no está en el perfil: {role.company!r}")
        else:
            if exp.get("status") == "pending_confirmation":
                rep.errors.append(f"{role.company}: experiencia sin confirmar")
            if role.title not in exp["title"].values():
                rep.errors.append(f"{role.company}: título distinto al del perfil: {role.title!r}")
            if role.start != str(exp["start"]) or (role.end or None) != (
                str(exp["end"]) if exp.get("end") else None
            ):
                rep.errors.append(f"{role.company}: fechas distintas a las del perfil")
        for n, bullet in enumerate(role.bullets, 1):
            where = f"{role.company} bullet {n}"
            _check_sources(where, bullet.source_ids, bullet.text, idx, rep, company=role.company)
            repeated = seen.intersection(bullet.source_ids)
            if repeated:
                rep.warnings.append(f"{where}: repite fuentes ya usadas: {sorted(repeated)}")
            seen.update(bullet.source_ids)

    cited = set(doc.summary.source_ids) | {i for r in doc.experience for b in r.bullets for i in b.source_ids}
    companies = {r.company for r in doc.experience}
    for i in sorted(cited):
        missing_roles = set(idx.items.get(i, {}).get("requires_companies", [])) - companies
        if missing_roles:
            rep.errors.append(
                f"'{i}' necesita que el CV muestre a {sorted(missing_roles)}: si no, las fechas no lo respaldan"
            )

    for project in doc.projects:
        _check_sources(f"proyecto {project.title!r}", project.source_ids,
                       f"{project.title} {project.text}", idx, rep)

    for line in doc.skills:
        for skill in line.items:
            if not idx.skill_exists(skill):
                rep.errors.append(f"skill que no está en el perfil: {skill!r}")

    full_text = " ".join(
        [doc.headline, doc.summary.text]
        + [b.text for r in doc.experience for b in r.bullets]
        + [p.text for p in doc.projects]
    ).lower()
    if re.search(r"\b\d+(?:[.,]\d+)?\s*x\b", full_text):
        rep.errors.append("hay un multiplicador de productividad ('2x', '3.4x'); está en not_claimable")

    return rep
