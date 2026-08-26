# NikitAI Rolling Context Log

Purpose: single-file, high-signal project state for IDE LLMs and humans.

Last updated: 2026-08-24
Owner: project maintainers + any active coding agent

## 1. Current Snapshot

- Project: NikitAI
- Package: nikitai
- Version: 0.1.0
- Python: >=3.12 (pyenv 3.12.14, pinned in .python-version)
- Main branch: main
- Last known commit: <current> (Remove NIKITAI_DEFAULT_MODEL fallback; per-agent model env vars with hardcoded defaults)
- Working tree status at log creation: clean

## 2. What This Project Does

NikitAI is an AI-powered assistant that integrates with Microsoft Graph (Outlook mail/calendar), Garmin Connect health/fitness data, WiZ smart lighting, and Anthropic models.

Core capabilities currently in repo:
- Read/search mailbox content
- Summarize calendar and mailbox context
- Create/send emails (approval-gated)
- Create calendar events (approval-gated)
- Manage mail folders (list/create/delete; destructive actions are gated)
- Fitness training coach over read-only Garmin data (activities, daily summary,
  sleep, body battery, profile, body composition) — no write-back to Garmin yet
- Smart home automation — currently WiZ lighting control (on/off, dimming, colour)
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
  - subagents/trainer.py: NikitAI Trainer prompt/tools/_execute_trainer_tool/
    trainer_agent_config()
  - subagents/home_wizard.py: Home Wizard prompt/tools/_execute_home_wizard_tool/
    home_wizard_agent_config()
