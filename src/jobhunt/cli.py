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
from jobhunt.salary import data_band, suggest as suggest_salary
from jobhunt.policy import monthly_usd_amount
from jobhunt.policy import company_excluded, decide, listing_filter_reason, title_priority, too_old
from jobhunt.sources import ats_boards, getonbrd, himalayas, jobicy, manual, startups_argentina, wwr
from jobhunt.sources.base import FetchContext
from jobhunt.store import Store

ROOT = Path(__file__).resolve().parents[2]
HOME = Path(os.environ.get("JOBHUNT_HOME", ROOT / "private"))
RUBRIC = ROOT / "rubrics" / "fit.md"
SOURCES = {m.SOURCE: m for m in (startups_argentina, ats_boards, getonbrd, himalayas, jobicy, wwr)}


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
    names = sorted(SOURCES) if args.source == "all" else [args.source]
    summary = {}
    with PoliteClient(delay_s=args.delay) as client:
        for name in names:
            try:
                summary[name] = _fetch_source(SOURCES[name], client, store, prefs, args)
            except Exception as err:  # una fuente caída no frena las demás
                summary[name] = {"error": f"{type(err).__name__}: {err}"}
            store.commit()
        backfilled, unavailable = [], []
        for row in store.missing_description():
            try:
                text = fetch_description(client, row["apply_url"])
            except Exception as err:
                print(f"ATS sin respuesta para {row['id']}: {err}", file=sys.stderr)
                text = ""
            store.save_ats_description(row["id"], text)
            (backfilled if text else unavailable).append(f"{row['company']}: {row['title']}")
            store.commit()
    print(json.dumps({
        "sources": summary, "description_from_ats": backfilled,
        "description_unavailable": unavailable, "status_counts": store.counts(),
    }, ensure_ascii=False, indent=1))


def _fetch_source(source, client: PoliteClient, store: Store, prefs: Preferences, args) -> dict:
    ctx = FetchContext(home=HOME, max_pages=args.max_pages)
    listings = list(source.iter_jobs(client, ctx))
    gone = store.mark_gone(source.SOURCE, {l.stub.id for l in listings}) if ctx.complete else []
    new = filtered = duplicates = 0
    candidates = []
    for listing in listings:
        stub = listing.stub
        new += store.upsert_stub(stub)
        if store.get(stub.id)["status"] not in ("listed", "filtered"):
            continue  # ya procesado en una corrida anterior
        reason = listing_filter_reason(stub.title, stub.location, prefs, stub.company)
        if not reason and listing.detail and too_old(listing.detail.posted_at, prefs):
            reason = "aviso viejo"
        if reason:
            store.set_status(stub.id, "filtered")
            filtered += 1
        elif store.duplicate_of(stub.id):
            store.set_status(stub.id, "duplicate")
            duplicates += 1
        else:
            store.set_status(stub.id, "listed")
            candidates.append(listing)
    candidates.sort(key=lambda l: title_priority(l.stub.title, prefs), reverse=True)
    quota = args.limit or prefs.max_new_per_source
    details = 0
    for listing in candidates[:quota]:
        try:
            detail = listing.detail or source.fetch_detail(client, listing.stub)
        except Exception as err:
            ctx.errors.append(f"{listing.stub.id}: {err}")
            continue
        store.save_detail(listing.stub.id, detail)
        details += 1
        store.commit()
    return {
        "listed": len(listings), "new": new, "filtered": filtered, "duplicates": duplicates,
        "analyzable": details, "deferred_to_next_run": max(len(candidates) - quota, 0),
        "closed_since_last_fetch": len(gone), "errors": ctx.errors[:5],
    }


