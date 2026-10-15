"""Formularios sintéticos con la estructura de cada sistema."""

import json

from jobhunt.forms import outbound_apply_link, parse_greenhouse, parse_html_form, parse_tally

GREENHOUSE = {
    "questions": [
        {"label": "Email", "required": True, "fields": [{"name": "email", "type": "input_text", "values": []}]},
        {"label": "Resume/CV", "required": True,
         "fields": [{"name": "resume", "type": "input_file"}, {"name": "resume_text", "type": "textarea"}]},
        {"label": "English level?", "required": True, "fields": [{
            "name": "question_1", "type": "multi_value_single_select",
            "values": [{"label": "B2", "value": 1}, {"label": "C1", "value": 2}]}]},
    ],
    "location_questions": [
        {"label": "Latitude", "required": True, "fields": [{"name": "latitude", "type": "input_hidden"}]},
    ],
    "demographic_questions": {"questions": []},
    "include_ai_disclaimer": True,
}


def test_greenhouse_normaliza_tipos_y_opciones():
    form = parse_greenhouse(GREENHOUSE, "u")
    assert [(f.id, f.type) for f in form.fields] == [
        ("email", "email"), ("resume", "file"), ("question_1", "single_select")]
    assert form.fields[2].options == ["B2", "C1"]
    assert any("IA" in n for n in form.notes)


def _tally(blocks):
    data = {"props": {"pageProps": {"blocks": blocks}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def test_tally_agrupa_opciones_y_toma_el_titulo_previo():
    html = _tally([
        {"type": "FORM_TITLE", "payload": {}},
        {"type": "TITLE", "payload": {"safeHTMLSchema": [["¿Qué usás?", [["tag", "span"]]]]}},
        {"type": "MULTI_SELECT_OPTION", "groupUuid": "g1", "payload": {"text": "React", "isRequired": True}},
        {"type": "MULTI_SELECT_OPTION", "groupUuid": "g1", "payload": {"text": "Redis", "isRequired": True}},
        {"type": "HEADING_3", "payload": {"safeHTMLSchema": [["WhatsApp"]]}},
        {"type": "INPUT_PHONE_NUMBER", "groupUuid": "g2", "payload": {"isRequired": False}},
        {"type": "FILE_UPLOAD", "groupUuid": "g3", "payload": {"isRequired": True}},
    ])
    form = parse_tally(html, "u")
    assert [(f.label, f.type, f.required) for f in form.fields] == [
        ("¿Qué usás?", "multi_select", True), ("WhatsApp", "phone", False),
        ("(sin título)", "file", True)]
    assert form.fields[0].options == ["React", "Redis"]


def test_html_generico_con_labels_radios_y_requeridos():
    html = """
    <form>
      <input type="hidden" name="token">
      <label for="n">Full name *</label><input id="n" name="name">
      <input type="email" name="email" required placeholder="Email">
      <div class="application-question"><div class="application-label">Remote?</div>
        <label><input type="radio" name="remote" value="y"> Yes</label>
        <label><input type="radio" name="remote" value="n"> No</label></div>
      <input type="file" name="resume" aria-required="true" aria-label="Resume">
    </form>"""
    form = parse_html_form(html, "u", "x")
    assert [(f.label, f.type, f.required) for f in form.fields] == [
        ("Full name", "text", True), ("Email", "email", True),
        ("Remote?", "single_select", False), ("Resume", "file", True)]
    assert form.fields[2].options == ["Yes", "No"]


def test_sin_formulario_no_es_legible():
    assert parse_html_form("<div id=root></div>", "u", "x").extractable is False


def test_link_de_postulacion_que_sale_del_agregador():
    html = """<a href="/remote-jobs">Más avisos</a>
              <a href="https://weworkremotely.com/x">Apply later</a>
              <a class="apply-btn" href="https://jobs.lever.co/acme/123">Apply for this position</a>"""
    assert outbound_apply_link(html, "weworkremotely.com") == "https://jobs.lever.co/acme/123"
    assert outbound_apply_link("<a href='/apply'>Apply</a>", "himalayas.app") is None
