"""Cobertura de keywords al estilo de un ATS: qué términos del aviso aparecen en el CV.

Separa tres grupos, porque la acción es distinta en cada uno:
- presentes: ya están en el CV;
- faltan pero las tenés: el perfil las respalda y el CV no las nombra → agregarlas;
- faltan y no las tenés: hueco real → no se agregan nunca (para eso está la entrevista).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Variantes que un ATS suele tratar como el mismo término.
ALIASES = {
    "node.js": ["node.js", "nodejs", "node"],
    "next.js": ["next.js", "nextjs"],
    "typescript": ["typescript"],
    "javascript": ["javascript"],
    "postgresql": ["postgresql", "postgres"],
    "react": ["react"],
    "react native": ["react native"],
    "rest apis": ["rest api", "rest apis", "restful"],
    "ci/cd": ["ci/cd"],
    "llm": ["llm", "llms"],
    "golang": ["golang", "go"],
    "tailwindcss": ["tailwindcss", "tailwind"],
    "github actions": ["github actions"],
}


def variants(term: str) -> list[str]:
    key = term.strip().lower()
    for canonical, names in ALIASES.items():
        if key == canonical or key in names:
            return names
    return [key]


def mentions(text: str, term: str) -> bool:
    lowered = text.lower()
    for name in variants(term):
        if re.search(rf"(?<![\w.]){re.escape(name)}(?![\w])", lowered):
            return True
    return False


@dataclass
class Coverage:
    present: list[str]
    missing_supported: list[str]
    missing_gap: list[str]

    @property
    def score(self) -> str:
        total = len(self.present) + len(self.missing_supported) + len(self.missing_gap)
        return f"{len(self.present)}/{total}"


def profile_text(profile: dict) -> str:
    parts = [s for items in profile.get("skills", {}).values() for s in items]
    for exp in profile.get("experience", []):
        for item in exp.get("achievements", []):
            if item.get("use") == "cv":
                parts += [item.get("en", ""), item.get("es", "")]
    return "\n".join(parts)


def posting_terms(stack: list[str], description: str, profile: dict) -> list[str]:
    """El stack que extrajo el scout, más las skills del perfil que el aviso nombra."""
    terms = {t.strip(): None for t in stack if t.strip()}
    for items in profile.get("skills", {}).values():
        for skill in items:
            base = skill.split(" (")[0]
            if len(base) > 2 and mentions(description, base) and not any(
                mentions(t, base) or mentions(base, t) for t in terms
            ):
                terms[base] = None
    return list(terms)


def coverage(terms: list[str], cv_text: str, profile: dict) -> Coverage:
    supported_text = profile_text(profile)
    present, supported, gap = [], [], []
    for term in terms:
        if mentions(cv_text, term):
            present.append(term)
        elif mentions(supported_text, term):
            supported.append(term)
        else:
            gap.append(term)
    return Coverage(present, supported, gap)
