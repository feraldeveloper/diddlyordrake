"""Integration checks for the persistent voting API; run python -m unittest."""

import http.client
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from server import COOKIE_NAME, VoteHandler, VoteServer


class VotingTests(unittest.TestCase):
    def setUp(self):
        self.logger = patch.object(VoteHandler, "log_message")
        self.logger.start()
        self.addCleanup(self.logger.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "votes.sqlite3"
        self.start_server()

    def start_server(self):
        self.server = VoteServer(("127.0.0.1", 0), self.database)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def tearDown(self):
        self.stop_server()
        self.directory.cleanup()

    def request(self, method="GET", path="/api/votes", body=None, cookie=None, headers=None):
        request_headers = dict(headers or {})
        if cookie:
            request_headers["Cookie"] = cookie
        if isinstance(body, dict):
            body = json.dumps(body)
            request_headers.setdefault("Content-Type", "application/json")
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            data = response.read()
            return response.status, dict(response.getheaders()), data
        finally:
            connection.close()

    def vote(self, choice, cookie=None):
        status, headers, data = self.request("POST", body={"choice": choice}, cookie=cookie)
        self.assertEqual(status, 200, data)
        return json.loads(data), headers.get("Set-Cookie", "").split(";", 1)[0]

    def test_new_vote_repeat_switch_and_separate_browser(self):
        status, _, data = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"votes": {"diddly": 0, "drake": 0}, "total": 0, "choice": None})
        state, cookie = self.vote("diddly")
        self.assertEqual(state, {"votes": {"diddly": 1, "drake": 0}, "total": 1, "choice": "diddly"})
        state, _ = self.vote("diddly", cookie)
        self.assertEqual(state["total"], 1)
        state, _ = self.vote("drake", cookie)
        self.assertEqual(state, {"votes": {"diddly": 0, "drake": 1}, "total": 1, "choice": "drake"})
        state, _ = self.vote("diddly")
        self.assertEqual(state["total"], 2)
        _, _, data = self.request(cookie=cookie)
        self.assertEqual(json.loads(data)["choice"], "drake")
        _, _, data = self.request()
        self.assertIsNone(json.loads(data)["choice"])

    def test_votes_survive_restart(self):
        _, cookie = self.vote("drake")
        self.stop_server()
        self.start_server()
        _, _, data = self.request(cookie=cookie)
        self.assertEqual(json.loads(data), {"votes": {"diddly": 0, "drake": 1}, "total": 1, "choice": "drake"})

    def test_cookie_attributes_and_invalid_cookie_recovery(self):
        status, headers, data = self.request("POST", body={"choice": "diddly"}, cookie=COOKIE_NAME + "=invalid")
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", headers["Set-Cookie"])
        self.assertIn("Path=/", headers["Set-Cookie"])
        self.assertNotIn(COOKIE_NAME, data.decode())
        token = headers["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
        self.assertEqual(len(token), 43)

    def test_bad_requests_do_not_vote(self):
        cases = [
            ("{", {"Content-Type": "application/json"}, 400),
            ({"choice": "other"}, {}, 400),
            ({"choice": []}, {}, 400),
            ("[]", {"Content-Type": "application/json"}, 400),
            ('{"choice":"diddly"}', {"Content-Type": "text/plain"}, 415),
            (" " * 1025, {"Content-Type": "application/json"}, 413),
            ({"choice": "diddly"}, {"Origin": "https://unrelated.example"}, 403),
            ({"choice": "diddly"}, {"Sec-Fetch-Site": "cross-site"}, 403),
        ]
        for body, headers, expected in cases:
            with self.subTest(body=str(body)[:40], headers=headers):
                status, _, data = self.request("POST", body=body, headers=headers)
                self.assertEqual(status, expected, data)
                self.assertIn("error", json.loads(data))
        _, _, data = self.request()
        self.assertEqual(json.loads(data)["total"], 0)

    def test_same_origin_and_head(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, _, _ = self.request("POST", body={"choice": "diddly"}, headers={"Origin": origin})
        self.assertEqual(status, 200)
        status, headers, data = self.request("HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(data, b"")
        self.assertGreater(int(headers["Content-Length"]), 0)

    def test_https_proxy_cookie_and_origin(self):
        origin = f"https://127.0.0.1:{self.server.server_port}"
        status, _, _ = self.request("POST", body={"choice": "diddly"}, headers={"Origin": origin})
        self.assertEqual(status, 403)
        self.server.secure_cookies = True
        status, headers, _ = self.request("POST", body={"choice": "diddly"}, headers={"Origin": origin})
        self.assertEqual(status, 200)
        self.assertIn("Secure", headers["Set-Cookie"])

    def test_private_files_not_served(self):
        for path in ("/server.py", "/test_server.py", "/start.cmd", "/data/votes.sqlite3",
                     "/.git/config", "/../server.py", "/%2e%2e/server.py"):
            with self.subTest(path=path):
                status, _, _ = self.request(path=path)
                self.assertEqual(status, 404)

    def test_parallel_votes_do_not_lose_updates(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            votes = list(executor.map(lambda _: self.vote("diddly"), range(16)))
        self.assertEqual(len({cookie for _, cookie in votes}), 16)
        _, _, data = self.request()
        self.assertEqual(json.loads(data)["votes"], {"diddly": 16, "drake": 0})


if __name__ == "__main__":
    unittest.main()
