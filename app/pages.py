"""Minimal test pages for local development.

The real frontend lives in the separate gmail-campaign-mailer-ui repo; these
pages are just dev aids for exercising the API directly:
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
    <strong>Login (Supabase Auth with Google)</strong>
    <div id="sbStatus">Loading...</div>
    <button id="sbLogin" style="display:none;">Login with Google</button>
    <button id="sbLogout" class="secondary" style="display:none;">Logout</button>
    <button id="sbMe" class="secondary" style="display:none;">Call /api/me</button>
    <pre id="sbResult"></pre>
  </div>

  <div class="card">
    <strong>Gmail connection (EmailProvider)</strong>
    <p><a id="gmailConnect" href="/auth/login"><button class="secondary" style="display:inline-block;">Connect Gmail</button></a>
       <a id="gmailDisconnect" href="/auth/logout"><button class="secondary" style="display:inline-block;">Disconnect Gmail</button></a></p>
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

  <div class="card">
    <strong>Campaign engine</strong>
    <div id="campaignCard" style="display:none;">
      <label for="connSel">Email connection (sending provider)</label>
      <select id="connSel"></select>
      <div id="connMsg" style="font-size:13px;margin-top:6px;"></div>
      <form id="campaignForm">
        <label for="campaignName">Campaign name</label>
        <input type="text" id="campaignName" name="name" placeholder="Q3 Hiring Outreach" required />
        <label for="campaignSubject">Subject template</label>
        <input type="text" id="campaignSubject" name="subject_template" value="Hiring Support for {{Company_name}}" required />
        <label for="campaignBody">Email template</label>
        <textarea id="campaignBody" name="body_template" required>Dear {{First_name}} {{Last_name}},&#10;&#10;We would love to support {{Company_name}}.&#10;&#10;Regards</textarea>
        <p style="margin-top:16px;"><button type="submit">Create campaign</button></p>
      </form>
      <div id="campaignResult"></div>

      <div id="campaignActions" style="display:none;">
        <label for="campaignSel">Existing campaigns (or create a new one below)</label>
        <select id="campaignSel"></select>
        <button id="loadCampaignBtn" class="secondary" type="button" style="margin-top:6px;">Load selected</button>
        <p style="margin-top:16px;"><strong>Campaign id: <span id="campaignId"></span></strong></p>
        <label for="contactsFile">Upload contacts (CSV / Excel)</label>
        <input type="file" id="contactsFile" accept=".csv,.xlsx" />
        <button id="uploadContactsBtn" class="secondary" type="button">Upload contacts</button>
        <label for="attachFile">Attachments (optional, multiple)</label>
        <input type="file" id="attachFile" multiple />
        <button id="uploadAttachBtn" class="secondary" type="button">Upload attachments</button>
        <p style="margin-top:16px;">
          <button id="validateBtn" class="secondary" type="button">Validate campaign</button>
          <button id="reportBtn" class="secondary" type="button">Show report</button>
          <button id="startBtn" type="button" style="background:#188038;">Start campaign</button>
        </p>
        <pre id="campaignOutput"></pre>
      </div>
    </div>
  </div>

  <script>
    {_supabase_js()}
    {_gmail_js()}
    {_campaign_js()}
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
    async function currentAccessToken() {
      if (typeof sb === "undefined") return "";
      try {
        const { data: { session } } = await sb.auth.getSession();
        return session ? session.access_token : "";
      } catch (e) {
        return "";
      }
    }

    async function refreshStatus() {
      const el = document.getElementById("status");
      try {
        const token = await currentAccessToken();
        const res = await fetch("/auth/status", {
          headers: token ? { "Authorization": "Bearer " + token } : {},
        });
        const data = await res.json();
        if (data.authenticated) {
          el.innerHTML = "Gmail connected as <strong>" + data.email + "</strong> (provider: " + data.provider + ")";
          document.getElementById("sendCard").style.display = "block";
        } else {
          el.textContent = "Gmail not connected. Click 'Connect Gmail' above.";
          document.getElementById("sendCard").style.display = "none";
        }
      } catch (e) {
        el.textContent = "Could not reach the server.";
      }
    }

    (async () => {
      const token = await currentAccessToken();
      const suffix = token ? "?token=" + encodeURIComponent(token) : "";
      document.getElementById("gmailConnect").href = "/auth/login" + suffix;
      document.getElementById("gmailDisconnect").href = "/auth/logout" + suffix;
    })();

    document.getElementById("sendForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const resEl = document.getElementById("sendResult");
      resEl.textContent = "Sending...";
      const form = new FormData(e.target);
      const body = { to: form.get("to"), subject: form.get("subject"), body: form.get("body") };
      try {
        const token = await currentAccessToken();
        const res = await fetch("/email/send", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { "Authorization": "Bearer " + token } : {}),
          },
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


def _campaign_js() -> str:
    if not SUPABASE_READY:
        return """
    document.getElementById("campaignCard").style.display = "none";
