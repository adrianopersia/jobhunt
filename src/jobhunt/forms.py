"""Lectura de formularios de postulación, sin navegador y sin enviar nada.

Cada sistema se normaliza a `ApplicationForm`: una lista de campos con tipo, obligatoriedad y
opciones. Si un formulario no se puede leer así, queda `extractable=False` y el revisor lo
marca para completar a mano.
"""

from __future__ import annotations

import json
import re
from typing import Literal
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel

from jobhunt.ats import clean_url
from jobhunt.http import PoliteClient
from jobhunt.policy import detect_ats

FieldType = Literal[
    "text", "textarea", "email", "phone", "number", "date", "link",
    "single_select", "multi_select", "file", "other",
]


class FormField(BaseModel):
    id: str
    label: str
    type: FieldType
    required: bool
    options: list[str] = []
    help: str = ""


class ApplicationForm(BaseModel):
    url: str
    system: str
    extractable: bool
    fields: list[FormField] = []
    notes: list[str] = []


# ---------- Greenhouse: API pública del board ----------

_GH_TYPES = {
    "input_text": "text", "textarea": "textarea", "input_file": "file",
    "multi_value_single_select": "single_select", "multi_value_multi_select": "multi_select",
}


def parse_greenhouse(data: dict, url: str) -> ApplicationForm:
    fields = []
    for n, q in enumerate(data.get("questions", []) + data.get("location_questions", [])):
        visible = [f for f in q.get("fields", []) if f.get("type") != "input_hidden"]
        if not visible:
            continue
        first = visible[0]
        label = (q.get("label") or "").strip()
        kind = _GH_TYPES.get(first.get("type"), "other")
        if kind == "text" and "email" in label.lower():
            kind = "email"
        elif kind == "text" and "phone" in label.lower():
            kind = "phone"
        fields.append(FormField(
            id=first.get("name") or f"q{n}", label=label, type=kind,
            required=bool(q.get("required")),
            options=[v["label"] for v in first.get("values", [])],
            help=BeautifulSoup(q.get("description") or "", "html.parser").get_text(" ", strip=True),
        ))
    notes = []
    if data.get("demographic_questions"):
        notes.append("Tiene preguntas demográficas voluntarias: las responde el candidato si quiere.")
    if data.get("include_ai_disclaimer"):
        notes.append("La empresa avisa que usa IA para evaluar postulaciones.")
    return ApplicationForm(url=url, system="greenhouse", extractable=True, fields=fields, notes=notes)


def fetch_greenhouse(client: PoliteClient, url: str) -> ApplicationForm:
    match = re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)", url)
    if not match:
        return ApplicationForm(url=url, system="greenhouse", extractable=False,
                               notes=["No se reconoció la URL de Greenhouse."])
    board, job = match.groups()
    data = client.get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job}?questions=true")
    return parse_greenhouse(data, url)


# ---------- Tally: el formulario viene como JSON en __NEXT_DATA__ ----------

_STYLE_KEYS = {"tag", "font-weight", "font-style", "href", "color", "text-decoration",
               "background-color", "target", "rel", "class"}
_TALLY_INPUTS = {
    "INPUT_TEXT": "text", "TEXTAREA": "textarea", "INPUT_EMAIL": "email",
    "INPUT_PHONE_NUMBER": "phone", "INPUT_NUMBER": "number", "INPUT_DATE": "date",
    "INPUT_LINK": "link", "FILE_UPLOAD": "file",
}
_TALLY_OPTIONS = {
    "MULTI_SELECT_OPTION": "multi_select", "CHECKBOX": "multi_select",
    "MULTIPLE_CHOICE_OPTION": "single_select", "DROPDOWN_OPTION": "single_select",
}


