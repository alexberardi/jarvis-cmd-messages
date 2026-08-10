"""Send/edit/dismiss callbacks: voice send (act_on_items shape, stored draft
verbatim), edit-on-phone (editable card; edited text wins on tap), honest
status mapping, dismiss drops the draft."""

from commands.draft_reply.command import DraftReplyCommand
from messages_shared.drafting import draft_ref_id
from messages_shared.threads import storage

from tests.conftest import SPEAKER, request_info


def _stored_draft(chat_id="cS", label="Sarah", text="Be there in 10!"):
    ref_id = draft_ref_id(chat_id)
    storage().save(ref_id, {"draft": text, "chat_id": chat_id, "label": label})
    return ref_id


def _cb(name):
    return DraftReplyCommand().get_callbacks()[name]


def _voice_send_data(ref_id, chat_id="cS", label="Sarah"):
    """Exact act_on_items dispatch payload: recorded attrs spread + key."""
    return {
        "action": "send",
        "selected": [
            {"chat_id": chat_id, "label": label, "confirm_offered": True, "key": ref_id}
        ],
        "context": {"source_tool": "draft_reply"},
    }


class TestVoiceSend:
    def test_sends_stored_text_verbatim(self, speaker, osx):
        ref_id = _stored_draft(text="Exact stored draft.")
        response = _cb("send")(_voice_send_data(ref_id), request_info())
        assert response.success
        assert osx.send_calls == [("cS", "Exact stored draft.")]
        assert response.context_data["message"] == "Sent to Sarah."
        # spent: a second "send it" must not double-send
        assert storage().get(ref_id) is None

    def test_voice_shape_never_carries_text_override(self, speaker, osx):
        """Recorded attrs can't smuggle a text override into the send."""
        ref_id = _stored_draft(text="Stored.")
        data = _voice_send_data(ref_id)
        data["selected"][0]["text"] = "attr-smuggled"  # even if attrs had it
        _cb("send")(data, request_info())
        assert osx.send_calls == [("cS", "Stored.")]

    def test_unverified_is_not_reported_as_sent(self, speaker, osx):
        ref_id = _stored_draft()
        osx.send_result = {"status": "unverified", "detail": "no row in chat.db"}
        response = _cb("send")(_voice_send_data(ref_id), request_info())
        assert response.success is False
        assert "couldn't confirm it actually went through" in response.context_data["message"]
        assert storage().get(ref_id) is not None  # kept for a retry

    def test_group_and_failure_statuses_spoken_honestly(self, speaker, osx):
        for status, phrase in [
            ("group_unsupported", "group chats"),
            ("send_failed", "didn't go through"),
            ("no_such_chat", "couldn't find that conversation"),
        ]:
            ref_id = _stored_draft()
            osx.send_result = {"status": status}
            response = _cb("send")(_voice_send_data(ref_id), request_info())
            assert response.success is False, status
            assert phrase in response.context_data["message"], status

    def test_expired_draft(self, speaker, osx):
        response = _cb("send")(_voice_send_data("draft:ghost"), request_info())
        assert response.success is False
        assert response.context_data["error"] == "draft_expired"
        assert osx.send_calls == []

    def test_missing_ref_id(self, speaker, osx):
        response = _cb("send")({}, request_info())
        assert response.success is False
        assert response.context_data["error"] == "no_selection"
        assert osx.send_calls == []

    def test_unreachable_mac_says_nothing_was_sent(self, speaker, osx):
        from tests.conftest import unreachable

        ref_id = _stored_draft()
        osx.send_error = unreachable()
        response = _cb("send")(_voice_send_data(ref_id), request_info())
        assert response.success is False
        assert "nothing was sent" in response.context_data["message"]


class TestEdit:
    def _edit(self, ref_id):
        data = _voice_send_data(ref_id)
        data["action"] = "edit"
        return _cb("edit")(data, request_info())

    def test_edit_posts_editable_card(self, speaker, osx, inbox):
        ref_id = _stored_draft(text="Draft body.")
        response = self._edit(ref_id)
        assert response.success
        assert "your phone" in response.context_data["message"]
        assert len(inbox.posts) == 1
        post = inbox.posts[0]
        assert post["user_id"] == SPEAKER
        assert post["target_type"] == "user"
        assert post["push"] is True
        # editor seeded from the stored draft (email's editable_text pattern)
        editable = post["metadata"]["editable_text"]
        assert editable == {"label": "Draft reply", "initial": "Draft body.", "data_key": "text"}
        elements = post["metadata"]["interactive_elements"]
        send_el, dismiss_el = elements
        assert send_el["callback"] == "send" and send_el["command"] == "draft_reply"
        # Send's data carries the data_key so mobile substitutes the edited value
        assert send_el["data"] == {"ref_id": ref_id, "text": "Draft body."}
        # Dismiss's data must NOT carry it (never picks up editor content)
        assert dismiss_el["callback"] == "dismiss_draft"
        assert dismiss_el["data"] == {"ref_id": ref_id}

    def test_edited_text_wins_on_tap(self, speaker, osx, inbox):
        """Mobile substitutes the live editor value into data['text'] at tap
        time; the human-edited text is what gets sent."""
        ref_id = _stored_draft(text="Original draft.")
        self._edit(ref_id)
        response = _cb("send")({"ref_id": ref_id, "text": "Edited by hand!"}, request_info())
        assert response.success
        assert osx.send_calls == [("cS", "Edited by hand!")]
        assert storage().get(ref_id) is None  # spent after verified send

    def test_tap_without_text_falls_back_to_stored_draft(self, speaker, osx):
        for payload_extra in ({}, {"text": "  "}):
            osx.send_calls.clear()
            ref_id = _stored_draft(text="Stored draft.")
            response = _cb("send")({"ref_id": ref_id, **payload_extra}, request_info())
            assert response.success
            assert osx.send_calls == [("cS", "Stored draft.")]

    def test_edit_expired_draft(self, speaker, osx, inbox):
        response = self._edit("draft:ghost")
        assert response.success is False
        assert response.context_data["error"] == "draft_expired"
        assert inbox.posts == []

    def test_edit_card_post_failure_is_honest_and_keeps_draft(self, speaker, osx):
        # No inbox fixture -> post() returns "no_backend".
        ref_id = _stored_draft()
        response = self._edit(ref_id)
        assert response.success is False
        assert response.context_data["error"] == "card_post_failed"
        assert "nothing was sent" in response.context_data["message"]
        assert storage().get(ref_id) is not None  # voice "send it as is" still works


class TestDismiss:
    def test_dismiss_drops_stored_draft(self, backend):
        ref_id = _stored_draft()
        response = _cb("dismiss_draft")({"ref_id": ref_id}, request_info())
        assert response.success
        assert response.context_data["message"] == "Discarded the draft to Sarah."
        assert storage().get(ref_id) is None

    def test_dismiss_is_idempotent(self, backend):
        response = _cb("dismiss_draft")({"ref_id": "draft:ghost"}, request_info())
        assert response.success
        assert response.context_data["message"] == "That draft was already gone."

    def test_dismissed_draft_cannot_be_sent(self, speaker, osx):
        ref_id = _stored_draft()
        _cb("dismiss_draft")({"ref_id": ref_id}, request_info())
        response = _cb("send")(_voice_send_data(ref_id), request_info())
        assert response.success is False
        assert response.context_data["error"] == "draft_expired"
        assert osx.send_calls == []
