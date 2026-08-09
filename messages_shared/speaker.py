"""Speaker resolution + hard-refusal helpers (PRD decisions #4 and #9).

Whisper only populates speaker_user_id on a confident enrolled-speaker match,
so `None` here means unknown/low-confidence — refuse. Same pattern as
jarvis-cmd-calendar's get_calendar_events (command.py:445-462).
"""

from __future__ import annotations

from typing import Any

from jarvis_command_sdk import CommandResponse, get_current_user_id


def resolve_speaker(request_info: Any) -> int | None:
    if hasattr(request_info, "user_id"):
        user_id = request_info.user_id
    elif isinstance(request_info, dict):
        user_id = request_info.get("user_id")
    else:
        user_id = None
    if user_id is None:
        user_id = get_current_user_id()
    return user_id


def refusal_unknown_speaker(what: str = "messages") -> CommandResponse:
    message = (
        f"I'm not sure whose {what} to check — I couldn't tell who's asking. "
        "Try training your voice in the app."
    )
    return CommandResponse.error_response(
        error_details="Unknown speaker — cannot resolve a personal Messages account.",
        context_data={"error": "unknown_speaker", "message": message},
    )


def refusal_unbound_speaker() -> CommandResponse:
    message = (
        "Your Mac isn't linked for messages yet. Set your Mac bridge URL and "
        "API key in the app settings first."
    )
    return CommandResponse.error_response(
        error_details="Speaker has no osx-api binding secrets set.",
        context_data={"error": "not_bound", "message": message},
    )


def service_error_response(detail: str) -> CommandResponse:
    message = "I couldn't reach your Mac to check messages. Make sure it's awake and on the network."
    return CommandResponse.error_response(
        error_details=detail,
        context_data={"error": "osx_api_unreachable", "message": message},
    )
