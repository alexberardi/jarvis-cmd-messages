"""The send approval callback: stored-draft-only, honest status mapping."""

from commands.draft_reply.command import DraftReplyCommand
from messages_shared.drafting import draft_ref_id
from messages_shared.threads import storage

from tests.conftest import request_info


def _stored_draft(chat_id="cS", label="Sarah", text="Be there in 10!"):
    ref_id = draft_ref_id(chat_id)
    storage().save(ref_id, {"draft": text, "chat_id": chat_id, "label": label})
    return ref_id


def _send(command, ref_id):
    return command.send_draft(
        {"action": "send", "selected": [{"key": ref_id, "chat_id": "cS", "label": "Sarah"}]},
        request_info(),
    )


def test_sends_stored_text_never_llm_text(speaker, osx):
    ref_id = _stored_draft(text="Exact stored draft.")
    response = _send(DraftReplyCommand(), ref_id)
    assert response.success
    assert osx.send_calls == [("cS", "Exact stored draft.")]
    assert response.context_data["message"] == "Sent to Sarah."
    # spent: a second "send it" must not double-send
    assert storage().get(ref_id) is None


def test_unverified_is_not_reported_as_sent(speaker, osx):
    ref_id = _stored_draft()
    osx.send_result = {"status": "unverified", "detail": "no row in chat.db"}
    response = _send(DraftReplyCommand(), ref_id)
    assert response.success is False
    assert "couldn't confirm it actually went through" in response.context_data["message"]
    assert storage().get(ref_id) is not None  # kept for a retry


def test_group_and_failure_statuses_spoken_honestly(speaker, osx):
    for status, phrase in [
        ("group_unsupported", "group chats"),
        ("send_failed", "didn't go through"),
        ("no_such_chat", "couldn't find that conversation"),
    ]:
        ref_id = _stored_draft()
        osx.send_result = {"status": status}
        response = _send(DraftReplyCommand(), ref_id)
        assert response.success is False, status
        assert phrase in response.context_data["message"], status


def test_expired_draft(speaker, osx):
    response = _send(DraftReplyCommand(), "draft:ghost")
    assert response.success is False
    assert response.context_data["error"] == "draft_expired"
    assert osx.send_calls == []


def test_unreachable_mac_says_nothing_was_sent(speaker, osx):
    from tests.conftest import unreachable

    ref_id = _stored_draft()
    osx.send_error = unreachable()
    response = _send(DraftReplyCommand(), ref_id)
    assert response.success is False
    assert "nothing was sent" in response.context_data["message"]
