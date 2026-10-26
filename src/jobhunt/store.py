"""Persistencia en SQLite. Un aviso pasa por estos estados:

  listed     -> visto en el listado, sin detalle
  filtered   -> descartado por título (no se baja el detalle)
  pending    -> con detalle, esperando análisis del agente
  analyzed   -> con análisis y decisión
  gone       -> ya no aparece en el listado de la fuente (se cerró o se despublicó)
  duplicate  -> el mismo aviso ya entró por otra fuente (misma empresa y título)
  needs_text -> vino de una alerta de LinkedIn y no está en el board de la empresa:
                falta que el candidato pegue el texto (`jobhunt add --paste`)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from jobhunt.models import JobAnalysis, JobDetail, JobStub
from jobhunt.policy import Decision, detect_ats
from jobhunt.sources.base import norm_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  company TEXT NOT NULL,
  location TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'listed',
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  description TEXT,
  apply_url TEXT,
  ats TEXT,
  posted_at TEXT,
  employment_type TEXT,
  modality_raw TEXT,
  location_raw TEXT,
  location_requirements TEXT,
  detail_fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS applications (
  job_id TEXT PRIMARY KEY REFERENCES jobs(id),
  folder TEXT NOT NULL,
  status TEXT NOT NULL,
  note TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
  job_id TEXT PRIMARY KEY REFERENCES jobs(id),
  analysis TEXT NOT NULL,
  fit_score INTEGER NOT NULL,
  decision TEXT NOT NULL,
  decision_reasons TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  analyzed_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(jobs)")}
        if "description_source" not in columns:
            self.db.execute("ALTER TABLE jobs ADD COLUMN description_source TEXT")
        if "norm_key" not in columns:
            self.db.execute("ALTER TABLE jobs ADD COLUMN norm_key TEXT")
        missing = self.db.execute("SELECT id, company, title FROM jobs WHERE norm_key IS NULL").fetchall()
        for row in missing:
            self.db.execute("UPDATE jobs SET norm_key = ? WHERE id = ?",
                            (norm_key(row["company"], row["title"]), row["id"]))
        if missing:
            self.db.commit()

    def upsert_stub(self, stub: JobStub) -> bool:
        """Devuelve True si el aviso es nuevo."""
        ts = now()
        cur = self.db.execute(
            "UPDATE jobs SET last_seen = ?, title = ?, company = ?, location = ?, norm_key = ? WHERE id = ?",
            (ts, stub.title, stub.company, stub.location, norm_key(stub.company, stub.title), stub.id),
        )
        if cur.rowcount:
            # Si había desaparecido y vuelve a estar publicado, recupera su estado.
            self.db.execute(
                "UPDATE jobs SET status = CASE WHEN EXISTS (SELECT 1 FROM analyses WHERE job_id = jobs.id)"
                " THEN 'analyzed' ELSE 'pending' END WHERE id = ? AND status = 'gone'",
                (stub.id,),
            )
            return False
        self.db.execute(
            "INSERT INTO jobs (id, source, external_id, url, title, company, location,"
            " first_seen, last_seen, norm_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (stub.id, stub.source, stub.external_id, stub.url, stub.title,
             stub.company, stub.location, ts, ts, norm_key(stub.company, stub.title)),
        )
        return True

    def duplicate_of(self, job_id: str) -> str | None:
        """Otro aviso vivo con la misma empresa y título, si lo hay."""
        row = self.db.execute(
            "SELECT o.id FROM jobs j JOIN jobs o ON o.norm_key = j.norm_key AND o.id != j.id"
            " WHERE j.id = ? AND o.status IN ('listed', 'pending', 'analyzed') LIMIT 1", (job_id,)
        ).fetchone()
        return row["id"] if row else None

    def mark_gone(self, source: str, seen_ids: set[str]) -> list[str]:
        """Marca como cerrados los avisos de la fuente que no aparecieron en el listado completo."""
        rows = self.db.execute(
            "SELECT id FROM jobs WHERE source = ? AND status IN ('pending', 'analyzed')", (source,)
        ).fetchall()
        gone = [r["id"] for r in rows if r["id"] not in seen_ids]
        self.db.executemany("UPDATE jobs SET status = 'gone' WHERE id = ?", [(i,) for i in gone])
        return gone

    def set_status(self, job_id: str, status: str) -> None:
        self.db.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))

    def save_detail(self, job_id: str, detail: JobDetail) -> None:
        self.db.execute(
            "UPDATE jobs SET description = ?, apply_url = ?, ats = ?, posted_at = ?,"
            " employment_type = ?, modality_raw = ?, location_raw = ?,"
            " location_requirements = ?, detail_fetched_at = ?, status = 'pending',"
            " description_source = CASE WHEN ? = '' THEN NULL ELSE 'site' END"
            " WHERE id = ?",
            (detail.description, detail.apply_url, detect_ats(detail.apply_url),
             detail.posted_at, detail.employment_type, detail.modality_raw,
             detail.location_raw, json.dumps(detail.location_requirements), now(),
             detail.description, job_id),
        )

    def missing_description(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM jobs WHERE status IN ('pending', 'analyzed')"
            " AND COALESCE(description, '') = '' AND COALESCE(apply_url, '') != ''"
            " AND COALESCE(description_source, '') != 'ats_failed'"
        ).fetchall()

    def save_ats_description(self, job_id: str, text: str) -> None:
        """Con texto nuevo, el aviso vuelve a 'pending' para re-analizarlo."""
        if text:
            self.db.execute(
                "UPDATE jobs SET description = ?, description_source = 'ats', status = 'pending'"
                " WHERE id = ?", (text, job_id))
            self.db.execute("DELETE FROM analyses WHERE job_id = ?", (job_id,))
        else:
            self.db.execute(
                "UPDATE jobs SET description_source = 'ats_failed' WHERE id = ?", (job_id,))

    def needs_detail(self, job_id: str) -> bool:
        row = self.db.execute(
            "SELECT detail_fetched_at FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return row is not None and row["detail_fetched_at"] is None

    def get(self, job_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def by_status(self, status: str, limit: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM jobs WHERE status = ? ORDER BY posted_at DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.db.execute(sql, (status,)).fetchall()

    def save_analysis(
        self, job_id: str, analysis: JobAnalysis, decision: Decision, rubric_version: str
    ) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO analyses (job_id, analysis, fit_score, decision,"
            " decision_reasons, rubric_version, analyzed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, analysis.model_dump_json(), analysis.fit_score, decision.decision,
             json.dumps(decision.reasons, ensure_ascii=False), rubric_version, now()),
        )
        self.set_status(job_id, "analyzed")

    def update_decision(self, job_id: str, decision: Decision) -> None:
        """Para recalcular con preferencias nuevas sin volver a pasar el aviso por el LLM."""
        self.db.execute(
            "UPDATE analyses SET decision = ?, decision_reasons = ? WHERE job_id = ?",
            (decision.decision, json.dumps(decision.reasons, ensure_ascii=False), job_id),
        )

    def analyses(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT a.*, j.title, j.company FROM analyses a JOIN jobs j ON j.id = a.job_id"
        ).fetchall()

    def ranked(self, include_gone: bool = False, since: str | None = None) -> list[sqlite3.Row]:
        where = ["1 = 1"]
        params: list[str] = []
        if not include_gone:
            where.append("j.status != 'gone'")
        if since:
            where.append("j.first_seen >= ?")
            params.append(since)
        return self.db.execute(
            "SELECT j.id, j.title, j.company, j.url, j.apply_url, j.ats, j.posted_at, j.status,"
            " j.first_seen, a.fit_score, a.decision, a.decision_reasons, a.analysis,"
            " p.status AS app_status"
            " FROM analyses a JOIN jobs j ON j.id = a.job_id"
            " LEFT JOIN applications p ON p.job_id = j.id"
            f" WHERE {' AND '.join(where)}"
            " ORDER BY CASE a.decision WHEN 'apply' THEN 0 WHEN 'maybe' THEN 1 ELSE 2 END,"
            " a.fit_score DESC",
            params,
        ).fetchall()

    def analysis(self, job_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM analyses WHERE job_id = ?", (job_id,)).fetchone()

    def upsert_application(self, job_id: str, folder: str, status: str, note: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO applications (job_id, folder, status, note, updated_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(job_id) DO UPDATE SET status = excluded.status,"
            " note = COALESCE(excluded.note, applications.note), updated_at = excluded.updated_at",
            (job_id, folder, status, note, now()),
        )

    def application(self, job_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()

    def applications(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT p.*, j.title, j.company, j.status AS job_status, a.fit_score FROM applications p"
            " JOIN jobs j ON j.id = p.job_id LEFT JOIN analyses a ON a.job_id = p.job_id"
            " ORDER BY p.updated_at DESC"
        ).fetchall()

    def analyses_with_salary(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT a.job_id, a.analysis, j.source FROM analyses a JOIN jobs j ON j.id = a.job_id"
            " WHERE json_extract(a.analysis, '$.salary') IS NOT NULL"
        ).fetchall()

    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    def commit(self) -> None:
        self.db.commit()
