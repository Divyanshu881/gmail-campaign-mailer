# Gmail Campaign Mailer

A personal, lightweight Python automation script to send ~50 personalized emails per day via Gmail SMTP.

---

## 🛠️ Installation

1. Make sure you have **Python 3.12** (or 3.9+) installed.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## 🔑 1. How to Create a Gmail App Password

Standard passwords do **not** work with Gmail SMTP. You must generate a 16-character App Password.

1. Go to your **Google Account settings** (https://myaccount.google.com/).
2. Enable **2-Step Verification** under Security (if not already enabled).
3. In the search bar at the top, type **"App Passwords"**.
4. Create a new App Password (e.g., name it `Mailer`).
5. Copy the 16-character password generated (e.g., `abcd efgh ijkl mnop`).

---

## ⚙️ 2. Configure Sender Details

Open `mailer.py` in any text editor and edit the configuration block at the top:

```python
SENDER_EMAIL = "your-email@gmail.com"
APP_PASSWORD = "your-16-digit-app-password"
```

---

## 📁 3. Campaign Setup & Customization

### Contacts
Place your contacts in `campaign/contacts.xlsx` (preferred) or `campaign/contacts.csv`.
- The mailer automatically cleans blank emails and removes duplicates.
- Apollo exports work out-of-the-box (`First Name`, `Last Name`, `Company`, `Email` columns are auto-mapped).
- Any extra columns in your file become available as Jinja2 placeholders!

### Subject Line
Edit `campaign/subject.txt`:
```
Hiring Support for {{Company name}}
```

### Email Template
Edit `campaign/template.txt`:
```
Dear {{First name}} {{Last name}},

Hope you are doing well.

We would be happy to support {{Company name}} with your hiring requirements.

Regards,
Ritik Anand
```

### Attachments
Place any files (PDFs, images, docs) into `campaign/attachments/`.
- Every file in this directory will automatically be attached to each outgoing email.

---

## 🚀 4. How to Run

Execute the script by providing the campaign folder as an argument:


1. Create the environment
```bash
python -m venv venv
```
2. Activate it (Command Prompt)
```bash
venv\Scripts\activate.bat
```
OR for PowerShell:
```bash
.\venv\Scripts\Activate.ps1
```
3. Install packages
```bash
pip install -r requirements.txt
```
4. Run
```bash
python mailer.py campaign/
```

1. The script will output contact validation statistics.
2. You will be prompted: `Type 'YES' to proceed with sending:`.
3. Type `YES` and press Enter to begin sending.

---

## 📊 5. Reports

After or during execution, check `campaign/reports/report.csv` to track:
- Recipient email address
- Status (`SUCCESS` or `FAILED`)
- Error reason (if failed)
- Timestamp of dispatch

---

## 🚀 Phase 0 — Google OAuth + Gmail API Proof of Concept

This phase replaces the SMTP/App-Password approach with proper **Google OAuth 2.0** and the **Gmail API**. It is a minimal proof of concept (`main.py`) — no payments, no campaigns, no database yet.

### What it does

1. `GET /auth/login` — redirects you to Google to sign in and authorize the app.
2. `GET /auth/callback` — Google redirects back; the app exchanges the code for a token and stores it locally in `token.json` (gitignored).
3. `GET /auth/status` — reports whether a usable Gmail connection exists.
4. `POST /email/send` — sends a plain-text test email **from the authenticated user's own Gmail** via the Gmail API.
5. `GET /` — minimal test page with a "Login with Google" button and a test-send form.

Only the minimum Gmail scope is requested: `https://www.googleapis.com/auth/gmail.send` (plus `openid`/`email` for identity). No full mailbox read access.

---

### 1. Create the Google Cloud project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown (top-left) → **New Project**.
3. Name it (e.g., `gmail-campaign-mailer`) and click **Create**.
4. With the new project selected, open **APIs & Services → Library**.
5. Search for **Gmail API** and click it → **Enable**.

### 2. Configure OAuth credentials

1. In **APIs & Services → OAuth consent screen**:
   - Choose **External** user type → **Create**.
   - Fill in the app name and your email. (Test users are fine — the consent screen doesn't need to be "Published".)
   - Under **Scopes**, add: `https://www.googleapis.com/auth/gmail.send`.
   - Under **Test users**, add the Google account you will sign in with.
   - Save.
2. In **APIs & Services → Credentials** → **Create Credentials → OAuth client ID**:
   - Application type: **Web application**.
   - **Authorized redirect URIs**: add exactly `http://localhost:8000/auth/callback`.
   - Click **Create**.
3. Copy the **Client ID** and **Client secret** shown in the dialog.

> The redirect URI you register here must **exactly** match `OAUTH_REDIRECT_URI` in your `.env`.

### 3. Configure the app

```bash
cp .env.example .env
```

Edit `.env` and set:

```ini
GOOGLE_CLIENT_ID = "your-client-id.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "your-client-secret"
OAUTH_REDIRECT_URI = "http://localhost:8000/auth/callback"
```

Never commit real credentials. `.env` and `token.json` are gitignored.

### 4. Install & run

```bash
python -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/uvicorn app.main:app --reload
```

Then open http://localhost:8000 in a browser.

### 5. Test Gmail sending

1. On the test page, click **Login with Google**.
2. Approve the consent screen. You'll be redirected back; the page will show **"Authenticated as <your-email>"**.
3. Fill in a recipient, subject, and body, then click **Send test email**. The page shows the Gmail message id on success.

You can also verify programmatically:

```bash
curl http://localhost:8000/auth/status          # {"authenticated": true, "email": "..."}
curl -X POST http://localhost:8000/email/send \
  -H "Content-Type: application/json" \
  -d '{"to":"you@example.com","subject":"Test","body":"Hello from Gmail API"}'
```

The email is sent from the **authenticated user's own account**. Emails land in that account's **Sent** folder.

---

### Common OAuth errors & debugging

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `redirect_uri_mismatch` | `OAUTH_REDIRECT_URI` doesn't match the registered redirect URI | Make them **byte-for-byte identical**, including trailing `/`. |
| `invalid_client` | Wrong client id/secret | Re-copy from Google Cloud Console → Credentials. |
| `access_denied` | User denied the consent screen | Re-run `/auth/login` and approve. |
| `consent screen not configured` / app marked invalid | Consent screen incomplete | Finish OAuth consent screen setup, add the test user. |
| `Error 403: Request had insufficient authentication scopes` | Token has wrong/missing scopes | Delete `token.json`, re-run `/auth/login`. |
| `dailyLimitExceeded` / `rateLimitExceeded` | Gmail API quota | Wait for quota reset (it's high for send, but strict in bursts). |
| `invalid_grant` | Token expired or revoked | Delete `token.json` and re-authenticate. |
| Token not saving | Permissions issue in project folder | Ensure the folder is writable; check `TOKEN_FILE` path. |

**Debugging tips**
- The server logs every step with `logging` — watch the terminal output.
- `GET /auth/status` distinguishes "no token" vs "token rejected by Gmail".
- Delete `token.json` anytime to force a clean re-authentication.
- Check `GET /auth/callback` errors in the browser URL bar — Google appends `error=` and `error_description=` there.

---

## 🚀 Phase 1 — Supabase Auth (FastAPI backend restructure)

Google **login** now goes through **Supabase Auth** (hosted OAuth). The backend never handles passwords; it verifies Supabase-issued JWTs and protects API endpoints. Gmail OAuth (Phase 0) remains separate — Google login and Gmail-sending authorization are independent concerns.

**Structure change:** the single-file `main.py` was migrated into the `app/` package:
`app/main.py` (app entry), `app/config.py` (env settings), `app/gmail.py` (Phase 0 logic), `app/auth.py` (Supabase JWT), `app/routers/` (routes), `app/pages.py` (dev test pages). Run command is now `venv/bin/uvicorn app.main:app --reload`.

### What it does

1. `GET /api/me` — **protected** endpoint; returns the current user's profile. Requires `Authorization: Bearer <supabase-access-token>`.
2. Supabase Google login is driven from the dev test page (`GET /`) using the Supabase JS client; the OAuth redirect completes at `GET /auth/supabase/callback` and returns home signed-in.
3. On each `/api/me` call, the user's profile row is upserted into the `users` table (service role key, RLS-bypassing) using the JWT identity.

### 1. Create the Supabase project

1. Go to [supabase.com](https://supabase.com) → **New project** → pick a region and set a database password.
2. After creation, open **Project Settings → API** and copy:
   - **Project URL** → `SUPABASE_URL`
   - **Project API keys → `anon` public** → `SUPABASE_ANON_KEY`
   - **Project API keys → `service_role`** → `SUPABASE_SERVICE_ROLE_KEY`
   - **JWT Settings → JWT Secret** → `SUPABASE_JWT_SECRET`

### 2. Enable Google login in Supabase

1. In the Supabase dashboard: **Authentication → Providers → Google** → enable.
2. Paste your **Google OAuth Client ID** and **Client secret** (the same client from Phase 0).
3. In Google Cloud Console → **APIs & Services → Credentials → your OAuth client**:
   - Add an **Authorized redirect URI**: `https://<your-project-ref>.supabase.co/auth/v1/callback`
4. In Supabase **Authentication → URL Configuration**, add `http://localhost:8000/auth/supabase/callback` to the allowed **Redirect URLs**.

> The `google` provider setup in Supabase is what makes "Login with Google" work; our backend only *verifies* the resulting token.

### 3. Create the `users` table

Run this in the Supabase **SQL Editor**:

```sql
create table if not exists public.users (
  id uuid primary key,
  email text,
  full_name text,
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.users enable row level security;

create policy "Users can view own profile"
  on public.users for select
  using (auth.uid() = id);

create policy "Users can update own profile"
  on public.users for update
  using (auth.uid() = id);
```

The backend writes via the `service_role` key (bypasses RLS); the RLS policies above are for when the frontend later reads profiles directly.

### 4. Environment variables

Add to `.env` (see `.env.example`):

```ini
SUPABASE_URL = "https://your-project-ref.supabase.co"
SUPABASE_ANON_KEY = "your-anon-key"
SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"
SUPABASE_JWT_SECRET = "your-jwt-secret"
```

`.env` and `token.json` are gitignored.

### 5. Local testing

```bash
venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000:
1. In the **Phase 1** card, click **Login with Google** → you'll be redirected to Google, then back to the test page signed in.
2. Click **Call /api/me** — the page sends the Supabase access token as a Bearer header and shows the returned profile (and the DB upsert happens server-side).
3. **Logout** signs out of the Supabase session.

Direct curl (get a token from the test page's localStorage, or via `supabase.auth.getSession()` in the browser console):

```bash
curl http://localhost:8000/api/me \
  -H "Authorization: Bearer <your-supabase-access-token>"
```

### Common authentication errors

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `404` / blank after "Login with Google" | Redirect URL not allowed in Supabase Auth settings | Add `http://localhost:8000/auth/supabase/callback` to Supabase **Auth → URL Configuration → Redirect URLs**. |
| `redirect_uri_mismatch` in Google | Google OAuth client missing Supabase callback | Add `https://<project>.supabase.co/auth/v1/callback` to the Google client's redirect URIs. |
| `Missing Authorization header` | No Bearer token sent | Send `Authorization: Bearer <token>`. |
| `401 Invalid or expired token: Signature has expired` | Access token expired | Refresh the session in the browser (`supabase.auth.refreshSession()`) and retry. |
| `401 Signature verification failed` | Wrong `SUPABASE_JWT_SECRET` | Copy the exact JWT Secret from Supabase → Project Settings → API. |
| `503 Supabase is not configured` | Missing `SUPABASE_URL` / `SUPABASE_JWT_SECRET` | Fill them in `.env` and restart. |
| Token valid but user upsert fails | Wrong/missing `SUPABASE_SERVICE_ROLE_KEY` or table missing | Set the service role key; run the `users` table SQL. `/api/me` still returns identity (upsert is non-fatal). |

**Debugging tips**
- `/api/me` never trusts the frontend — it always re-verifies the JWT with the JWT secret (HS256, `aud=authenticated`).
- Watch server logs: `app.auth` logs token rejections and upsert warnings.
- Supabase tokens are viewable in the browser console via `supabase.auth.getSession()`.

---

## 🚀 Phase 3 — EmailProvider abstraction + GmailProvider

Campaign/business logic must **never** depend on Gmail directly. This phase adds a
generic `EmailProvider` interface plus a `GmailProvider` implementation, and moves
Gmail OAuth token storage from a plaintext `token.json` into an **encrypted** row in
the `email_connections` table.

Design: `Campaign → EmailProvider → GmailProvider`. Later phases add `SMTPProvider`,
`SESProvider`, and `ResendProvider` by implementing the same interface — campaign logic
does not change.

### New structure

```
app/
  providers/
    __init__.py    # registry: get_provider("gmail") -> GmailProvider
    base.py        # EmailProvider ABC + ProviderError
    gmail.py       # GmailProvider (OAuth connect/callback/disconnect/validate/send)
  security.py      # Fernet encrypt/decrypt for stored tokens
  connections.py   # email_connections DB layer (service-role key)
  supabase_client.py  # shared lazy Supabase service client
  routers/gmail_auth.py  # /auth/login, /auth/callback, /auth/logout, /auth/status
  routers/gmail_send.py  # /email/send
```

`EmailProvider` methods: `connect(user_id)`, `handle_callback(state, params)`,
`disconnect(connection)`, `validate(connection)`, `send_email(connection, to, subject,
body, html=..., attachments=...)`. All provider routes go through
`get_provider("gmail")`.

### 1. Create the `email_connections` table

Run this in the Supabase **SQL Editor**:

```sql
create table if not exists public.email_connections (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  provider text not null default 'gmail',
  account_email text,
  encrypted_token text not null,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_validated_at timestamptz,
  unique (user_id, provider)
);

alter table public.email_connections enable row level security;

create policy "Users can view own connections"
  on public.email_connections for select
  using (auth.uid()::text = user_id);

create policy "Users can insert own connections"
  on public.email_connections for insert
  with check (auth.uid()::text = user_id);

create policy "Users can update own connections"
  on public.email_connections for update
  using (auth.uid()::text = user_id);

create policy "Users can delete own connections"
  on public.email_connections for delete
  using (auth.uid()::text = user_id);
```

The backend writes via the `service_role` key (bypasses RLS). `user_id` is `text`
so dev flows without a Supabase session can use a fixed `dev-user` id.

### 2. Credential encryption

Tokens are encrypted at rest with **Fernet** (`cryptography`). Generate a key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set it in `.env`:

```ini
EMAIL_TOKEN_ENCRYPTION_KEY = "<the-generated-key>"
```

If the variable is empty (dev), the app generates a key and saves it to
`encryption.key` (gitignored) so tokens survive restarts. In production always set
`EMAIL_TOKEN_ENCRYPTION_KEY`.

> Changing the key makes existing stored connections unreadable — reconnect Gmail.

### 3. Endpoints (same paths as Phase 0, now per-user + encrypted)

> **redirect_uri_mismatch?** The Google OAuth client must list **both** the app's
> local callback AND the Supabase callback as Authorized redirect URIs (Google
> Cloud Console → APIs & Services → Credentials → OAuth client). Adding the
> Supabase URI in Phase 1 often overwrites the list. Both are required:
> `http://localhost:8000/auth/callback` and
> `https://<project-ref>.supabase.co/auth/v1/callback`.

| Endpoint | What it does |
| --- | --- |
| `GET /auth/login?user_id=<id>` | Start Gmail OAuth; redirects to Google consent. |
| `GET /auth/callback` | Google redirects back; token is encrypted and upserted into `email_connections`. |
| `GET /auth/status?user_id=<id>` | Decrypts + refreshes the stored token; reports usable or not. |
| `GET /auth/logout?user_id=<id>` | Revokes the Google token (best-effort) and deletes the connection. |
| `POST /email/send?user_id=<id>` | Sends a test email through the provider (from the connected Gmail account). |

On the dev test page (`GET /`), the connect/disconnect/status/send controls pass the
Supabase user id automatically when signed in (falls back to `dev-user`).

### 4. Local testing

```bash
venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000 → **Phase 3 card**: connect Gmail, check status, send a
test email, disconnect. Previously connected accounts must reconnect once (the old
`token.json` is no longer read by the routers).

Verify with curl (after a browser connect):

```bash
curl "http://localhost:8000/auth/status?user_id=dev-user"
curl -X POST "http://localhost:8000/email/send?user_id=dev-user" \
  -H "Content-Type: application/json" \
  -d '{"to":"you@example.com","subject":"Test","body":"Hello from GmailProvider"}'
```

---

## 🚀 Phase 4 — Campaign engine

Campaign creation, CSV/Excel contact upload, parsing/validation, Jinja2 templates,
attachments, and reports. Sending is intentionally **not** implemented yet (that's
Phase 5, the worker). All validation runs BEFORE any sending would start.

Reuses the useful logic from the legacy `mailer.py` (column normalization, email
validation, duplicate removal) — see `app/contacts.py`. Contact rows are stored as
JSONB (`data` column) so arbitrary Excel/CSV columns become Jinja2 placeholders.

### New structure

```
app/
  contacts.py            # CSV/Excel parse, normalize columns, validate, dedupe
  campaigns.py           # campaigns + campaign_contacts DB layer (service-role key)
  campaign_validation.py # template/placeholder/connection validation
  routers/campaigns.py   # /api/campaigns/* endpoints (protected)
```

### 1. Create the `campaigns` and `campaign_contacts` tables

Run this in the Supabase **SQL Editor**:

```sql
create table if not exists public.campaigns (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  name text not null,
  subject_template text not null,
  body_template text not null,
  email_connection_id uuid references public.email_connections(id) on delete set null,
  status text not null default 'draft',
  total_contacts integer not null default 0,
  valid_contacts integer not null default 0,
  sent_count integer not null default 0,
  failed_count integer not null default 0,
  attachments jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz
);

alter table public.campaigns enable row level security;

create policy "Users can view own campaigns"
  on public.campaigns for select
  using (auth.uid()::text = user_id);

create policy "Users can insert own campaigns"
  on public.campaigns for insert
  with check (auth.uid()::text = user_id);

create policy "Users can update own campaigns"
  on public.campaigns for update
  using (auth.uid()::text = user_id);

create policy "Users can delete own campaigns"
  on public.campaigns for delete
  using (auth.uid()::text = user_id);

create table if not exists public.campaign_contacts (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.campaigns(id) on delete cascade,
  email text not null,
  data jsonb not null default '{}'::jsonb,
  status text not null default 'pending',
  reason text,
  attempts integer not null default 0,
  sent_at timestamptz,
  created_at timestamptz not null default now()
);

alter table public.campaign_contacts enable row level security;

create policy "Users can view own campaign contacts"
  on public.campaign_contacts for select
  using (exists (select 1 from public.campaigns c
                 where c.id = campaign_contacts.campaign_id and c.user_id = auth.uid()::text));

create policy "Users can insert own campaign contacts"
  on public.campaign_contacts for insert
  with check (exists (select 1 from public.campaigns c
                      where c.id = campaign_contacts.campaign_id and c.user_id = auth.uid()::text));

create policy "Users can update own campaign contacts"
  on public.campaign_contacts for update
  using (exists (select 1 from public.campaigns c
                 where c.id = campaign_contacts.campaign_id and c.user_id = auth.uid()::text));

create policy "Users can delete own campaign contacts"
  on public.campaign_contacts for delete
  using (exists (select 1 from public.campaigns c
                 where c.id = campaign_contacts.campaign_id and c.user_id = auth.uid()::text));
```

Contact status: `pending` (valid & unique), `invalid` (bad/missing email),
`duplicate` (email already seen), later `sent`/`failed` (Phase 5). Only `pending`
contacts are ever sent.

> **Existing databases (already created before Phase 5):** add the retry counter:
> ```sql
> alter table public.campaign_contacts add column if not exists attempts integer not null default 0;
> ```

### 2. Placeholders

Column names are normalized (same rules as the legacy mailer):
`First Name`/`firstname`/`First_Name` → `First_name`, `Company`/`Organization` →
`Company_name`, `Email` → `Email`. Everything else keeps its original name.
Any column can be used in templates.

**Placeholders always use underscores** — Jinja2 variable names cannot contain
spaces, so `{{ First_name }}` works but `{{ First name }}` is invalid (validation
returns a hint about this):

```
{{ First_name }} {{ Last_name }}
{{ Company_name }}
```

The uploaded contact **headers must match the placeholders** in your templates
(unknown placeholders produce a clear error listing the available fields).
A common workflow is to upload the template/contacts first, run **Validate
campaign**, and fix the reported mismatches.

### 2b. Why two tables (`campaigns` + `campaign_contacts`)?

The contact data and the campaign are stored separately because they change
independently:

- `campaigns` = the thing you configure once: name, subject/body template,
  attachments, the sending provider (email connection), and overall counters
  (total/valid/sent/failed) plus status.
- `campaign_contacts` = one row per person: their email, the full row as JSONB
  (so arbitrary columns become placeholders), and a per-row `status`/`reason`/
  `sent_at` — this is exactly what the Phase 4 report (and later the Phase 5
  worker) reads. One campaign has many contacts.

You still do everything in one flow: write/paste the template, upload the contact
file (headers = placeholders), upload attachments, then validate.

### 3. API endpoints (all protected — Supabase Bearer token)

| Endpoint | What it does |
| --- | --- |
| `POST /api/campaigns` | Create a campaign (name, subject template, body template, `email_connection_id`). |
| `GET /api/campaigns` | List the user's campaigns. |
| `GET /api/campaigns/{id}` | Campaign detail + contact counts. |
| `POST /api/campaigns/{id}/contacts` | Upload a CSV/Excel file (multipart `file`); parses, validates, stores rows. |
| `POST /api/campaigns/{id}/attachments` | Upload one or more files (multipart `files`) attached to every email. |
| `POST /api/campaigns/{id}/validate` | Run all pre-send checks; returns errors/summary. |
| `GET /api/campaigns/{id}/report` | Per-contact report (email, status, reason, timestamp). |
| `DELETE /api/campaigns/{id}` | Delete a campaign and its contacts. |
| `GET /api/connections` | List the user's provider connections (id, provider, account email). |

### 4. Local testing

```bash
venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000 → **Phase 4 card**: sign in (Phase 1), connect Gmail
(Phase 3), then create a campaign, upload contacts, add attachments, validate, and
view the report.

Direct curl (get a token via the test page, then):

```bash
curl -X POST http://localhost:8000/api/campaigns \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","subject_template":"Hi {{First_name}}","body_template":"Dear {{First_name}}","email_connection_id":"<conn-id>"}'

curl -X POST http://localhost:8000/api/campaigns/<campaign-id>/contacts \
  -H "Authorization: Bearer <token>" \
  -F "file=@campaign/contacts.csv"

curl -X POST http://localhost:8000/api/campaigns/<campaign-id>/validate \
  -H "Authorization: Bearer <token>"

curl http://localhost:8000/api/campaigns/<campaign-id>/report \
  -H "Authorization: Bearer <token>"
```

### 5. Notes

- Attachments are stored on the local disk under `uploads/{campaign_id}/` (gitignored).
  Supabase Storage will replace this in the deployment phase.
- The campaign engine talks only to `EmailProvider` (via `campaign_validation.py`);
  it never depends on Gmail directly.
- `python-multipart` was added to `requirements.txt` for file uploads.

---

## 🚀 Phase 5 — Redis queue + background worker

Sending is **asynchronous**: `POST /api/campaigns/{id}/start` validates the campaign,
checks the daily quota, and pushes a job onto Redis. A **Python worker** in its own
process pops one campaign at a time and sends its pending contacts **one email at a
time** with a configurable delay. No HTTP request ever stays open while emailing.

```
POST /api/campaigns/{id}/start
        ↓
validate campaign            (same checks as /validate)
        ↓
check daily quota            (server-side, DAILY_EMAIL_QUOTA)
        ↓
queue campaign (Redis list)
        ↓
worker processes emails      (one at a time, delay, retry-once)
        ↓
update campaign/contact status + report
```

### New structure

```
app/
  queue.py       # Redis queue: enqueue_campaign / dequeue_job (BLPOP)
  worker.py      # background worker: python -m app.worker
  campaigns.py   # + get_contacts_by_status, update_contact_status, count_sent_today
  campaign_validation.py  # + render_templates (Jinja2 per-contact render)
  routers/campaigns.py    # + POST /{id}/start, attempts in /report
```

### 1. Redis

- **Local (macOS):** `brew install redis && redis-server`
- **Upstash (for Render deployment):** copy the `redis://` (or `rediss://`) URL from
  the dashboard and set it as `REDIS_URL`. redis-py speaks TCP, so the Upstash REST
  URL/token are **not** used.

Add to `.env`:

```ini
REDIS_URL = "redis://localhost:6379/0"
CAMPAIGN_QUEUE = "campaigns"
SEND_DELAY_MIN = 30      # rate-limit window (random delay between emails)
SEND_DELAY_MAX = 75
SEND_RETRY_DELAY = 10    # wait before retrying a failed email
MAX_SEND_ATTEMPTS = 2    # 1 initial + 1 retry
DAILY_EMAIL_QUOTA = 50   # hard server-side cap per user per day
```

> The delay is **rate limiting** to avoid bursty sending — it is NOT a guarantee
> of inbox placement.

### 2. Database change

The worker records how many times a contact was attempted (for the retry-once
rule). If `campaign_contacts` was already created (Phase 4), run:

```sql
alter table public.campaign_contacts add column if not exists attempts integer not null default 0;
```

Campaign `status` now also takes `queued`, `running`, `completed`, `paused`
(quota reached), and `failed` (missing connection) — in addition to `draft`.

### 3. Run it

Terminal 1 — the API server:

```bash
venv/bin/uvicorn app.main:app --reload
```

Terminal 2 — the worker:

```bash
venv/bin/python -m app.worker
```

Worker flags for debugging:

| Command | What it does |
| --- | --- |
| `venv/bin/python -m app.worker` | Watch the queue forever (production mode). |
| `venv/bin/python -m app.worker --once` | Process one queued job, then exit. |
| `venv/bin/python -m app.worker --campaign <id>` | Force-process one campaign immediately. |

The worker recovers campaigns left `running`/`queued` by a previous crash by
re-queueing them at startup. Logs are verbose and prefixed with timestamps
(`app.worker`).

### 4. Endpoint

| Endpoint | What it does |
| --- | --- |
| `POST /api/campaigns/{id}/start` | Validate + quota-check + enqueue. Returns `{status: "queued", remaining_daily_quota}` immediately (200). Fails with `422` (validation errors), `429` (quota reached), `409` (already queued/running/completed), `503` (Redis/Supabase unavailable). |

Watch progress via `GET /api/campaigns/{id}` (sent_count/failed_count/status) and
`GET /api/campaigns/{id}/report` (per-contact `status`, `reason`, `attempts`,
`sent_at`).

### 5. Worker behavior

- Sends one email at a time; sleeps a random `SEND_DELAY_MIN..MAX` seconds between
  emails.
- Retries a failed send once (`MAX_SEND_ATTEMPTS = 2`), then records the contact as
  `failed` with the reason and continues with the next one.
- Enforces `DAILY_EMAIL_QUOTA` server-side **before every send**; when the user hits
  it the campaign is marked `paused` and the remaining contacts stay `pending` so it
  can be resumed the next day (run `/start` again).
- Updates `campaigns.sent_count`/`failed_count` after each email and writes
  `completed_at` when done.
- Payments are **not** implemented yet (Phase 7); for now every user shares the
  `DAILY_EMAIL_QUOTA` cap.
