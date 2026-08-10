"""draft_reply — compose a reply, then send-by-voice or edit-on-phone.

The full human-in-the-loop send (PRD decisions #5/#14, final):

1. run() composes the draft IN-COMMAND via the node's generic `ask_llm`
   primitive (resolved PRD Q6), stores the EXACT text in JarvisStorage keyed
   by ref_id, and speaks it verbatim ending with the direct question
   "want me to send this, or edit it yourself?".
2. Spoken "send" -> act_on_items dispatches the "send" callback (mixin). The
   node's destructive-action gate allows it ONLY because the draft item's
   RECORDED attrs carry confirm_offered=True — set by us precisely because
   step 1 asked the direct question, making the user's reply the
   confirmation. The send uses the STORED draft (never LLM re-emission).
3. Spoken "edit" -> the "edit" callback pushes an EDITABLE card to the
   speaker's phone (email's editable_text pattern); its Send tap delivers the
   human-edited text — allowed by the exact-text rule, which forbids LLM
   paraphrase, not human authorship. Dismiss drops the stored draft.
4. Every send is chat.db-verified by osx-api before being reported as "Sent";
   all other statuses are phrased honestly.

All callbacks live on messages_shared.guards.ThreadCallbacksMixin (shared
with the other verbs because item ownership follows whichever command
surfaced the item). See messages_shared/drafting.py for the verified card /
tap dispatch chain and the editable-text round-trip file:line references.
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
)

from messages_shared.drafting import draft_flow
from messages_shared.guards import ThreadCallbacksMixin, bound_client_or_refusal, osx_secrets
from messages_shared.osx_client import OsxApiError
from messages_shared.phrasing import chat_label
from messages_shared.speaker import service_error_response
from messages_shared.threads import LAST_THREAD_KEY, match_chat, storage


class DraftReplyCommand(ThreadCallbacksMixin, IJarvisCommand):
    """Draft a reply to a text; send by voice or edit on the phone."""

    @property
    def command_name(self) -> str:
        return "draft_reply"

    @property
    def description(self) -> str:
        return (
            "Draft a reply to a text message conversation (optionally following "
            "an instruction like 'tell her I'm running late'). The draft is read "
            "aloud; the user then says to send it, or edits it on their phone."
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
            "After a draft is read aloud: 'send it / yes send' -> act_on_items action='send' on the "
            "shown draft; 'let me edit it / I'll tweak it' -> act_on_items action='edit'.",
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


def _labels_overlap(contact: str, label: str | None) -> bool:
    if not label:
        return False
    contact_tokens = {t for t in contact.lower().split() if t}
    label_tokens = {t for t in label.lower().split() if t}
    return bool(contact_tokens & label_tokens)
