"""PRD decisions #4 + #9: unknown speaker OR missing binding secrets = hard
refusal on every verb, before any osx-api traffic."""

import pytest
from jarvis_command_sdk.context import set_current_user_id

from commands.check_texts.command import CheckTextsCommand
from commands.draft_reply.command import DraftReplyCommand
from commands.read_thread.command import ReadThreadCommand

from tests.conftest import request_info

COMMANDS = [CheckTextsCommand, ReadThreadCommand, DraftReplyCommand]


@pytest.mark.parametrize("command_cls", COMMANDS)
def test_unknown_speaker_refused(backend, command_cls):
    set_current_user_id(None)
    response = command_cls().run(request_info(user_id=None))
    assert response.success is False
    assert response.context_data["error"] == "unknown_speaker"
    assert "couldn't tell who's asking" in response.context_data["message"]


@pytest.mark.parametrize("command_cls", COMMANDS)
def test_missing_secrets_refused(backend, command_cls):
    set_current_user_id(7)
    try:
        response = command_cls().run(request_info(user_id=7))
    finally:
        set_current_user_id(None)
    assert response.success is False
    assert response.context_data["error"] == "not_bound"
    assert "isn't linked" in response.context_data["message"]


def test_send_callback_also_refuses_unknown_speaker(backend):
    set_current_user_id(None)
    response = DraftReplyCommand().send_draft({"ref_id": "draft:x"}, request_info(user_id=None))
    assert response.success is False
    assert response.context_data["error"] == "unknown_speaker"
