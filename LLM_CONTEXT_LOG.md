# NikitAI Rolling Context Log

Purpose: single-file, high-signal project state for IDE LLMs and humans.

Last updated: 2026-08-13
Owner: project maintainers + any active coding agent

## 1. Current Snapshot

- Project: NikitAI
- Package: nikitai
- Version: 0.1.0
- Python: >=3.8
- Main branch: main
- Last known commit: bd1ce78 (readme and .env.example updated)
- Working tree status at log creation: clean

## 2. What This Project Does

NikitAI is an AI-powered assistant that integrates with Microsoft Graph (Outlook mail/calendar) and Anthropic models.

Core capabilities currently in repo:
- Read/search mailbox content
- Summarize calendar and mailbox context
- Create/send emails (approval-gated)
- Create calendar events (approval-gated)
- Manage mail folders (list/create/delete; destructive actions are gated)
- Web UI + CLI interfaces over shared agent logic

## 3. Architecture At A Glance

- Core package: src/nikitai/
- Entrypoints:
  - CLI runtime: src/nikitai/cli.py and src/nikitai/__main__.py
  - Web runtime: src/nikitai/web.py
- Orchestrator (routing layer): src/nikitai/orchestrator.py
- Agent (domain-agnostic worker): src/nikitai/agent.py — ONLY Agent, PendingConfirmation,
  AgentResponse, build_system_prompt(), resolve_model() (+ DEFAULT_MODEL, UK_TIMEZONE,
  ToolDispatcher). No Outlook/Platform Nerd content, and no routing/classification logic.
- Sub-agent configs: src/nikitai/subagents/ (package)
  - subagents/organiser.py: Outlook prompt/tools/_execute_tool/outlook_agent_config()
  - subagents/platform_nerd.py: Platform Nerd prompt/tools/_execute_platform_nerd_tool/
    platform_nerd_agent_config()
