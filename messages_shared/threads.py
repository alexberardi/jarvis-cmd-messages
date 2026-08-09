"""Shared thread-reading flow — used by the read_thread verb and by the
"read_thread" item action on check_texts results ("read the one from Sarah")."""

from __future__ import annotations

import re

from jarvis_command_sdk import CommandResponse, JarvisStorage, ReferenceableItem

from .osx_client import OsxApiClient, OsxApiError
from .phrasing import chat_label, collapse_bursts
from .speaker import service_error_response

# One storage namespace for the whole bundle so verbs can share thread context
# (JarvisStorage is namespaced by this string, not enforced per command).
STORAGE_NAMESPACE = "messages"

LAST_THREAD_KEY = "last_thread"


def storage() -> JarvisStorage:
    return JarvisStorage(STORAGE_NAMESPACE)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def match_chat(chats: list[dict], chat_id: str | None, contact: str | None) -> dict | None:
    if chat_id:
        for chat in chats:
            if chat.get("chat_id") == chat_id or str(chat.get("chat_rowid")) == str(chat_id):
                return chat
        return None
    if contact:
        query = _tokens(contact)
        best: tuple[int, dict] | None = None
        for chat in chats:
            names = _tokens(chat_label(chat))
            for message in chat.get("messages") or []:
                if message.get("sender_name"):
                    names |= _tokens(str(message["sender_name"]))
            overlap = len(query & names)
            if overlap and (best is None or overlap > best[0]):
                best = (overlap, chat)
        return best[1] if best else None
    if len(chats) == 1:
        return chats[0]
    return None


def read_thread_flow(
    client: OsxApiClient,
    chat_id: str | None = None,
    contact: str | None = None,
) -> CommandResponse:
    try:
        unread = client.unread()
    except OsxApiError as exc:
        return service_error_response(str(exc))

    chats = unread.get("chats") or []
    if not chats:
        who = f" from {contact}" if contact else ""
        return CommandResponse.success_response(
            context_data={"message": f"You have no new texts{who}."}, wait_for_input=False
        )

    chat = match_chat(chats, chat_id, contact)
    if chat is None:
        if contact:
            return CommandResponse.success_response(
                context_data={"message": f"No new texts from {contact}."}, wait_for_input=False
            )
        names = ", ".join(chat_label(c) for c in chats)
        return CommandResponse.success_response(
            context_data={"message": f"You have new texts from {names}. Which one should I read?"}
        )

    label = chat_label(chat)
    bursts = collapse_bursts(chat.get("messages") or [], chat)
    if not bursts:
        return CommandResponse.success_response(
            context_data={"message": f"No new texts from {label}."}, wait_for_input=False
        )

    spoken_guids = [g for burst in bursts for g in burst["guids"] if g]
    lines = [f"{label} said: {bursts[0]['text']}"] + [b["text"] for b in bursts[1:]]
    message = " ".join(lines)

    # Speech composed successfully — NOW record it in the read-aloud ledger
    # (PRD decision #12: mark after speaking, never on listing). A mark-read
    # failure must not eat the speech.
    ledger_ok = True
    try:
        client.mark_read(spoken_guids)
    except OsxApiError:
        ledger_ok = False

    store = storage()
    store.save(LAST_THREAD_KEY, {"chat_id": chat["chat_id"], "label": label})
    store.save(f"thread:{chat['chat_id']}", {"chat_id": chat["chat_id"], "label": label})

    return CommandResponse.with_items(
        message,
        [
            ReferenceableItem(
                ref_id=str(chat["chat_id"]),
                label=f"conversation with {label}",
                attrs={"chat_id": chat["chat_id"], "label": label},
                actions=["draft_reply"],
            )
        ],
        context_data={"chat_id": chat["chat_id"], "marked_read": ledger_ok},
    )
