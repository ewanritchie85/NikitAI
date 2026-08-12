# NikitAI

AI-powered personal assistant using the Claude API, built on a multi-agent
architecture. A top-level **Orchestrator** routes each message to a domain-specific
sub-agent:

- **NikitAI Organiser** — Outlook email and calendar via Microsoft Graph: reads and
  searches your inbox, summarizes your calendar, and can draft/send emails, create
  calendar events, and manage mail folders (list, create, delete).
- **NikitAI Platform Nerd** — home network / self-hosting / Raspberry Pi advisor,
  grounded in your own local notes files (read + confirmation-gated append).

Sensitive actions always require explicit approval before anything happens.

## Architecture

<a href="https://ewanritchie85.github.io/NikitAI/nikitai-architecture.html" target="_blank" rel="noopener">
  <img src="https://img.shields.io/badge/docs-architecture-ff9d00" alt="Architecture">
</a>

## Project status

- Multi-agent orchestrator routing is live, with **Organiser** and **Platform Nerd**
  as the two working sub-agents.
- A **Trainer** (Garmin fitness) sub-agent is planned but not yet implemented.
- Terminal CLI and a minimal local web UI are both available.
- Web app auth, secure Pi hosting, and external access hardening are still on the
  roadmap (see `todolist.md`).

Quickstart
---------

### 1. Register an Azure AD app (one-time)

Microsoft Graph API access requires an app registration:

1. Go to https://portal.azure.com → **App registrations** → **New registration**
2. Name it anything (e.g. "NikitAI")
3. Supported account types: **"Accounts in any organizational directory and personal Microsoft accounts"**
4. Leave redirect URI blank for now, click **Register**
5. Copy the **Application (client) ID** from the Overview page
6. Go to **Authentication** → **Add a platform** → **Mobile and desktop applications**,
   and add the redirect URI `https://login.microsoftonline.com/common/oauth2/nativeclient`
7. Still on **Authentication**, set **"Allow public client flows"** to **Yes**
8. Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**, and add:
   - `Mail.Read`
   - `Mail.Send`
   - `Calendars.ReadWrite`
   (no admin consent needed for personal use — you'll consent on first login)

If you're using a **personal** Microsoft account (`@outlook.com`, `@hotmail.com`, etc.),
set `AZURE_TENANT_ID=consumers` in step 3 below. For a work/school account, use your
tenant ID (found on the app's Overview page) or `organizations`.

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install

```bash
make install
```

(equivalent to `pip install -r requirements.txt && pip install -e .`)

### 4. Configure

Copy `.env.example` to `.env` and fill in:

- `AZURE_CLIENT_ID` — from step 1
- `AZURE_TENANT_ID` — `consumers` for personal accounts, or your tenant ID / `organizations` for work/school
- `ANTHROPIC_API_KEY` — from https://console.anthropic.com
- `NIKITAI_ROUTER_MODEL` — optional, model for the orchestrator's routing classification
  (defaults to `claude-haiku-4-5`). A cheap/fast model is recommended here.
- `NIKITAI_DEFAULT_MODEL` — optional fallback model for any sub-agent without its own
  override (defaults to `claude-sonnet-5`).
- `NIKITAI_ORGANISER_MODEL` / `NIKITAI_PLATFORM_NERD_MODEL` / `NIKITAI_TRAINER_MODEL` —
  optional per-sub-agent overrides. If unset, the sub-agent uses `NIKITAI_DEFAULT_MODEL`.
  Consider a stronger model for a sub-agent doing harder reasoning.
- `NIKITAI_HOME_INFRA_NOTES_DIR` — optional, required only for the Platform Nerd
  sub-agent. Absolute path to a LOCAL folder (outside this repo) holding your
  private home-network / self-hosting notes as `.txt` files. Platform Nerd can read
  these and append confirmed config-change entries to existing files.

### 5. Run

```bash
python -m nikitai
```

First run opens a device-code login — visit the printed URL, sign in, and approve
the requested permissions. A token cache is saved to `~/.nikitai_token_cache.json`
so you won't have to log in every time.

### 6. Test

```bash
make test
```

### 7. (Optional) Run the web UI

A minimal local web chat interface is also available as an alternative to the
terminal:

```bash
make web
```

(equivalent to `uvicorn nikitai.web:app --reload`)

Then open http://127.0.0.1:8000 in your browser. It's a single-user, single-session
tool with no auth — don't expose it beyond localhost. Approval-required actions
(sending email, deleting a mail folder, creating a calendar event) are still gated
behind explicit Approve/Deny prompts.

Development
-----------

```bash
make install-dev   # install runtime + dev dependencies (ruff, pytest-cov)
make lint          # ruff check .
make format        # ruff format . (auto-fix)
make format-check  # ruff format --check . (CI-friendly, no changes made)
make coverage      # pytest with coverage (term + htmlcov/ report)
make check         # lint + format-check + test
make ci            # install-dev + lint + format-check + coverage (what CI runs)
```

Safety notes
------------
- `send_email`, `delete_mail_folder`, `create_calendar_event`, and Platform Nerd's
  `append_to_log` always require explicit approval before execution. In CLI this
  appears as `y/N`; in web UI it appears as Approve/Deny.
- The Organiser uses Microsoft Graph delegated permissions (`Mail.Read`, `Mail.Send`,
  `Calendars.ReadWrite`) and operates only within the signed-in user's mailbox and
  calendar context.
- Platform Nerd file access is confined to `NIKITAI_HOME_INFRA_NOTES_DIR`: path
  traversal, absolute paths, and symlinks escaping the directory are rejected;
  `append_to_log` is pure-append to existing `.txt` files only (no create, overwrite,
  or delete).
- Calendar behavior defaults to UK timezone handling (`Europe/London` in prompt
  guidance, `GMT Standard Time` for Graph event creation) unless the user explicitly
  specifies a different timezone.
- Delete `~/.nikitai_token_cache.json` to force a fresh login / revoke local access.

License
-------
MIT