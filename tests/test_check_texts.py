from commands.check_texts.command import CheckTextsCommand

from tests.conftest import chat, message, request_info, unreachable


def test_summary_and_items(speaker, osx):
    osx.unread_payload = {
        "total": 3,
        "chats": [
            chat("cS", [message("g1", "hi", sender_name="Sarah"), message("g2", "yo", sender_name="Sarah")]),
            chat("cM", [message("g3", "call me", sender_name="Mom")]),
        ],
    }
    response = CheckTextsCommand().run(request_info())
    assert response.success
    assert response.context_data["message"] == (
        "You have three new texts: two from Sarah and one from Mom."
    )
    items = response.referenceable_items
    assert [i.ref_id for i in items] == ["cS", "cM"]
    assert all(i.actions == ["read_thread"] for i in items)
    assert items[0].attrs["chat_id"] == "cS"
    # listing must NOT touch the read-aloud ledger
    assert osx.mark_read_calls == []


def test_no_unread_closes_turn(speaker, osx):
    response = CheckTextsCommand().run(request_info())
    assert response.success
    assert response.context_data["message"] == "No new texts."
    assert response.wait_for_input is False
    assert not response.referenceable_items


def test_unreachable_mac(speaker, osx):
    osx.unread_error = unreachable()
    response = CheckTextsCommand().run(request_info())
    assert response.success is False
    assert response.context_data["error"] == "osx_api_unreachable"
    assert "couldn't reach your Mac" in response.context_data["message"]


def test_read_thread_callback_dispatches(speaker, osx):
    osx.unread_payload = {
        "total": 1,
        "chats": [chat("cS", [message("g1", "you around?", sender_name="Sarah")])],
    }
    command = CheckTextsCommand()
    assert "read_thread" in command.get_callbacks()
    response = command.get_callbacks()["read_thread"](
        {"action": "read_thread", "selected": [{"chat_id": "cS", "key": "cS"}]},
        request_info(),
    )
    assert "Sarah said: you around?" in response.context_data["message"]
    assert osx.mark_read_calls == [["g1"]]
