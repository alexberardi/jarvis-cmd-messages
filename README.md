# jarvis-cmd-messages

Voice verbs for iMessage via a [jarvis-osx-api](../jarvis-osx-api) instance on
the speaker's Mac. Design doc: `jarvis/prds/osx-api.md`.

**The loop:** "any new texts?" → `check_texts` → "read the one from Sarah" →
`read_thread` (marks read-aloud only AFTER speaking) → "reply that I'm running
late" → `draft_reply` (composes via the node's `ask_llm`, stores the exact
draft by ref_id, asks "want me to send it?") → "yes, send it" →
`@callback("send")` re-fetches the stored draft and sends. Only a chat.db-
verified send is ever reported as "Sent."

**Speaker binding (per-user secrets, hard refusal without them):**
`user_osx_api_instance_url` + `user_osx_api_api_key` — set per user in the app;
secrets are node-local.

**Known gate:** voice "send" is refused by the node's destructive-action gate
until the confirmation round-trip lands in jarvis-node-setup (the
draft-approval turn is the confirmation — PRD decision #14). Do not rename the
action to bypass it.

## Tests

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ../jarvis-command-sdk requests pytest
.venv/bin/python -m pytest -q   # 35 tests, no network / no node runtime needed
```
