"""Read-only live web view of a running `serialtools tap`.

Serves the newest capture's tap.log as a live-scrolling page so a colleague on
the LAN can watch the byte stream in a browser -- one-way, no remote access.

    python serve_feed.py                 # follow the newest capture dir
    python serve_feed.py --port 8686
    python serve_feed.py --capture captures\\20260820-122109-tap-ab-swapped

Then share  http://<this-machine's-ip>:8686  (IPs are printed on start).
The server only ever reads tap.log; it accepts no input and writes nothing.
"""

from __future__ import annotations

import argparse
import io
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TAIL_LINES = 200          # history shown to a newly connected viewer
POLL_S = 0.25             # file poll interval
PING_S = 15               # SSE keep-alive comment interval

ROOT = "captures"
PINNED: str | None = None  # --capture overrides "follow newest"


def newest_capture(root: str) -> str | None:
    try:
        dirs = [os.path.join(root, d) for d in os.listdir(root)
                if os.path.isdir(os.path.join(root, d))]
    except FileNotFoundError:
        return None
    dirs = [d for d in dirs if os.path.exists(os.path.join(d, "tap.log"))]
    return max(dirs, key=os.path.getmtime) if dirs else None


def lan_ips() -> list[str]:
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except socket.gaierror:
        pass
    return sorted(ips)


PAGE = """<!doctype html>
<meta charset="utf-8">
<title>serialtools live tap</title>
<style>
  body { margin:0; background:#0d1117; color:#c9d1d9;
         font:13px/1.5 Consolas, "Cascadia Mono", monospace; }
  #bar { position:sticky; top:0; background:#161b22; padding:6px 12px;
         border-bottom:1px solid #30363d; display:flex; gap:16px; }
  #bar b { color:#58a6ff; font-weight:normal; }
  #st.ok { color:#3fb950; } #st.bad { color:#f85149; }
  #log { padding:8px 12px; white-space:pre-wrap; word-break:break-all; }
  .err { color:#f85149; }
</style>
<div id="bar"><b>serialtools tap</b><span id="src">-</span>
  <span id="st" class="bad">connecting&#8230;</span>
  <span id="n">0 lines</span></div>
<div id="log"></div>
<script>
  const log = document.getElementById("log"), st = document.getElementById("st"),
        n = document.getElementById("n"), src = document.getElementById("src");
  let count = 0;
  function pinned() {  // don't yank the view if the reader scrolled up
    return window.innerHeight + window.scrollY >= document.body.offsetHeight - 60;
  }
  const es = new EventSource("/stream");
  es.onopen  = () => { st.textContent = "live"; st.className = "ok"; };
  es.onerror = () => { st.textContent = "reconnecting…"; st.className = "bad"; };
  es.addEventListener("src", e => { src.textContent = e.data; });
  es.onmessage = e => {
    const stick = pinned();
    const div = document.createElement("div");
    div.textContent = e.data;
    if (e.data.includes("ERR ")) div.className = "err";
    log.appendChild(div);
    n.textContent = (++count) + " lines";
    while (log.childElementCount > 4000) log.removeChild(log.firstChild);
    if (stick) window.scrollTo(0, document.body.scrollHeight);
  };
</script>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter console
        print(f"[{self.address_string()}] {fmt % args}")

    def do_GET(self):
        if self.path == "/stream":
            self.stream()
        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def sse(self, data: str, event: str | None = None):
        msg = ""
        if event:
            msg += f"event: {event}\n"
        for line in data.splitlines() or [""]:
            msg += f"data: {line}\n"
        self.wfile.write((msg + "\n").encode("utf-8", "replace"))
        self.wfile.flush()

    def stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        current: str | None = None
        f: io.TextIOBase | None = None
        last_ping = time.time()
        try:
            while True:
                want = PINNED or newest_capture(ROOT)
                if want and want != current:
                    if f:
                        f.close()
                    current = want
                    f = open(os.path.join(current, "tap.log"),
                             encoding="utf-8", errors="replace")
                    tail = f.readlines()[-TAIL_LINES:]
                    self.sse(os.path.basename(current), event="src")
                    for line in tail:
                        self.sse(line.rstrip("\n"))
                if f:
                    line = f.readline()
                    if line:
                        self.sse(line.rstrip("\n"))
                        continue
                if time.time() - last_ping > PING_S:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_ping = time.time()
                time.sleep(POLL_S)
        except (ConnectionError, BrokenPipeError, OSError):
            pass
        finally:
            if f:
                f.close()


def main():
    global ROOT, PINNED
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8686)
    ap.add_argument("--root", default="captures", help="captures directory to watch")
    ap.add_argument("--capture", help="pin to one capture dir instead of following newest")
    args = ap.parse_args()
    ROOT, PINNED = args.root, args.capture

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"[+] read-only tap feed on port {args.port}")
    for ip in lan_ips() or ["<your-lan-ip>"]:
        print(f"    share:  http://{ip}:{args.port}")
    print("[+] following " + (PINNED or f"newest capture under {ROOT}/") + ". Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
