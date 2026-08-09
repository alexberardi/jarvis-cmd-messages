"""Voice phrasing helpers — the CC-side half of sanitization (PRD open Q4).

The service already replaced attachments/URLs in `spoken_text`; here we
collapse the N-messages-in-a-row texting style into one utterance per
sender-burst and phrase unread summaries.
"""

from __future__ import annotations

_COUNT_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine",
}


def count_word(n: int) -> str:
    return _COUNT_WORDS.get(n, str(n))


def sender_label(message: dict, chat: dict | None = None) -> str:
    if message.get("is_from_me"):
        return "you"
    if message.get("sender_name"):
        return str(message["sender_name"])
    if chat and chat.get("display_name"):
        return str(chat["display_name"])
    return str(message.get("sender_handle") or "someone")


def collapse_bursts(messages: list[dict], chat: dict | None = None) -> list[dict]:
    """Merge consecutive messages from the same sender into one utterance.

    Returns [{"sender": label, "text": joined spoken text, "guids": [...]}].
    """
    bursts: list[dict] = []
    for message in messages:
        label = sender_label(message, chat)
        text = str(message.get("spoken_text") or message.get("text") or "").strip()
        if not text:
            continue
        if bursts and bursts[-1]["sender"] == label:
            bursts[-1]["text"] = _join_utterances(bursts[-1]["text"], text)
            bursts[-1]["guids"].append(message.get("guid"))
        else:
            bursts.append({"sender": label, "text": text, "guids": [message.get("guid")]})
    return bursts


def _join_utterances(first: str, second: str) -> str:
    if first and first[-1] not in ".!?…":
        return f"{first}. {second}"
    return f"{first} {second}"


def chat_label(chat: dict) -> str:
    if chat.get("display_name"):
        return str(chat["display_name"])
    messages = chat.get("messages") or []
    for message in messages:
        if message.get("sender_name"):
            return str(message["sender_name"])
    return str(chat.get("identifier") or "someone")


def summarize_unread(chats: list[dict]) -> str:
    """'You have two new texts from Sarah and one from Mom.'"""
    if not chats:
        return "No new texts."
    parts: list[str] = []
    for chat in chats:
        n = len(chat.get("messages") or [])
        label = chat_label(chat)
        parts.append(f"{count_word(n)} from {label}")
    total = sum(len(c.get("messages") or []) for c in chats)
    noun = "text" if total == 1 else "texts"
    if len(parts) == 1:
        joined = parts[0]
    elif len(parts) == 2:
        joined = f"{parts[0]} and {parts[1]}"
    else:
        joined = ", ".join(parts[:-1]) + f", and {parts[-1]}"
    return f"You have {count_word(total)} new {noun}: {joined}." if len(parts) > 1 else (
        f"You have {count_word(total)} new {noun} from {chat_label(chats[0])}."
    )
