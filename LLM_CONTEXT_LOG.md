# NikitAI Rolling Context Log

Purpose: single-file, high-signal project state for IDE LLMs and humans.

Last updated: 2026-08-09
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
- Agent orchestration: src/nikitai/agent.py
- Auth/token handling: src/nikitai/auth.py
- Outlook/Graph tools: src/nikitai/tools/outlook.py
- Static web assets: src/nikitai/static/
- Tests: tests/

Design notes:
- Agent interaction is stateful via an Agent class.
- Approval-required operations return pending confirmation state instead of auto-executing.
- Web app is local-first, single-session style, with explicit approve/deny flow.

## 4. Safety + Auth Boundaries

- Approval gates are expected for high-impact actions (for example sending mail, deleting folders, creating events).
- Graph delegated permissions include mail/calendar scopes; local token cache is used.
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

### 2026-08-09 - Initial Context Baseline
- Scope: project-wide context document
- Summary: created this rolling LLM context file with architecture, priorities, safety boundaries, and command map
- Why: give any IDE LLM immediate project state without re-discovery
- Impact: faster onboarding for future prompts and fewer repeated context-gathering steps
- Validation: derived from README.md, pyproject.toml, Makefile, todolist.md, and current git branch/log
- Follow-ups: keep this file updated whenever features, security posture, workflows, or priorities change
