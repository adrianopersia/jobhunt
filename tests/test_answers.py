from jobhunt.answers import AnswerSheet, check_answers
from jobhunt.forms import ApplicationForm, FormField

PROFILE = {
    "person": {"name": "Ana Ejemplo", "email": "ana@example.com", "phone": "+54 9 341 000-0000"},
    "facts": [{"id": "f-years", "en": "4+ years of experience", "es": "más de 4 años", "use": "cv"}],
    "experience": [{"company": "Acme", "achievements": [
        {"id": "acme-x", "en": "Built 3 services in Node.js.", "es": "Construí 3 servicios en Node.js.", "use": "cv"},
    ]}],
    "skills": {"backend": ["Node.js", "PostgreSQL"]},
    "languages": {"en": "Spanish (native) | English (B2)", "es": "Español (nativo) | Inglés (B2)"},
}

FORM = ApplicationForm(url="u", system="x", extractable=True, fields=[
    FormField(id="email", label="Email", type="email", required=True),
    FormField(id="cv", label="CV", type="file", required=True),
    FormField(id="stack", label="Stack", type="multi_select", required=True,
              options=["Node.js", "PostgreSQL", "Redis"]),
    FormField(id="about", label="About you", type="textarea", required=True),
    FormField(id="salary", label="Salary", type="number", required=True),
    FormField(id="video", label="Video", type="link", required=False),
    FormField(id="eng", label="English", type="single_select", required=True, options=["B2", "C1"]),
])


def sheet(**overrides):
    answers = {
        "email": {"action": "answer", "value": "ana@example.com"},
        "cv": {"action": "attach_cv"},
        "stack": {"action": "answer", "value": ["Node.js", "PostgreSQL"]},
        "about": {"action": "answer", "value": "Developer with 4+ years; built 3 services.",
                  "source_ids": ["f-years", "acme-x"]},
        "salary": {"action": "candidate_decides", "note": "Definí el número."},
        "video": {"action": "skip_optional"},
        "eng": {"action": "answer", "value": "C1"},
    }
    answers.update(overrides)
    return AnswerSheet.model_validate({"job_id": "j", "answers": [
        {"field_id": k, **v} for k, v in answers.items() if v is not None]})


def test_hoja_correcta_pasa():
    assert check_answers(FORM, sheet(), PROFILE) == []


def test_falta_campo_obligatorio():
    assert any("sin respuesta" in e for e in check_answers(FORM, sheet(eng=None), PROFILE))


def test_obligatorio_no_se_saltea():
    errs = check_answers(FORM, sheet(eng={"action": "skip_optional"}), PROFILE)
    assert any("obligatorio" in e for e in errs)


def test_tecnologia_sin_respaldo_en_multiselect():
    errs = check_answers(FORM, sheet(stack={"action": "answer", "value": ["Node.js", "Redis"]}), PROFILE)
    assert errs == ["'Stack': marcó 'Redis', que el perfil no respalda"]


def test_opcion_inexistente():
    errs = check_answers(FORM, sheet(eng={"action": "answer", "value": "Fluent"}), PROFILE)
    assert any("no existe en el formulario" in e for e in errs)


def test_numero_inventado_en_texto_libre():
    errs = check_answers(FORM, sheet(about={"action": "answer", "value": "Built 12 services.",
                                            "source_ids": ["acme-x"]}), PROFILE)
    assert any("12" in e for e in errs)


def test_numero_de_salario_no_lo_decide_el_agente():
    errs = check_answers(FORM, sheet(salary={"action": "answer", "value": "3000"}), PROFILE)
    assert any("candidate_decides" in e for e in errs)


def test_email_ajeno():
    errs = check_answers(FORM, sheet(email={"action": "answer", "value": "otra@example.com"}), PROFILE)
    assert any("email" in e for e in errs)


def test_nivel_de_idioma_del_perfil_no_es_numero_inventado():
    errs = check_answers(FORM, sheet(about={"action": "answer", "value": "My English level is B2.",
                                            "source_ids": ["f-years"]}), PROFILE)
    assert errs == []
