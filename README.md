# jarvis-cmd-messages

Voice verbs for iMessage via a [jarvis-osx-api](../jarvis-osx-api) instance on
the speaker's Mac. Design doc: `jarvis/prds/osx-api.md`.

**The loop:** "any new texts?" → `check_texts` → "read the one from Sarah" →
`read_thread` (marks read-aloud only AFTER speaking) → "reply that I'm running
late" → `draft_reply` composes via the node's `ask_llm`, stores the exact
draft by ref_id, speaks it, and posts a **Send/Dismiss card to the speaker's
phone**. **Nothing is ever sent by voice alone** (PRD revised decision #5) —
the human tap on Send is the confirmation; the `@callback("send")` re-fetches
the stored draft and only a chat.db-verified send is ever reported as "Sent."
Dismiss drops the stored draft.

**Speaker binding (per-user secrets, hard refusal without them):**
`user_osx_api_instance_url` + `user_osx_api_api_key` — set per user in the app;
secrets are node-local.

**Permanent guard:** the node's destructive-action gate refuses voice `send`
forever — by design. No item in this bundle advertises a send action to voice;
the inbox tap card (same chain as the email bundle's reply cards) is the only
send path.

## Tests

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ../jarvis-command-sdk requests pytest
.venv/bin/python -m pytest -q   # 41 tests, no network / no node runtime needed
```
