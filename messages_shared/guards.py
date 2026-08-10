"""Per-verb entry guard + shared secret declarations + item callbacks."""

from __future__ import annotations

from typing import Any, List

from jarvis_command_sdk import CommandResponse, IJarvisSecret, JarvisSecret, RequestInformation, callback

from .drafting import dismiss_by_ref, draft_flow, edit_flow, send_by_ref
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


def _ref_and_text(data: dict) -> tuple[str | None, str | None]:
    """Extract (ref_id, edited_text) from either callback payload shape.

    - Phone tap: the inbox element's data dict verbatim — {"ref_id": ...} and,
      for the editable Send element, "text" (mobile substitutes the live
      editor value at tap time; see drafting.py module docstring).
    - Voice act_on_items: {"action", "selected": [{**recorded_attrs,
      "key": ref_id}], "context"} — never carries text, so the voice path
      always sends the STORED draft.
    """
    data = data or {}
    if data.get("ref_id"):
        return data["ref_id"], data.get("text")
    selected = data.get("selected") or []
    if selected:
        return selected[0].get("key"), None
    return None, None


class ThreadCallbacksMixin:
    """act_on_items + inbox-tap targets for message items.

    Inherited by ALL bundle commands: the node dispatches an item action to
    the command that RECORDED the item (its owner), and follow-up responses
    are re-recorded under the dispatched owner — so any of the three verbs can
    end up owning thread/draft items. Sharing the callbacks makes ownership
    irrelevant.
    """

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

    @callback("send")
    def on_send(self, data: dict, request_info: RequestInformation) -> CommandResponse:
        """Two entry points, one implementation (send_by_ref):
        - voice "send" — dispatched only because the draft item's RECORDED
          attrs carry confirm_offered=True (the draft turn asked the direct
          question; the node's destructive gate verified the flag);
        - phone-card Send tap — may carry the human-edited text."""
        client, refusal = bound_client_or_refusal(request_info)
        if refusal:
            return refusal
        ref_id, edited_text = _ref_and_text(data)
        return send_by_ref(client, ref_id, text_override=edited_text)

    @callback("edit")
    def on_edit(self, data: dict, request_info: RequestInformation) -> CommandResponse:
        """Voice "edit" -> editable card on the speaker's phone. Requires the
        binding guard: the card's Send tap will need the same instance, and an
        unbound speaker should hear the refusal now, not after a tap."""
        _client, refusal = bound_client_or_refusal(request_info)
        if refusal:
            return refusal
        ref_id, _ = _ref_and_text(data)
        return edit_flow(resolve_speaker(request_info), ref_id)

    @callback("dismiss_draft")
    def on_dismiss_draft(self, data: dict, request_info: RequestInformation) -> CommandResponse:
        # No binding guard: touches only our own stored draft, never osx-api.
        del request_info
        ref_id, _ = _ref_and_text(data)
        return dismiss_by_ref(ref_id)
