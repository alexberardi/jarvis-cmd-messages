"""Per-verb entry guard + shared secret declarations + item callbacks."""

from __future__ import annotations

from typing import Any, List

from jarvis_command_sdk import CommandResponse, IJarvisSecret, JarvisSecret, RequestInformation, callback

from .drafting import draft_flow
from .osx_client import API_KEY_SECRET, INSTANCE_URL_SECRET, OsxApiClient, client_from_storage
from .speaker import refusal_unbound_speaker, refusal_unknown_speaker, resolve_speaker
from .threads import read_thread_flow, storage


def osx_secrets() -> List[IJarvisSecret]:
    return [
        JarvisSecret(
            INSTANCE_URL_SECRET,
            "URL of your Mac's jarvis-osx-api instance, e.g. http://alexs-mac.local:7723",
            scope="user",
            value_type="string",
            is_sensitive=False,
            friendly_name="Mac bridge URL",
        ),
        JarvisSecret(
            API_KEY_SECRET,
            "API key minted on the Mac (python cli.py generate-api-key)",
            scope="user",
            value_type="string",
            friendly_name="Mac bridge API key",
        ),
    ]


def bound_client_or_refusal(
    request_info: Any,
) -> tuple[OsxApiClient | None, CommandResponse | None]:
    """PRD decisions #4 + #9: unknown speaker OR missing binding secrets =
    hard refusal, checked before anything else."""
    if resolve_speaker(request_info) is None:
        return None, refusal_unknown_speaker()
    client = client_from_storage(storage())
    if client is None:
        return None, refusal_unbound_speaker()
    return client, None


def _selected_chat(data: dict) -> tuple[str | None, str | None]:
    selected = (data or {}).get("selected") or []
    if not selected:
        return None, None
    entry = selected[0]
    return entry.get("chat_id") or entry.get("key"), entry.get("label")


class ThreadCallbacksMixin:
    """act_on_items targets for message items ("read the one from Sarah",
    "reply to it"). Inherited by commands whose items name these actions."""

    @callback("read_thread")
    def on_read_thread(self, data: dict, request_info: RequestInformation) -> CommandResponse:
        client, refusal = bound_client_or_refusal(request_info)
        if refusal:
            return refusal
        chat_id, _ = _selected_chat(data)
        return read_thread_flow(client, chat_id=chat_id)

    @callback("draft_reply")
    def on_draft_reply(self, data: dict, request_info: RequestInformation) -> CommandResponse:
        client, refusal = bound_client_or_refusal(request_info)
        if refusal:
            return refusal
        chat_id, label = _selected_chat(data)
        return draft_flow(client, chat_id=chat_id, label=label, instruction=None)