def cmd_add(args, store: Store) -> None:
    prefs = load_prefs()
    listings = []
    if args.paste:
        if not (args.title and args.company):
            sys.exit("Con --paste hacen falta --title y --company.")
        text = Path(args.paste).read_text(encoding="utf-8")
        listings.append(manual.from_text(text, args.title, args.company, args.url or "", args.location or ""))
    elif not args.urls:
        sys.exit("Pasá uno o más links, o un aviso copiado con --paste.")
    with PoliteClient() as client:
        for url in ([] if args.paste else args.urls):
            try:
                listings.append(manual.fetch_listing(client, url))
            except Exception as err:
                print(f"No pude leer {url}: {err}", file=sys.stderr)
    for listing in listings:
        stub = listing.stub
        store.upsert_stub(stub)
        store.save_detail(stub.id, listing.detail)
        store.commit()
        warning = listing_filter_reason(stub.title, stub.location, prefs, stub.company)
        print(json.dumps({"id": stub.id, "title": stub.title, "company": stub.company,
                          "status": store.get(stub.id)["status"],
                          "warning": f"los filtros lo habrían descartado: {warning}" if warning else None},
                         ensure_ascii=False))


def cmd_linkedin_ingest(args, store: Store) -> None:
    from jobhunt.models import AlertBatch
    from jobhunt.sources import linkedin_alerts

    try:
        batch = AlertBatch.model_validate_json(Path(args.file).read_text(encoding="utf-8"))
    except ValidationError as err:
        print(err, file=sys.stderr)
        sys.exit("El archivo de alertas no cumple el esquema (`jobhunt schema linkedin`).")
    with PoliteClient() as client:
        resolver = linkedin_alerts.BoardResolver(client, HOME, ats_boards.load_boards(FetchContext(home=HOME)))
        try:
            summary = linkedin_alerts.ingest(batch, store, load_prefs(), resolver)
        except ValueError as err:
            sys.exit(str(err))
        resolver.save()
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def cmd_linkedin_pending(args, store: Store) -> None:
    rows = store.by_status("needs_text")
    if not rows:
        print("No hay avisos de LinkedIn esperando texto.")
    for r in rows:
        print(f"- {r['company']}: {r['title']} ({r['location'] or 'sin ubicación'})\n  {r['url']}\n"
              f"  jobhunt add --paste aviso.txt --title \"{r['title']}\" --company \"{r['company']}\" "
              f"--url {r['url']}")


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


