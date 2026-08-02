#!/usr/bin/env python3
"""arnold-session - on-demand warm session for the Arnold doorbell soundboard.

go2rtc tears down the RTSP backchannel to the doorbell after every clip, so each
button press pays a fresh handshake (~1.55s measured). Holding a consumer open on
the talk stream keeps that session established and cuts a press to ~0.7s.

Keeping it open permanently is wasteful, so this opens the session on the first
press, keeps it warm while the soundboard is in use, and drops it after
IDLE_TIMEOUT seconds of inactivity.

Also validates that the clip exists before handing off. go2rtc answers 200 for a
missing file, so a clip directory that disappears fails completely silently -
Home Assistant logs every press as successful while nothing plays.
"""

import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GO2RTC = os.environ.get("GO2RTC_URL", "http://127.0.0.1:1984").rstrip("/")
STREAM = os.environ.get("STREAM", "doorbell_talk")
CLIP_DIR = os.environ.get("CLIP_DIR", "/clips")
REMOTE_CLIP_DIR = os.environ.get("REMOTE_CLIP_DIR", "/arnold-clips")
IDLE_TIMEOUT = float(os.environ.get("IDLE_TIMEOUT", "90"))
PLAY_TIMEOUT = float(os.environ.get("PLAY_TIMEOUT", "20"))
PORT = int(os.environ.get("PORT", "8098"))

# Clip names come from a Lovelace dashboard, but this endpoint is reachable on
# the LAN. Refuse anything that could climb out of the clip directory.
CLIP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


class Session:
    """Holds a consumer on the talk stream so the camera handshake stays warm."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active = False
        self._stop = threading.Event()
        self._resp = None
        self._last_used = 0.0
        threading.Thread(target=self._reaper, daemon=True).start()

    def touch(self):
        """Mark the soundboard as in use, starting the session if needed."""
        with self._lock:
            self._last_used = time.time()
            if self._active:
                return False
            self._active = True
            self._stop.clear()
            threading.Thread(target=self._hold, daemon=True).start()
            log(f"session opened (idle timeout {IDLE_TIMEOUT:.0f}s)")
            return True

    def _hold(self):
        """Read and discard the talk stream until asked to stop."""
        url = f"{GO2RTC}/api/stream.mp4?src={urllib.parse.quote(STREAM)}"
        while not self._stop.is_set():
            try:
                resp = urllib.request.urlopen(url, timeout=10)
                with self._lock:
                    self._resp = resp
                while not self._stop.is_set():
                    if not resp.read(16384):
                        break
            except Exception as exc:
                if not self._stop.is_set():
                    log(f"keepalive dropped ({exc}); retrying")
                    time.sleep(2)
            finally:
                with self._lock:
                    if self._resp is not None:
                        try:
                            self._resp.close()
                        except Exception:
                            pass
                        self._resp = None

    def _reaper(self):
        while True:
            time.sleep(2)
            with self._lock:
                if not self._active:
                    continue
                if time.time() - self._last_used < IDLE_TIMEOUT:
                    continue
                self._active = False
                self._stop.set()
                if self._resp is not None:
                    try:
                        self._resp.close()
                    except Exception:
                        pass
                    self._resp = None
            log("session closed (idle)")

    def status(self):
        with self._lock:
            idle = time.time() - self._last_used if self._last_used else None
            return {
                "active": self._active,
                "idle_seconds": round(idle, 1) if idle is not None else None,
                "idle_timeout": IDLE_TIMEOUT,
                "stream": STREAM,
            }


session = Session()


def play(clip):
    """Validate the clip, warm the session, then hand off to go2rtc."""
    if not CLIP_RE.match(clip):
        return 400, f"invalid clip name: {clip!r}"

    local = os.path.join(CLIP_DIR, f"{clip}.mp3")
    if not os.path.isfile(local):
        # The whole point of this check: go2rtc would return 200 regardless.
        return 404, f"clip not found: {clip}.mp3"

    opened = session.touch()

    url = (
        f"{GO2RTC}/api/ffmpeg"
        f"?dst={urllib.parse.quote(STREAM)}"
        f"&file={urllib.parse.quote(REMOTE_CLIP_DIR + '/' + clip + '.mp3')}"
    )
    started = time.time()
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=PLAY_TIMEOUT) as resp:
            code = resp.status
    except urllib.error.HTTPError as exc:
        return 502, f"go2rtc rejected clip {clip}: HTTP {exc.code}"
    except Exception as exc:
        return 502, f"go2rtc unreachable: {exc}"

    took = time.time() - started
    log(f"played {clip} in {took:.2f}s ({'cold' if opened else 'warm'})")
    return (200, f"ok {clip} {took:.2f}s") if code == 200 else (502, f"go2rtc HTTP {code}")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, code, body):
        payload = (body + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/healthz":
            return self._reply(200, "ok")
        if parsed.path == "/status":
            st = session.status()
            return self._reply(200, " ".join(f"{k}={v}" for k, v in st.items()))
        if parsed.path == "/warm":
            # Pre-warm so the first press is not the one that pays the cold
            # handshake. Costs an extra RTSP pull from the doorbell while held,
            # so trigger it on something deliberate like a doorbell press.
            opened = session.touch()
            log("warmed" + ("" if opened else " (already active)"))
            return self._reply(200, "warming" if opened else "already warm")
        if parsed.path == "/play":
            clip = (query.get("clip") or [""])[0]
            if not clip:
                return self._reply(400, "missing clip parameter")
            return self._reply(*play(clip))
        self._reply(404, "not found")

    def do_POST(self):
        self.do_GET()

    def log_message(self, fmt, *args):
        pass  # play() already logs; skip the per-request access noise


if __name__ == "__main__":
    log(f"listening on :{PORT} -> {GO2RTC} stream={STREAM} clips={CLIP_DIR}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
