#!/usr/bin/env python3
"""Dependency-free web server for the investment assistant."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict

from core.storage import Storage


MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
PORT = int(os.getenv("PORT", "5000"))
SESSION_COOKIE = "investment_assistant_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
storage = Storage()


def _auth_password_hash() -> str:
    password = os.getenv("AUTH_PASSWORD", "")
    if password:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()
    config_hash = storage.get_config().get("auth_password_hash", "")
    return config_hash if isinstance(config_hash, str) else ""


def auth_enabled() -> bool:
    return bool(_auth_password_hash())


def _session_secret() -> str:
    configured = os.getenv("AUTH_SESSION_SECRET", "")
    return configured or _auth_password_hash() or "investment-assistant-dev-secret"


def _make_session_value() -> str:
    expires = str(int(time.time()) + SESSION_TTL_SECONDS)
    nonce = secrets.token_hex(8)
    payload = f"{expires}:{nonce}"
    signature = hmac.new(
        _session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def _session_is_valid(cookie_value: str) -> bool:
    if not cookie_value:
        return False
    parts = cookie_value.split(":")
    if len(parts) != 3:
        return False
    expires, nonce, signature = parts
    if not expires.isdigit() or int(expires) < int(time.time()):
        return False
    payload = f"{expires}:{nonce}"
    expected = hmac.new(
        _session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def gemini_generate(prompt: str) -> str:
    api_key = storage.get_api_key() or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    candidates = body.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts)


def render_login_page(error: str = "") -> bytes:
    error_html = f"<p class='error'>{error}</p>" if error else ""
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login | Investment Assistant</title>
  <style>
    :root {{
      --bg: linear-gradient(135deg, #0f172a 0%, #16213e 45%, #274060 100%);
      --card: rgba(255, 252, 245, 0.96);
      --line: #d4c6ad;
      --text: #23180f;
      --muted: #705643;
      --accent: #235347;
      --accent-strong: #173b31;
      --danger: #a12626;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: var(--bg);
      color: var(--text);
      font-family: Georgia, serif;
      padding: 24px;
    }}
    .shell {{
      width: min(460px, 100%);
      background: var(--card);
      border: 1px solid rgba(212, 198, 173, 0.9);
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 24px 80px rgba(15, 23, 42, 0.28);
    }}
    h1 {{ margin: 0 0 10px; font-size: 32px; }}
    p {{ margin: 0 0 14px; color: var(--muted); line-height: 1.6; }}
    label {{ display: block; margin: 18px 0 8px; font-weight: bold; }}
    input {{
      width: 100%;
      padding: 14px 16px;
      border-radius: 14px;
      border: 1px solid var(--line);
      font-size: 16px;
      font-family: inherit;
      background: #fff;
    }}
    button {{
      width: 100%;
      margin-top: 18px;
      padding: 14px 16px;
      border: 0;
      border-radius: 14px;
      background: var(--accent);
      color: #fff;
      font-size: 16px;
      font-weight: bold;
      cursor: pointer;
    }}
    button:hover {{ background: var(--accent-strong); }}
    .hint {{ font-size: 14px; }}
    .error {{
      background: #fde8e8;
      border: 1px solid #f6c1c1;
      color: var(--danger);
      padding: 12px 14px;
      border-radius: 12px;
      margin: 12px 0 0;
    }}
  </style>
</head>
<body>
  <main class="shell">
    <h1>Investment Assistant</h1>
    <p>登录验证已启用。输入管理员密码后，才能访问组合配置、研究记录和 Gemini 对话功能。</p>
    {error_html}
    <form method="post" action="/login">
      <label for="password">管理员密码</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">登录</button>
    </form>
    <p class="hint">会话有效期 7 天。后续如果你想换密码，只需要更新部署环境变量 <code>AUTH_PASSWORD</code> 并重部署。</p>
  </main>
</body>
</html>"""
    return html.encode("utf-8")


