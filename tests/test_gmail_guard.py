"""El guardia de Gmail es la única barrera entre el agente y el resto del correo: se prueba
como caja negra sobre los payloads que manda Claude Code."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "gmail_linkedin_only.py"
spec = importlib.util.spec_from_file_location("gmail_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

SEARCH = "mcp__claude_ai_Gmail__search_threads"
READ = "mcp__claude_ai_Gmail__get_thread"


@pytest.fixture(autouse=True)
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return tmp_path


def allowed(tool, **tool_input):
    return guard.pre({"tool_name": tool, "tool_input": tool_input})[0]


@pytest.mark.parametrize("query,ok", [
    ("from:jobalerts-noreply@linkedin.com newer_than:14d", True),
    ("from:(jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com) newer_than:14d", True),
    ("from:linkedin.com subject:job", True),
    ("newer_than:14d", False),
    ("from:banco@ejemplo.com", False),
    ("from:linkedin.com OR subject:factura", False),
    ("from:(jobs-noreply@linkedin.com OR amigo@ejemplo.com)", False),
    ("-from:linkedin.com", False),
    ("from:linkedin.com NOT subject:x", False),
    ("{from:linkedin.com from:otro.com}", False),
    ("from:x@linkedin.com.evil.io", False),
])
def test_busquedas(query, ok):
    assert allowed(SEARCH, query=query) is ok


def test_remitente_estructurado():
    assert allowed(SEARCH, sender="jobalerts-noreply@linkedin.com")
    assert not allowed(SEARCH, sender="otra@ejemplo.com", query="from:linkedin.com")


@pytest.mark.parametrize("tool", ["send_message", "create_draft", "delete_message", "modify_labels",
                                  "trash_thread", "list_labels_and_update"])
def test_herramientas_que_escriben_siempre_bloqueadas(tool):
    assert not allowed(f"mcp__claude_ai_Gmail__{tool}", query="from:linkedin.com")


def test_herramienta_desconocida_bloqueada():
    assert not allowed("mcp__claude_ai_Gmail__get_profile", )


def test_solo_se_leen_ids_de_busquedas_de_linkedin():
    assert not allowed(READ, thread_id="t-linkedin-1")
    guard.post({"hook_event_name": "PostToolUse", "tool_name": SEARCH,
                "tool_input": {"query": "from:jobalerts-noreply@linkedin.com"},
                "tool_response": {"threads": [{"id": "t-linkedin-1"}]}})
    guard.post({"hook_event_name": "PostToolUse", "tool_name": SEARCH,
                "tool_input": {"query": "from:banco@ejemplo.com"},
                "tool_response": {"threads": [{"id": "t-banco-1"}]}})
    assert allowed(READ, thread_id="t-linkedin-1")
    assert not allowed(READ, thread_id="t-banco-1")
    assert not allowed(READ, thread_ids=["t-linkedin-1", "t-banco-1"])


def test_ids_dentro_de_un_string_json():
    guard.post({"hook_event_name": "PostToolUse", "tool_name": SEARCH,
                "tool_input": {"query": "from:linkedin.com"},
                "tool_response": '[{"type":"text","text":"{\\"messages\\":[{\\"id\\":\\"m-123456\\"}]}"}]'})
    assert allowed("mcp__claude_ai_Gmail__get_message", message_id="m-123456")
