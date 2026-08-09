from commands.read_thread.command import ReadThreadCommand
from messages_shared.threads import LAST_THREAD_KEY, storage

from tests.conftest import chat, message, request_info, unreachable


def _two_chats(osx):
    osx.unread_payload = {
        "total": 3,
        "chats": [
            chat("cS", [message("g1", "hey", sender_name="Sarah"), message("g2", "you around?", sender_name="Sarah")]),
            chat("cM", [message("g3", "call me", sender_name="Mom")]),
        ],
    }


def test_reads_contact_thread_and_marks_after_speech(speaker, osx):
    _two_chats(osx)
    response = ReadThreadCommand().run(request_info(), contact="Sarah")
    assert response.success
    assert response.context_data["message"] == "Sarah said: hey. you around?"
    assert osx.mark_read_calls == [["g1", "g2"]]  # only Sarah's, only after speech
    assert response.context_data["marked_read"] is True
    # thread item offered for the reply follow-up
    items = response.referenceable_items
    assert items and items[0].actions == ["draft_reply"]
    assert items[0].attrs == {"chat_id": "cS", "label": "Sarah"}
    # last-read context stored for a bare "reply to it"
    assert storage().get(LAST_THREAD_KEY) == {"chat_id": "cS", "label": "Sarah"}


def test_no_mark_read_when_fetch_fails(speaker, osx):
    osx.unread_error = unreachable()
    response = ReadThreadCommand().run(request_info(), contact="Sarah")
    assert response.success is False
    assert osx.mark_read_calls == []


def test_mark_read_failure_still_speaks(speaker, osx):
    _two_chats(osx)
    osx.mark_read_error = unreachable()
    response = ReadThreadCommand().run(request_info(), contact="Sarah")
    assert response.success
    assert response.context_data["message"].startswith("Sarah said:")
    assert response.context_data["marked_read"] is False


def test_unknown_contact(speaker, osx):
    _two_chats(osx)
    response = ReadThreadCommand().run(request_info(), contact="Dave")
    assert response.context_data["message"] == "No new texts from Dave."


def test_multiple_chats_without_contact_asks_which(speaker, osx):
    _two_chats(osx)
    response = ReadThreadCommand().run(request_info())
    assert "Which one should I read?" in response.context_data["message"]
    assert osx.mark_read_calls == []


def test_single_chat_without_contact_reads_directly(speaker, osx):
    osx.unread_payload = {
        "total": 1,
        "chats": [chat("cM", [message("g3", "call me", sender_name="Mom")])],
    }
    response = ReadThreadCommand().run(request_info())
    assert response.context_data["message"] == "Mom said: call me"
    assert osx.mark_read_calls == [["g3"]]
