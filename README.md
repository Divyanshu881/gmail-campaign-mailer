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
