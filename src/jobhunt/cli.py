"""CLI que usan los agentes. El LLM nunca escribe en la base directo: pasa por estos comandos,
que validan el JSON contra el esquema y aplican las reglas deterministas."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import yaml
from pydantic import ValidationError

from jobhunt.answers import AnswerSheet, check_answers
from jobhunt.ats import fetch_description
from jobhunt.cv import CvDocument, render_pdf
from jobhunt.forms import ApplicationForm, fetch_form
from jobhunt.grounding import ProfileIndex, check as check_grounding
from jobhunt.http import PoliteClient
from jobhunt.keywords import coverage, posting_terms
from jobhunt.models import JobAnalysis, Preferences
from jobhunt.profile import validate as validate_profile
from jobhunt.policy import decide, listing_filter_reason
from jobhunt.sources import startups_argentina
from jobhunt.store import Store

ROOT = Path(__file__).resolve().parents[2]
HOME = Path(os.environ.get("JOBHUNT_HOME", ROOT / "private"))
RUBRIC = ROOT / "rubrics" / "fit.md"
SOURCES = {startups_argentina.SOURCE: startups_argentina}


def load_prefs() -> Preferences:
    path = HOME / "preferences.yaml"
    if not path.is_file():
        sys.exit(f"Falta {path}. Copiá examples/preferences.example.yaml y ajustalo.")
    return Preferences.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def rubric_version() -> str:
    for line in RUBRIC.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("version:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def cmd_fetch(args, store: Store) -> None:
    prefs = load_prefs()
    source = SOURCES[args.source]
    new = filtered = details = 0
    with PoliteClient(delay_s=args.delay) as client:
        stubs = list(source.iter_listing(client, max_pages=args.max_pages))
        for stub in stubs:
            new += store.upsert_stub(stub)
            if listing_filter_reason(stub.title, stub.location, prefs):
                store.set_status(stub.id, "filtered")
                filtered += 1
                continue
            if store.needs_detail(stub.id):
                store.save_detail(stub.id, source.fetch_detail(client, stub))
                details += 1
                store.commit()
        backfilled, unavailable = [], []
        for row in store.missing_description():
            try:
                text = fetch_description(client, row["apply_url"])
            except Exception as err:  # una página caída no frena el resto
                print(f"ATS sin respuesta para {row['id']}: {err}", file=sys.stderr)
                text = ""
            store.save_ats_description(row["id"], text)
            (backfilled if text else unavailable).append(f"{row['company']}: {row['title']}")
            store.commit()
    print(json.dumps({
        "listed": len(stubs), "new": new, "filtered_by_title": filtered,
        "details_fetched": details, "description_from_ats": backfilled,
        "description_unavailable": unavailable, "status_counts": store.counts(),
    }, ensure_ascii=False, indent=1))


def cmd_pending(args, store: Store) -> None:
    rows = store.by_status("pending", limit=args.limit)
    print(json.dumps([
        {"id": r["id"], "title": r["title"], "company": r["company"]} for r in rows
    ], ensure_ascii=False, indent=1))


def cmd_show(args, store: Store) -> None:
    if not store.get(args.job_id):
        sys.exit(f"No existe {args.job_id}")
    print(_render_show(store, args.job_id), end="")


def _render_show(store: Store, job_id: str) -> str:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_show(store, job_id)
    return buffer.getvalue()


def _print_show(store: Store, job_id: str) -> None:
    row = store.get(job_id)
    reqs = json.loads(row["location_requirements"] or "[]")
    print(f"# {row['title']} — {row['company']}\n")
    print(f"- id: {row['id']}")
    print(f"- publicado: {row['posted_at']}")
    print(f"- ubicación (sitio): {row['location_raw'] or row['location']}")
    print(f"- modalidad (sitio): {row['modality_raw']}")
    print(f"- países aceptados (sitio): {', '.join(reqs) or 'sin dato'}")
    print(f"- tipo: {row['employment_type']}")
    print(f"- postulación: {row['apply_url']} ({row['ats']})")
    source = {"site": "del agregador", "ats": "del ATS de la empresa",
              "ats_failed": "no disponible (el ATS necesita navegador)"}
    print(f"- descripción: {source.get(row['description_source'], 'sin dato')}")
    print("\n## Descripción\n")
    print(row["description"] or "(sin descripción)")
    analysis = store.analysis(job_id)
    if analysis:
        print(f"\n## Análisis del scout ({analysis['rubric_version']})\n")
        print(f"- decisión: {analysis['decision']} ({analysis['fit_score']})")
        print(f"- motivos: {'; '.join(json.loads(analysis['decision_reasons'])) or '—'}")
        print("```json")
        print(json.dumps(json.loads(analysis["analysis"]), ensure_ascii=False, indent=1))
        print("```")


def cmd_analyze(args, store: Store) -> None:
    if not store.get(args.job_id):
        sys.exit(f"No existe {args.job_id}")
    raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    try:
        analysis = JobAnalysis.model_validate_json(raw)
    except ValidationError as err:
        print(err, file=sys.stderr)
        sys.exit("El análisis no cumple el esquema; corregilo y volvé a enviarlo.")
    decision = decide(analysis, load_prefs())
    store.save_analysis(args.job_id, analysis, decision, rubric_version())
    store.commit()
    print(json.dumps({"job_id": args.job_id, "decision": decision.decision,
                      "reasons": decision.reasons}, ensure_ascii=False))


def cmd_report(args, store: Store) -> None:
    rows = store.ranked()
    if args.decision:
        rows = [r for r in rows if r["decision"] in args.decision]
    print("| # | Decisión | Score | Puesto | Empresa | Familia | Seniority | ATS | Motivos |")
    print("|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        a = json.loads(r["analysis"])
        reasons = "; ".join(json.loads(r["decision_reasons"])) or "—"
        print(f"| {i} | {r['decision']} | {r['fit_score']} | [{r['title']}]({r['url']}) "
              f"| {r['company']} | {a['role_family']} | {a['seniority']} | {r['ats']} | {reasons} |")
    print(f"\nEstados: {store.counts()}")


def cmd_schema(args, store: Store | None = None) -> None:
    model = {"analysis": JobAnalysis, "cv": CvDocument, "answers": AnswerSheet}[args.which]
    print(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=1))


def load_profile() -> dict:
    path = HOME / "profile" / "profile.yaml"
    if not path.is_file():
        sys.exit(f"Falta {path}.")
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    errors = validate_profile(profile)
    if errors:
        print("\n".join(f"PERFIL  {e}" for e in errors), file=sys.stderr)
        sys.exit(f"El perfil tiene {len(errors)} errores de formato; corregilo antes de seguir.")
    return profile


def load_cv(path: str) -> CvDocument:
    try:
        return CvDocument.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except ValidationError as err:
        print(err, file=sys.stderr)
        sys.exit("El CV no cumple el esquema.")


def run_check(doc: CvDocument) -> bool:
    report = check_grounding(doc, load_profile())
    for error in report.errors:
        print(f"ERROR  {error}")
    for warning in report.warnings:
        print(f"AVISO  {warning}")
    print("Anclaje OK" if report.ok else f"Anclaje FALLÓ: {len(report.errors)} errores")
    return report.ok


APPLICATION_STATUSES = ["created", "tailored", "needs_changes", "ready", "submitted", "discarded"]


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def cmd_app_init(args, store: Store) -> None:
    row = store.get(args.job_id)
    if not row:
        sys.exit(f"No existe {args.job_id}")
    existing = store.application(args.job_id)
    folder = Path(existing["folder"]) if existing else (
        HOME / "applications" / f"{slugify(row['company'])}-{slugify(row['title'])}-{row['external_id'][:8]}"
    )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "posting.md").write_text(_render_show(store, args.job_id), encoding="utf-8")
    if not existing:
        store.upsert_application(args.job_id, str(folder), "created")
        store.commit()
    analysis = store.analysis(args.job_id)
    lang = json.loads(analysis["analysis"])["posting_language"] if analysis else "en"
    stem = load_profile()["person"].get("file_stem", "CV")
    print(json.dumps({
        "folder": str(folder), "cv_json": str(folder / "cv.json"),
        "cv_pdf": str(folder / f"{stem}-CV-{lang.upper()}.pdf"), "lang": lang,
        "status": (existing or {"status": "created"})["status"],
    }, ensure_ascii=False, indent=1))


def cmd_app_set(args, store: Store) -> None:
    app = store.application(args.job_id)
    if not app:
        sys.exit(f"{args.job_id} no tiene carpeta de postulación; corré `jobhunt app init` primero.")
    store.upsert_application(args.job_id, app["folder"], args.status, args.note)
    store.commit()
    print(f"{args.job_id}: {args.status}")


def cmd_app_list(args, store: Store) -> None:
    print("| Estado | Score | Puesto | Empresa | Carpeta | Nota |")
    print("|---|---|---|---|---|---|")
    for r in store.applications():
        print(f"| {r['status']} | {r['fit_score'] or '—'} | {r['title']} | {r['company']} "
              f"| {Path(r['folder']).name} | {r['note'] or '—'} |")


def cmd_cv_keywords(args, store: Store) -> None:
    row, analysis = store.get(args.job_id), store.analysis(args.job_id)
    if not row or not analysis:
        sys.exit(f"{args.job_id} no existe o no tiene análisis.")
    doc = load_cv(args.doc)
    profile = load_profile()
    terms = posting_terms(json.loads(analysis["analysis"])["stack"], row["description"] or "", profile)
    cv_text = " ".join([doc.headline, doc.summary.text]
                       + [s for line in doc.skills for s in line.items]
                       + [b.text for r in doc.experience for b in r.bullets]
                       + [p.title + " " + p.text for p in doc.projects])
    cov = coverage(terms, cv_text, profile)
    print(json.dumps({
        "score": cov.score,
        "present": cov.present,
        "missing_but_supported": cov.missing_supported,
        "missing_gap_do_not_add": cov.missing_gap,
    }, ensure_ascii=False, indent=1))


def _app_folder(store: Store, job_id: str) -> Path:
    app = store.application(job_id)
    if not app:
        sys.exit(f"{job_id} no tiene carpeta de postulación; corré `jobhunt app init` primero.")
    return Path(app["folder"])


def cmd_app_form(args, store: Store) -> None:
    folder = _app_folder(store, args.job_id)
    row = store.get(args.job_id)
    if not row["apply_url"]:
        sys.exit("El aviso no tiene link de postulación.")
    with PoliteClient() as client:
        form = fetch_form(client, row["apply_url"])
    (folder / "form.json").write_text(form.model_dump_json(indent=1), encoding="utf-8")
    print(f"Formulario: {form.system} ({'legible' if form.extractable else 'NO legible: revisar a mano'})")
    for note in form.notes:
        print(f"Nota: {note}")
    for f in form.fields:
        opts = f" opciones={f.options}" if f.options else ""
        print(f"- [{'obligatorio' if f.required else 'opcional'}] {f.id} | {f.type} | {f.label}{opts}")
    print(f"Guardado en {folder / 'form.json'}")


def cmd_app_check(args, store: Store) -> None:
    folder = _app_folder(store, args.job_id)
    problems: list[str] = []
    profile = load_profile()
    cv_json = folder / "cv.json"
    if not cv_json.is_file():
        problems.append("falta cv.json")
    else:
        report = check_grounding(load_cv(str(cv_json)), profile)
        problems += [f"CV: {e}" for e in report.errors]
    if not list(folder.glob("*-CV-*.pdf")):
        problems.append("falta el PDF del CV")
    form_path, answers_path = folder / "form.json", folder / "answers.json"
    if not form_path.is_file():
        problems.append("falta form.json (correr `jobhunt app form`)")
    elif not answers_path.is_file():
        problems.append("falta answers.json")
    else:
        form = ApplicationForm.model_validate_json(form_path.read_text(encoding="utf-8"))
        try:
            sheet = AnswerSheet.model_validate_json(answers_path.read_text(encoding="utf-8"))
        except ValidationError as err:
            print(err, file=sys.stderr)
            sys.exit("answers.json no cumple el esquema.")
        problems += [f"Formulario: {e}" for e in check_answers(form, sheet, profile)]
        pending = [a for a in sheet.answers if a.action == "candidate_decides"]
        if pending:
            print(f"Campos que completa el candidato: {len(pending)}")
    for problem in problems:
        print(f"ERROR  {problem}")
    print("Postulación OK" if not problems else f"Postulación con {len(problems)} problemas")
    sys.exit(0 if not problems else 1)


def cmd_cv_sources(args) -> None:
    """Cada texto del CV junto a sus fuentes, para que un juez revise la fidelidad semántica."""
    doc = load_cv(args.doc)
    idx = ProfileIndex(load_profile())

    def show(where: str, text: str, ids: list[str]) -> None:
        print(f"### {where}\nCV: {text}")
        for i in ids:
            item = idx.items.get(i, {})
            print(f"- {i}: {item.get(doc.lang) or item.get('en', '(no existe)')}")
        print()

    show("resumen", doc.summary.text, doc.summary.source_ids)
    for role in doc.experience:
        for n, bullet in enumerate(role.bullets, 1):
            show(f"{role.company} #{n}", bullet.text, bullet.source_ids)
    for project in doc.projects:
        show(f"proyecto {project.title}", project.text, project.source_ids)


def cmd_cv_check(args) -> None:
    sys.exit(0 if run_check(load_cv(args.doc)) else 1)


def cmd_cv_render(args) -> None:
    doc = load_cv(args.doc)
    if not run_check(doc):
        sys.exit("No se genera el PDF de un CV que no pasa la verificación.")
    pages = render_pdf(doc, Path(args.out))
    print(f"PDF: {args.out} ({pages} página{'s' if pages != 1 else ''})")
    if pages > 1:
        sys.exit("El CV tiene que entrar en una página: recortá bullets.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jobhunt")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch", help="Bajar avisos de una fuente")
    p.add_argument("source", choices=sorted(SOURCES))
    p.add_argument("--max-pages", type=int)
    p.add_argument("--delay", type=float, default=1.5)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("pending", help="Avisos esperando análisis")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_pending)

    p = sub.add_parser("show", help="Ver un aviso completo")
    p.add_argument("job_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("analyze", help="Guardar el análisis de un aviso (JSON por archivo o stdin)")
    p.add_argument("job_id")
    p.add_argument("--file")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("report", help="Ranking de avisos analizados")
    p.add_argument("--decision", nargs="*", choices=["apply", "maybe", "skip"])
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("schema", help="Esquema JSON de un análisis o de un CV")
    p.add_argument("which", nargs="?", choices=["analysis", "cv", "answers"], default="analysis")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("cv", help="Verificar o renderizar un CV")
    cv_sub = p.add_subparsers(dest="cv_cmd", required=True)
    c = cv_sub.add_parser("check", help="Verificar que el CV no inventa nada")
    c.add_argument("doc")
    c.set_defaults(func=cmd_cv_check)
    c = cv_sub.add_parser("render", help="Verificar y generar el PDF")
    c.add_argument("doc")
    c.add_argument("--out", required=True)
    c.set_defaults(func=cmd_cv_render)

    c = cv_sub.add_parser("keywords", help="Cobertura de keywords del aviso en el CV")
    c.add_argument("job_id")
    c.add_argument("doc")
    c.set_defaults(func=cmd_cv_keywords, needs_store=True)

    c = cv_sub.add_parser("sources", help="Cada texto del CV junto a sus fuentes")
    c.add_argument("doc")
    c.set_defaults(func=cmd_cv_sources)

    p = sub.add_parser("app", help="Carpetas de postulación")
    app_sub = p.add_subparsers(dest="app_cmd", required=True)
    a = app_sub.add_parser("init", help="Crear (o reabrir) la carpeta de un aviso")
    a.add_argument("job_id")
    a.set_defaults(func=cmd_app_init)
    a = app_sub.add_parser("set", help="Cambiar el estado de una postulación")
    a.add_argument("job_id")
    a.add_argument("--status", required=True, choices=APPLICATION_STATUSES)
    a.add_argument("--note")
    a.set_defaults(func=cmd_app_set)
    a = app_sub.add_parser("form", help="Leer el formulario de postulación (sin enviar nada)")
    a.add_argument("job_id")
    a.set_defaults(func=cmd_app_form)
    a = app_sub.add_parser("check", help="Verificar CV, PDF y respuestas de una postulación")
    a.add_argument("job_id")
    a.set_defaults(func=cmd_app_check)
    a = app_sub.add_parser("list", help="Postulaciones y su estado")
    a.set_defaults(func=cmd_app_list)

    args = parser.parse_args(argv)
    if args.cmd in ("schema", "cv") and not getattr(args, "needs_store", False):
        args.func(args)
        return
    args.func(args, Store(HOME / "jobhunt.db"))


if __name__ == "__main__":
    main()
