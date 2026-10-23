#!/usr/bin/env python3
"""Guardia de Gmail: el pipeline solo puede leer emails de LinkedIn.

Corre como hook de Claude Code sobre cualquier herramienta MCP de Gmail.

PreToolUse (cerrado por defecto):
- Herramientas que escriben, envían o modifican (send, draft, delete, label, ...): bloqueadas.
- Búsquedas: solo si el filtro limita el remitente a direcciones @linkedin.com y no tiene
  operadores que amplíen los resultados (OR, llaves) fuera de ese filtro.
- Lecturas de mensajes o hilos: solo IDs que devolvió una búsqueda permitida.
- Cualquier otra herramienta: bloqueada.

PostToolUse: guarda los IDs que devolvió una búsqueda permitida, para habilitar su lectura.

Salida: exit 2 bloquea la llamada y el motivo vuelve al agente por stderr.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

WRITE_MARKERS = ("send", "draft", "create", "update", "modify", "delete", "trash", "label",
                 "archive", "mark", "move", "reply", "forward", "insert", "import", "remove",
                 "spam", "setting", "filter", "batch", "attach_upload", "upload")
SEARCH_MARKERS = ("search", "list", "query", "find")
READ_MARKERS = ("get", "read", "fetch", "thread", "message")
QUERY_KEYS = ("q", "query", "search_query", "searchquery", "filter", "search")
SENDER_KEYS = ("from", "sender", "from_address")
ID_KEY = re.compile(r"(^|_)(id|ids)$|Id$|Ids$")

LINKEDIN_ADDRESS = re.compile(r"^([a-z0-9._%+-]+@)?([a-z0-9-]+\.)*linkedin\.com$", re.IGNORECASE)
FROM_GROUP = re.compile(r"from:\(([^)]*)\)", re.IGNORECASE)
FROM_TERM = re.compile(r"from:([^\s()]+)", re.IGNORECASE)
WIDENING = re.compile(r"\bOR\b|[{}|]")
TTL_SECONDS = 7 * 86400


def project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def allowlist_path() -> Path:
    return project_dir() / "private" / "runs" / "gmail_allowed_ids.json"


def short_name(tool_name: str) -> str:
    return tool_name.split("__")[-1].lower()


def classify(tool_name: str) -> str:
    name = short_name(tool_name)
    if any(m in name for m in WRITE_MARKERS):
        return "write"
    if any(m in name for m in SEARCH_MARKERS):
        return "search"
    if any(m in name for m in READ_MARKERS):
        return "read"
    return "unknown"


def query_is_linkedin_only(query: str) -> tuple[bool, str]:
    """True si todo resultado posible tiene remitente @linkedin.com."""
    if re.search(r"-\s*from:|\bNOT\b", query, re.IGNORECASE):
        return False, "la búsqueda niega el remitente (-from: o NOT), y eso trae emails que no son de LinkedIn"
    senders: list[str] = []
    rest = query
    for group in FROM_GROUP.findall(query):
        senders += [s.strip() for s in re.split(r"\s+OR\s+|\s+", group) if s.strip() and s.strip() != "OR"]
    rest = FROM_GROUP.sub(" ", rest)
    senders += FROM_TERM.findall(rest)
    rest = FROM_TERM.sub(" ", rest)
    if not senders:
        return False, "la búsqueda no filtra por remitente (falta from:...@linkedin.com)"
    bad = [s for s in senders if not LINKEDIN_ADDRESS.match(s)]
    if bad:
        return False, f"remitentes que no son de LinkedIn: {bad}"
    if WIDENING.search(rest):
        return False, "la búsqueda usa OR o llaves fuera del filtro de remitente, y eso amplía los resultados"
    return True, ""


def find_values(tool_input: dict, keys: tuple[str, ...]) -> list[str]:
    return [str(v) for k, v in tool_input.items() if k.lower() in keys and v not in (None, "")]


def requested_ids(tool_input: dict) -> list[str]:
    ids: list[str] = []
    for key, value in tool_input.items():
        if ID_KEY.search(key):
            ids += [str(v) for v in value] if isinstance(value, list) else [str(value)]
    return ids


def load_allowlist() -> dict[str, float]:
    path = allowlist_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {k: v for k, v in data.items() if now - v < TTL_SECONDS}


def save_allowlist(data: dict[str, float]) -> None:
    path = allowlist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def pre(payload: dict) -> tuple[bool, str]:
    tool, tool_input = payload.get("tool_name", ""), payload.get("tool_input") or {}
    kind = classify(tool)
    if kind == "write":
        return False, f"{short_name(tool)}: el pipeline no escribe, envía ni modifica nada en Gmail"
    if kind == "search":
        senders = find_values(tool_input, SENDER_KEYS)
        if any(not LINKEDIN_ADDRESS.match(s.strip()) for s in senders):
            return False, f"remitente que no es de LinkedIn: {senders}"
        queries = find_values(tool_input, QUERY_KEYS)
        if not queries and not senders:
            return False, "búsqueda sin filtro: solo se permite buscar emails de LinkedIn"
        for q in queries:
            ok, reason = query_is_linkedin_only(q if senders == [] else f"from:{senders[0]} {q}")
            if not ok:
                return False, reason
        return True, ""
    if kind == "read":
        ids = requested_ids(tool_input)
        if not ids:
            return False, "lectura sin ID de mensaje o hilo"
        allowed = load_allowlist()
        missing = [i for i in ids if i not in allowed]
        if missing:
            return False, f"IDs que no salieron de una búsqueda de LinkedIn: {missing}"
        return True, ""
    return False, f"{short_name(tool)}: herramienta de Gmail no habilitada para este pipeline"


_ID_IN_RESPONSE = re.compile(
    r'"(?:id|threadId|thread_id|messageId|message_id)"\s*:\s*"([A-Za-z0-9_-]{6,})"')


def post(payload: dict) -> None:
    tool, tool_input = payload.get("tool_name", ""), payload.get("tool_input") or {}
    if classify(tool) != "search" or not pre({"tool_name": tool, "tool_input": tool_input})[0]:
        return
    response = payload.get("tool_response")
    text = response if isinstance(response, str) else json.dumps(response)
    found = set(_ID_IN_RESPONSE.findall(text))
    # Algunas respuestas vienen como JSON adentro de un string: se busca también desescapado.
    found |= set(_ID_IN_RESPONSE.findall(text.replace('\\"', '"')))
    if found:
        data = load_allowlist()
        now = time.time()
        data.update({i: now for i in found})
        save_allowlist(data)


def main() -> int:
    payload = json.load(sys.stdin)
    if payload.get("hook_event_name") == "PostToolUse":
        post(payload)
        return 0
    ok, reason = pre(payload)
    if not ok:
        print(f"Gmail bloqueado por el guardia de LinkedIn: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
