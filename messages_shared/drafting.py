"""Draft composition, storage, voice-send, and the editable phone card.

The draft is composed HERE, in the command layer, via the node runtime's
generic `ask_llm` primitive (node -> CC /api/v0/node/llm/chat -> llm-proxy),
and the EXACT text is stored in JarvisStorage keyed by ref_id.

Send confirmation (PRD decisions #5/#14, final): the draft turn reads the
draft verbatim and asks "want me to send this, or edit it yourself?".
- Spoken "send" -> act_on_items dispatches the "send" callback. The node's
  destructive-action gate allows it because the draft item's RECORDED attrs
  carry `confirm_offered: True` (jarvis-node-setup
  command_execution_service.py — the flag is command-controlled; we set it
  precisely because this turn offered the send as a direct question, making
  the user's reply the confirmation). The send uses the STORED draft text.
- Spoken "edit" -> the "edit" callback posts an EDITABLE card to the
  speaker's phone; its Send tap delivers the human-edited text.

Editable-card round-trip (email bundle pattern, verified):
`metadata.editable_text = {label, initial, data_key}` seeds the mobile editor
(jarvis-cmd-email email_shared/reply_drafts.py:203-209); on tap, mobile
substitutes the live editor text into `data[data_key]` for elements whose
data contains that key (reply_drafts.py:183-188 — Send carries it, Dismiss
doesn't), and the callback reads it from its data payload
(jarvis-cmd-email commands/email/command.py:1727). We use data_key "text".

Tap dispatch chain (same as email's reply cards): JarvisInbox
interactive_elements (sdk inbox.py:34-51,108) -> CC -> notifications -> tap ->
node handle_callback (jarvis-node-setup scripts/mqtt_tts_listener.py:300)
fetches {command_name, callback_name, data, user_id}, sets the SDK user
context (:384), and invokes the @callback with the element data verbatim.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jarvis_command_sdk import CommandResponse, JarvisInbox, ReferenceableItem

from .osx_client import OsxApiClient, OsxApiError
from .speaker import service_error_response
from .threads import LAST_THREAD_KEY, storage

_DRAFT_TTL = timedelta(minutes=30)  # phone pickup can lag the voice turn
_THREAD_TAIL = 8

_SYSTEM_PROMPT = (
    "You draft short text-message replies on the user's behalf. "
    "Reply with ONLY the message text — no quotes, no preamble, no sign-off."
)

_SEND_SPOKEN = {
    "sent": "Sent to {label}.",
    "unverified": (
        "I asked Messages to send it, but I couldn't confirm it actually went "
        "through — better double-check on your Mac or phone."
    ),
    "send_failed": "Messages reported an error sending it — it didn't go through.",
    "group_unsupported": "I can't send to group chats yet — only one-on-one conversations.",
    "no_such_chat": "I couldn't find that conversation on your Mac to send to.",
    "applescript_error": "Your Mac refused the send — it may need the Automation permission re-granted.",
}


def draft_ref_id(chat_id: str) -> str:
    return f"draft:{chat_id}"


def _ask_llm_guarded(prompt: str, system: str) -> str | None:
    # Node-runtime module; unavailable in unit tests / non-node contexts.
    # Guarded like jarvis-cmd-email's reply_rubric — fail closed.
    try:
        from services.node_llm_client import ask_llm
    except ImportError:
        return None
    return ask_llm(prompt, system=system, model="live", temperature=0.4, timeout=20)


def _strip_noise(draft: str) -> str:
    draft = draft.strip()
    if len(draft) >= 2 and draft[0] in "\"'“”" and draft[-1] in "\"'“”":
        draft = draft[1:-1].strip()
    return draft


def compose_prompt(thread: dict, style: dict, label: str, instruction: str | None) -> str:
    lines = []
    for message in (thread.get("messages") or [])[-_THREAD_TAIL:]:
        who = "Me" if message.get("is_from_me") else label
        text = str(message.get("text") or message.get("spoken_text") or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    convo = "\n".join(lines) or "(no recent messages)"

    if style.get("sparse") or not style.get("messages"):
        style_block = "Write in a neutral, casual texting tone."
    else:
        examples = "\n".join(f"- {m}" for m in style["messages"])
        style_block = f"Examples of how I text in this conversation (match this tone):\n{examples}"

    ask = instruction or "Write an appropriate short reply to the last message."
    return (
        f"Conversation with {label} (most recent last):\n{convo}\n\n"
        f"{style_block}\n\n"
        f"Instruction: {ask}\n"
        "Reply with only the message text."
    )


def draft_flow(
    client: OsxApiClient,
    chat_id: str | None,
    label: str | None,
    instruction: str | None,
) -> CommandResponse:
    store = storage()
    if not chat_id:
        last = store.get(LAST_THREAD_KEY)
        if not last:
            return CommandResponse.error_response(
                error_details="No thread in context for draft_reply.",
                context_data={
                    "error": "no_thread_context",
                    "message": "Which conversation should I reply to? Ask me to read a text first.",
                },
            )
        chat_id, label = last["chat_id"], last.get("label")
    label = label or "them"

    try:
        thread = client.thread(chat_id)
        style = client.style_context(chat_id)
    except OsxApiError as exc:
        return service_error_response(str(exc))

    draft = _ask_llm_guarded(compose_prompt(thread, style, label, instruction), _SYSTEM_PROMPT)
    if not draft or not draft.strip():
        return CommandResponse.error_response(
            error_details="ask_llm unavailable or returned empty draft.",
            context_data={
                "error": "draft_failed",
                "message": "I couldn't put a draft together right now. Try again in a moment.",
            },
        )
    draft = _strip_noise(draft)

    ref_id = draft_ref_id(chat_id)
    store.save(
        ref_id,
        {"draft": draft, "chat_id": chat_id, "label": label},
        expires_at=datetime.now(timezone.utc) + _DRAFT_TTL,
    )

    # The direct question makes the follow-up the confirmation: this exact turn
    # is why the item may carry confirm_offered=True (the node's destructive
    # gate dispatches "send" only for items recorded with the flag). No card is
    # posted here — the phone card exists only on the "edit" path.
    message = (
        f"Here's the draft to {label}: \"{draft}\" — "
        "want me to send this, or edit it yourself?"
    )
    return CommandResponse.with_items(
        message,
        [
            ReferenceableItem(
                ref_id=ref_id,
                label=f"draft reply to {label}",
                attrs={"chat_id": chat_id, "label": label, "confirm_offered": True},
                actions=["send", "edit"],
            )
        ],
        context_data={"chat_id": chat_id, "draft": draft},
    )


def send_by_ref(client: OsxApiClient, ref_id: str | None, text_override: str | None = None) -> CommandResponse:
    """Single send implementation behind both entry points (voice + phone tap).

    ``text_override`` is the phone editor's text (tap path only — mobile
    substitutes it into the element data at tap time). Human edits are allowed
    by the exact-text rule: it forbids LLM re-emission of the draft, not human
    authorship. The voice path never carries an override, so it always sends
    the STORED draft verbatim.
    """
    if not ref_id:
        return CommandResponse.error_response(
            error_details="send without ref_id",
            context_data={"error": "no_selection", "message": "I'm not sure which draft to send."},
        )
    record = storage().get(ref_id)
    if not record or not record.get("draft"):
        return CommandResponse.error_response(
            error_details=f"No stored draft for ref_id {ref_id!r} (expired?)",
            context_data={
                "error": "draft_expired",
                "message": "That draft has expired — ask me to draft the reply again.",
            },
        )

    label = record.get("label") or "them"
    text = (text_override or "").strip() or record["draft"]
    try:
        result = client.send(record["chat_id"], text)
    except OsxApiError as exc:
        return CommandResponse.error_response(
            error_details=str(exc),
            context_data={
                "error": "osx_api_unreachable",
                "message": "I couldn't reach your Mac to send it — nothing was sent.",
            },
        )

    status = result.get("status")
    spoken = _SEND_SPOKEN.get(status, f"Sending failed ({status}).").format(label=label)
    if status == "sent":
        storage().delete(ref_id)  # spent — a second "send it"/tap must not double-send
        return CommandResponse.success_response(
            context_data={"message": spoken, "status": status}, wait_for_input=False
        )
    return CommandResponse.error_response(
        error_details=f"send returned status={status}: {result.get('detail')}",
        context_data={"error": status, "message": spoken},
    )


def edit_flow(user_id: int | None, ref_id: str | None) -> CommandResponse:
    """Voice "edit" -> push the EDITABLE card to the speaker's phone."""
    record = storage().get(ref_id) if ref_id else None
    if not record or not record.get("draft"):
        return CommandResponse.error_response(
            error_details=f"No stored draft for ref_id {ref_id!r} (expired?)",
            context_data={
                "error": "draft_expired",
                "message": "That draft has expired — ask me to draft the reply again.",
            },
        )
    label = record.get("label") or "them"
    tag = post_editable_card(user_id, ref_id, label, record["draft"])
    if tag != "ok":
        return CommandResponse.error_response(
            error_details=f"editable card post failed: {tag}",
            context_data={
                "error": "card_post_failed",
                "message": (
                    "I couldn't get the draft to your phone — nothing was sent. "
                    "You can still tell me to send it as is."
                ),
            },
        )
    return CommandResponse.success_response(
        context_data={
            "message": "Okay — it's on your phone. Edit it there and tap Send when it's ready.",
        },
        wait_for_input=False,
    )