def render_page() -> bytes:
    portfolio = storage.get_portfolio_playbook()
    stocks = storage.list_stocks()
    rows = "".join(
        f"<tr><td>{s['stock_name']}</td><td>{s['ticker']}</td><td>{s['summary']}</td><td>{(s['updated_at'] or '')[:10]}</td></tr>"
        for s in stocks
    ) or "<tr><td colspan='4'>暂无股票</td></tr>"
    portfolio_html = (
        f"<pre>{json.dumps(portfolio, ensure_ascii=False, indent=2)}</pre>"
        if portfolio
        else "<p>暂无组合 Playbook</p>"
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Investment Assistant</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 0; background: #f5f1e8; color: #2f2419; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    .hero, .card {{ background: #fffaf1; border: 1px solid #d8cdb8; border-radius: 20px; padding: 20px; margin-bottom: 16px; }}
    .hero-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #d8cdb8; text-align: left; padding: 10px; }}
    code, pre {{ font-family: Consolas, monospace; white-space: pre-wrap; }}
    .pill {{ display:inline-block; background:#dff2eb; color:#1f6f5f; padding:4px 10px; border-radius:999px; }}
    .logout {{ display:inline-flex; align-items:center; justify-content:center; padding:10px 16px; border-radius:999px; border:1px solid #d8cdb8; background:#fff; color:#2f2419; font-weight:bold; cursor:pointer; }}
    .logout:hover {{ background:#f1e6d5; }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="hero-head">
        <div>
          <h1>Investment Assistant</h1>
          <p>当前是无依赖部署模式，本地和 Render 共用同一套运行逻辑。</p>
          <p>当前模型：<span class="pill">{MODEL}</span></p>
        </div>
        <form method="post" action="/logout">
          <button class="logout" type="submit">退出登录</button>
        </form>
      </div>
      <p>API 示例：</p>
      <pre>GET  /api/portfolio
POST /api/portfolio
GET  /api/stocks
POST /api/stock/NVDA
POST /api/chat</pre>
    </section>
    <section class="grid">
      <div class="card">
        <h2>组合 Playbook</h2>
        {portfolio_html}
      </div>
      <div class="card">
        <h2>股票列表</h2>
        <table>
          <tr><th>名称</th><th>代码</th><th>摘要</th><th>更新时间</th></tr>
          {rows}
        </table>
      </div>
    </section>
  </main>
</body>
</html>"""
    return html.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _cookies(self) -> Dict[str, str]:
        raw = self.headers.get("Cookie", "")
        cookies: Dict[str, str] = {}
        for part in raw.split(";"):
            if "=" not in part:
                continue
            key, value = part.strip().split("=", 1)
            cookies[key] = urllib.parse.unquote(value)
        return cookies

    def _is_authenticated(self) -> bool:
        if not auth_enabled():
            return True
        return _session_is_valid(self._cookies().get(SESSION_COOKIE, ""))

    def _wants_json(self) -> bool:
        return self.path.startswith("/api/")

    def _require_auth(self) -> bool:
        if self._is_authenticated():
            return True
        if self._wants_json():
            self._send_json({"success": False, "error": "Authentication required."}, status=401)
            return False
        self.send_response(302)
        self.send_header("Location", "/login")
        self.end_headers()
        return False

    def _send_json(self, payload: Dict, status: int = 200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, body: bytes, status: int = 200, extra_headers: Dict[str, str] | None = None):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _read_form(self) -> Dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
        return {key: values[-1] for key, values in parsed.items()}

    def do_GET(self):
        if self.path == "/login":
            if self._is_authenticated():
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            self._send_html(render_login_page())
            return
        if self.path == "/":
            if not self._require_auth():
                return
            self._send_html(render_page())
            return
        if self.path == "/health":
            self._send_json({"ok": True, "model": MODEL, "auth_enabled": auth_enabled()})
            return
        if self.path == "/api/portfolio":
            if not self._require_auth():
                return
            self._send_json(storage.get_portfolio_playbook() or {})
            return
        if self.path == "/api/stocks":
            if not self._require_auth():
                return
            self._send_json({"stocks": storage.list_stocks()})
            return
        match = re.fullmatch(r"/api/stock/([^/]+)", self.path)
        if match:
            if not self._require_auth():
                return
            self._send_json(storage.get_stock_playbook(match.group(1)) or {})
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_POST(self):
        if self.path == "/login":
            password = self._read_form().get("password", "")
            expected_hash = _auth_password_hash()
            provided_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
            if expected_hash and hmac.compare_digest(provided_hash, expected_hash):
                cookie_value = urllib.parse.quote(_make_session_value(), safe="")
                headers = {
                    "Set-Cookie": f"{SESSION_COOKIE}={cookie_value}; HttpOnly; Path=/; Max-Age={SESSION_TTL_SECONDS}; SameSite=Lax",
                    "Location": "/",
                }
                self._send_html(b"", status=302, extra_headers=headers)
                return
            self._send_html(render_login_page("密码不正确，请重试。"), status=401)
            return
        if self.path == "/logout":
            headers = {
                "Set-Cookie": f"{SESSION_COOKIE}=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax",
                "Location": "/login",
            }
            self._send_html(b"", status=302, extra_headers=headers)
            return
        if self.path == "/api/portfolio":
            if not self._require_auth():
                return
            storage.save_portfolio_playbook(self._read_json())
            self._send_json({"success": True})
            return
        match = re.fullmatch(r"/api/stock/([^/]+)", self.path)
        if match:
            if not self._require_auth():
                return
            stock_id = match.group(1)
            data = self._read_json()
            data["stock_id"] = stock_id
            storage.save_stock_playbook(stock_id, data)
            self._send_json({"success": True})
            return
        if self.path == "/api/chat":
            if not self._require_auth():
                return
            data = self._read_json()
            prompt = data.get("prompt", "")
            try:
                answer = gemini_generate(prompt)
                self._send_json({"success": True, "answer": answer, "model": MODEL})
            except urllib.error.HTTPError as exc:
                self._send_json(
                    {"success": False, "error": exc.read().decode("utf-8", errors="ignore")},
                    status=500,
                )
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, status=500)
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_DELETE(self):
        match = re.fullmatch(r"/api/stock/([^/]+)", self.path)
        if match:
            if not self._require_auth():
                return
            self._send_json({"success": storage.delete_stock(match.group(1))})
            return
        self._send_json({"error": "Not found"}, status=404)

    def log_message(self, format: str, *args):
        return


if __name__ == "__main__":
    print(f"Investment Assistant running on http://127.0.0.1:{PORT}")
    print(f"Model: {MODEL}")
    print(f"Authentication enabled: {auth_enabled()}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
