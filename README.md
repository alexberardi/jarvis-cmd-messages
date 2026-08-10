# jarvis-cmd-messages

Voice verbs for iMessage via a [jarvis-osx-api](../jarvis-osx-api) instance on
the speaker's Mac. Design doc: `jarvis/prds/osx-api.md`.

**The loop:** "any new texts?" → `check_texts` → "read the one from Sarah" →
`read_thread` (marks read-aloud only AFTER speaking) → "reply that I'm running
late" → `draft_reply` composes via the node's `ask_llm`, stores the exact
draft by ref_id, reads it verbatim, and asks **"want me to send this, or edit
it yourself?"**:

- **"Send"** — delivered immediately by voice. The read-aloud + direct
  question is the confirmation: the draft item is recorded with
  `confirm_offered: True`, which is what the node's destructive-action gate
  requires to dispatch a voice `send` (jarvis-node-setup PR #104). The voice
  path always sends the STORED draft verbatim.
- **"Edit"** — an editable card is pushed to the speaker's phone (email's
  `editable_text` pattern); its Send tap delivers the human-edited text.
  Dismiss drops the stored draft.

Only a chat.db-verified send is ever reported as "Sent"; every other status
(unverified/failed/group) is phrased honestly.

**Speaker binding (per-user secrets, hard refusal without them):**
`user_osx_api_instance_url` + `user_osx_api_api_key` — set per user in the app;
secrets are node-local.

## Tests

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ../jarvis-command-sdk requests pytest
.venv/bin/python -m pytest -q   # 46 tests, no network / no node runtime needed
```