- Auth/token handling: src/nikitai/auth.py
- Outlook/Graph tools: src/nikitai/tools/outlook.py
- Home-infra notes tools: src/nikitai/tools/logs.py (Platform Nerd's read/append tools)
- Static web assets: src/nikitai/static/ (index.html, script.js, style.css, and
  vendor/ hosting the vendored marked + DOMPurify min builds - no CDN dependency)
- Tests: tests/ (test_agent = core; test_organiser / test_platform_nerd = sub-agent configs)

Design notes:
- Two-layer design: a top-level "NikitAI" Orchestrator routes each message to a
  domain sub-agent, each backed by the generalized Agent class.
- Orchestrator (src/nikitai/orchestrator.py):
  - SubAgentSpec(key, display_name, description, config_factory) describes a
    registered sub-agent; SUB_AGENT_REGISTRY maps key -> spec.
  - Registry holds "organiser" -> subagents.organiser.outlook_agent_config()
    (NikitAI Organiser) and "platform_nerd" ->
    subagents.platform_nerd.platform_nerd_agent_config() (NikitAI Platform Nerd: home
    network / self-hosting / Raspberry Pi / general networking, backed by
    tools/logs.py). Each factory has exactly ONE canonical import path — its own
    subagents module; orchestrator imports them only to populate the registry and
    does NOT re-export them. resolve_router_model() / DEFAULT_ROUTER_MODEL live in
    orchestrator.py (routing is an orchestrator concern, not core Agent infra).
    "trainer" (Garmin) is still registered-but-unimplemented:
    it exists ONLY as a clearly-marked commented placeholder in orchestrator.py,
    with no config factory yet — do not add it to the live registry until built.
  - send(): a cheap classification call (resolve_router_model():
    NIKITAI_ROUTER_MODEL → NIKITAI_DEFAULT_MODEL → "claude-haiku-4-5") picks a
    registered key or "unclear". A known key is dispatched to that sub-agent's
    Agent.send(); "unclear"/unknown returns a clarifying question naming only
    active sub-agents (never a default fallthrough).
  - send() sticky routing: if a sub-agent has a live PendingConfirmation (the
    pending_id -> key map is non-empty), the message skips classification and routes
    straight to that sub-agent's Agent.resolve_pending_reply(), which resolves it by
    strict pattern matching (classify_confirmation_reply()/phrase sets in agent.py) —
    affirm executes, negate cancels, anything else clears the pending (implicit
    cancel) and the message is re-classified fresh.
  - send() last-active fallback: _last_active_key records the most recently routed
    sub-agent key (set at the end of every send() that reaches a sub-agent, sticky or
    classified). If the classifier returns "unclear"/an unregistered key, the message
    routes to the last-active sub-agent instead of the clarification prompt (which
    only appears when no sub-agent has ever been active). A confidently classified
    registered key always wins over the fallback. Distinct from sticky-pending
    routing; together they enable conversational-confirm -> button-confirm UX.
  - confirm(): routed to the originating sub-agent via a pending_id -> key map
    (populated whenever send()/confirm() returns a pending), never re-classified.
  - One Agent per sub-agent is lazily constructed on first use (same lazy pattern
    web.get_agent() used before).
- Agent is domain-agnostic: parameterized by system_prompt, tool_definitions,
  tool_dispatcher, confirmation_required_tools, and model. Outlook wiring lives in
  subagents/organiser.py (outlook_agent_config, dispatcher _execute_tool); Platform
  Nerd wiring in subagents/platform_nerd.py (platform_nerd_agent_config, dispatcher
  _execute_platform_nerd_tool -> tools/logs.py; gated tool set {"append_to_log"},
  read tools ungated). Sub-agent configs import build_system_prompt/resolve_model
  from agent.py.
- Platform Nerd notes access (src/nikitai/tools/logs.py): list_log_files /
  read_log_file / append_to_log operate on .txt files inside NIKITAI_HOME_INFRA_NOTES_DIR
  (env, no default — raises if unset). All paths are resolved and confirmed inside that
  dir (rejects ../, absolute paths, and symlinks escaping the dir). append_to_log is
  pure-append only: never creates/truncates/overwrites, requires an existing .txt file.
- Model selection is per sub-agent via agent.resolve_model(specific_env_var):
  specific override → NIKITAI_DEFAULT_MODEL → agent.DEFAULT_MODEL ("claude-sonnet-5").
  organiser uses NIKITAI_ORGANISER_MODEL; platform_nerd uses NIKITAI_PLATFORM_NERD_MODEL;
  a future trainer would use NIKITAI_TRAINER_MODEL. The legacy NIKITAI_MODEL var is no
  longer read anywhere.
- cli.py and web.py now construct a single lazy Orchestrator (not a single Agent).
  web.get_agent() returns the Orchestrator; route handler shapes are unchanged.
- Approval-required operations return pending confirmation state instead of auto-executing.
- Web app is local-first, single-session style, with explicit approve/deny flow.

## 4. Safety + Auth Boundaries

- Approval gates are expected for high-impact actions (for example sending mail, deleting folders, creating events, appending to infra notes).
- Graph delegated permissions include mail/calendar scopes; local token cache is used.
- Platform Nerd file access is confined to NIKITAI_HOME_INFRA_NOTES_DIR: path traversal / absolute / symlink-escape rejected; append is pure-append to existing .txt files only (no create/overwrite/delete). append_to_log is confirmation-gated.
- Current TODO indicates app-level auth for web access is still pending before external exposure.

## 5. Build, Test, and Quality Commands

Primary Make targets:
- make install
- make install-dev
- make test
- make coverage
- make lint
- make format
- make format-check
- make check
- make ci
- make build
- make web

## 6. Active Priorities (From TODO)

Highest-priority sequencing currently documented:
1. App authentication for web access (login/session/logout/expiry)
2. Secure hosting path on Raspberry Pi as a separate service
3. Secure external access (TLS, reverse proxy, rate limiting, monitoring)

Parallel/secondary tracks:
- Voice control integrated into existing chat flow
- Linux/platform/networking assistant knowledge workflow
- Garmin data fitness coach integration

## 7. Recent Change Signal

Recent commits (most recent first at log creation):
- bd1ce78 readme and .env.example updated
- 7c87786 gitignore updated
- e3a7dee scroll bar colour changed ot match scheme
- 2d3c197 minor tweaks to spacing in style.css
- c76b61c formatting fixed
- a8c18dd check timezone for new calendar events removed from agent instruction
- 3d4935a html/css/js separated into index/style/script files - colour scheme updated
- 5dd3501 agent made aware of current datetime - following GMT/BST

## 8. Known Conventions and Notes

- Ruff is the formatter/linter (line length 100, target py38).
- CI path is effectively: install-dev + lint + format-check + coverage.
- Existing repo memory notes indicate previous package rename history and current module layout around confirmation flow and web integration.

## 9. Update Protocol (Important)

After each meaningful code change, append a new entry under "Change Log Entries" using this format:

- Date: YYYY-MM-DD
- Scope: files/modules changed
- Summary: what changed
- Why: reason for the change
- Impact: user-visible behavior, security, reliability, or dev workflow effects
- Validation: tests/commands run and results
- Follow-ups: remaining tasks or caveats

Keep entries factual and short. Prefer links/paths over long prose.

## 10. Change Log Entries

### 2026-08-13 - Copy-to-clipboard button on fenced code blocks in the web UI
- Scope: src/nikitai/static/script.js, src/nikitai/static/style.css, tests/test_web.py, LLM_CONTEXT_LOG.md
- Summary: After markdown rendering, each `<pre><code>` block in assistant messages gets a small top-right copy button (`addCopyButtons()` in script.js, invoked from appendMessage post-sanitize; `.code-copy-btn` inserted as an absolutely-positioned button inside the pre). Clicks are handled via one delegated listener on `#messages`, so dynamically inserted blocks work. `copyText()` uses `navigator.clipboard.writeText()` in secure contexts (localhost/HTTPS) and falls back to a hidden-textarea `document.execCommand("copy")` for plain-HTTP LAN access (Pi hosting). `flashCopyFeedback()` swaps the button to "Copied!"/"Failed" for ~1.5s (tracked per-button timer) then restores the copy icon. Styling: button is hover-revealed (opacity transition), theme-consistent (JetBrains Mono, muted text, orange hover, green `.copied` state), uses the existing `pre` with `position: relative` added.
- Why: Claude/Copilot-style code-copy UX for Platform Nerd's bash/yaml/config snippets; no external dependency required.
- Impact: fenced code blocks now have a copy affordance; raw text (not HTML) is copied via `code.textContent`; secure-context and execCommand fallbacks cover localhost and plain-HTTP LAN.
- Validation: `make test` → 139 passed (was 138; +1 web test asserting addCopyButtons/navigator.clipboard/delegated handler are present). `node --check` on script.js passes. `make lint` + `make format-check` clean.
- Follow-ups: optional syntax highlighting (highlight.js/prism) for language-aware coloring; Trainer (Garmin) sub-agent still pending.

### 2026-08-13 - Robust markdown rendering in the web UI (vendored parser + code-block CSS)
- Scope: src/nikitai/static/index.html, src/nikitai/static/script.js, src/nikitai/static/style.css, src/nikitai/static/vendor/{marked.min.js,purify.min.js} (new), tests/test_web.py, LLM_CONTEXT_LOG.md
- Summary: Assistant responses were already routed through marked + DOMPurify, but both were loaded from cdn.jsdelivr.net, so the UI broke (or fell back to raw text) wherever the CDN was unreachable — a problem for the local-first / Pi hosting target — and there was no CSS for the rendered output, leaving fenced code blocks unstyled. Now marked@12.0.2 and dompurify@3.2.4 are vendored under static/vendor/ and served locally via the existing /static mount; index.html references them by local path. script.js gained renderMarkdown() (DOMPurify.sanitize(marked.parse(text))) used from appendMessage, degrading to plain textContent if the libs fail to load instead of throwing. Added CSS for .msg.assistant pre (monospace, distinct dark background, padding, border, overflow-x:auto horizontal scroll, no wrap) and inline code spans, plus a pre code reset.
- Why: model output includes fenced code blocks (bash/yaml/config) that were showing as literal text; the app must render markdown without depending on external CDNs.
- Impact: fenced + inline code now render as styled code blocks; the UI has no network dependency; a missing-lib failure degrades gracefully to plain text rather than breaking the message.
- Validation: `make test` → 138 passed (was 135; +3 web tests: index references vendored libs with no cdn.jsdelivr.net, vendor files served 200, script routes assistant text through parser+sanitizer). Node-`vm` smoke test of the vendored marked build confirms fenced blocks → `<pre><code class="language-bash">` and inline → `<code>`. `make lint` + `make format-check` clean. (DOMPurify.sanitize can't execute without a DOM in node; it's the standard browser sanitizer used exactly as before.)
- Follow-ups: optional syntax highlighting (highlight.js/prism) for language-aware coloring of Platform Nerd's config snippets; Trainer (Garmin) sub-agent still pending.

### 2026-08-13 - Last-active sub-agent fallback for unclear replies
- Scope: src/nikitai/orchestrator.py, tests/test_orchestrator.py, LLM_CONTEXT_LOG.md
- Summary: Added `Orchestrator._last_active_key` (None initially), updated to the routed key at the end of every `send()` that actually reaches a sub-agent (both the sticky-pending branch and the normal classified branch). When `_classify()` returns "unclear" or an unregistered key, `send()` now falls back to the last-active sub-agent instead of the clarification prompt; only if there is no last-active key does it return `_clarify_text()`. A confidently classified registered key still wins over the fallback (the fallback runs only in the unclear/unregistered branch).
- Why: pre-orchestrator, a single agent made conversational confirmations ("shall I proceed?" -> "yes") trivial. Post-split, a bare "yes" before any tool call has no domain signal, so the classifier returns "unclear" and it hit the clarification prompt, breaking the two-stage conversational-confirm -> hard-button-confirm UX. This is a separate mechanism from sticky-pending routing (which resolves a live PendingConfirmation via resolve_pending_reply); they chain: unclear -> last-active -> model calls tool -> real PendingConfirmation -> next reply via sticky-pending.
- Impact: off-topic/unclear replies now stay in conversation with the sub-agent that was last active; the clarification prompt only appears when no sub-agent has been used yet (e.g. first message is ambiguous). No LLM judgment call added — pure in-memory key check. Explicit y/N / Approve-Deny paths unchanged.
- Validation: `make test` → 135 passed (was 130; +5: unclear-with-no-last-active clarifies, unclear-with-last-active routes, unregistered-key-with-last-active routes, confident-key-wins-over-last-active, last-active set on successful route; +2 assertions added to existing sticky tests). `make lint` + `make format-check` clean.
- Follow-ups: Trainer (Garmin) sub-agent still pending.

### 2026-08-13 - Sticky routing for pending confirmation replies
- Scope: src/nikitai/agent.py, src/nikitai/orchestrator.py, tests/test_agent.py, tests/test_orchestrator.py, LLM_CONTEXT_LOG.md
- Summary: Fixed a confirmation-handling bug where replying "yes"/"no" to a pending confirmation re-ran the router classifier (usually hitting the "unclear" clarification fallback). `Orchestrator.send()` now checks `_active_pending()` (the pending_id -> key map) before classifying; if a sub-agent has a live PendingConfirmation, the message is routed straight to it via new `Agent.resolve_pending_reply(pending_id, user_text)`. That method makes a strict, LLM-free decision with new `classify_confirmation_reply()` (exact normalized match against `_CONFIRMATION_AFFIRMATIONS`/`_CONFIRMATION_NEGATIONS` phrase sets): affirm -> `confirm(approved=True)` (execute), negate -> `confirm(approved=False)` (cancel), anything else -> clear pending and return None so the orchestrator treats it as an implicit cancel and re-classifies the message fresh (compound messages like "yes, and also check my logs" fall here, per scope). Pending state stays purely in-memory on the Agent.
- Why: replies to a pending confirmation were being treated as brand-new, off-topic messages instead of answers, so actions stalled into a clarification loop.
- Impact: while a confirmation is pending, a typed "yes"/"no" now resolves it (executes or cancels) without an extra classification LLM call; the explicit CLI y/N and web Approve/Deny paths are unchanged. Non-reply messages arriving mid-pending cancel the pending and get routed normally.
- Validation: `make test` → 130 passed (was 120; +4 classifier unit tests, +4 agent resolve_pending_reply tests, +2 orchestrator sticky-routing tests). `make lint` and `make format-check` clean.
- Follow-ups: consider surfacing which sub-agent handled a turn in the UI; Trainer (Garmin) sub-agent still pending.

### 2026-08-12 - README updated to reflect multi-agent architecture and current status
- Scope: README.md, LLM_CONTEXT_LOG.md
- Summary: README intro now describes the Orchestrator + sub-agent model (Organiser + Platform Nerd, Trainer planned). Added "Project status" section (live routing, CLI/web, pending web auth + secure hosting roadmap). Config section documents NIKITAI_HOME_INFRA_NOTES_DIR; safety notes cover Platform Nerd's append_to_log gate and notes-dir sandbox. Dropped stale claude-opus-4-8 recommendation.
- Why: README still described a single-Outlook-agent tool; repo now routes across domain sub-agents.
- Impact: docs only; no runtime behavior change.
- Validation: none needed (docs only).
- Follow-ups: none.

### 2026-08-11 - Cleanup: single import path for factories; router model back in orchestrator
- Scope: src/nikitai/agent.py, src/nikitai/orchestrator.py, tests/test_agent.py, tests/test_orchestrator.py, LLM_CONTEXT_LOG.md
- Summary: (1) Removed orchestrator.py's __all__ re-export of outlook_agent_config / platform_nerd_agent_config. Nothing in the repo (production or tests) imported them via orchestrator except two test identity-asserts, which now reference the canonical subagents.* modules. orchestrator still imports the factories directly to populate SUB_AGENT_REGISTRY, but they have exactly one advertised import path (their own subagents module). (2) Moved resolve_router_model() and DEFAULT_ROUTER_MODEL from agent.py back to orchestrator.py — they are used only by the routing classification call, not by Agent or any sub-agent. Verified there is NO import-cycle reason to keep them in agent.py: agent.py does not import orchestrator, and the helpers depend only on os.environ + a literal default. Router-model tests consolidated in test_orchestrator.py (removed the duplicate set from test_agent.py).
- Why: one correct import path per factory; keep agent.py strictly core Agent infra and put routing concerns with the orchestrator.
- Impact: import paths / module boundaries only; runtime behavior unchanged.
- Validation: pytest -q → 120 passed (was 123; -3 duplicate router-model tests removed from test_agent.py, still covered in test_orchestrator.py). ruff check + ruff format --check clean.
- Follow-ups: none for this cleanup; Trainer (Garmin) sub-agent still pending as subagents/trainer.py.

### 2026-08-11 - File-level separation: subagents/ package; slim agent.py
- Scope: src/nikitai/agent.py, src/nikitai/orchestrator.py, src/nikitai/subagents/{__init__,organiser,platform_nerd}.py (new), tests/{test_agent,test_organiser,test_platform_nerd}.py, LLM_CONTEXT_LOG.md
- Summary: Pure file reorganization, no behavior change. agent.py now holds only the domain-agnostic core: Agent, PendingConfirmation, AgentResponse, build_system_prompt(), resolve_model(), resolve_router_model() (+ DEFAULT_MODEL, DEFAULT_ROUTER_MODEL, UK_TIMEZONE, ToolDispatcher). Moved resolve_router_model()/DEFAULT_ROUTER_MODEL from orchestrator.py into agent.py. Created subagents/ package: organiser.py (SYSTEM_PROMPT_TEMPLATE, TOOL_DEFINITIONS, _execute_tool, outlook_agent_config) and platform_nerd.py (PLATFORM_NERD_* prompt/tools, _execute_platform_nerd_tool, platform_nerd_agent_config). orchestrator.py imports the factories from subagents.* and re-exports outlook_agent_config / platform_nerd_agent_config / resolve_router_model / DEFAULT_ROUTER_MODEL for backward-compatible orchestrator.* access. cli.py/web.py unchanged (they only construct Orchestrator). Split tests to mirror module boundaries: test_agent.py exercises Agent with a fake dispatcher/config + model/router-model/build_system_prompt; test_organiser.py and test_platform_nerd.py patch nikitai.subagents.{organiser,platform_nerd}.* .
- Why: separation of concerns — keep the reusable Agent free of any domain content so sub-agents are self-contained and easy to add.
- Impact: import paths only. Public runtime behavior identical; orchestrator.* names preserved via re-export.
- Validation: pytest -q → 123 passed (was 118; +5 from test-file split/coverage, e.g. test_outlook_config_shape and router-model tests relocated into test_agent.py — no assertions dropped). ruff check + ruff format --check clean (fixed one import-order nit in orchestrator.py). Ran in fresh venv (repo .venv still stale — see earlier entries).
- Follow-ups: build the Trainer (Garmin) sub-agent as subagents/trainer.py following the same pattern.

### 2026-08-11 - Build & register the Platform Nerd sub-agent (home infra notes)
- Scope: src/nikitai/tools/logs.py (new), src/nikitai/agent.py, src/nikitai/orchestrator.py, .env.example, tests/test_logs.py (new), tests/test_agent.py, tests/test_orchestrator.py, LLM_CONTEXT_LOG.md
- Summary: Added tools/logs.py with list_log_files/read_log_file/append_to_log over NIKITAI_HOME_INFRA_NOTES_DIR (env, no default → raises if unset), non-recursive .txt only, tail-with-truncation-note reads, and pure-append writes to existing files. All paths resolved + confined to the notes dir (rejects ../, absolute, symlink-escape); append refuses non-existent files and non-.txt extensions and never truncates/overwrites. Added Platform Nerd domain to agent.py: PLATFORM_NERD_SYSTEM_PROMPT_TEMPLATE (networking/self-hosting expert that reads notes before answering setup questions and offers confirmation-gated logging of config changes), PLATFORM_NERD_TOOL_DEFINITIONS, _execute_platform_nerd_tool dispatcher (token-agnostic; str results pass through, dicts JSON-encoded), and platform_nerd_agent_config() (confirmation set {"append_to_log"}, model via resolve_model("NIKITAI_PLATFORM_NERD_MODEL")). Registered "platform_nerd" in SUB_AGENT_REGISTRY (trainer remains a commented placeholder). .env.example documents NIKITAI_HOME_INFRA_NOTES_DIR (commented).
- Why: deliver the second working sub-agent (home network / hosting advisor grounded in the user's own notes) while keeping the same config-factory + registry pattern.
- Impact: infra/networking messages now route to Platform Nerd instead of Organiser. New local filesystem surface, tightly sandboxed to the notes dir; append is confirmation-gated. No change to Outlook behavior.
- Validation: pytest -q → 118 passed (was 91; +27 across logs path-safety/append rules, platform_nerd config+dispatcher, infra routing; updated 1 stale registry test). ruff check + ruff format --check clean. Ran in fresh venv (repo .venv still stale — see earlier entries). Note: logs tests exercised real symlinks (not skipped) on this machine.
- Follow-ups: build the Trainer (Garmin) sub-agent next; consider surfacing which sub-agent handled a turn in the UI; consider size/rate limits on append_to_log content.

### 2026-08-11 - Per-sub-agent model selection via env vars
- Scope: src/nikitai/agent.py, src/nikitai/orchestrator.py, .env.example, README.md, tests/test_agent.py, tests/test_orchestrator.py
- Summary: Model is now per-sub-agent instead of a single hardcoded/`NIKITAI_MODEL` global. Added `agent.resolve_model(specific_env_var)` with precedence: specific override → `NIKITAI_DEFAULT_MODEL` → hardcoded `agent.DEFAULT_MODEL` ("claude-sonnet-5"). `Agent.__init__` gained a `model` param (stored as `self.model`, used in `_run_loop`'s `messages.create`). `outlook_agent_config()` now sets `model=resolve_model("NIKITAI_ORGANISER_MODEL")`. Orchestrator routing model moved to `orchestrator.resolve_router_model()` (precedence: `NIKITAI_ROUTER_MODEL` → `NIKITAI_DEFAULT_MODEL` → `DEFAULT_ROUTER_MODEL` "claude-haiku-4-5"), replacing the module-level `ROUTER_MODEL` that fell back to the now-removed `NIKITAI_MODEL`. `_classify` calls `resolve_router_model()` per call. Registry placeholders note that platform_nerd/trainer factories will use `resolve_model("NIKITAI_PLATFORM_NERD_MODEL"/"NIKITAI_TRAINER_MODEL")`.
- Why: let each sub-agent pick a model suited to its workload while sharing one default; route with a cheap model; retire the stale single `NIKITAI_MODEL`.
- Impact: env-driven model config. `NIKITAI_MODEL` is no longer read anywhere. `.env.example` updated (`NIKITAI_ROUTER_MODEL`, `NIKITAI_DEFAULT_MODEL` uncommented; the three per-sub-agent overrides present but commented as optional). README config section updated.
- Validation: `pytest -q` → 91 passed (81 prior + 10 new: resolve_model precedence x3, outlook_agent_config override/default, agent uses resolved model, resolve_router_model precedence x3, classify uses resolved router model); `ruff check .` + `ruff format --check .` clean. Ran in fresh venv (repo `.venv` still stale — see earlier entries).
- Follow-ups: when platform_nerd/trainer factories are built, wire their `resolve_model(...)` calls; consider surfacing the active model in CLI/web for debugging.

### 2026-08-11 - Add orchestrator/routing layer over the generalized Agent
- Scope: src/nikitai/orchestrator.py (new), src/nikitai/web.py, src/nikitai/cli.py, tests/test_orchestrator.py (new), tests/test_web.py, tests/test_cli.py
- Summary: Introduced top-level "NikitAI" Orchestrator. `SubAgentSpec(key, display_name, description, config_factory)` + `SUB_AGENT_REGISTRY` (only `organiser` -> `outlook_agent_config`; `platform_nerd`/`trainer` are commented placeholders, not implemented). `Orchestrator.send()` classifies via a cheap ROUTER_MODEL (default Haiku, `NIKITAI_ROUTER_MODEL`) → dispatches to the matching sub-agent's `Agent.send()`, or returns a clarifying question (naming only active sub-agents) on "unclear"/unknown, with no default fallthrough. `Orchestrator.confirm()` routes to the originating sub-agent via a `pending_id -> key` map (never re-classifies) and errors on unknown ids. One Agent is lazily built per sub-agent. web.py holds a single lazy Orchestrator (`get_agent()` returns it); cli.py constructs an Orchestrator. Route handler shapes/error handling unchanged.
- Why: enable multi-domain routing while keeping Organiser (Outlook) as the only live sub-agent; leave a clean extension point for Platform Nerd and Trainer.
- Impact: user-visible only when a message is off-topic (now a clarifying prompt instead of always hitting Outlook). Adds one cheap classification LLM call per user message. No change to the approval/confirm gate behavior.
- Validation: `pytest -q` → 81 passed (72 existing + 9 new orchestrator tests); `ruff check .` clean; `ruff format --check .` clean. (Run in a fresh venv; repo `.venv` still stale — see prior entry.)
- Follow-ups: implement platform_nerd/trainer config factories before registering them; consider persisting/ejecting sub-agent conversations; router prompt is minimal and may need tuning as sub-agents grow.

### 2026-08-11 - Make Agent domain-agnostic (reusable for future sub-agents)
- Scope: src/nikitai/agent.py, src/nikitai/cli.py, src/nikitai/web.py, tests/test_agent.py, tests/test_web.py
- Summary: `Agent.__init__` now takes `system_prompt`, `tool_definitions`, `tool_dispatcher`, and `confirmation_required_tools`, stored as instance attrs (`self.system_prompt`, `self.tools`, `self.tool_dispatcher`, `self.confirmation_required_tools`). `_run_loop`/`_process_blocks`/`confirm` reference those attrs instead of module-level `TOOL_DEFINITIONS`/`CONFIRMATION_REQUIRED_TOOLS`/`_execute_tool`. Added `build_system_prompt(template, tz)` helper (Europe/London datetime logic, reusable by any domain) and `outlook_agent_config()` factory bundling the Outlook prompt/tools/dispatcher/gates. `cli.py` and `web.py` now build via `Agent(**outlook_agent_config())`.
- Why: prepare a single reusable Agent for planned sub-agents (Outlook, home infra logs, Garmin) without an orchestrator yet.
- Impact: pure refactor — no behavior change. `_execute_tool` and Outlook constants remain in agent.py; the Agent class body has no Outlook-specific references.
- Validation: `pytest -q` → 72 passed; `ruff check .` clean; `ruff format --check .` clean. (Note: repo `.venv` was stale/broken from an old `Nikita` path; ran suite in a fresh venv.)
- Follow-ups: repo `.venv` needs recreating; orchestrator/routing and additional sub-agents intentionally not added in this change.

### 2026-08-09 - Initial Context Baseline
- Scope: project-wide context document
- Summary: created this rolling LLM context file with architecture, priorities, safety boundaries, and command map
- Why: give any IDE LLM immediate project state without re-discovery
- Impact: faster onboarding for future prompts and fewer repeated context-gathering steps
- Validation: derived from README.md, pyproject.toml, Makefile, todolist.md, and current git branch/log
- Follow-ups: keep this file updated whenever features, security posture, workflows, or priorities change
