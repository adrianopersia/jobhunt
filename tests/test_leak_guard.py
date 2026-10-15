import shutil
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "leak_guard.py"


def run(cmd, cwd, check=True):
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    run(["git", "init", "-q", "-b", "work"], tmp_path)
    run(["git", "config", "user.name", "Test Person"], tmp_path)
    run(["git", "config", "user.email", "test@example.com"], tmp_path)
    (tmp_path / "scripts").mkdir()
    shutil.copy(GUARD, tmp_path / "scripts" / "leak_guard.py")
    (tmp_path / ".leak-denylist").write_text("# comentario\nacmecorp\nre:\\bzork\\b\n")
    return tmp_path


def guard(repo, *args):
    return run([sys.executable, "scripts/leak_guard.py", *args], repo, check=False)


def stage(repo, name, content):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    run(["git", "add", "-f", name], repo)


def test_falla_cerrado_sin_denylist(repo):
    (repo / ".leak-denylist").unlink()
    stage(repo, "a.txt", "nada raro")
    result = guard(repo, "--staged")
    assert result.returncode != 0
    assert "falta" in result.stderr


def test_deja_pasar_contenido_limpio(repo):
    stage(repo, "a.txt", "contenido inocente")
    assert guard(repo, "--staged").returncode == 0


def test_bloquea_termino_sin_importar_mayusculas(repo):
    stage(repo, "a.txt", "trabajé en AcmeCorp dos años")
    result = guard(repo, "--staged")
    assert result.returncode != 0
    assert "a.txt:1" in result.stderr


def test_regex_respeta_limites_de_palabra(repo):
    stage(repo, "a.txt", "zorkian no matchea")
    assert guard(repo, "--staged").returncode == 0
    stage(repo, "b.txt", "pero zork sí")
    assert guard(repo, "--staged").returncode != 0


def test_bloquea_termino_en_la_ruta(repo):
    stage(repo, "notas/acmecorp.md", "limpio")
    assert guard(repo, "--staged").returncode != 0


def test_bloquea_carpeta_privada_aunque_se_fuerce(repo):
    stage(repo, "private/profile.yaml", "limpio")
    result = guard(repo, "--staged")
    assert result.returncode != 0
    assert "privada" in result.stderr


def test_bloquea_binarios(repo):
    stage(repo, "cv.pdf", b"%PDF\0\x01\x02")
    assert guard(repo, "--staged").returncode != 0


def test_bloquea_identidad_de_git(repo):
    run(["git", "config", "user.email", "yo@acmecorp.com"], repo)
    stage(repo, "a.txt", "limpio")
    assert guard(repo, "--staged").returncode != 0


def test_bloquea_mensaje_de_commit(repo, tmp_path):
    msg = repo / "MSG"
    msg.write_text("feat: integración con zork\n")
    assert guard(repo, "--message", str(msg)).returncode != 0


def test_historial_encuentra_commits_que_saltearon_el_hook(repo):
    stage(repo, "a.txt", "limpio")
    run(["git", "commit", "-q", "-m", "chore: limpio"], repo)
    stage(repo, "a.txt", "ahora menciona acmecorp")
    run(["git", "commit", "-q", "--no-verify", "-m", "chore: cambio"], repo)
    stage(repo, "a.txt", "limpio otra vez")
    run(["git", "commit", "-q", "-m", "chore: arreglo"], repo)

    assert guard(repo, "--staged").returncode == 0
    result = guard(repo, "--history")
    assert result.returncode != 0
    assert "commit" in result.stderr


@pytest.mark.parametrize("url,owner_ok", [
    ("git@github.com:persona/repo.git", True),
    ("https://github.com/Persona/repo", True),
    ("https://token@github.com/persona/repo.git", True),
    ("git@github.com:persona1/repo.git", False),
    ("git@gitlab.com:persona/repo.git", False),
])
def test_push_solo_al_dueno_permitido(repo, url, owner_ok):
    run(["git", "config", "hooks.allowedRemoteOwner", "persona"], repo)
    result = guard(repo, "--push", url)
    assert (result.returncode == 0) is owner_ok


def test_push_sin_dueno_configurado_bloquea(repo):
    result = guard(repo, "--push", "git@github.com:persona/repo.git")
    assert result.returncode != 0
    assert "allowedRemoteOwner" in result.stderr