def _ranking_table(rows) -> list[str]:
    lines = ["| # | Decisión | Score | Puesto | Empresa | Familia | Seniority | ATS | Postulación | Motivos |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        a = json.loads(r["analysis"])
        reasons = "; ".join(json.loads(r["decision_reasons"])) or "—"
        lines.append(
            f"| {i} | {r['decision']} | {r['fit_score']} | [{r['title']}]({r['url']}) | {r['company']} "
            f"| {a['role_family']} | {a['seniority']} | {r['ats']} | {r['app_status'] or '—'} | {reasons} |")
    return lines


def _ranked(store: Store, **kwargs) -> list:
    """El ranking sin las empresas excluidas en las preferencias (incluye las analizadas antes de excluirlas)."""
    prefs = load_prefs()
    return [r for r in store.ranked(**kwargs) if not company_excluded(r["company"], prefs)]


def cmd_report(args, store: Store) -> None:
    rows = _ranked(store, include_gone=args.all, since=args.since)
    if args.decision:
        rows = [r for r in rows if r["decision"] in args.decision]
    if args.new:
        rows = [r for r in rows if not r["app_status"]]
    print("\n".join(_ranking_table(rows)))
    print(f"\nEstados: {store.counts()}")


def cmd_digest(args, store: Store) -> None:
    from datetime import date, datetime

    rows = _ranked(store, since=args.since)
    candidates = [r for r in rows if r["decision"] in ("apply", "maybe") and not r["app_status"]]
    counts = {d: sum(r["decision"] == d for r in rows) for d in ("apply", "maybe", "skip")}
    out = [f"# Ciclo de búsqueda — {date.today().isoformat()}", ""]
    out.append(f"Avisos nuevos analizados{' desde ' + args.since if args.since else ''}: "
               f"{len(rows)} ({counts['apply']} aplicar, {counts['maybe']} dudosos, {counts['skip']} descartados).")
    out += ["", "## Para decidir", ""]
    out += _ranking_table(candidates) if candidates else ["Nada nuevo que valga la pena."]
    waiting = store.by_status("needs_text")
    if waiting:
        out += ["", "## LinkedIn: pegá el texto", "",
                "No están en el board de la empresa. Copiá el aviso y usá `jobhunt add --paste` (ver `jobhunt linkedin pending`).", ""]
        out += [f"- [{r['title']}]({r['url']}) — {r['company']}" for r in waiting]
    out += ["", "## Postulaciones", "", "| Estado | Score | Puesto | Empresa | Hace | Aviso | Nota |",
            "|---|---|---|---|---|---|---|"]
    today = datetime.now().date()
    for r in store.applications():
        days = (today - datetime.fromisoformat(r["updated_at"]).date()).days
        closed = "cerrado" if r["job_status"] == "gone" else "publicado"
        out.append(f"| {r['status']} | {r['fit_score'] or '—'} | {r['title']} | {r['company']} "
                   f"| {days} días | {closed} | {r['note'] or '—'} |")
    print("\n".join(out))


def cmd_schema(args, store: Store | None = None) -> None:
    from jobhunt.models import AlertBatch
    model = {"analysis": JobAnalysis, "cv": CvDocument, "answers": AnswerSheet, "linkedin": AlertBatch}[args.which]
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


APPLICATION_STATUSES = ["created", "tailored", "needs_changes", "ready", "submitted",
                        "interviewing", "offer", "rejected", "discarded"]


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


def cmd_app_clean(args, store: Store) -> None:
    import time
    from datetime import date

    from jobhunt import cleanup

    before = args.before or date.today().isoformat()
    actions = cleanup.plan(store.applications(), before)
    if not actions:
        print("Nada para limpiar.")
    for a in actions:
        what = "borrar carpeta y marcar descartada" if a.new_status else "borrar carpeta"
        print(f"- {a.label} [{a.status}]: {what} ({a.reason})")
    if not args.apply:
        print("\nSimulación: no se borró nada. Repetí con --apply para ejecutar.")
        return
    root = HOME / "applications"
    for a in actions:
        cleanup.remove_folder(a.folder, root)
        if a.new_status:
            store.upsert_application(a.job_id, str(a.folder), a.new_status, f"limpiada el {date.today()}: {a.reason}")
    store.commit()
    pruned = cleanup.prune_runs(HOME / "runs", args.runs_older_than, time.time())
    print(f"\nListo: {len(actions)} postulaciones limpiadas, {len(pruned)} salidas viejas de agentes borradas.")


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
    # Algunos agregadores (Himalayas) bloquean la lectura: el candidato abre "Apply" y pasa el link real.
    url = args.url or row["apply_url"]
    if not url:
        sys.exit("El aviso no tiene link de postulación.")
    with PoliteClient() as client:
        try:
            form = fetch_form(client, url)
        except Exception as err:  # 403, timeout, etc.: el paquete se arma igual, para completar a mano
            form = ApplicationForm(url=url, system="unknown", extractable=False, notes=[
                f"No se pudo leer el formulario ({type(err).__name__}: {err}); completarlo a mano, o abrir "
                f"Apply y pasar el link del formulario con `jobhunt app form {args.job_id} --url <link>`."])
    if args.url:
        form.notes.insert(0, "Link del formulario pasado a mano por el candidato.")
    (folder / "form.json").write_text(form.model_dump_json(indent=1), encoding="utf-8")
    print(f"Formulario: {form.system} ({'legible' if form.extractable else 'NO legible: revisar a mano'})")
    for note in form.notes:
        print(f"Nota: {note}")
    for f in form.fields:
        opts = f" opciones={f.options}" if f.options else ""
        if f.min_length or f.max_length:
            opts += f" largo={f.min_length or 0}-{f.max_length or '∞'}"
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


# Solo fuentes donde el salario publicado es lo que se paga en la región. Las bandas que publican
# empresas de EE.UU. en boards globales son para gente en EE.UU. y no sirven de referencia.
REGIONAL_SALARY_SOURCES = {"getonbrd", "startups_argentina"}


def _salary_points(store: Store, prefs: Preferences) -> dict[tuple[str, str], list[float]]:
    """Salarios mensuales en USD de avisos regionales que aceptan Argentina, por (quién paga, seniority)."""
    ceiling = 2 * max((b.max for b in (prefs.salary_reference.local, prefs.salary_reference.foreign) if b),
                      default=float("inf"))
    points: dict[tuple[str, str], list[float]] = {}
    for row in store.analyses_with_salary():
        if row["source"] not in REGIONAL_SALARY_SOURCES:
            continue
        a = JobAnalysis.model_validate_json(row["analysis"])
        if a.remote_accepts_argentina != "yes" and a.modality.value == "remote":
            continue
        amounts = [v for v in (a.salary.min, a.salary.max) if v is not None]
        usd = monthly_usd_amount(sum(amounts) / len(amounts), a.salary.currency, a.salary.period, prefs) if amounts else None
        if usd and usd <= ceiling:
            points.setdefault((a.employer_market, a.seniority.value), []).append(usd)
    return points


def cmd_salary_market(args, store: Store) -> None:
    from statistics import median
    print("| Quién paga | Seniority | n | Mínimo | Mediana | Máximo |")
    print("|---|---|---|---|---|---|")
    for (market, seniority), values in sorted(_salary_points(store, load_prefs()).items()):
        print(f"| {market} | {seniority} | {len(values)} | {min(values):,.0f} | {median(values):,.0f} | {max(values):,.0f} |")


def cmd_salary(args, store: Store) -> None:
    analysis = store.analysis(args.job_id)
    if not analysis:
        sys.exit(f"{args.job_id} no tiene análisis.")
    parsed = JobAnalysis.model_validate_json(analysis["analysis"])
    prefs = load_prefs()
    market = args.market or parsed.employer_market
    observed = data_band(_salary_points(store, prefs).get((market, "semi_senior"), []))
    try:
        s = suggest_salary(parsed, prefs, market=args.market, observed=observed)
    except ValueError as err:
        sys.exit(str(err))
    print(json.dumps({
        "ask_usd_month": s.ask, "acceptable_range": [s.low, s.high], "band": s.band,
        "market": args.market or parsed.employer_market, "source": s.source,
        "rationale": s.rationale,
    }, ensure_ascii=False, indent=1))


def cmd_eval_inputs(args) -> None:
    from jobhunt import evals
    cases = evals.load_cases(ROOT / "evals" / "auditor" / "cases.jsonl")
    Path(args.out).write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in evals.blind(cases)) + "\n",
                              encoding="utf-8")
    print(f"{len(cases)} casos sin etiqueta en {args.out}")


