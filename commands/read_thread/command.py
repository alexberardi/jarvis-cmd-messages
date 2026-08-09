"""read_thread — "read the one from Sarah" / "what did Mom say?"

Speaks the unread messages in one conversation (burst-collapsed, using the
service's sanitized spoken_text), then — and only then — records them in the
service's read-aloud ledger (PRD decision #12: mark after speech, never on
listing)."""

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

from messages_shared.guards import ThreadCallbacksMixin, bound_client_or_refusal, osx_secrets
from messages_shared.threads import read_thread_flow


class ReadThreadCommand(ThreadCallbacksMixin, IJarvisCommand):
    """Read a conversation's new texts aloud."""

    @property
    def command_name(self) -> str:
        return "read_thread"

    @property
    def description(self) -> str:
        return (
            "Read the speaker's new text messages from one person/conversation "
            "aloud. Use for 'read the text from Sarah', 'what did Mom say', "
            "'read my new messages'. After reading, the user can ask to reply."
        )

    @property
    def keywords(self) -> List[str]:
        return ["read", "text", "texts", "message", "messages", "said", "say"]

    @property
    def parameters(self) -> List[IJarvisParameter]:
        return [
            JarvisParameter(
                "contact",
                "string",
                required=False,
                description="Who the conversation is with (name as spoken), e.g. 'Sarah', 'Mom'",
            ),
        ]

    @property
    def required_secrets(self) -> List[IJarvisSecret]:
        return osx_secrets()

    @property
    def rules(self) -> List[str]:
        return [
            "'read the text/message from X' or 'what did X say' -> contact=X",
            "'read my new texts' with no name -> omit contact (single unread thread reads directly)",
        ]

    def generate_prompt_examples(self) -> List[CommandExample]:
        return [
            CommandExample("Read the text from Sarah", {"contact": "Sarah"}, is_primary=True),
            CommandExample("What did Mom say?", {"contact": "Mom"}),
            CommandExample("Read my new messages", {}),
            CommandExample("Can you read the one from Dave?", {"contact": "Dave"}),
        ]

    def generate_adapter_examples(self) -> List[CommandExample]:
        pairs: list[tuple[str, dict]] = [
            ("Read the text from Sarah", {"contact": "Sarah"}),
            ("Read Sarah's message", {"contact": "Sarah"}),
            ("What did Mom say?", {"contact": "Mom"}),
            ("What did Dave text me?", {"contact": "Dave"}),
            ("Read the one from Grandma", {"contact": "Grandma"}),
            ("Read my new messages", {}),
            ("Read my texts", {}),
            ("What does the message say?", {}),
            ("Read that text for me", {}),
            ("Can you read the message from my wife?", {"contact": "wife"}),
            ("Read the new text out loud", {}),
        ]
        return [
            CommandExample(voice, params, is_primary=(i == 0))
            for i, (voice, params) in enumerate(pairs)
        ]

    def run(self, request_info: RequestInformation, **kwargs: Any) -> CommandResponse:
        client, refusal = bound_client_or_refusal(request_info)
        if refusal:
            return refusal
        return read_thread_flow(client, contact=kwargs.get("contact"))
