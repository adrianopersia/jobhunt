from jobhunt.ats import MIN_CHARS, clean_url, fetch_description, html_to_text


class FakeClient:
    def __init__(self, text="", json=None):
        self.text, self.json, self.urls = text, json, []

    def get_text(self, url):
        self.urls.append(url)
        return self.text

    def get_json(self, url):
        self.urls.append(url)
        return self.json


def test_saca_utms():
    assert clean_url("https://x.com/jobs/1?utm_source=a&utm_medium=b#top") == "https://x.com/jobs/1"


def test_html_a_texto_ignora_scripts_y_navegacion():
    html = "<nav>Menú</nav><main><h1>Puesto</h1><script>x()</script><p>Detalle</p></main>"
    assert html_to_text(html) == "Puesto\nDetalle"


def test_bamboohr_usa_el_json_de_detalle():
    body = "<p>" + "Requisitos. " * 40 + "</p>"
    client = FakeClient(json={"result": {"jobOpening": {"description": body}}})
    text = fetch_description(client, "https://acme.bamboohr.com/careers/42?utm_source=x")
    assert client.urls == ["https://acme.bamboohr.com/careers/42/detail"]
    assert text.startswith("Requisitos.")


def test_pagina_sin_contenido_devuelve_vacio():
    client = FakeClient(text="<main><div id='root'></div></main>")
    assert fetch_description(client, "https://spa.example.com/job/1") == ""


def test_pagina_generica_con_contenido():
    client = FakeClient(text="<main><p>" + "x" * MIN_CHARS + "</p></main>")
    assert len(fetch_description(client, "https://jobs.example.com/1")) == MIN_CHARS