"""
    return """
    async function authHeaders() {
      const { data: { session } } = await sb.auth.getSession();
      return { "Authorization": "Bearer " + (session ? session.access_token : "") };
    }

    async function refreshConnections() {
      const card = document.getElementById("campaignCard");
      const sel = document.getElementById("connSel");
      const msg = document.getElementById("connMsg");
      try {
        const res = await fetch("/api/connections", { headers: await authHeaders() });
        const data = await res.json();
        if (!res.ok) throw new Error((data.detail || res.status));
        sel.innerHTML = "";
        (data.connections || []).forEach((c) => {
          const opt = document.createElement("option");
          opt.value = c.id;
          opt.textContent = c.provider + " - " + (c.account_email || c.id);
          sel.appendChild(opt);
        });
        if (data.connections.length) {
          card.style.display = "block";
          msg.textContent = "";
        } else {
          card.style.display = "block";
          msg.textContent = "No connections. Connect Gmail in the card above first.";
          sel.innerHTML = '<option value="">(none)</option>';
        }
      } catch (e) {
        card.style.display = "block";
        msg.textContent = "Could not load connections: " + e.message + " (sign in via the login card above)";
      }
    }

    async function apiJson(url, options = {}) {
      const res = await fetch(url, { ...options, headers: { ...(options.headers||{}), ...(await authHeaders()) } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((data.detail && JSON.stringify(data.detail)) || (res.status + " " + res.statusText));
      return data;
    }

    document.getElementById("campaignForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const resEl = document.getElementById("campaignResult");
      resEl.textContent = "Creating campaign...";
      const form = new FormData(e.target);
      try {
        const data = await apiJson("/api/campaigns", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: form.get("name"),
            subject_template: form.get("subject_template"),
            body_template: form.get("body_template"),
            email_connection_id: document.getElementById("connSel").value,
          }),
        });
        document.getElementById("campaignId").textContent = data.id;
        document.getElementById("campaignActions").style.display = "block";
        resEl.textContent = "Campaign created: " + data.name + " (" + data.status + ")";
        const opt = document.createElement("option");
        opt.value = data.id;
        opt.textContent = data.name + " (" + data.id.slice(0, 8) + ")";
        opt.selected = true;
        document.getElementById("campaignSel").appendChild(opt);
      } catch (err) {
        resEl.textContent = "Error: " + err.message;
      }
    });

    async function loadCampaigns() {
      const sel = document.getElementById("campaignSel");
      try {
        const data = await apiJson("/api/campaigns");
        sel.innerHTML = "";
        (data || []).forEach((c) => {
          const opt = document.createElement("option");
          opt.value = c.id;
          opt.textContent = c.name + " (" + c.status + ", " + (c.valid_contacts || 0) + " contacts)";
          sel.appendChild(opt);
        });
        if ((data || []).length) {
          document.getElementById("campaignActions").style.display = "block";
        }
      } catch (e) {
        /* ignore; user can still create a campaign */
      }
    }

    document.getElementById("loadCampaignBtn").addEventListener("click", () => {
      const sel = document.getElementById("campaignSel");
      if (!sel.value) { document.getElementById("campaignOutput").textContent = "No campaigns to load."; return; }
      document.getElementById("campaignId").textContent = sel.value;
      document.getElementById("campaignOutput").textContent = "Loaded campaign " + sel.value + ". You can now upload contacts / validate / view report.";
    });

    function requireCampaign(out) {
      const id = document.getElementById("campaignId").textContent.trim();
      if (!id) { out.textContent = "Create a campaign first (or load an existing one above)."; return null; }
      return id;
    }

    document.getElementById("uploadContactsBtn").addEventListener("click", async () => {
      const out = document.getElementById("campaignOutput");
      const id = requireCampaign(out);
      if (!id) return;
      const file = document.getElementById("contactsFile").files[0];
      if (!file) { out.textContent = "Choose a file first."; return; }
      out.textContent = "Uploading " + file.name + "...";
      try {
        const fd = new FormData();
        fd.append("file", file);
        const data = await apiJson("/api/campaigns/" + id + "/contacts", {
          method: "POST", body: fd,
        });
        out.textContent = JSON.stringify({ summary: data.summary, columns: data.columns, errors: data.errors }, null, 2);
      } catch (err) {
        out.textContent = "Error: " + err.message;
      }
    });

    document.getElementById("uploadAttachBtn").addEventListener("click", async () => {
      const out = document.getElementById("campaignOutput");
      const id = requireCampaign(out);
      if (!id) return;
      const files = document.getElementById("attachFile").files;
      if (!files.length) { out.textContent = "Choose files first."; return; }
      out.textContent = "Uploading attachments...";
      try {
        const fd = new FormData();
        Array.from(files).forEach((f) => fd.append("files", f));
        const data = await apiJson("/api/campaigns/" + id + "/attachments", {
          method: "POST", body: fd,
        });
        out.textContent = JSON.stringify(data.attachments, null, 2);
      } catch (err) {
        out.textContent = "Error: " + err.message;
      }
    });

    document.getElementById("validateBtn").addEventListener("click", async () => {
      const out = document.getElementById("campaignOutput");
      const id = requireCampaign(out);
      if (!id) return;
      out.textContent = "Validating...";
      try {
        const data = await apiJson("/api/campaigns/" + id + "/validate", { method: "POST" });
        out.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        out.textContent = "Error: " + err.message;
      }
    });

    document.getElementById("reportBtn").addEventListener("click", async () => {
      const out = document.getElementById("campaignOutput");
      const id = requireCampaign(out);
      if (!id) return;
      out.textContent = "Loading report...";
      try {
        const data = await apiJson("/api/campaigns/" + id + "/report");
        out.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        out.textContent = "Error: " + err.message;
      }
    });

    document.getElementById("startBtn").addEventListener("click", async () => {
      const out = document.getElementById("campaignOutput");
      const id = requireCampaign(out);
      if (!id) return;
      out.textContent = "Validating + queuing...";
      try {
        const data = await apiJson("/api/campaigns/" + id + "/start", { method: "POST" });
        out.textContent = "Queued: " + JSON.stringify(data, null, 2) + "\n\nRun the worker to send: venv/bin/python -m app.worker";
      } catch (err) {
        out.textContent = "Error: " + err.message;
      }
    });

    refreshConnections();
    loadCampaigns();
"""