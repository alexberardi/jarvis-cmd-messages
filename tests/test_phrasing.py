from messages_shared.phrasing import collapse_bursts, count_word, summarize_unread

from tests.conftest import chat, message


def test_count_word():
    assert count_word(1) == "one"
    assert count_word(9) == "nine"
    assert count_word(12) == "12"


def test_collapse_bursts_merges_consecutive_same_sender():
    msgs = [
        message("g1", "hey", sender_name="Sarah"),
        message("g2", "you around?", sender_name="Sarah"),
        message("g3", "sure am", is_from_me=True),
        message("g4", "cool!", sender_name="Sarah"),
    ]
    bursts = collapse_bursts(msgs)
    assert [b["sender"] for b in bursts] == ["Sarah", "you", "Sarah"]
    assert bursts[0]["text"] == "hey. you around?"
    assert bursts[0]["guids"] == ["g1", "g2"]


def test_collapse_bursts_no_double_punctuation():
    msgs = [
        message("g1", "Done!", sender_name="Sarah"),
        message("g2", "See you soon.", sender_name="Sarah"),
    ]
    assert collapse_bursts(msgs)[0]["text"] == "Done! See you soon."


def test_collapse_bursts_uses_spoken_text_and_skips_empty():
    msgs = [
        message("g1", "raw url http://x", sender_name="Sarah", spoken_text="raw url [a link]"),
        message("g2", "", sender_name="Sarah", spoken_text=""),
    ]
    bursts = collapse_bursts(msgs)
    assert len(bursts) == 1
    assert bursts[0]["text"] == "raw url [a link]"


def test_summarize_unread_single_chat():
    chats = [chat("c1", [message("g1", "hi", sender_name="Sarah"), message("g2", "yo", sender_name="Sarah")])]
    assert summarize_unread(chats) == "You have two new texts from Sarah."


def test_summarize_unread_multiple_chats():
    chats = [
        chat("c1", [message("g1", "hi", sender_name="Sarah"), message("g2", "yo", sender_name="Sarah")]),
        chat("c2", [message("g3", "call me", sender_name="Mom")]),
    ]
    assert summarize_unread(chats) == "You have three new texts: two from Sarah and one from Mom."


def test_summarize_unread_empty():
    assert summarize_unread([]) == "No new texts."
