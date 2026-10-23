import os
import time
from pathlib import Path

from jobhunt.cleanup import plan, prune_runs, remove_folder


def app(tmp_path, name, status, updated):
    folder = tmp_path / "applications" / name
    folder.mkdir(parents=True)
    (folder / "cv.pdf").write_text("x")
    return {"job_id": name, "folder": str(folder), "status": status, "updated_at": updated,
            "company": "Acme", "title": name}


def test_se_conserva_lo_enviado_y_lo_del_ciclo_actual(tmp_path):
    apps = [
        app(tmp_path, "viejo-listo", "ready", "2026-10-15T10:00:00+00:00"),
        app(tmp_path, "viejo-enviado", "submitted", "2026-10-15T10:00:00+00:00"),
        app(tmp_path, "en-entrevista", "interviewing", "2026-10-15T10:00:00+00:00"),
        app(tmp_path, "rechazado", "rejected", "2026-10-16T10:00:00+00:00"),
        app(tmp_path, "nuevo-listo", "ready", "2026-10-23T09:00:00+00:00"),
    ]
    actions = {a.job_id: a for a in plan(apps, before="2026-10-23")}
    assert set(actions) == {"viejo-listo", "rechazado"}
    assert actions["viejo-listo"].new_status == "discarded"
    assert actions["rechazado"].new_status is None


def test_nunca_borra_fuera_de_la_carpeta_de_postulaciones(tmp_path):
    root = tmp_path / "applications"
    inside = root / "x"
    inside.mkdir(parents=True)
    outside = tmp_path / "otra"
    outside.mkdir()
    assert remove_folder(inside, root) and not inside.exists()
    assert not remove_folder(outside, root) and outside.exists()
    assert not remove_folder(root, root) and root.exists()


def test_poda_salidas_crudas_viejas_pero_no_los_resumenes(tmp_path):
    runs = tmp_path / "runs"
    (runs / "scout").mkdir(parents=True)
    old = runs / "scout" / "a.json"
    old.write_text("{}")
    fetch = runs / "fetch-2026-09-01.json"
    fetch.write_text("{}")
    digest = runs / "ciclo-2026-09-01.md"
    digest.write_text("#")
    past = time.time() - 40 * 86400
    for f in (old, fetch, digest):
        os.utime(f, (past, past))
    removed = prune_runs(runs, older_than_days=30, now=time.time())
    assert set(removed) == {old, fetch}
    assert digest.exists()
