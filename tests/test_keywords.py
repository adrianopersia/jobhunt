from jobhunt.keywords import coverage, mentions, posting_terms

PROFILE = {
    "skills": {"backend": ["Node.js", "NestJS", "PostgreSQL"], "frontend": ["React", "Next.js"]},
    "experience": [{"achievements": [
        {"use": "cv", "en": "Built REST APIs with NestJS.", "es": ""},
        {"use": "interview", "en": "Tried Kubernetes once.", "es": ""},
    ]}],
}


def test_alias_y_limites_de_palabra():
    assert mentions("Backend en NodeJS", "Node.js")
    assert mentions("We use Postgres", "PostgreSQL")
    assert not mentions("reactive streams", "React")
    assert not mentions("Next.js apps", "Node.js")


def test_tres_grupos():
    cv = "Built APIs with NestJS and Node.js."
    cov = coverage(["Node.js", "NestJS", "React", "Golang", "Kubernetes"], cv, PROFILE)
    assert cov.present == ["Node.js", "NestJS"]
    assert cov.missing_supported == ["React"]
    assert cov.missing_gap == ["Golang", "Kubernetes"]  # lo de "interview" no respalda el CV
    assert cov.score == "2/5"


def test_suma_skills_del_perfil_que_el_aviso_nombra():
    terms = posting_terms(["React"], "Buscamos alguien con PostgreSQL y React.", PROFILE)
    assert terms == ["React", "PostgreSQL"]


def test_terminos_con_barra_se_separan_salvo_nombres_conocidos():
    terms = posting_terms(["JavaScript/TypeScript", "CI/CD", "AWS/Azure/GCP"], "", PROFILE)
    assert terms == ["JavaScript", "TypeScript", "CI/CD", "AWS", "Azure", "GCP"]


def test_frases_genericas_cuentan_con_terminos_concretos():
    cov = coverage(["Relational databases", "Third-party APIs"],
                   "PostgreSQL search; third-party API integrations.", PROFILE)
    assert cov.present == ["Relational databases", "Third-party APIs"]
