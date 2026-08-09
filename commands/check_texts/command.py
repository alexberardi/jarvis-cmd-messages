"""check_texts — "Hey Jarvis, do I have any new texts?"

Pull-only (PRD decision #2): answers from the speaker's osx-api unread view
(chat.db is_read + the service's read-aloud ledger). Never marks anything
read — that happens in read_thread AFTER a text is actually spoken.
"""

from __future__ import annotations

from typing import Any, List

from jarvis_command_sdk import (
    CommandExample,
    CommandResponse,
    IJarvisCommand,
    IJarvisParameter,
    IJarvisSecret,
    ReferenceableItem,
    RequestInformation,
)

from messages_shared.guards import ThreadCallbacksMixin, bound_client_or_refusal, osx_secrets
from messages_shared.osx_client import OsxApiError
from messages_shared.phrasing import chat_label, summarize_unread
from messages_shared.speaker import service_error_response


class CheckTextsCommand(ThreadCallbacksMixin, IJarvisCommand):
    """Summarize unread iMessages, grouped by sender."""

    @property
    def command_name(self) -> str:
        return "check_texts"

    @property
    def description(self) -> str:
        return (
            "Check whether the speaker has any new (unread) text messages / "
            "iMessages, and from whom. Use for 'do I have any new texts', "
            "'any messages?', 'did anyone text me'. Does not read message "
            "bodies aloud — that's read_thread."
        )

    @property
    def keywords(self) -> List[str]:
        return ["text", "texts", "message", "messages", "imessage", "texted", "unread"]

    @property
    def parameters(self) -> List[IJarvisParameter]:
        return []

    @property
    def required_secrets(self) -> List[IJarvisSecret]:
        return osx_secrets()

    @property
    def rules(self) -> List[str]:
        return [
            "'do I have any new texts / any messages / did anyone text me' -> check_texts",
            "'read it / read the one from X' after a check -> act on the shown item or read_thread",
        ]

    def generate_prompt_examples(self) -> List[CommandExample]:
        return [
            CommandExample("Do I have any new texts?", {}, is_primary=True),
            CommandExample("Any new messages?", {}),
            CommandExample("Did anyone text me?", {}),
            CommandExample("Check my texts", {}),
        ]

    def generate_adapter_examples(self) -> List[CommandExample]:
        phrases = [
            "Do I have any new texts?",
            "Any new texts?",
            "Any new messages?",
            "Did anyone text me?",
            "Did I get any texts?",
            "Check my messages",
            "Check my texts",
            "Do I have unread messages?",
            "Has anyone texted me today?",
            "Are there any texts I haven't read?",
            "Any iMessages for me?",
            "What texts did I miss?",
        ]
        return [CommandExample(p, {}, is_primary=(i == 0)) for i, p in enumerate(phrases)]

    def run(self, request_info: RequestInformation, **kwargs: Any) -> CommandResponse:
        client, refusal = bound_client_or_refusal(request_info)
        if refusal:
            return refusal
        try:
            unread = client.unread()
        except OsxApiError as exc:
            return service_error_response(str(exc))

        chats = unread.get("chats") or []
        message = summarize_unread(chats)
        if not chats:
            return CommandResponse.success_response(
                context_data={"message": message}, wait_for_input=False
            )
        items = [
            ReferenceableItem(
                ref_id=str(chat["chat_id"]),
                label=f"texts from {chat_label(chat)}",
                attrs={"chat_id": chat["chat_id"], "label": chat_label(chat)},
                actions=["read_thread"],
            )
            for chat in chats
        ]
        return CommandResponse.with_items(message, items, context_data={"total": unread.get("total")})
