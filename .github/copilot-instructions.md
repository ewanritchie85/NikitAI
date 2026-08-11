## Context log

This project maintains `LLM_CONTEXT_LOG.md` at the repo root — a rolling,
high-signal summary of architecture, priorities, and recent changes, meant
to give any coding assistant (Copilot, opencode, etc.) immediate context
without re-discovering the codebase from scratch each session.

After any meaningful code change, append a new entry to
`LLM_CONTEXT_LOG.md` under "Change Log Entries" following the format
already defined in that file's "Update Protocol" section (Date, Scope,
Summary, Why, Impact, Validation, Follow-ups). Keep entries factual and
short — prefer file paths over long prose.

If a change affects the "Current Snapshot", "Architecture", "Safety +
Auth Boundaries", or "Active Priorities" sections, update those sections
directly rather than only relying on the change log to convey it.