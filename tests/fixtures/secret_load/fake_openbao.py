"""Local OpenBao KV v2 stand-in for secret-load behavior tests."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class FakeOpenBao:
    def __init__(self):
        self.entries = {}
        self.requests = []
        self.raw_request_bodies = []
        self.request_headers = []
        self.write_error = False
        self.readback_mismatch = False
        self.raise_version = False
        self.revoke_error = False
        self.token_live = False
        self.written = False
        self.read_fault = None
        self.login_fault = None
        self.write_fault = None
        self.revoke_disconnect = False
        self.on_revoke = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self, status, body=None):
                raw = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def handle_request(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                body = json.loads(raw_body) if raw_body else None
                token = self.headers.get("X-Vault-Token")
                owner.requests.append((self.command, self.path, token, body))
                owner.raw_request_bodies.append(raw_body)
                owner.request_headers.append(dict(self.headers.items()))
                if (
                    self.path == "/v1/auth/userpass/login/keepbreath0"
                    and self.command == "POST"
                ):
                    if owner.login_fault is not None:
                        self.answer(
                            200,
                            None
                            if owner.login_fault == "no-body"
                            else owner.login_fault,
                        )
                        return
                    if body == {"password": "dummy-login-pw-5555"}:
                        owner.token_live = True
                        self.answer(
                            200,
                            {
                                "auth": {
                                    "client_token": "dummy-bao-token-7777",
                                    "lease_duration": 2764800,
                                    "renewable": True,
                                }
                            },
                        )
                    else:
                        self.answer(400, {"errors": ["invalid username or password"]})
                    return
                if not owner.token_live or token != "dummy-bao-token-7777":
                    self.answer(403, {"errors": ["permission denied"]})
                    return
                if self.path == "/v1/auth/token/revoke-self" and self.command == "POST":
                    if owner.on_revoke is not None:
                        owner.on_revoke()
                    if owner.revoke_disconnect:
                        self.connection.close()
                        return
                    if owner.revoke_error:
                        self.answer(500, {"errors": ["internal error"]})
                    else:
                        owner.token_live = False
                        self.answer(204)
                    return
                if not self.path.startswith("/v1/secret/data/"):
                    self.answer(404, {"errors": ["no handler for route"]})
                    return
                path = self.path[len("/v1/secret/data/") :]
                entry = owner.entries.get(path)
                if self.command == "GET":
                    if owner.read_fault is not None:
                        fault = owner.read_fault
                        owner.read_fault = None
                        if fault == "invalid-json":
                            self.send_response(200)
                            self.end_headers()
                            self.wfile.write(b"not json")
                        elif fault == "body-timeout":
                            self.send_response(200)
                            self.send_header("Content-Length", "1")
                            self.end_headers()
                            time.sleep(40)
                        elif fault == "malformed-one-field":
                            self.answer(
                                200,
                                {"data": {"data": None, "metadata": {"version": 1}}},
                            )
                        elif fault == "malformed-present":
                            self.answer(
                                200,
                                {"data": {"data": [], "metadata": {"version": "bad"}}},
                            )
                        elif fault == "malformed-deleted":
                            self.answer(
                                404,
                                {"data": {"data": "bad", "metadata": {"version": 3}}},
                            )
                        else:
                            self.answer(500, {"errors": ["internal error"]})
                        return
                    if entry is None:
                        self.answer(404, {"errors": []})
                    elif entry["deleted"]:
                        self.answer(
                            404,
                            {
                                "data": {
                                    "data": None,
                                    "metadata": {
                                        "version": entry["version"],
                                        "deletion_time": "2026-11-25T04:09:21Z",
                                        "destroyed": False,
                                    },
                                }
                            },
                        )
                    else:
                        data = dict(entry["data"])
                        if owner.written and owner.readback_mismatch:
                            data[next(iter(data))] = "different"
                        self.answer(
                            200,
                            {
                                "data": {
                                    "data": data,
                                    "metadata": {
                                        "version": entry["version"],
                                        "deletion_time": "",
                                        "destroyed": False,
                                    },
                                }
                            },
                        )
                    return
                if self.command == "POST":
                    if owner.write_fault is not None:
                        status, body = owner.write_fault
                        self.answer(status, body)
                        return
                    if owner.write_error:
                        self.answer(500, {"errors": ["internal error"]})
                        return
                    if owner.raise_version:
                        owner.raise_version = False
                        if entry is None:
                            entry = {"data": {}, "version": 0, "deleted": False}
                        entry["version"] += 1
                        owner.entries[path] = entry
                    current = entry["version"] if entry else 0
                    if body.get("options", {}).get("cas") != current:
                        self.answer(
                            400,
                            {
                                "errors": [
                                    "check-and-set parameter did not match the current version"
                                ]
                            },
                        )
                        return
                    owner.entries[path] = {
                        "data": dict(body["data"]),
                        "version": current + 1,
                        "deleted": False,
                    }
                    owner.written = True
                    self.answer(
                        200,
                        {
                            "data": {
                                "version": current + 1,
                                "deletion_time": "",
                                "destroyed": False,
                            }
                        },
                    )

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def address(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def seed(self, path, data, version=1, deleted=False):
        self.entries[path] = {
            "data": dict(data),
            "version": version,
            "deleted": deleted,
        }
