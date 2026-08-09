"""draft_reply + the send approval callback.

The full human-in-the-loop send (PRD decisions #5, #13, #14):

1. run() composes the draft IN-COMMAND via the node's generic `ask_llm`
   primitive (resolved PRD Q6), stores the EXACT text in JarvisStorage keyed
   by ref_id, and speaks it verbatim ending with "want me to send it?".
2. "Yes, send it" -> act_on_items(action="send") -> @callback("send") below
   re-fetches the stored draft by ref_id (NEVER takes text from the LLM —
   paraphrase risk) and calls osx-api /v1/messages/send.
3. The service verifies the row landed in chat.db before saying "sent"; every
   other status is reported honestly.

NOTE: the node's act_on_items destructive-action gate (_DESTRUCTIVE_ACTIONS in
jarvis-node-setup command_execution_service.py:122, refusal at :1093-1107)
currently refuses "send" by voice until the confirmation round-trip is wired —
that node-setup work item treats the draft-approval turn as the confirmation
(PRD decision #14). Do NOT rename this action to something outside the
frozenset to evade the gate.
"""

from __future__ import annotations

from typing import Any, List

from jarvis_command_sdk import (
    CommandExample,
    CommandResponse,
    IJarvisCommand,
    IJarvisParameter,
    IJarvisSecret,
    JarvisParameter,
    RequestInformation,
    callback,
)

from messages_shared.drafting import draft_flow
from messages_shared.guards import bound_client_or_refusal, osx_secrets
from messages_shared.osx_client import OsxApiError
from messages_shared.speaker import service_error_response
from messages_shared.threads import LAST_THREAD_KEY, match_chat, storage
from messages_shared.phrasing import chat_label

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


class DraftReplyCommand(IJarvisCommand):
    """Draft a reply to a text; sending requires spoken approval."""

    @property
    def command_name(self) -> str:
        return "draft_reply"

    @property
    def description(self) -> str:
        return (
            "Draft a reply to a text message conversation (optionally following "
            "an instruction like 'tell her I'm running late'). The draft is read "
            "aloud for approval — nothing is sent until the user says to send it."
        )

    @property
    def keywords(self) -> List[str]:
        return ["reply", "respond", "text back", "tell", "answer", "write back", "send"]

    @property
    def is_risky(self) -> bool:
        """Sending as the user is the highest-stakes verb in the stack."""
        return True

    @property
    def parameters(self) -> List[IJarvisParameter]:
        return [
            JarvisParameter(
                "contact",
                "string",
                required=False,
                description="Who to reply to (omit to use the conversation just read)",
            ),
            JarvisParameter(
                "instruction",
                "string",
                required=False,
                description=(
                    "What the reply should say, as the user phrased it, e.g. "
                    "'tell her I'm running late', 'say yes sounds good'"
                ),
            ),
        ]

    @property
    def required_secrets(self) -> List[IJarvisSecret]:
        return osx_secrets()

    @property
    def rules(self) -> List[str]:
        return [
            "'reply that X / tell them X / text her back saying X' -> instruction=X",
            "'reply to Sarah ...' -> contact=Sarah; bare 'reply to it' after reading -> omit contact",
            "NEVER claim a message was sent — the command reports send status itself.",
        ]

    def generate_prompt_examples(self) -> List[CommandExample]:
        return [
            CommandExample(
                "Reply that I'm running late",
                {"instruction": "I'm running late"},
                is_primary=True,
            ),
            CommandExample("Tell Sarah I'll be there in ten", {"contact": "Sarah", "instruction": "I'll be there in ten"}),
            CommandExample("Text her back", {}),
            CommandExample("Reply to Mom saying yes that works", {"contact": "Mom", "instruction": "yes that works"}),
        ]

    def generate_adapter_examples(self) -> List[CommandExample]:
        pairs: list[tuple[str, dict]] = [
            ("Reply that I'm running late", {"instruction": "I'm running late"}),
            ("Tell her I'm on my way", {"instruction": "I'm on my way"}),
            ("Text him back saying sounds good", {"instruction": "sounds good"}),
            ("Reply to Sarah that dinner works", {"contact": "Sarah", "instruction": "dinner works"}),
            ("Tell Mom I'll call her tonight", {"contact": "Mom", "instruction": "I'll call her tonight"}),
            ("Write back that I can't make it", {"instruction": "I can't make it"}),
            ("Respond with yes please", {"instruction": "yes please"}),
            ("Reply to that text", {}),
            ("Text her back", {}),
            ("Draft a reply to Dave", {"contact": "Dave"}),
            ("Answer the message from Grandma", {"contact": "Grandma"}),
        ]
        return [
            CommandExample(voice, params, is_primary=(i == 0))
            for i, (voice, params) in enumerate(pairs)
        ]

    def run(self, request_info: RequestInformation, **kwargs: Any) -> CommandResponse:
        client, refusal = bound_client_or_refusal(request_info)
        if refusal:
            return refusal

        contact = kwargs.get("contact")
        chat_id: str | None = None
        label: str | None = None
        if contact:
            try:
                chats = client.unread().get("chats") or []
            except OsxApiError as exc:
                return service_error_response(str(exc))
            chat = match_chat(chats, None, contact)
            if chat is not None:
                chat_id, label = chat["chat_id"], chat_label(chat)
            else:
                last = storage().get(LAST_THREAD_KEY)
                if last and _labels_overlap(contact, last.get("label")):
                    chat_id, label = last["chat_id"], last.get("label")
                else:
                    return CommandResponse.error_response(
                        error_details=f"No conversation found for contact '{contact}'.",
                        context_data={
                            "error": "no_thread_context",
                            "message": (
                                f"I don't see a conversation with {contact} to reply to — "
                                "ask me to read their text first."
                            ),
                        },
                    )
        # chat_id=None falls back to the last-read thread inside draft_flow.
        return draft_flow(client, chat_id=chat_id, label=label, instruction=kwargs.get("instruction"))

    @callback("send")
    def send_draft(self, data: dict, request_info: RequestInformation) -> CommandResponse:
        client, refusal = bound_client_or_refusal(request_info)
        if refusal:
            return refusal

        selected = (data or {}).get("selected") or []
        if not selected:
            return CommandResponse.error_response(
                error_details="send callback with no selected item",
                context_data={"error": "no_selection", "message": "I'm not sure which draft to send."},
            )
        ref_id = selected[0].get("key")
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
        try:
            result = client.send(record["chat_id"], record["draft"])
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
            storage().delete(ref_id)  # spent — a second "send it" must not double-send
            return CommandResponse.success_response(
                context_data={"message": spoken, "status": status}, wait_for_input=False
            )
        return CommandResponse.error_response(
            error_details=f"send returned status={status}: {result.get('detail')}",
            context_data={"error": status, "message": spoken},
        )


def _labels_overlap(contact: str, label: str | None) -> bool:
    if not label:
        return False
    contact_tokens = {t for t in contact.lower().split() if t}
    label_tokens = {t for t in label.lower().split() if t}
    return bool(contact_tokens & label_tokens)
