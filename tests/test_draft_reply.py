from commands.draft_reply.command import DraftReplyCommand
from messages_shared.drafting import draft_ref_id
from messages_shared.threads import LAST_THREAD_KEY, storage

from tests.conftest import chat, message, request_info


def _seed_last_thread(osx, chat_id="cS", label="Sarah"):
    storage().save(LAST_THREAD_KEY, {"chat_id": chat_id, "label": label})
    osx.threads[chat_id] = {
        "messages": [
            message("g1", "you around tonight?", sender_name=label),
        ]
    }
    osx.styles[chat_id] = {"messages": ["omw!", "yeah for sure", "lol ok"], "sparse": False}


def test_draft_stored_exactly_and_spoken_verbatim(speaker, osx, fake_ask_llm):
    _seed_last_thread(osx)
    fake_ask_llm["state"]["reply"] = '"Yes! Be there at 8."'
    response = DraftReplyCommand().run(request_info(), instruction="say yes, 8pm")
    assert response.success
    stored = storage().get(draft_ref_id("cS"))
    assert stored["draft"] == "Yes! Be there at 8."  # noise-stripped, exact
    assert '"Yes! Be there at 8."' in response.context_data["message"]
    assert response.context_data["message"].endswith("want me to send it?")
    items = response.referenceable_items
    assert items[0].ref_id == draft_ref_id("cS")
    assert items[0].actions == ["send"]


def test_prompt_carries_style_thread_and_instruction(speaker, osx, fake_ask_llm):
    _seed_last_thread(osx)
    DraftReplyCommand().run(request_info(), instruction="tell her I'm running late")
    prompt = fake_ask_llm["calls"][0]["prompt"]
    assert "Sarah: you around tonight?" in prompt
    assert "omw!" in prompt  # style few-shots present
    assert "tell her I'm running late" in prompt


def test_sparse_style_uses_neutral_tone(speaker, osx, fake_ask_llm):
    _seed_last_thread(osx)
    osx.styles["cS"] = {"messages": [], "sparse": True}
    DraftReplyCommand().run(request_info())
    assert "neutral, casual texting tone" in fake_ask_llm["calls"][0]["prompt"]


def test_ask_llm_unavailable_fails_closed(speaker, osx):
    # No fake_ask_llm fixture -> the guarded import fails -> spoken error.
    _seed_last_thread(osx)
    response = DraftReplyCommand().run(request_info())
    assert response.success is False
    assert response.context_data["error"] == "draft_failed"
    assert storage().get(draft_ref_id("cS")) is None


def test_no_thread_context(speaker, osx, fake_ask_llm):
    response = DraftReplyCommand().run(request_info())
    assert response.success is False
    assert response.context_data["error"] == "no_thread_context"


def test_contact_resolves_via_unread(speaker, osx, fake_ask_llm):
    osx.unread_payload = {
        "total": 1,
        "chats": [chat("cM", [message("g3", "call me", sender_name="Mom")])],
    }
    osx.threads["cM"] = {"messages": [message("g3", "call me", sender_name="Mom")]}
    response = DraftReplyCommand().run(request_info(), contact="Mom", instruction="I'll call tonight")
    assert response.success
    assert storage().get(draft_ref_id("cM"))["label"] == "Mom"
