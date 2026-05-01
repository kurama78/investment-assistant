#!/usr/bin/env python3
"""Dependency-free local web server for the investment assistant."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict

from core.storage import Storage


MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
PORT = int(os.getenv("PORT", "5000"))
storage = Storage()


def gemini_generate(prompt: str) -> str:
    api_key = storage.get_api_key() or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 未设置")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    candidates = body.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts)


def render_page() -> bytes:
    portfolio = storage.get_portfolio_playbook()
    stocks = storage.list_stocks()
    rows = "".join(
        f"<tr><td>{s['stock_name']}</td><td>{s['ticker']}</td><td>{s['summary']}</td><td>{(s['updated_at'] or '')[:10]}</td></tr>"
        for s in stocks
    ) or "<tr><td colspan='4'>暂无股票</td></tr>"
    portfolio_html = (
        f"<pre>{json.dumps(portfolio, ensure_ascii=False, indent=2)}</pre>" if portfolio else "<p>暂无组合 Playbook</p>"
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
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #d8cdb8; text-align: left; padding: 10px; }}
    code, pre {{ font-family: Consolas, monospace; white-space: pre-wrap; }}
    .pill {{ display:inline-block; background:#dff2eb; color:#1f6f5f; padding:4px 10px; border-radius:999px; }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>Investment Assistant</h1>
      <p>本地无依赖启动模式已启用。</p>
      <p>当前模型：<span class="pill">{MODEL}</span></p>
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
    def _send_json(self, payload: Dict, status: int = 200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> Dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if self.path == "/":
            body = render_page()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/health":
            self._send_json({"ok": True, "model": MODEL})
            return
        if self.path == "/api/portfolio":
            self._send_json(storage.get_portfolio_playbook() or {})
            return
        if self.path == "/api/stocks":
            self._send_json({"stocks": storage.list_stocks()})
            return
        match = re.fullmatch(r"/api/stock/([^/]+)", self.path)
        if match:
            self._send_json(storage.get_stock_playbook(match.group(1)) or {})
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_POST(self):
        if self.path == "/api/portfolio":
            storage.save_portfolio_playbook(self._read_json())
            self._send_json({"success": True})
            return
        match = re.fullmatch(r"/api/stock/([^/]+)", self.path)
        if match:
            stock_id = match.group(1)
            data = self._read_json()
            data["stock_id"] = stock_id
            storage.save_stock_playbook(stock_id, data)
            self._send_json({"success": True})
            return
        if self.path == "/api/chat":
            data = self._read_json()
            prompt = data.get("prompt", "")
            try:
                answer = gemini_generate(prompt)
                self._send_json({"success": True, "answer": answer, "model": MODEL})
            except urllib.error.HTTPError as exc:
                self._send_json({"success": False, "error": exc.read().decode("utf-8", errors="ignore")}, status=500)
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, status=500)
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_DELETE(self):
        match = re.fullmatch(r"/api/stock/([^/]+)", self.path)
        if match:
            self._send_json({"success": storage.delete_stock(match.group(1))})
            return
        self._send_json({"error": "Not found"}, status=404)

    def log_message(self, format: str, *args):
        return


if __name__ == "__main__":
    print(f"Investment Assistant running on http://127.0.0.1:{PORT}")
    print(f"Model: {MODEL}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