- Auth/token handling: src/nikitai/auth.py
- Outlook/Graph tools: src/nikitai/tools/outlook.py
- Home-infra notes tools: src/nikitai/tools/logs.py (Platform Nerd's read/append tools)
- WiZ smart lighting tools: src/nikitai/tools/wiz.py (Home Wizard's tools; local UDP
  control via pywizlight; config file path from NIKITAI_WIZ_LIGHTS_CONFIG)
- Garmin health/fitness tools: src/nikitai/tools/garmin.py (Trainer's read-only tools;
  lazy Garmin client from GARMIN_CONNECT_USERNAME/PASSWORD + on-disk session at
  ~/.nikitai_garmin_session via the library's built-in token store)
- Static web assets: src/nikitai/static/ (index.html, script.js, style.css, and
  vendor/ hosting the vendored marked + DOMPurify min builds - no CDN dependency)
- Tests: tests/ (test_agent = core; test_organiser / test_platform_nerd = sub-agent configs)

Design notes:
- Two-layer design: a top-level "NikitAI" Orchestrator routes each message to a
  domain sub-agent, each backed by the generalized Agent class.
- Orchestrator (src/nikitai/orchestrator.py):
  - SubAgentSpec(key, display_name, description, config_factory) describes a
    registered sub-agent; SUB_AGENT_REGISTRY maps key -> spec.
  -   Registry holds "organiser" -> subagents.organiser.outlook_agent_config()
    (NikitAI Organiser), "platform_nerd" ->
    subagents.platform_nerd.platform_nerd_agent_config() (NikitAI Platform Nerd: home
    network / self-hosting / Raspberry Pi / general networking, backed by
    tools/logs.py), "trainer" -> subagents.trainer.trainer_agent_config()
    (NikitAI Trainer: Garmin health/fitness, backed by tools/garmin.py), and
    "home_wizard" -> subagents.home_wizard.home_wizard_agent_config()
    (NikitAI Home Wizard: WiZ smart lighting control, backed by tools/wiz.py).
    Each factory has exactly ONE canonical import path — its own
    subagents module; orchestrator imports them only to populate the registry and
    does NOT re-export them. resolve_router_model() / DEFAULT_ROUTER_MODEL live in
    orchestrator.py (routing is an orchestrator concern, not core Agent infra).
  - send(): a cheap classification call (resolve_router_model():
    NIKITAI_ROUTER_MODEL → "claude-haiku-4-5") picks a
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
  read tools ungated); Trainer wiring in subagents/trainer.py (trainer_agent_config,
  dispatcher _execute_trainer_tool -> tools/garmin.py; confirmation_required_tools
  is empty — all Trainer tools are read-only). Sub-agent configs import
  build_system_prompt/resolve_model from agent.py.
- Platform Nerd notes access (src/nikitai/tools/logs.py): list_log_files /
  read_log_file / append_to_log operate on .txt files inside NIKITAI_HOME_INFRA_NOTES_DIR
  (env, no default — raises if unset). All paths are resolved and confirmed inside that
  dir (rejects ../, absolute paths, and symlinks escaping the dir). append_to_log is
  pure-append only: never creates/truncates/overwrites, requires an existing .txt file.
- Model selection is per sub-agent via agent.resolve_model(specific_env_var, hardcoded_default):
  specific override → hardcoded default. No shared fallback.
  organiser uses NIKITAI_ORGANISER_MODEL → "claude-sonnet-5";
  platform_nerd uses NIKITAI_PLATFORM_NERD_MODEL → "claude-sonnet-5";
  trainer uses NIKITAI_TRAINER_MODEL → "claude-sonnet-5";
  home_wizard uses NIKITAI_HOME_WIZARD_MODEL → "claude-haiku-4-5".
  Router uses NIKITAI_ROUTER_MODEL → "claude-haiku-4-5".
- cli.py and web.py now construct a single lazy Orchestrator (not a single Agent).
  web.get_agent() returns the Orchestrator; route handler shapes are unchanged.
- Approval-required operations return pending confirmation state instead of auto-executing.
- Web app is local-first, single-session style, with explicit approve/deny flow.

## 4. Safety + Auth Boundaries

- Approval gates are expected for high-impact actions (for example sending mail, deleting folders, creating events, appending to infra notes).
- Graph delegated permissions include mail/calendar scopes; local token cache is used.
- Platform Nerd file access is confined to NIKITAI_HOME_INFRA_NOTES_DIR: path traversal / absolute / symlink-escape rejected; append is pure-append to existing .txt files only (no create/overwrite/delete). append_to_log is confirmation-gated.
- Trainer access to Garmin Connect is READ-ONLY (recent activities, activity details, daily summary, sleep, body battery, profile, body composition) — no write-back to the account in v1 (no workout logging, no weigh-ins), and no confirmation-gated tools in this domain yet (confirmation_required_tools is empty, though the read-only design keeps escalation trivial for any future write tools). Credentials come from GARMIN_CONNECT_USERNAME/GARMIN_CONNECT_PASSWORD via an UNOFFICIAL client (garminconnect, Cyberjunky's) using real account credentials rather than OAuth — a dedicated, non-critical account is recommended; the token/session cache lives outside the repo at ~/.nikitai_garmin_session.
- The web UI is login-gated (single-user username + argon2id-hashed password via env vars NIKITAI_WEB_USERNAME/NIKITAI_WEB_PASSWORD_HASH). Every route except /login, /logout, and the /static assets (shared CSS/JS, no secrets) requires a signed HttpOnly session cookie; login attempts are rate-limited (5 per 15 min per IP, in-memory); sessions expire after NIKITAI_WEB_SESSION_TTL (default 12h); NIKITAI_WEB_SECRET signs cookies (random per-process when unset → sign-out on restart); NIKITAI_WEB_HTTPS_ONLY=true marks the cookie Secure-only behind TLS. Fails closed: with no hash configured the login page is shown but no credential can succeed.

**Local state files live outside the repo and git.** Four paths must exist on the machine
actually running the server; they do not transfer via `git pull` or any deploy step.
See the "Local machine state" checklist in README.md for the authoritative list with
regeneration/copy instructions per file:
- `~/.nikitai_token_cache.json` (Outlook/MSAL token cache — auto-regenerates on device-code login)
- `~/.nikitai_garmin_session/` (Garmin session + rate-limit cooldown sentinel — partial auto-regeneration, first login may hit Garmin SSO block)
- `NIKITAI_HOME_INFRA_NOTES_DIR` folder (Platform Nerd notes — **manual copy required**, does not regenerate)
- `NIKITAI_WIZ_LIGHTS_CONFIG` file (WiZ bulb name→IP mapping — **manual copy required**, does not regenerate)

Each new local-file-dependent tool domain added in the future should get an entry
added to that README checklist as a standing convention.

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
1. [DONE] App authentication for web access (login/session/logout/expiry) — see Safety + Auth Boundaries
2. Secure hosting path on Raspberry Pi as a separate service
3. Secure external access (TLS, reverse proxy, rate limiting, monitoring)

Parallel/secondary tracks:
- Voice control integrated into existing chat flow
- Linux/platform/networking assistant knowledge workflow
- Trainer (Garmin) shipped read-only (activities/summary/sleep/body battery); deeper
  coaching features (write-back caution, MFA handling, training plans) can follow

## 7. Recent Change Signal

Recent commits (most recent first):
- <current> Remove NIKITAI_DEFAULT_MODEL fallback; per-agent model env vars with hardcoded defaults
- d882908 Platform Nerd answers succinctly first, expands only on request
- a0e17f7 Stream web chat replies via SSE so text renders as it arrives
- 817c65d Trainer answers succinctly first, expands only on request
- 58ba0c3 Broaden Garmin block cooldown to 403/429 signals and default to 24h
- f16b7f0 Persist Garmin 429 rate-limit cooldown across processes and bump to Python 3.12 / garminconnect 0.3.10
- d55d448 architecture.html updated to reflect current build
- 2800075 Add NikitAI Trainer sub-agent with read-only Garmin tools

## 8. Known Conventions and Notes

- Ruff is the formatter/linter (line length 100, target py312).
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

### 2026-08-26 - Remove NIKITAI_DEFAULT_MODEL fallback; per-agent model env vars with hardcoded defaults
- Scope: src/nikitai/agent.py, src/nikitai/orchestrator.py, src/nikitai/subagents/{organiser,platform_nerd,trainer,home_wizard}.py, tests/test_{agent,organiser,platform_nerd,trainer,home_wizard,orchestrator}.py, LLM_CONTEXT_LOG.md
- Summary: Eliminated the shared `NIKITAI_DEFAULT_MODEL` fallback from model resolution. Each sub-agent now uses its dedicated env var with a hardcoded default passed directly to `resolve_model()`. Router uses `NIKITAI_ROUTER_MODEL` with `DEFAULT_ROUTER_MODEL` ("claude-haiku-4-5"). Sub-agents: Organiser/Platform Nerd/Trainer → `NIKITAI_<AGENT>_MODEL` → `claude-sonnet-5`; Home Wizard → `NIKITAI_HOME_WIZARD_MODEL` → `claude-haiku-4-5`. Removed `DEFAULT_MODEL` constant from agent.py. Updated `resolve_model()` signature to require `default_model` parameter. Updated all sub-agent configs to pass their specific default. Updated `resolve_router_model()` to skip `NIKITAI_DEFAULT_MODEL`.
- Why: Simpler, explicit model configuration per the .env.example pattern; removes an ambiguous shared fallback that was never set in practice.
- Impact: Model selection is now fully explicit via dedicated env vars. No runtime behavior change if env vars are already set; if unset, agents use their hardcoded defaults (same values as before).
- Validation: `make test` → 231 passed (was 233; tests updated to match new signature and expectations). `make lint` clean.
- Follow-ups: Update SOLUTION_OVERVIEW.md to reflect new model resolution.

### 2026-08-24 - NikitAI Home Wizard sub-agent (WiZ smart lighting)
- Scope: src/nikitai/tools/wiz.py (new), src/nikitai/subagents/home_wizard.py (new),
  src/nikitai/orchestrator.py, requirements.txt, pyproject.toml, .env.example,
  tests/test_wiz.py (new), tests/test_home_wizard.py (new), tests/test_orchestrator.py,
  LLM_CONTEXT_LOG.md
- Summary: Built and registered the Home Wizard sub-agent for smart home automation,
  initially scoped to WiZ smart lighting via local UDP (pywizlight). tools/wiz.py:
  config loader reading JSON from NIKITAI_WIZ_LIGHTS_CONFIG (friendly name -> IP
  mapping); five synchronous tool wrappers around async pywizlight calls
  (list_lights, get_light_state, turn_on, turn_off, set_brightness) using
  asyncio.run; clear error types (WizConfigError, WizLightNotFoundError,
  WizConnectionError) surfaced as "Tool error: ..." via dispatcher.
  subagents/home_wizard.py: system prompt establishing practical lighting assistant
  that calls list_lights when unsure, asks for clarification on unknown/ambiguous
  lights; five tool definitions; empty confirmation_required_tools (lighting runs
  immediately); model via resolve_model("NIKITAI_HOME_WIZARD_MODEL").
  orchestrator.py: added "home_wizard" SubAgentSpec to SUB_AGENT_REGISTRY.
  .env.example: documented NIKITAI_WIZ_LIGHTS_CONFIG (path to local JSON config)
  and NIKITAI_HOME_WIZARD_MODEL (optional per-sub-agent model override).
- Why: extend NikitAI into home automation with a local-first, no-cloud approach;
  WiZ bulbs are a common starting point; config-file pattern mirrors Platform Nerd's
  notes directory for security and portability.
- Impact: lighting commands ("turn on the bedroom lamp", "dim the desk light to 30%")
  now route to Home Wizard. No cloud account/API key needed; bulbs controlled over
  LAN. Confirmation-free for all lighting actions (read-write but low-risk).
- Validation: `make test` → 233 passed (was ~200; +17 wiz tools, +13 home_wizard
  config/dispatcher, +2 orchestrator registry/routing). `ruff check` + `ruff format`
  clean.
- Follow-ups: extend to other domains (e.g. Spotify, climate control) by adding
  tools and extending the system prompt; consider scenes/groups for multi-light
  commands.

### 2026-08-18 - Trainer gains profile + body-composition tools
- Scope: src/nikitai/tools/garmin.py, src/nikitai/subagents/trainer.py, tests/{test_garmin,test_trainer}.py, docs/nikitai-architecture.html, README.md, LLM_CONTEXT_LOG.md
- Summary: Added two read-only Garmin tools so the Trainer has body context (it previously had no knowledge of height/weight). tools/garmin.py: get_profile() condenses Garmin.get_user_profile() to height/weight/gender/birth_date (+ unit system when present; non-dict → {}), and get_body_composition(date) wraps Garmin.get_body_composition(startdate) with a single date defaulting to today. trainer.py: both registered in TRAINER_TOOL_DEFINITIONS, dispatched in _execute_trainer_tool, and listed in the system prompt. confirmation_required_tools stays empty (still fully read-only).
- Why: the coach was reasoning about training load, recovery, and goals without knowing the user's height/weight — a gap for weight targets / body-type advice.
- Impact: Trainer can now pull static profile data and per-date weight/body-fat/muscle/bone. No write-back; no config change.
- Validation: `make test` → 199 passed (was 195; +4: profile condense, profile omits missing/non-dict, body-composition today + explicit date; +2 trainer dispatcher tests; config-shape test tool set extended). `ruff check` + `ruff format --check` clean. docs greps updated; inline architecture script `node --check` clean.
- Follow-ups: none. (Raw weigh-in endpoints deliberately skipped — get_body_composition already includes weight.)

### 2026-08-18 - Bump GitHub Actions to Node 24 majors
- Scope: .github/workflows/ci.yml, LLM_CONTEXT_LOG.md
- Summary: Bumped the Node-20 actions flagged by GitHub's deprecation warning to their Node-24-capable majors: actions/checkout@v4 → v5, actions/setup-python@v4 → v6, actions/upload-artifact@v4 → v6.
- Why: GitHub is forcing actions off Node 20 (default Node 24 since 2026-06-16, Node 20 removed from runners 2026-09-16); the old pins logged a warning on every CI run.
- Impact: CI warning gone; no behavior change to the check steps (python 3.12, make ci, coverage artifact inputs unchanged).
- Validation: config reviewed after edit; workflow runs on next push.
- Follow-ups: none.

### 2026-08-18 - Architecture page reflects the secure web login
- Scope: docs/nikitai-architecture.html, LLM_CONTEXT_LOG.md
- Summary: The architecture diagram now shows a "Login — single user · session cookie" box between "You" and the orchestrator, the orchestrator popup gained a "login-gated entry" tool line (argon2 password hash, signed session cookie), the Roadmap intro notes app login is shipped (with external access + voice still future), and the footer date bumped to 2026-08-18.
- Why: the page documents the live build, which now includes the login gate.
- Impact: docs only; no runtime behavior change.
- Validation: inline script passes `node --check`; structural greps for the new box, modal line, roadmap note, and footer date all pass.
- Follow-ups: none.

### 2026-08-18 - Login page reuses the shared stylesheet; /static served without auth
- Scope: src/nikitai/web.py, src/nikitai/static/{login.html, style.css}, tests/test_web.py, README.md, LLM_CONTEXT_LOG.md
- Summary: The login page previously carried its own inline CSS because /static was behind the auth gate. Made /static public (static assets hold no secrets; the gate still protects the chat APIs, index, and everything else) via _is_public() in web.py (allowlist of /login, /logout, and any /static prefix). login.html now links /static/style.css and the shared theme via new .login rules appended to style.css (label/input/button/error styling using the existing CSS variables); its small inline submit script is unchanged. The tiny inline JS remains page-local since the chat's script.js logic doesn't apply to the login form.
- Why: avoid duplicating the theme and keep one stylesheet of record for the web UI.
- Impact: unauthenticated users can fetch /static assets (CSS/JS/vendor libs — no secrets); all functional routes stay gated. Login page now matches the chat page theme exactly and updates with style.css.
- Validation: `make test` → 195 passed (test_unauthenticated_static_redirects_to_login replaced by test_static_is_public asserting 200 + text/css; test_login_page_is_public_and_uses_shared_stylesheet asserts /static/style.css link and no CDN). `ruff check` + `ruff format --check` clean.
- Follow-ups: none.

### 2026-08-18 - Secure login for the web UI (single-user, fail-closed)
- Scope: src/nikitai/web_auth.py (new), src/nikitai/web.py, src/nikitai/static/{login.html (new), index.html, style.css, script.js}, tests/test_web.py, requirements.txt, .env.example, README.md, LLM_CONTEXT_LOG.md
- Summary: The web UI is now login-gated. web_auth.py owns config + hashing + rate limiting: env NIKITAI_WEB_USERNAME / NIKITAI_WEB_PASSWORD_HASH (argon2id, verified via argon2-cffi; plaintext never stored; hash generator CLI `python -m nikitai.web_auth <password>`), NIKITAI_WEB_SECRET (random per-process when unset), NIKITAI_WEB_SESSION_TTL (default 43200s), NIKITAI_WEB_HTTPS_ONLY. Fails closed: unset hash → login page shown but no credential succeeds (403). web.py adds Starlette SessionMiddleware (signed HttpOnly same_site=lax cookie, registered outermost) plus a `require_login` HTTP middleware gating everything except /login and /logout: unauthenticated POSTs (the /message, /confirm, and /stream APIs) get 401 JSON, unauthenticated GETs (/ and /static) 303-redirect to /login. New routes GET /login (self-contained inline-styled login.html, no /static/CDN dependency; redirects to / when already authed), POST /login (JSON, per-IP in-memory rate limit 5 fails/15min → 429, sets session on success), GET /logout (clears session, redirects to /login). index.html gains a Log out link; script.js 401-handles both stream fetches → window.location to /login. Requirements: argon2-cffi + itsdangerous added (Dockerfile inherits via requirements.txt).
- Why: app-level auth was priority #1 before any external/Pi exposure; single user so one configured credential suffices; fail-closed keeps the hosting-readiness posture safe by default.
- Impact: `make web` now requires login — users must set NIKITAI_WEB_USERNAME + NIKITAI_WEB_PASSWORD_HASH (generate via `python -m nikitai.web_auth`) or the app is unreachable-by-credential. Sessions expire, logout works, and brute-force is throttled. No change to CLI or sub-agent behavior.
- Validation: `make test` → 195 passed (was 182; +13 web auth tests: unauth redirect/401 for /, /static, /message; public self-contained login page; wrong creds; wrong username; unconfigured 403; rate limit 429; logout; success sets session; login redirect when authed; index logout link; script 401 redirect). `ruff check` + `ruff format --check` clean; `node --check src/nikitai/static/script.js` clean.
- Follow-ups: reverse-proxy note — trust X-Forwarded-For for rate limiting only behind a proxy you control; monitor failed-login attempts once hosted (todolist #3); NIKITAI_WEB_SECRET should be pinned for persistence when hosted.

### 2026-08-16 - README and context log refreshed to current state
- Scope: README.md, LLM_CONTEXT_LOG.md
- Summary: README now lists Trainer as a live sub-agent (read-only Garmin) alongside Organiser and Platform Nerd, notes all three answer succinctly-first, and updates Project status (Trainer shipped, web chat streams replies via SSE). Step 4 config gains GARMIN_CONNECT_USERNAME/PASSWORD (with a warning that this is an unofficial, non-OAuth client — use a dedicated account) and NIKITAI_GARMIN_RATE_LIMIT_COOLDOWN. Web-UI section and Safety notes updated (SSE streaming; Garmin SSO block is clientId+account tied, ~24h window, every attempt extends it; 401 wrong-credentials does NOT trigger a cooldown; session cache at ~/.nikitai_garmin_session). Context log: Current Snapshot commit → d882908; Recent Change Signal → d882908/a0e17f7/817c65d/58ba0c3/f16b7f0/d55d448/2800075.
- Why: README still called Trainer "planned" and lacked Garmin config; snapshot/commit lists were stale.
- Impact: docs only; no runtime behavior change.
- Validation: none needed (docs only).
- Follow-ups: none.

### 2026-08-16 - Fix web streaming crash: onDone is not a function
- Scope: src/nikitai/static/script.js
- Summary: consumeStream() called onDone() after the SSE body was exhausted, but no caller (sendMessage/resolvePending) ever passed the callback, so every completed stream reply threw "TypeError: onDone is not a function" (visible only after the full text had already rendered). Removed the dead callback parameter and its call — handleStreamEvent() already finalizes the bubble per event.
- Why: the reply rendered fine but the console error on every message looked like a failure.
- Impact: web chat streams cleanly to completion with no post-stream error.
- Validation: `node --check src/nikitai/static/script.js` clean.
- Follow-ups: none.

### 2026-08-16 - Platform Nerd answers succinctly first, expands only on request
- Scope: src/nikitai/subagents/platform_nerd.py
- Summary: Applied the same succinct-first style the Trainer got: Platform Nerd now leads with the verdict, fix, or key command in a sentence or two (short paragraph max, one most-relevant detail), and only expands into a full walkthrough when the user asks for more detail.
- Why: consistent reply style across all sub-agents.
- Impact: shorter default answers from Platform Nerd; deeper detail on explicit request.
- Validation: `python -m pytest tests/test_platform_nerd.py -q` → 7 passed; ruff check + format clean.
- Follow-ups: none.

### 2026-08-16 - Trainer answers succinctly first, expands only on request
- Scope: src/nikitai/subagents/trainer.py
- Summary: Trainer system prompt now instructs leading with the verdict/key takeaway in a sentence or two, keeping the first reply tight, and only expanding when the user explicitly asks for more detail.
- Why: first reply from Trainer was verbose; users want a quick take.
- Impact: shorter default answers from the Trainer sub-agent.
- Validation: pytest -q → 167 passed; ruff clean.
- Follow-ups: none.

### 2026-08-16 - Streaming web chat (SSE): text renders as it arrives
- Scope: src/nikitai/agent.py, src/nikitai/orchestrator.py, src/nikitai/web.py, src/nikitai/static/script.js, tests/test_agent.py, tests/test_orchestrator.py, tests/test_web.py, LLM_CONTEXT_LOG.md
- Summary: The web chat previously did a blocking POST (`/message`) that returned one JSON body only after the whole LLM turn finished, so users stared at the typing indicator for the full reply. Added end-to-end streaming so text appears progressively. `Agent` gained `stream_send()` / `stream_confirm()` / `stream_resolve_pending_reply()` plus `_stream_loop()`, which uses `client.messages.stream(...)` (`stream.text_stream` for deltas, `get_final_message()` for the block), yielding `("text", chunk)` events followed by one terminal `("done", AgentResponse)`; multi-turn tool loops stream each assistant text block, tools still run synchronously, and APIErrors surface as a `done` event with `error`. `Orchestrator` gained `stream_send()` / `stream_confirm()` mirroring its routing exactly (sticky-pending, classification, last-active fallback, pending tracking on `done`). `web.py` gained `POST /message/stream` and `POST /confirm/stream` returning `text/event-stream` (StreamingResponse, `X-Accel-Buffering: no`), serializing each event as an SSE frame; the old blocking `/message` + `/confirm` endpoints are kept for CLI/tests. `script.js` switched `sendMessage`/`resolvePending` to fetch + `getReader()` SSE consumption: a live assistant bubble fills with plain text per delta (fast, no re-parse), then the terminal `done` re-renders markdown + copy buttons (or shows error/pending); empty-bubble cleanup and partial-text-on-error finalization handled. All sub-agents streamed (shared Agent, no per-domain changes needed).
- Why: eliminate the "wait for the full answer" UX; text appearing word-by-word is the standard modern chat behavior.
- Impact: web UI renders assistant text incrementally; confirm follow-ups stream too. CLI unchanged (still blocking `send()`). No new dependencies (SSE over fetch; anthropic stream is built-in).
- Validation: `python -m pytest -q` → 182 passed (was 167; +15: 6 agent streaming, 5 orchestrator streaming, 3 web SSE, 1 frontend SSE-consumption). `ruff check` + `ruff format --check` clean; `node --check` on script.js clean. Live TestClient stream smoke test returned correctly-ordered `text`/`text`/`done` SSE frames.
- Follow-ups: none known. If a sub-agent ever yields no text and no pending (edge), the UI drops the empty bubble — already handled.

### 2026-08-16 - Broaden Garmin block cooldown: cover 403/429, default 24h, fix messaging
- Scope: src/nikitai/tools/garmin.py, tests/test_garmin.py, .env.example, LLM_CONTEXT_LOG.md
- Summary: Live Trainer run still failed after the previous 429 fix (message surfaced "403 from their login security check"). Debug reproduced the real failure chain: mobile+cffi/mobile+requests → 429, widget+cffi → "unexpected title 'GARMIN Authentication Application'" (Garmin changed their SSO page), portal → 401. Community analysis (garminconnect issue #344): Garmin's SSO block is tied to clientId+account email (not purely IP), browser login keeps working, and EVERY failed login attempt resets/extends the block timer; recovery is ~24h of zero login attempts. The old code only persisted the cooldown sentinel on a typed 429 and defaulted to 1h, so fresh processes kept re-attempting and extending the block. Changes: (1) `_is_block_signal(exc)` classifies 429 + Cloudflare 403 + CAPTCHA as block signals; `GarminConnectConnectionError` matching those now also writes the sentinel (a plain 401 deliberately does NOT — ambiguous vs. genuinely bad credentials). (2) Default cooldown `NIKITAI_GARMIN_RATE_LIMIT_COOLDOWN` 3600 → 86400 (24h, Garmin's observed window). (3) Fail-fast message rewritten: "blocking SSO logins for this account", ~hours remaining, warns attempts reset the cooldown, points to connect.garmin.com for browser login.
- Why: stop the app from self-extending Garmin's SSO lockout (previous fix only caught the 429 path and used too-short a window), and report the block accurately instead of the misleading "rate-limiting this IP".
- Impact: after any block-signal login failure, Trainer tool calls across all processes fail fast with an accurate message for ~24h (or configured cooldown), making zero network calls; a successful login clears the sentinel. 401-only failures (e.g. wrong password) do NOT trigger a persisted cooldown.
- Validation: `python -m pytest -q` → 167 passed (was 165; +3: Cloudflare 403 persists cooldown, 401 does not persist, 429 test retained; fail-fast test re-matched to new message). `ruff check src tests` + `ruff format --check src tests` clean.
- Follow-ups: no login should be attempted for ~24h to let Garmin's block elapse (verify creds via browser at connect.garmin.com meanwhile). If 0.3.x library releases a widget-flow fix for the changed SSO page, re-test. 401 "Invalid Username or Password" from portal may be a bot-block artifact — monitor whether real bad-credential vs block can be distinguished.

### 2026-08-16 - Persist Garmin 429 rate-limit cooldown across processes
- Scope: src/nikitai/tools/garmin.py, tests/test_garmin.py, .env.example, LLM_CONTEXT_LOG.md
- Summary: Garmin started returning HTTP 429 (IP rate limit) on login (mobile+cffi/mobile+requests 429, widget failed on an unexpected SSO page). Because `_auth_failed` is in-memory only, every new process (each web session / CLI run) immediately re-ran the full 5-strategy login and *extended* the lockout. Added a persisted cooldown sentinel inside SESSION_DIR (`rate_limited_until`, epoch timestamp): a 429 now writes `time.time() + NIKITAI_GARMIN_RATE_LIMIT_COOLDOWN` (default 3600s; `0` disables), `_get_client()` fails fast with a clear message while it is unexpired (no network calls, no Garmin construction), and a successful login clears the sentinel. Helpers `_rate_limited_until`/`_write_rate_limit`/`_clear_rate_limit`; corrupt/missing sentinel falls back to allowing a login.
- Why: stop the app from hammering Garmin's login endpoints after an IP rate limit, so the cooldown can actually elapse instead of being repeatedly reset by restart-triggered logins.
- Impact: after a 429, Trainer tool calls across all processes fail fast with a readable "rate-limited, try again later" error for up to the cooldown; the IP stops accumulating new login attempts. Successful sessions are unaffected. New env var documented in .env.example.
- Validation: `make test` → 165 passed (was 162; +3: 429 persists sentinel, unexpired cooldown fails fast with Garmin never constructed, expired cooldown allows login and clears sentinel). `ruff check .` + `ruff format --check .` clean.
- Follow-ups: root cause is repeated credential logins because no cached session has ever been persisted (SESSION_DIR was empty); once a valid token is saved, login is skipped entirely. Account confirmed to have no MFA, so no `prompt_mfa` wiring needed.

### 2026-08-16 - Python 3.12 bump + garminconnect 0.3.2 → 0.3.10
- Scope: pyproject.toml, requirements.txt, .github/workflows/ci.yml, Dockerfile, .python-version (new), src/nikitai/tools/garmin.py, src/nikitai/tools/outlook.py, src/nikitai/agent.py, tests/test_outlook.py, LLM_CONTEXT_LOG.md
- Summary: (1) Python floor raised 3.8 → 3.12: `requires-python` and Ruff `target-version` bumped to py312 in pyproject.toml; CI workflow now tests on 3.12 and Dockerfile uses python:3.12-slim; `.python-version` (new, 3.12.14) added via pyenv. `.venv` deleted and recreated against 3.12.14. (2) garminconnect pin `>=0.3.2,<0.3.3` → `>=0.3.10,<0.4.0` (0.3.10 confirmed latest on PyPI, requires Python ≥3.12). All deps resolved cleanly under 3.12 (`pip check` clean; requests resolved to 2.34.2, above the library's `>=2.33.0`). (3) `_auth_failed` review: no functional change needed. 0.3.5+'s `login()` self-healing (clears stale state on entry, discards API-rejected cached tokens and retries credentials) and typed failures (GarminConnectAuthenticationError / TooManyRequests / Connection) are entirely internal to the single `login()` call `_get_client` makes, and `_run_request` only does an in-library token refresh on 401 — so the at-most-one-login-per-process guarantee still holds. Docstrings updated to document the layering; `SESSION_DIR.mkdir(...)` now passes `mode=0o700` as defense-in-depth. (4) Token-store security fix verified on macOS by dry-run `dump()` (no network): token file written 0o600 inside a 0o700 dir; the real path `~/.nikitai_garmin_session` (`/Users/...`) has no symlinked ancestors, so 0.3.10's symlink-ancestry rejection (which refuses `/var/folders/...` temp paths on macOS) doesn't affect it. (5) Ruff py312 target surfaced 7 pre-existing issues, all fixed with `ruff --fix`: UP017 `datetime.UTC` in tools/outlook.py + test_outlook.py, I001 import sort in agent.py. (6) Environment fix: on this macOS machine a background process re-applies the UF_HIDDEN flag to the whole `.venv` tree, so CPython's site.py skips pip's editable `__editable__*.pth` and `src/` never reaches sys.path (the likely cause of the recurring "repo .venv still stale" notes). Added a venv-local `sitecustomize.py` that appends `src/` to sys.path — module imports are unaffected by the flag, only `.pth` processing is. Not tracked by git.
- Why: garminconnect 0.3.3+ requires Python 3.12, so the Python bump is mandatory to unblock the pinned library upgrade; 0.3.10 is a security-hardened release (token store 0o600/0o700, symlink rejection, JWT hardening, typed auth failures) worth the pin.
- Impact: project now requires Python ≥3.12 (pyenv 3.12.14); Garmin session tokens are locked down on disk regardless of umask; failed logins still fail fast once per process (unchanged); dev venv on this machine now imports the package reliably. No live Garmin login was performed.
- Validation: `make check` → lint + format-check clean, 162 passed (was 162). `pip check` clean under 3.12.14. Dry-run `dump()` verified dir 0o700 / file 0o600 on macOS.
- Follow-ups: if the UF_HIDDEN/sitecustomize workaround seems off, investigate the daemon re-flagging `.venv`; consider bumping the direct `requests>=2.32.0` pin to `>=2.33.0` to match garminconnect's declared floor (currently harmless, pip resolves higher).

### 2026-08-13 - Architecture page: orchestrator gets its own popup
- Scope: docs/nikitai-architecture.html, LLM_CONTEXT_LOG.md
- Summary: The "NikitAI / routes each request" node in the architecture diagram is now clickable (`data-agent="orchestrator"`, amber accent matching the page theme, focus/enter/spc). Popup populated from a new `orchestrator` entry in the `AGENTS` data describing the real behaviour from src/nikitai/orchestrator.py: one entry point, cheap `claude-haiku-4-5` classification call, asks to clarify rather than guessing domains, sticky routing of pending-approval replies straight back to the originating sub-agent, last-active fallback for off-topic chatter, and lazy sub-agent init (auth + setup happen once per session, on first use, since a fresh `Orchestrator` is created per session in cli.py). Added `.arch-box.amber` and `.modal.orchestrator` accent styles; diagram caption generalised from "click a sub-agent" to "click a box to see what it does".
- Why: the diagram's central entry point was the only box without detail, even though the user-facing flow starts there.
- Impact: docs/visual only.
- Validation: python presence checks (clickable box, amber+modal CSS, AGENTS entry, caption) + `node --check` + DOM-stubbed smoke test (open/close, scroll lock, aria-hidden, focus trap) — all PASS.
- Follow-ups: none.

### 2026-08-13 - Architecture page: modal accessibility, contrast, housekeeping
- Scope: docs/nikitai-architecture.html, LLM_CONTEXT_LOG.md
- Summary: (1) Modal a11y: opening the agent popup now locks body scroll (`lockPageScroll`, previous overflow restored on close) and marks the page content inert with `aria-hidden=true` on `.frame` while open; all interactions move to the dialog. Added a focus trap in the global keydown handler — Tab/Shift+Tab cycle within the modal's focusables and can't escape into the page behind; `modalFocusables()` selects dialog buttons/links/tabbables. (2) WCAG-AA contrast: `--text-faint` bumped `#6b6558 → #8a8272` (3.4:1 → 4.6–5.2:1 across --bg/surface/surface2; used for 11–12px labels, `th` headers, eyebrow, hints). (3) Animation hygiene: caret blink now defined once — `@keyframes blink` moved inside the `@media (prefers-reduced-motion: no-preference)` block (it was previously defined unconditionally AND re-applied inside the media query, so reduced-motion users still saw the caret animate and the keyframes shipped even when unused). (4) Footer annotated `· last updated 2026-08-13`.
- Why: modal failed keyboard/AT isolation (focus could tab into the page, background scrollable) and faint text fell below AA on the darker surfaces; redundant keyframes + missing date broke the page's freshness signal.
- Impact: docs/visual only. Modal is now fully keyboard-trap-safe and inert-safe; faint labels readable on all three backgrounds.
- Validation: DOM-stubbed node smoke test — open locks scroll + inerts page + focuses ✕, Shift+Tab from first focusable is defaulted, Escape restores scroll + returns focus, backdrop click closes (all PASS); `node --check` clean; grep shows no residual `safety` refs and a single `@keyframes blink`.
- Follow-ups: none.

### 2026-08-13 - Architecture page: sub-agent details pop up instead of a separate section
- Scope: docs/nikitai-architecture.html, LLM_CONTEXT_LOG.md
- Summary: The static "The Specialists" card section is gone. Clicking an agent box in the "One entry point, a growing team" diagram (organiser/platform_nerd/trainer, `class="arch-box … clickable"`, `data-agent` + role/tabindex/aria-label) now opens a centered modal overlay populated from an in-page `AGENTS` data object (name, domain, model badge, description, tool list with per-tool notes and "requires approval" gates; Trainer shown as fully read-only). Modal styles in CSS (`.modal-backdrop`/`.modal` with per-agent border-top colour via `.modal.organiser/.platform_nerd/.trainer`); modal closes via ✕ button, backdrop click, or Escape; focus returns to the originating box. Old `.cards`/`.card`/`.toggle` CSS and `revealCard`/`scrollIntoView` behaviour removed. Caption updated to "click a sub-agent to see its tools".
- Why: user wanted the agent detail to pop up in place (no page scrolling) and no longer needed a dedicated specialists section.
- Impact: docs/visual only. Agent descriptions + tools now accessible from the diagram with no separate section.
- Validation: agent data-smoke-tested in node with a stubbed DOM — open/close for all three agents renders name/description/tools, no scrollIntoView remains; `node --check` passes on the inline script.
- Follow-ups: none.

### 2026-08-13 - Architecture page: Trainer shown as built and live
- Scope: docs/nikitai-architecture.html, LLM_CONTEXT_LOG.md
- Summary: The visual architecture overview now reflects the Trainer (Garmin) sub-agent as shipped rather than planned. Diagram: Trainer box changed from dashed `planned` ("Garmin — planned") to a solid green accent ("Garmin — health & fitness"). Sub-agent card: converted from the `planned` template to a live card (badge `claude-sonnet-5`, coaching-judgment description, tool list: get_recent_activities, get_activity_details, get_daily_summary, get_sleep_data, get_body_battery with a "read-only — nothing requires approval, nothing is written back to Garmin" note). Models table: Trainer row's "Provisional, pending actual design" updated to "Coaching judgment over training load, recovery, and trends from Garmin data". Roadmap: "Trainer — Garmin health & fitness" ticked [x]. Added --green/--green-dim palette + .arch-box.green/.card.green styles; kept .card.planned styles for future slots.
- Why: page was stale after the Trainer build; keeps the living architecture doc accurate.
- Impact: docs/visual only; no runtime behavior change.
- Validation: structure sanity-checked via grep (green classes, Trainer box/card/table row/roadmap all updated); no tests apply to a static page.
- Follow-ups: none.

### 2026-08-13 - Harden Garmin authentication flow (once-per-process, resume-first)
- Scope: src/nikitai/tools/garmin.py, tests/test_garmin.py, LLM_CONTEXT_LOG.md
- Summary: Reviewed tools/garmin.py's auth flow against three guarantees. (1) Module-level reuse already held: all five tool functions share the cached `_client` built once by `_get_client()`. (2) Resume-first held and is now documented: on the first build, `Garmin.login(SESSION_DIR)` attempts to load the cached session from `~/.nikitai_garmin_session` (refreshing the DI token if nearing expiry) and only falls through to a credential login when the token store is missing/corrupt/missing-tokens — verified against garminconnect 0.3.2 source (load failure is the only path that sets `tokens_loaded=False`; `_refresh_session` swallows its own errors). (3) Fixed one real gap: if `login()` raised, `_client` stayed `None` so every later tool call re-attempted the whole resume+login dance. Added an `_auth_failed` module-level cache so a failed auth is re-raised immediately on subsequent calls — causing at most one Garmin login attempt per process, never a retry merely because one attempt failed. Docstrings/module docstring updated to state the ordering explicitly. The library has no per-request re-login (401 in `_run_request` only triggers `_refresh_session`).
- Why: guarantee the account is never hammered with repeated credential logins and that the cached session is always preferred over fresh logins.
- Impact: on auth failure, tool calls fail fast with the same cached error until the process restarts (conservative; avoids lockout). Successful path unchanged: one client per process, session resumed across runs.
- Validation: `make test` → 162 passed (was 160; +`test_second_tool_call_does_not_trigger_second_login` — two tool calls assert Garmin constructed once + login called once — and +`test_failed_login_is_cached_not_retried_per_call`; existing tests updated to reset `_auth_failed`). `make lint` + `make format-check` clean.
- Follow-ups: none.

### 2026-08-13 - NikitAI Trainer sub-agent (read-only Garmin health/fitness)
- Scope: src/nikitai/tools/garmin.py (new), src/nikitai/subagents/trainer.py (new), src/nikitai/orchestrator.py, requirements.txt, .env.example, tests/test_garmin.py (new), tests/test_trainer.py (new), tests/test_orchestrator.py, LLM_CONTEXT_LOG.md
- Summary: Built and registered the Trainer (Garmin) sub-agent, the final domain in the "NikitAI" trio. tools/garmin.py wraps Cyberjunky's garminconnect client (added as `garminconnect>=0.3.2,<0.3.3` — the last line compatible with the repo's Python 3.11; 0.3.3+ needs 3.12) with a module-level client built lazily from GARMIN_CONNECT_USERNAME/GARMIN_CONNECT_PASSWORD (clear RuntimeError if either is unset) and the library's built-in token store persisted at ~/.nikitai_garmin_session (same spirit as auth.py's MSAL cache), so runs resume the session instead of re-logging in. Five read-only tools: get_recent_activities (condensed type/date/duration/distance/key-stats + id), get_activity_details, get_daily_summary, get_sleep_data, get_body_battery (single-day list unwrapped to a dict). No write-back to Garmin (no workout/weigh-in logging) in this v1. subagents/trainer.py mirrors platform_nerd.py: coaching-judgment system prompt that pulls recent activities/sleep/body battery before answering about how the user is doing or what to do next, TRAINER_TOOL_DEFINITIONS, _execute_trainer_tool dispatcher (token unused; str passes through, dicts JSON-encoded), confirmation_required_tools = set() (nothing gated — everything is read-only), model via resolve_model("NIKITAI_TRAINER_MODEL"). orchestrator.py: removed the commented placeholder and registered "trainer" -> SubAgentSpec(key="trainer", display_name="NikitAI Trainer", description="fitness, workouts, sleep, recovery, and general health/training questions based on Garmin Connect data.", config_factory=trainer_agent_config); module docstring + registry comment updated. .env.example: Garmin creds now commented with a warning that this is an unofficial client using real account credentials (not OAuth), so a dedicated non-shared account is advised.
- Why: complete the planned sub-agent set; give the assistant a Garmin-grounded fitness coach with read-only access first.
- Impact: fitness/health/training messages now route to Trainer. New read-only Garmin surface; no confirmation gate needed (no writes). Trainer is the only sub-agent whose external API is unofficial + credential-based — flagged in .env.example and Safety + Auth Boundaries.
- Validation: `make test` → 160 passed (was 139; +12 tools/garmin incl. env-error, lazy init/caching, summarisation, body-battery unwrap; +8 trainer config/dispatcher; +2 orchestrator: registry includes trainer + fitness message routes to trainer). `make lint` + `make format-check` clean (ruff reformatted 4 files, all checks green). Coverage: tools/garmin.py 98%, subagents/trainer.py 96%.
- Follow-ups: MFA prompt handling (prompt_mfa callback) for accounts that need it; optionally surface which sub-agent handled a turn in the UI; if future write tools are added to Trainer, gate them via confirmation_required_tools.

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