def post_editable_card(user_id: int | None, ref_id: str, label: str, draft: str) -> str:
    """Editable Send/Dismiss card. Returns the inbox tag ("ok" on success).

    The draft is seeded into the mobile editor via metadata.editable_text; the
    Send element's data carries the "text" data_key so the tap substitutes the
    edited value (email's reply-card pattern). Dismiss's data has no "text"
    key, so it never picks up editor content.
    """
    elements = [
        {
            "id": f"send-{ref_id}",
            "label": "Send",
            "kind": "send",
            "command": "draft_reply",
            "callback": "send",
            "data": {"ref_id": ref_id, "text": draft},
            # stack: poll + show the send result inline (the honest
            # sent/unverified phrasing from send_by_ref).
            "navigation_type": "stack",
        },
        {
            # No navigation_type => fire-and-forget; the chip just checks off.
            "id": f"dismiss-{ref_id}",
            "label": "Dismiss",
            "command": "draft_reply",
            "callback": "dismiss_draft",
            "data": {"ref_id": ref_id},
        },
    ]
    return JarvisInbox("draft_reply").post(
        title=f"Text reply ready — {label}",
        summary="Edit if you like, then tap Send",
        body=f"To: {label}",
        category="general",
        metadata={
            "editable_text": {
                "label": "Draft reply",
                "initial": draft,
                "data_key": "text",
            },
        },
        interactive_elements=elements,
        user_id=user_id,
        target_type="user",
        create_push_notification=True,
    )


def dismiss_by_ref(ref_id: str | None) -> CommandResponse:
    """Drop a stored draft. Idempotent (double-tap / expired still succeeds)."""
    record = storage().get(ref_id) if ref_id else None
    if ref_id:
        storage().delete(ref_id)
    label = (record or {}).get("label") or "them"
    message = f"Discarded the draft to {label}." if record else "That draft was already gone."
    return CommandResponse.success_response(context_data={"message": message}, wait_for_input=False)
