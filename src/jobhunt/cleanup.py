"""Limpieza de carpetas de postulación entre ciclos.

Lo que se envió se conserva: si la empresa responde, hace falta saber qué CV y qué respuestas
recibió. Lo que nunca se envió y los procesos rechazados se borran del disco; el registro queda
en la base, así esos avisos no vuelven a aparecer como nuevos.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

KEEP = {"submitted", "interviewing", "offer"}
UNSENT = {"created", "tailored", "needs_changes", "ready"}
FINISHED = {"discarded", "rejected"}


@dataclass
class Action:
    job_id: str
    folder: Path
    label: str
    status: str
    new_status: str | None   # None: el estado no cambia, solo se borra la carpeta
    reason: str


def plan(apps, before: str) -> list[Action]:
    """`apps`: filas de `Store.applications()`. `before`: fecha ISO; lo no enviado desde esa
    fecha en adelante es del ciclo actual y no se toca."""
    actions = []
    for app in apps:
        folder = Path(app["folder"])
        label = f"{app['company']}: {app['title']}"
        if app["status"] in UNSENT and app["updated_at"][:10] < before:
            actions.append(Action(app["job_id"], folder, label, app["status"], "discarded",
                                  "no se envió en su ciclo"))
        elif app["status"] in FINISHED and folder.exists():
            actions.append(Action(app["job_id"], folder, label, app["status"], None,
                                  "proceso terminado"))
    return actions


def remove_folder(folder: Path, root: Path) -> bool:
    """Borra la carpeta solo si está adentro de `root` (nunca fuera de private/applications)."""
    folder, root = folder.resolve(), root.resolve()
    if root not in folder.parents or not folder.is_dir():
        return False
    shutil.rmtree(folder)
    return True


def prune_runs(runs: Path, older_than_days: int, now: float) -> list[Path]:
    """Salidas crudas de los agentes y de las descargas; los análisis ya están en la base.
    Los resúmenes de ciclo (`ciclo-*.md`) y los evals se conservan."""
    removed = []
    cutoff = now - older_than_days * 86400
    for path in list(runs.glob("scout/*.json")) + list(runs.glob("fetch-*")):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            removed.append(path)
    return removed
