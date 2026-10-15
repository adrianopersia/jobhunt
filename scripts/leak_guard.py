#!/usr/bin/env python3
"""Bloquea commits y pushes que contengan términos de la denylist local.

La denylist (`.leak-denylist`) no se versiona: contiene justamente los nombres que no
pueden salir. Si falta o está vacía, el guard falla cerrado.

Modos:
  --staged          contenido y rutas del índice, más la identidad de git configurada
  --message FILE    mensaje de commit (hook commit-msg)
  --history         todo el historial: rutas, contenido, mensajes, autores y committers
  --push URL        historial completo + el remote tiene que ser del dueño permitido
                    (`git config hooks.allowedRemoteOwner`); si no está configurado, bloquea
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

DENYLIST_NAME = ".leak-denylist"
BLOCKED_PREFIXES = ("private/",)


def git(*args: str, cwd: Path | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True
    ).stdout


def repo_root() -> Path:
    return Path(git("rev-parse", "--show-toplevel").decode().strip())


def load_patterns(path: Path) -> list[tuple[str, re.Pattern[str]]]:
    if not path.is_file():
        raise SystemExit(
            f"leak-guard: falta {path.name}. Sin denylist no se puede verificar nada, "
            "así que el commit queda bloqueado."
        )
    patterns = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("re:"):
            source = line[3:]
        else:
            source = re.escape(line)
        patterns.append((line, re.compile(source, re.IGNORECASE)))
    if not patterns:
        raise SystemExit(f"leak-guard: {path.name} está vacía; el commit queda bloqueado.")
    return patterns


def find_hits(
    text: str, where: str, patterns: list[tuple[str, re.Pattern[str]]]
) -> list[str]:
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pattern in patterns:
            if pattern.search(line):
                hits.append(f"{where}:{lineno}: coincide con '{label}'")
    return hits


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def check_staged(root: Path, patterns) -> list[str]:
    hits: list[str] = []
    for key in ("user.name", "user.email"):
        value = git("config", key, cwd=root).decode().strip()
        hits += find_hits(value, f"git config {key}", patterns)

    names = git(
        "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR", cwd=root
    ).split(b"\0")
    for name in filter(None, (n.decode() for n in names)):
        if name.startswith(BLOCKED_PREFIXES):
            hits.append(f"{name}: está dentro de una carpeta privada")
            continue
        hits += find_hits(name, f"ruta {name}", patterns)
        blob = git("show", f":{name}", cwd=root)
        if is_binary(blob):
            hits.append(f"{name}: archivo binario; no se puede revisar, así que no entra")
            continue
        hits += find_hits(blob.decode("utf-8", errors="replace"), name, patterns)
    return hits


def check_message(path: Path, patterns) -> list[str]:
    return find_hits(path.read_text(encoding="utf-8"), "mensaje de commit", patterns)


def check_history(root: Path, patterns) -> list[str]:
    hits: list[str] = []
    if not git("rev-list", "--all", cwd=root).strip():
        return hits
    meta = git("log", "--all", "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B%x01", cwd=root)
    for record in filter(None, meta.decode("utf-8", errors="replace").split("\x01")):
        sha, *fields = record.strip("\n").split("\0")
        hits += find_hits("\n".join(fields), f"commit {sha[:8]} (autor/mensaje)", patterns)

    log = git("log", "--all", "-p", "--format=commit %H", cwd=root)
    sha = "?"
    for line in log.decode("utf-8", errors="replace").splitlines():
        if line.startswith("commit "):
            sha = line.split()[1][:8]
            continue
        if line.startswith(("+", "diff --git", "rename to", "Binary files")):
            hits += find_hits(line, f"commit {sha}", patterns)
    return hits


def remote_owner(url: str) -> str | None:
    """Dueño del repo en GitHub, para URLs SSH (git@github.com:dueño/repo) o HTTPS."""
    match = re.match(r"^(?:git@github\.com:|ssh://git@github\.com/|https://(?:[^@/]+@)?github\.com/)([^/]+)/", url)
    return match.group(1) if match else None


def check_remote(root: Path, url: str) -> list[str]:
    try:
        allowed = git("config", "hooks.allowedRemoteOwner", cwd=root).decode().strip()
    except subprocess.CalledProcessError:
        return ["falta `git config hooks.allowedRemoteOwner`: sin dueño permitido no se pushea"]
    owner = remote_owner(url)
    if owner is None:
        return [f"remote que no es de GitHub o no se reconoce: {url}"]
    if owner.lower() != allowed.lower():
        return [f"el remote es de '{owner}' y solo se permite '{allowed}'"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--message", type=Path)
    mode.add_argument("--history", action="store_true")
    mode.add_argument("--push", metavar="URL")
    args = parser.parse_args()

    root = repo_root()
    patterns = load_patterns(root / DENYLIST_NAME)

    if args.staged:
        hits = check_staged(root, patterns)
    elif args.message:
        hits = check_message(args.message, patterns)
    elif args.push:
        hits = check_remote(root, args.push) + check_history(root, patterns)
    else:
        hits = check_history(root, patterns)

    if hits:
        print("leak-guard: bloqueado. Hay datos que no pueden salir de esta máquina:", file=sys.stderr)
        for hit in hits:
            print(f"  - {hit}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
