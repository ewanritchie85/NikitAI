# NikitAI

AI-powered personal assistant using Claude API with Outlook email and calendar access.

Reads and searches your inbox, summarizes your calendar, and can draft/send emails,
create calendar events, and manage mail folders (list, create, delete) on your
behalf. Sensitive actions always require explicit approval before anything happens.

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

### 7. (Optional) Run the web UI

A minimal local web chat interface is also available as an alternative to the
terminal:

```bash
make web
```

(equivalent to `uvicorn nikitai.web:app --reload`)

Then open http://127.0.0.1:8000 in a browser. It's a single-user, single-session
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
- `send_email`, `delete_mail_folder`, and `create_calendar_event` always require
  explicit approval before execution. In CLI this appears as `y/N`; in web UI it
  appears as Approve/Deny.
- The agent uses Microsoft Graph delegated permissions (`Mail.Read`, `Mail.Send`,
  `Calendars.ReadWrite`) and operates only within the signed-in user's mailbox and
  calendar context.
- Calendar behavior defaults to UK timezone handling (`Europe/London` in prompt
  guidance, `GMT Standard Time` for Graph event creation) unless the user explicitly
  specifies a different timezone.
- Delete `~/.nikitai_token_cache.json` to force a fresh login / revoke local access.

License
-------
MIT