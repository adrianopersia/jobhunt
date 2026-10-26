"""Respuestas propuestas para un formulario de postulación, y su verificación.

El revisor (LLM) propone una acción por campo; esto controla lo que se puede controlar con
código: que no falte ningún campo obligatorio, que las opciones existan, que los números y las
tecnologías estén respaldados por el perfil, y que los datos de contacto sean los reales.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobhunt.forms import ApplicationForm
from jobhunt.grounding import ProfileIndex, normalize_numbers
from jobhunt.keywords import mentions, profile_text

Action = Literal["answer", "attach_cv", "candidate_decides", "skip_optional"]


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_id: str
    action: Action = Field(description=(
        "answer: respuesta propuesta. attach_cv: adjuntar el PDF de la carpeta. "
        "candidate_decides: lo decide o lo provee el candidato (salario, fecha, video). "
        "skip_optional: campo opcional que conviene dejar vacío."))
    value: str | list[str] | None = None
    source_ids: list[str] = Field(default=[], description="IDs del perfil que respaldan la respuesta")
    suggested: str | None = Field(
        default=None, description="Valor recomendado cuando decide el candidato (ej. salario)")
    note: str = Field(default="", description="Para el candidato: contexto o sugerencia")


class AnswerSheet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    answers: list[Answer]


def _dial(phone: str) -> str:
    """Los formularios piden el teléfono en formatos distintos; lo que tiene que coincidir es el número."""
    return re.sub(r"[^\d+]", "", phone)


def _text(node) -> str:
    if isinstance(node, dict):
        return " ".join(_text(v) for v in node.values())
    if isinstance(node, list):
        return " ".join(_text(v) for v in node)
    return str(node)


def check_answers(form: ApplicationForm, sheet: AnswerSheet, profile: dict) -> list[str]:
    errors: list[str] = []
    idx = ProfileIndex(profile)
    supported = profile_text(profile)
    person = profile["person"]
    fields = {f.id: f for f in form.fields}
    by_field: dict[str, Answer] = {}

    for answer in sheet.answers:
        if answer.field_id not in fields:
            errors.append(f"respuesta para un campo que no existe: {answer.field_id!r}")
        elif answer.field_id in by_field:
            errors.append(f"campo respondido dos veces: {answer.field_id!r}")
        by_field[answer.field_id] = answer

    for field in form.fields:
        answer = by_field.get(field.id)
        where = f"{field.label!r}"
        if answer is None:
            errors.append(f"{where}: sin respuesta ni acción")
            continue
        if field.required and answer.action == "skip_optional":
            errors.append(f"{where}: es obligatorio y quedó como opcional")
        if answer.action == "attach_cv" and field.type != "file":
            errors.append(f"{where}: attach_cv en un campo que no es de archivo")
        if answer.action != "answer":
            continue

        if answer.value in (None, "", []):
            errors.append(f"{where}: action=answer sin valor")
            continue
        values = answer.value if isinstance(answer.value, list) else [answer.value]

        for i in answer.source_ids:
            item = idx.items.get(i)
            if item is None and not i.startswith(("skills.", "education", "languages", "person")):
                errors.append(f"{where}: cita '{i}', que no existe en el perfil")
            elif item is not None and item.get("use") not in ("cv", "interview"):
                errors.append(f"{where}: cita '{i}', que no está confirmado")

        if field.type in ("single_select", "multi_select"):
            if field.type == "single_select" and len(values) != 1:
                errors.append(f"{where}: selección única con {len(values)} valores")
            for value in values:
                if field.options and value not in field.options:
                    errors.append(f"{where}: la opción {value!r} no existe en el formulario")
            if field.type == "multi_select":
                cited = idx.source_text(answer.source_ids)
                for value in values:
                    if not (mentions(supported, value) or mentions(cited, value)):
                        errors.append(f"{where}: marcó {value!r}, que el perfil no respalda")

        if field.type in ("text", "textarea", "number"):
            text = " ".join(values)
            length = len(text.strip())
            if field.min_length and length < field.min_length:
                errors.append(f"{where}: tiene {length} caracteres y el mínimo es {field.min_length}")
            if field.max_length and length > field.max_length:
                errors.append(f"{where}: tiene {length} caracteres y el máximo es {field.max_length}")
            allowed = normalize_numbers(idx.source_text(answer.source_ids))
            allowed |= normalize_numbers(" ".join(str(v) for v in person.values() if isinstance(v, str)))
            allowed |= normalize_numbers(" ".join((profile.get("languages") or {}).values()))
            allowed |= normalize_numbers(_text(profile.get("education", [])))
            extra = normalize_numbers(text) - allowed
            if field.type in ("text", "textarea") and extra:
                errors.append(f"{where}: números sin respaldo en las fuentes citadas: {sorted(extra)}")
            if field.type == "number":
                errors.append(f"{where}: un número lo decide el candidato (usar candidate_decides)")

        if field.type == "email" and values[0] != person["email"]:
            errors.append(f"{where}: el email no es el del perfil")
        if field.type == "phone" and _dial(values[0]) != _dial(person["phone"]):
            errors.append(f"{where}: el teléfono no es el del perfil")
    return errors
