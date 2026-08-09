"""Draft composition + storage (PRD approve-turn flow, resolved Q6).

The draft is composed HERE, in the command layer, via the node runtime's
generic `ask_llm` primitive (node -> CC /api/v0/node/llm/chat -> llm-proxy).
The exact text is stored in JarvisStorage keyed by ref_id so the send callback
re-fetches it verbatim — the LLM never copies the draft (paraphrase risk).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jarvis_command_sdk import CommandResponse, ReferenceableItem

from .osx_client import OsxApiClient, OsxApiError
from .speaker import service_error_response
from .threads import LAST_THREAD_KEY, storage

_DRAFT_TTL = timedelta(minutes=15)  # outlives the 10-min conversation TTL
_THREAD_TAIL = 8

_SYSTEM_PROMPT = (
    "You draft short text-message replies on the user's behalf. "
    "Reply with ONLY the message text — no quotes, no preamble, no sign-off."
)


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

    # Ends with a direct question on purpose: the approval turn IS the
    # destructive-gate confirmation (PRD decision #14), and a question keeps
    # the bare "yes" from reading as room noise.
    message = f"Here's the draft to {label}: \"{draft}\" — want me to send it?"
    return CommandResponse.with_items(
        message,
        [
            ReferenceableItem(
                ref_id=ref_id,
                label=f"draft reply to {label}",
                attrs={"chat_id": chat_id, "label": label},
                actions=["send"],
            )
        ],
        context_data={"chat_id": chat_id, "draft": draft},
    )
