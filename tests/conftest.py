"""Shared fixtures: in-memory StorageBackend (mirrors jarvis-cmd-medication's
conftest), a fake osx-api client patched over the single guards seam, speaker
context, and a stubbed node ask_llm module."""

from __future__ import annotations

import sys
import types

import pytest
from jarvis_command_sdk import RequestInformation
from jarvis_command_sdk.context import set_current_user_id
from jarvis_command_sdk.storage import StorageBackend, get_backend, set_backend

from messages_shared.osx_client import API_KEY_SECRET, INSTANCE_URL_SECRET, OsxApiError

SPEAKER = 7


class FakeStorageBackend(StorageBackend):
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], dict] = {}
        self.secrets: dict[tuple[str, str, int | None], str] = {}

    def save(self, command_name, data_key, data, expires_at=None):
        self.data[(command_name, data_key)] = dict(data)

    def get(self, command_name, data_key):
        rec = self.data.get((command_name, data_key))
        return dict(rec) if rec is not None else None

    def get_all(self, command_name):
        return [dict(v) for (c, _k), v in self.data.items() if c == command_name]

    def delete(self, command_name, data_key):
        return self.data.pop((command_name, data_key), None) is not None

    def delete_all(self, command_name):
        keys = [(c, k) for (c, k) in self.data if c == command_name]
        for key in keys:
            del self.data[key]
        return len(keys)

    def get_secret(self, key, scope, user_id=None):
        return self.secrets.get((key, scope, user_id))

    def set_secret(self, key, value, scope, value_type="string", user_id=None):
        self.secrets[(key, scope, user_id)] = value

    def delete_secret(self, key, scope, user_id=None):
        self.secrets.pop((key, scope, user_id), None)


@pytest.fixture
def backend():
    prev = get_backend()
    fake = FakeStorageBackend()
    set_backend(fake)
    yield fake
    set_backend(prev)  # type: ignore[arg-type]


@pytest.fixture
def speaker(backend):
    """Recognized, bound speaker: contextvar set + both binding secrets present."""
    set_current_user_id(SPEAKER)
    backend.set_secret(INSTANCE_URL_SECRET, "http://mac.local:7723", "user", user_id=SPEAKER)
    backend.set_secret(API_KEY_SECRET, "joxk_test", "user", user_id=SPEAKER)
    yield SPEAKER
    set_current_user_id(None)


def request_info(user_id: int | None = SPEAKER) -> RequestInformation:
    return RequestInformation(voice_command="x", conversation_id="c1", user_id=user_id)


def message(
    guid: str,
    text: str,
    sender_name: str | None = None,
    is_from_me: bool = False,
    spoken_text: str | None = None,
    handle: str = "+15551234567",
) -> dict:
    return {
        "guid": guid,
        "sender_handle": handle,
        "sender_name": sender_name,
        "is_from_me": is_from_me,
        "text": text,
        "spoken_text": spoken_text if spoken_text is not None else text,
        "timestamp": 1_754_700_000.0,
        "has_attachments": False,
    }


def chat(chat_id: str, messages: list[dict], display_name: str | None = None) -> dict:
    return {
        "chat_id": chat_id,
        "chat_rowid": 1,
        "identifier": chat_id,
        "display_name": display_name,
        "is_group": False,
        "messages": messages,
    }


class FakeOsxClient:
    def __init__(
        self,
        unread: dict | None = None,
        threads: dict | None = None,
        styles: dict | None = None,
        send_result: dict | None = None,
    ):
        self.unread_payload = unread or {"total": 0, "chats": []}
        self.threads = threads or {}
        self.styles = styles or {}
        self.send_result = send_result or {"status": "sent"}
        self.mark_read_calls: list[list[str]] = []
        self.send_calls: list[tuple[str, str]] = []
        self.unread_error: Exception | None = None
        self.thread_error: Exception | None = None
        self.mark_read_error: Exception | None = None
        self.send_error: Exception | None = None

    def unread(self) -> dict:
        if self.unread_error:
            raise self.unread_error
        return self.unread_payload

    def thread(self, chat_id: str, limit: int = 30) -> dict:
        if self.thread_error:
            raise self.thread_error
        return self.threads.get(chat_id, {"messages": []})

    def style_context(self, chat_id: str) -> dict:
        return self.styles.get(chat_id, {"messages": [], "sparse": True})

    def mark_read(self, guids: list[str]) -> dict:
        if self.mark_read_error:
            raise self.mark_read_error
        self.mark_read_calls.append(list(guids))
        return {"marked": len(guids)}

    def send(self, chat_id: str, text: str) -> dict:
        if self.send_error:
            raise self.send_error
        self.send_calls.append((chat_id, text))
        return self.send_result


@pytest.fixture
def osx(monkeypatch):
    """Patch the single seam every verb uses to obtain its client."""
    client = FakeOsxClient()
    monkeypatch.setattr("messages_shared.guards.client_from_storage", lambda _storage: client)
    return client


@pytest.fixture
def fake_ask_llm(monkeypatch):
    """Stub the node runtime's services.node_llm_client module (absent in unit
    tests) so drafting's guarded import resolves. Records prompts."""
    calls: list[dict] = []
    state = {"reply": "On my way, be there in 10!"}

    def ask_llm(prompt, *, system=None, model="live", temperature=0.0, timeout=15):
        calls.append({"prompt": prompt, "system": system, "model": model})
        return state["reply"]

    services_pkg = types.ModuleType("services")
    llm_mod = types.ModuleType("services.node_llm_client")
    llm_mod.ask_llm = ask_llm
    services_pkg.node_llm_client = llm_mod
    monkeypatch.setitem(sys.modules, "services", services_pkg)
    monkeypatch.setitem(sys.modules, "services.node_llm_client", llm_mod)
    return {"calls": calls, "state": state}


def unreachable() -> OsxApiError:
    return OsxApiError("connection refused")
