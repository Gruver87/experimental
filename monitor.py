#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import time
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

class BlockchainMonitor:
    def __init__(self, api_url: str = "http://127.0.0.1:8080", node_id: str = "node"):
        self.api_url = api_url.rstrip("/")
        self.node_id = node_id
        self.alerts = []
        self.metrics = {}
        self.is_running = True
        self._peer_warn_count = 0
        self._last_critical_key = ""
        self._last_critical_at = 0.0
        self._busy = False
        self._start_monitoring()
        print(f"[Monitor] Blockchain Monitor initialized ({self.node_id} -> {self.api_url})")

    def _get_stats(self):
        """Slim probe only — full GET /status HOL under mesh load (30–60s+).

        Same contract as 48h health_watch: ``/status?probe=1``.
        """
        try:
            r = requests.get(f"{self.api_url}/status?probe=1", timeout=5)
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        for path in ("/health/ready", "/health/live"):
            try:
                r = requests.get(f"{self.api_url}{path}", timeout=3)
                if r.status_code == 200:
                    body = {}
                    try:
                        body = r.json() if r.content else {}
                    except Exception:
                        body = {}
                    if not isinstance(body, dict):
                        body = {}
                    return {
                        "status": "running",
                        "height": int(
                            body.get("height") or body.get("local_height") or 0
                        ),
                        "mempool_size": 0,
                        "validator_count": 0,
                        "node_version": str(body.get("node_version") or ""),
                        "deployment_mode": str(body.get("deployment_mode") or ""),
                        "peers": int(body.get("peers") or body.get("peer_count") or 0),
                        "probe_fallback": path,
                    }
            except Exception:
                continue
        return {}

    def _get_peers(self):
        for path in ("/peers", "/network/peers"):
            try:
                r = requests.get(f"{self.api_url}{path}", timeout=3)
                if r.status_code == 200:
                    data = r.json()
                    peers = data.get("peers", data if isinstance(data, list) else [])
                    return peers
            except Exception:
                continue
        return []

    def _check_health(self):
        stats = self._get_stats()
        peer_count = 0
        if stats:
            try:
                peer_count = int(stats.get("peers") or stats.get("peer_count") or 0)
            except (TypeError, ValueError):
                peer_count = 0
        # Only hit /peers when probe did not already report peer_count.
        if peer_count <= 0 and stats:
            peers = self._get_peers()
            peer_count = len(peers) if peers else 0
        elif not stats:
            peers = self._get_peers()
            peer_count = len(peers) if peers else 0

        self.metrics = {
            "timestamp": int(time.time()),
            "blocks": stats.get("height", stats.get("blocks", 0)),
            "pending": stats.get("mempool_size", stats.get("pending_transactions", 0)),
            "validators": stats.get("validator_count", 0),
            "node_version": stats.get("node_version", ""),
            "peers_count": int(peer_count or 0),
            "api_status": "online" if stats else "offline",
            "probe": bool(stats.get("probe")) if stats else False,
        }

        if not stats:
            self._add_alert(
                "CRITICAL",
                f"API not responding ({self.api_url}/status?probe=1)",
                debounce_s=120.0,
            )
        elif self.metrics["pending"] > 100:
            self._add_alert("WARNING", f"Large mempool queue: {self.metrics['pending']}")
        elif self.metrics["peers_count"] == 0:
            bootstrap = os.getenv("BOOTSTRAP_PEERS", "").strip()
            mode = stats.get("deployment_mode", os.getenv("DEPLOYMENT_MODE", "dev"))
            # Intentional solo (no bootstrap peers): do not spam WARNING every cycle,
            # even when DEPLOYMENT_MODE=prod (local prod-profile solo is valid).
            if bootstrap:
                self._peer_warn_count += 1
                if self._peer_warn_count >= 2:
                    self._add_alert("WARNING", "No connected peers")
            elif self._peer_warn_count == 0:
                self._peer_warn_count = 1
                label = "prod-profile" if mode in ("prod", "staging") else "local dev"
                print(
                    f"[Monitor] Solo node (0 peers) — OK for {label}; "
                    "set BOOTSTRAP_PEERS to expect mesh"
                )

    def _add_alert(self, level, message, *, debounce_s: float = 0.0):
        now = time.time()
        key = f"{level}:{message}"
        if debounce_s > 0 and key == self._last_critical_key:
            if (now - float(self._last_critical_at or 0.0)) < float(debounce_s):
                return
        if level == "CRITICAL":
            self._last_critical_key = key
            self._last_critical_at = now
        alert = {"level": level, "message": message, "timestamp": int(now)}
        self.alerts.append(alert)
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]
        print(f"[{level}] {message}")

    def _start_monitoring(self):
        def monitor():
            while self.is_running:
                if not self._busy:
                    self._busy = True
                    try:
                        self._check_health()
                    finally:
                        self._busy = False
                time.sleep(30)

        threading.Thread(target=monitor, daemon=True).start()
    
    def get_metrics(self):
        return self.metrics
    
    def get_alerts(self, limit=20):
        return self.alerts[-limit:][::-1]


class MonitorServer:
    def __init__(self, api_url: str = "http://127.0.0.1:8080", port: int = 8092, node_id: str = "node"):
        self.port = port
        self.monitor = BlockchainMonitor(api_url=api_url, node_id=node_id)
    
    def start(self):
        class Handler(BaseHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                self.monitor = monitor
                super().__init__(*args, **kwargs)
            
            def log_message(self, format, *args):
                pass
            
            def do_GET(self):
                if self.path == '/':
                    self._send_html(self._get_html())
                elif self.path == '/api/monitor/metrics':
                    self._send_json(self.monitor.get_metrics())
                elif self.path == '/api/monitor/alerts':
                    self._send_json({'alerts': self.monitor.get_alerts()})
                else:
                    self._send_error(404)
            
            def _send_json(self, data):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            
            def _send_html(self, html):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(html.encode())
            
            def _send_error(self, code):
                self.send_response(code)
                self.end_headers()
            
            def _get_html(self):
                return '''
                <!DOCTYPE html>
                <html>
                <head><title>Monitor</title>
                <style>body{font-family:monospace;background:#0a0a2a;color:white;padding:20px}</style>
                </head>
                <body>
                <h1>📊 Blockchain Monitor</h1>
                <div id="metrics"></div>
                <div id="alerts"></div>
                <script>
                async function load(){const r=await fetch('/api/monitor/metrics');const d=await r.json();document.getElementById('metrics').innerHTML=JSON.stringify(d,null,2);const a=await fetch('/api/monitor/alerts');const al=await a.json();document.getElementById('alerts').innerHTML='<h2>⚠️ Alerts</h2>'+JSON.stringify(al,null,2);}
                load();setInterval(load,5000);
                </script>
                </body>
                </html>
                '''
        
        monitor = self.monitor
        server = HTTPServer(('0.0.0.0', self.port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"[Monitor] Monitor started on http://localhost:{self.port}")
        return server


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  ABSOLUTE BLOCKCHAIN - MONITOR (FIXED)")
    print("="*60)
    
    server = MonitorServer()
    server.start()
    
    print(f"\n[Monitor] Active: http://localhost:8092")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Monitor] Stopped")