def _tally_text(node) -> str:
    parts: list[str] = []

    def walk(n):
        if isinstance(n, str):
            parts.append(n)
        elif isinstance(n, list):
            if len(n) == 2 and isinstance(n[0], str) and n[0] in _STYLE_KEYS:
                return
            for child in n:
                walk(child)

    walk(node)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def parse_tally(html: str, url: str) -> ApplicationForm:
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        return ApplicationForm(url=url, system="tally", extractable=False,
                               notes=["La página no trae el formulario embebido."])
    blocks = json.loads(match.group(1))["props"]["pageProps"].get("blocks", [])
    fields: list[FormField] = []
    groups: dict[str, FormField] = {}
    last_title = ""
    for block in blocks:
        kind, payload = block.get("type", ""), block.get("payload") or {}
        if kind in ("TITLE", "HEADING_3"):
            last_title = _tally_text(payload.get("safeHTMLSchema"))
        elif kind in ("HEADING_1", "HEADING_2", "FORM_TITLE"):
            last_title = ""
        elif kind in _TALLY_INPUTS:
            fields.append(FormField(
                id=block.get("groupUuid") or block.get("uuid", ""),
                label=last_title or payload.get("placeholder") or "(sin título)",
                type=_TALLY_INPUTS[kind], required=bool(payload.get("isRequired")),
                help=payload.get("placeholder") or "",
            ))
            last_title = ""
        elif kind in _TALLY_OPTIONS:
            group = block.get("groupUuid", "")
            if group not in groups:
                groups[group] = FormField(
                    id=group, label=last_title or "(sin título)", type=_TALLY_OPTIONS[kind],
                    required=bool(payload.get("isRequired")),
                )
                fields.append(groups[group])
                last_title = ""
            if payload.get("text"):
                groups[group].options.append(payload["text"].strip())
    return ApplicationForm(url=url, system="tally", extractable=True, fields=fields)


# ---------- HTML genérico (PeopleForce, Lever y formularios simples) ----------

def _label_for(control: Tag, soup: BeautifulSoup) -> str:
    if control.get("id"):
        label = soup.find("label", attrs={"for": control["id"]})
        if label:
            return label.get_text(" ", strip=True)
    wrapper = control.find_parent("label")
    if wrapper:
        return wrapper.get_text(" ", strip=True)
    question = control.find_parent(class_=re.compile("question|field|form-group", re.I))
    if question:
        label = question.find(class_=re.compile("label", re.I)) or question.find("label")
        if label:
            return label.get_text(" ", strip=True)
    return control.get("placeholder") or control.get("aria-label") or control.get("name", "")


def parse_html_form(html: str, url: str, system: str) -> ApplicationForm:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if not form:
        return ApplicationForm(url=url, system=system, extractable=False,
                               notes=["No hay un formulario en el HTML (probablemente se arma con JavaScript)."])
    fields: list[FormField] = []
    choices: dict[str, FormField] = {}
    for control in form.find_all(["input", "textarea", "select"]):
        ctype = (control.get("type") or control.name).lower()
        name = control.get("name") or control.get("id") or ""
        if ctype in {"hidden", "submit", "button", "reset"} or not name:
            continue
        required = control.has_attr("required") or control.get("aria-required") == "true"
        if ctype in {"radio", "checkbox"}:
            group_label = control.find_parent(class_=re.compile("question|field|form-group", re.I))
            title = group_label.find(class_=re.compile("label", re.I)) if group_label else None
            if name not in choices:
                choices[name] = FormField(
                    id=name, label=title.get_text(" ", strip=True) if title else name,
                    type="single_select" if ctype == "radio" else "multi_select", required=required,
                )
                fields.append(choices[name])
            option = _label_for(control, soup) or control.get("value", "")
            choices[name].options.append(option)
            choices[name].required |= required
            continue
        kind = {"textarea": "textarea", "select": "single_select", "file": "file", "email": "email",
                "tel": "phone", "number": "number", "date": "date", "url": "link"}.get(ctype, "text")
        label = _label_for(control, soup)
        if label.endswith("*"):
            required, label = True, label.rstrip("* ").strip()
        options = [o.get_text(strip=True) for o in control.find_all("option") if o.get("value")]
        fields.append(FormField(id=name, label=label, type=kind, required=required, options=options))
    return ApplicationForm(url=url, system=system, extractable=bool(fields), fields=fields)


# ---------- entrada ----------

def fetch_form(client: PoliteClient, apply_url: str) -> ApplicationForm:
    url = clean_url(apply_url)
    ats = detect_ats(url)
    host = urlparse(url).netloc
    if ats == "greenhouse":
        return fetch_greenhouse(client, url)
    if host.endswith("tally.so"):
        return parse_tally(client.get_text(url), url)
    if ats == "lever" and not url.rstrip("/").endswith("/apply"):
        url = url.rstrip("/") + "/apply"
    if ats in {"ashby", "workable", "linkedin", "google_forms", "workday"}:
        return ApplicationForm(url=url, system=ats, extractable=False,
                               notes=[f"{ats}: el formulario se arma en el navegador; revisarlo a mano."])
    return parse_html_form(client.get_text(url), url, ats if ats != "other" else host)
