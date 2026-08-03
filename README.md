# NikitAI

AI-powered personal assistant using Claude API with Outlook email and calendar access.

Reads and searches your inbox, summarizes your calendar, and can draft/send emails
and create calendar events on your behalf — sending an email or creating an event
always requires an explicit confirmation in the terminal before anything happens.

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
- `NIKITAI_MODEL` — optional, defaults to `claude-sonnet-5`. Use a cheaper/faster model
  for development, and consider `claude-opus-4-8` for harder reasoning tasks if needed.

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
- `send_email` and `create_calendar_event` always prompt for an explicit `y/N`
  confirmation in the terminal before anything happens — this is enforced in code,
  not just in the system prompt.
- The agent only has `Mail.Read`, `Mail.Send`, and `Calendars.ReadWrite` — it cannot
  delete mail or calendar events, or access anything beyond your own mailbox.
- Delete `~/.nikitai_token_cache.json` to force a fresh login / revoke local access.

License
-------
MIT