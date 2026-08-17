"""Minimal test pages for local development.

No real frontend exists yet (that is Phase 6). These pages are dev aids:
  - /                          -> Supabase Google login + Gmail test-send page
  - /auth/supabase/callback    -> completes the Supabase PKCE redirect
"""

from app.config import settings

SUPABASE_JS_CDN = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"

SUPABASE_READY = bool(settings.SUPABASE_URL and settings.SUPABASE_ANON_KEY)


def render_supabase_callback() -> str:
    """Tiny page that finishes the Supabase OAuth redirect, then goes home."""
    if not SUPABASE_READY:
        return "<h1>Supabase is not configured.</h1><p><a href='/'>Back</a></p>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Signing you in...</title>
  <script src="{SUPABASE_JS_CDN}"></script>
</head>
<body>
  <p>Finishing sign in...</p>
  <script>
    (async () => {{
      const supabase = window.supabase.createClient("{settings.SUPABASE_URL}", "{settings.SUPABASE_ANON_KEY}");
      await supabase.auth.getSession();
      window.location.href = "/";
    }})();
  </script>
</body>
</html>
"""


def render_index() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Gmail Campaign Mailer - Dev Test Page</title>
  {'<script src="' + SUPABASE_JS_CDN + '"></script>' if SUPABASE_READY else ''}
  <style>
    body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
           max-width: 640px; margin: 48px auto; padding: 0 16px; color: #202124; }}
    h1 {{ font-size: 22px; }}
    .card {{ border: 1px solid #dadce0; border-radius: 8px; padding: 20px; margin-top: 16px; }}
    button {{ background: #1a73e8; color: #fff; border: 0; border-radius: 6px;
             padding: 10px 18px; font-size: 15px; cursor: pointer; }}
    button.secondary {{ background: #fff; color: #1a73e8; border: 1px solid #1a73e8; }}
    label {{ display: block; margin: 12px 0 4px; font-weight: 500; }}
    input, textarea {{ width: 100%; box-sizing: border-box; padding: 8px;
             border: 1px solid #dadce0; border-radius: 6px; font-size: 14px; }}
    textarea {{ min-height: 120px; }}
    pre {{ background: #f8f9fa; border: 1px solid #dadce0; border-radius: 6px;
          padding: 10px; font-size: 12px; overflow: auto; }}
    #status, #sbStatus {{ margin-top: 12px; font-size: 14px; }}
    a {{ color: #1a73e8; }}
  </style>
</head>
<body>
  <h1>Gmail Campaign Mailer - Dev Test Page</h1>

  <div class="card">
    <strong>Phase 1 - Login (Supabase Auth with Google)</strong>
    <div id="sbStatus">Loading...</div>
    <button id="sbLogin" style="display:none;">Login with Google</button>
    <button id="sbLogout" class="secondary" style="display:none;">Logout</button>
    <button id="sbMe" class="secondary" style="display:none;">Call /api/me</button>
    <pre id="sbResult"></pre>
  </div>

  <div class="card">
    <strong>Phase 0 - Gmail API test</strong>
    <p><a href="/auth/login"><button class="secondary" style="display:inline-block;">Connect Gmail</button></a>
       <a href="/auth/logout"><button class="secondary" style="display:inline-block;">Disconnect Gmail</button></a></p>
    <div id="status">Checking Gmail status...</div>
    <div id="sendCard" style="display:none;">
      <form id="sendForm">
        <label for="to">To</label>
        <input type="email" id="to" name="to" required />
        <label for="subject">Subject</label>
        <input type="text" id="subject" name="subject" required />
        <label for="body">Body</label>
        <textarea id="body" name="body" required></textarea>
        <p style="margin-top:16px;"><button type="submit">Send test email</button></p>
      </form>
      <div id="sendResult"></div>
    </div>
  </div>

  <script>
    {_supabase_js()}
    {_gmail_js()}
  </script>
</body>
</html>
"""


def _supabase_js() -> str:
    if not SUPABASE_READY:
        return """
    document.getElementById("sbStatus").textContent =
      "Supabase not configured. Add SUPABASE_URL and SUPABASE_ANON_KEY to .env (see .env.example).";
"""
    return f"""
    const sb = window.supabase.createClient("{settings.SUPABASE_URL}", "{settings.SUPABASE_ANON_KEY}");

    async function refreshSbStatus() {{
      const status = document.getElementById("sbStatus");
      const loginBtn = document.getElementById("sbLogin");
      const logoutBtn = document.getElementById("sbLogout");
      const meBtn = document.getElementById("sbMe");
      const result = document.getElementById("sbResult");
      const {{ data: {{ session }} }} = await sb.auth.getSession();
      if (session) {{
        status.innerHTML = "Signed in as <strong>" + session.user.email + "</strong>";
        loginBtn.style.display = "none";
        logoutBtn.style.display = "inline-block";
        meBtn.style.display = "inline-block";
        result.textContent = "Session OK. Access token expires: " + new Date(session.expires_at * 1000).toLocaleString();
      }} else {{
        status.textContent = "Not signed in.";
        loginBtn.style.display = "inline-block";
        logoutBtn.style.display = "none";
        meBtn.style.display = "none";
        result.textContent = "";
      }}
    }}

    document.getElementById("sbLogin").addEventListener("click", async () => {{
      const {{ error }} = await sb.auth.signInWithOAuth({{
        provider: "google",
        options: {{ redirectTo: window.location.origin + "/auth/supabase/callback" }},
      }});
      if (error) alert("Sign in error: " + error.message);
    }});

    document.getElementById("sbLogout").addEventListener("click", async () => {{
      await sb.auth.signOut();
      location.reload();
    }});

    document.getElementById("sbMe").addEventListener("click", async () => {{
      const result = document.getElementById("sbResult");
      result.textContent = "Calling /api/me...";
      const {{ data: {{ session }} }} = await sb.auth.getSession();
      const res = await fetch("/api/me", {{
        headers: {{ "Authorization": "Bearer " + session.access_token }},
      }});
      const body = await res.json();
      result.textContent = res.ok
        ? "GET /api/me -> " + JSON.stringify(body, null, 2)
        : "GET /api/me failed (" + res.status + "): " + JSON.stringify(body);
    }});

    refreshSbStatus();
"""


def _gmail_js() -> str:
    return """
    async function refreshStatus() {
      const el = document.getElementById("status");
      try {
        const res = await fetch("/auth/status");
        const data = await res.json();
        if (data.authenticated) {
          el.innerHTML = "Gmail connected as <strong>" + data.email + "</strong>";
          document.getElementById("sendCard").style.display = "block";
        } else {
          el.textContent = "Gmail not connected. Click 'Connect Gmail' above.";
          document.getElementById("sendCard").style.display = "none";
        }
      } catch (e) {
        el.textContent = "Could not reach the server.";
      }
    }

    document.getElementById("sendForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const resEl = document.getElementById("sendResult");
      resEl.textContent = "Sending...";
      const form = new FormData(e.target);
      const body = { to: form.get("to"), subject: form.get("subject"), body: form.get("body") };
      try {
        const res = await fetch("/email/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await res.json();
        if (res.ok) {
          resEl.textContent = "Sent! Gmail message id: " + data.message_id;
        } else {
          resEl.textContent = "Error: " + (data.detail || res.status);
        }
      } catch (e) {
        resEl.textContent = "Network error: " + e;
      }
    });

    refreshStatus();
"""