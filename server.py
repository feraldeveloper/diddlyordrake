"""Serve the Diddly or Drake page and its small, persistent voting API."""

import argparse
import json
import re
import secrets
import sqlite3
import ssl
from contextlib import closing
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
COOKIE_NAME = "diddlyordrake_voter"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
CHOICES = ("diddly", "drake")
MAX_BODY_BYTES = 1024
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/config.js": ("config.js", "text/javascript; charset=utf-8"),
    "/assets/fonts/PixelifySans.ttf": ("assets/fonts/PixelifySans.ttf", "font/ttf"),
}


class VoteStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS votes ("
                "voter_id TEXT PRIMARY KEY, "
                "choice TEXT NOT NULL CHECK (choice IN ('diddly', 'drake')))"
            )
            connection.commit()

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def snapshot(self, voter_id=None, choice=None):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if choice else "BEGIN")
            if choice:
                connection.execute(
                    "INSERT INTO votes (voter_id, choice) VALUES (?, ?) "
                    "ON CONFLICT(voter_id) DO UPDATE SET choice=excluded.choice",
                    (voter_id, choice),
                )
            counts = dict.fromkeys(CHOICES, 0)
            counts.update(connection.execute(
                "SELECT choice, COUNT(*) FROM votes GROUP BY choice"
            ).fetchall())
            selected = connection.execute(
                "SELECT choice FROM votes WHERE voter_id=?", (voter_id,)
            ).fetchone() if voter_id else None
            connection.commit()
            return {"votes": counts, "total": sum(counts.values()),
                    "choice": selected[0] if selected else None}
        finally:
            connection.close()


class VoteServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, database_path, secure_cookies=False):
        self.secure_cookies = secure_cookies
        self.store = VoteStore(database_path)
        super().__init__(address, VoteHandler)


class VoteHandler(BaseHTTPRequestHandler):
    server_version = "DiddlyOrDrake/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def send_payload(self, status, payload, content_type, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; "
                         "script-src 'self'; style-src 'self'; img-src 'self' data:; "
                         "connect-src 'self' https:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def send_json(self, status, data, cookie=None):
        self.send_payload(status, json.dumps(data, separators=(",", ":")).encode(),
                          "application/json; charset=utf-8", cookie)

    def send_error(self, code, message=None, explain=None):
        self.send_json(code, {"error": message or HTTPStatus(code).phrase})

    def voter_id(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        cookie = cookies.get(COOKIE_NAME)
        return cookie.value if cookie and TOKEN_PATTERN.fullmatch(cookie.value) else None

    def same_origin(self):
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        try:
            parsed = urlsplit(origin)
            host = urlsplit("//" + self.headers.get("Host", ""))
            expected_scheme = "https" if self.server.secure_cookies or isinstance(self.connection, ssl.SSLSocket) else "http"
            if parsed.scheme != expected_scheme or not parsed.hostname:
                return False
            if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                return False
            default_port = 443 if parsed.scheme == "https" else 80
            return (parsed.hostname.lower(), parsed.port or default_port) == (
                (host.hostname or "").lower(), host.port or default_port)
        except ValueError:
            return False

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/votes":
            try:
                self.send_json(200, self.server.store.snapshot(self.voter_id()))
            except sqlite3.Error:
                self.send_error(503, "Voting is temporarily unavailable. Please try again.")
            return
        static_file = STATIC_FILES.get(path)
        if not static_file:
            self.send_error(404, "Not found")
            return
        filename, content_type = static_file
        try:
            payload = (ROOT / filename).read_bytes()
        except OSError:
            self.send_error(404, "Not found")
            return
        self.send_payload(200, payload, content_type)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/votes":
            self.send_error(404, "Not found")
            return
        if not self.same_origin():
            self.send_error(403, "Please vote from this website.")
            return
        if self.headers.get("Transfer-Encoding"):
            self.send_error(400, "Transfer-Encoding is not supported.")
            return
        if self.headers.get_content_type() != "application/json":
            self.send_error(415, "Use application/json.")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if not lengths:
            self.send_error(411, "Content-Length is required.")
            return
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
            self.send_error(400, "Invalid Content-Length.")
            return
        length = int(lengths[0])
        if length > MAX_BODY_BYTES:
            self.send_error(413, "Vote request is too large.")
            return
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                self.send_error(400, "Incomplete request body.")
                return
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            self.send_error(400, "Invalid JSON.")
            return
        except TimeoutError:
            self.send_error(408, "Request timed out.")
            return
        if not isinstance(data, dict) or data.get("choice") not in CHOICES:
            self.send_error(400, "Choose diddly or drake.")
            return
        voter_id = self.voter_id()
        cookie_header = None
        if voter_id is None:
            voter_id = secrets.token_urlsafe(32)
            cookie = SimpleCookie()
            cookie[COOKIE_NAME] = voter_id
            cookie[COOKIE_NAME]["path"] = "/"
            cookie[COOKIE_NAME]["httponly"] = True
            cookie[COOKIE_NAME]["samesite"] = "Lax"
            cookie[COOKIE_NAME]["max-age"] = 31536000
            if self.server.secure_cookies or isinstance(self.connection, ssl.SSLSocket):
                cookie[COOKIE_NAME]["secure"] = True
            cookie_header = cookie.output(header="").strip()
        try:
            snapshot = self.server.store.snapshot(voter_id, data["choice"])
        except sqlite3.Error:
            self.send_error(503, "Voting is temporarily unavailable. Please try again.")
            return
        self.send_json(200, snapshot, cookie_header)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "votes.sqlite3",
                        help="SQLite file (default: data/votes.sqlite3 beside server.py)")
    parser.add_argument("--secure-cookies", action="store_true",
                        help="Require HTTPS origins and Secure cookies behind an HTTPS proxy")
    args = parser.parse_args()
    server = VoteServer((args.host, args.port), args.database, args.secure_cookies)
    print(f"Diddly or Drake: http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