def cmd_eval_score(args) -> None:
    from jobhunt import evals
    cases = evals.load_cases(ROOT / "evals" / "auditor" / "cases.jsonl")
    raw = json.loads(Path(args.predictions).read_text(encoding="utf-8"))
    predictions = {p["id"]: p["verdict"] for p in raw}
    s = evals.score(cases, predictions)
    text = evals.report(args.name, s, cases)
    out = ROOT / "evals" / "auditor" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.name}.md").write_text(text, encoding="utf-8")
    (out / f"{args.name}.predictions.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)


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
    p.add_argument("source", choices=sorted(SOURCES) + ["all"])
    p.add_argument("--max-pages", type=int)
    p.add_argument("--limit", type=int, help="Cupo de avisos nuevos por fuente (pisa la preferencia)")
    p.add_argument("--delay", type=float, default=1.5)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("add", help="Sumar avisos a mano: por URL, o pegando el texto (LinkedIn y similares)")
    p.add_argument("urls", nargs="*")
    p.add_argument("--paste", metavar="ARCHIVO", help="Texto del aviso copiado a mano (para LinkedIn, Indeed, etc.)")
    p.add_argument("--title", help="Con --paste: título del puesto")
    p.add_argument("--company", help="Con --paste: empresa")
    p.add_argument("--url", help="Con --paste: link del aviso, para tenerlo en el paquete")
    p.add_argument("--location", help="Con --paste: ubicación o modalidad, ej. 'Argentina · remote'")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("linkedin", help="Alertas de empleo de LinkedIn (leídas del email)")
    li_sub = p.add_subparsers(dest="li_cmd", required=True)
    li = li_sub.add_parser("ingest", help="Cargar una tanda de alertas (JSON, ver `jobhunt schema linkedin`)")
    li.add_argument("file")
    li.set_defaults(func=cmd_linkedin_ingest)
    li = li_sub.add_parser("pending", help="Avisos de LinkedIn que esperan que pegues el texto")
    li.set_defaults(func=cmd_linkedin_pending)

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
    p.add_argument("--new", action="store_true", help="Solo avisos sin postulación")
    p.add_argument("--since", help="Solo avisos vistos por primera vez desde esta fecha (YYYY-MM-DD)")
    p.add_argument("--all", action="store_true", help="Incluir avisos cerrados")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("digest", help="Resumen del ciclo: avisos nuevos y estado de las postulaciones")
    p.add_argument("--since", help="Fecha del ciclo anterior (YYYY-MM-DD)")
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("schema", help="Esquema JSON de un análisis o de un CV")
    p.add_argument("which", nargs="?", choices=["analysis", "cv", "answers", "linkedin"], default="analysis")
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

    p = sub.add_parser("eval", help="Evals del auditor semántico")
    eval_sub = p.add_subparsers(dest="eval_cmd", required=True)
    e = eval_sub.add_parser("auditor-inputs", help="Casos sin etiqueta para el juez")
    e.add_argument("--out", required=True)
    e.set_defaults(func=cmd_eval_inputs)
    e = eval_sub.add_parser("auditor-score", help="Puntuar las predicciones del juez")
    e.add_argument("predictions")
    e.add_argument("--name", required=True)
    e.set_defaults(func=cmd_eval_score)

    p = sub.add_parser("salary", help="Recomendación salarial para un aviso analizado")
    p.add_argument("job_id")
    p.add_argument("--market", choices=["local", "foreign", "unclear"],
                   help="Forzar quién paga si el análisis no lo sabe")
    p.set_defaults(func=cmd_salary)

    p = sub.add_parser("salary-market", help="Salarios publicados en los avisos analizados")
    p.set_defaults(func=cmd_salary_market)

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
    a.add_argument("--url", help="Link del formulario real, si el del aviso no se puede leer (ej. Himalayas)")
    a.set_defaults(func=cmd_app_form)
    a = app_sub.add_parser("check", help="Verificar CV, PDF y respuestas de una postulación")
    a.add_argument("job_id")
    a.set_defaults(func=cmd_app_check)
    a = app_sub.add_parser("clean", help="Borrar carpetas de postulaciones no enviadas o terminadas")
    a.add_argument("--before", help="Solo lo no enviado antes de esta fecha (YYYY-MM-DD; default: hoy)")
    a.add_argument("--runs-older-than", type=int, default=30,
                   help="Días para borrar salidas crudas de agentes en private/runs")
    a.add_argument("--apply", action="store_true", help="Ejecutar (sin esto, solo muestra el plan)")
    a.set_defaults(func=cmd_app_clean)
    a = app_sub.add_parser("list", help="Postulaciones y su estado")
    a.set_defaults(func=cmd_app_list)

    args = parser.parse_args(argv)
    if args.cmd in ("schema", "cv", "eval") and not getattr(args, "needs_store", False):
        args.func(args)
        return
    args.func(args, Store(HOME / "jobhunt.db"))


if __name__ == "__main__":
    main()
