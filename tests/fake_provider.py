#!/usr/bin/env python3
"""A LOOPBACK SERVER THAT SPEAKS THE REAL PROVIDER API.

Every test in this suite drives the `type = "mock"` branch of
`Agent.call_model`, which returns a scripted message and never touches the
network. That branch is ~10 lines. The LIVE branch is ~90, and until now it
had never been executed by anything: payload construction, the Authorization
header, `extra_headers`, response parsing, usage-based cost, the 429/5xx
backoff ladder, the non-retryable break, `permanent_net_error` failover, the
fallback-provider chain and tool-call parsing were all first exercised the
moment somebody spent real money.

This server is the missing half. It implements `POST /chat/completions` the
way an OpenAI-compatible provider does, and it can be told to misbehave —
rate-limit, 500, hang, return malformed JSON, demand a particular key — so
the failure paths are exercised too.

It is a TEST DOUBLE and says so: it proves the platform's HTTP client is
correct, not that any real provider behaves this way. A provider that
deviates from this shape will still surprise us, and `python loop.py check`
remains the only live probe.

Usage:
    srv = FakeProvider()
    srv.reply(tool="write_file", args={"path": "out/a.md", "content": "x"})
    ... point a provider's base_url at srv.base_url ...
    srv.stop()
"""

import http.server
import json
import os
import threading
import time

# A private reference to the REAL sleep, captured at import.
#
# Tests that exercise the client's backoff ladder patch `time.sleep` to make
# it instant — and the server shares that module, so a patched sleep silently
# turned this server's deliberate hang into no hang at all. The test then
# "passed" a timeout it had never actually caused. A test double must be
# immune to the instrumentation applied to the thing it is doubling for.
_REAL_SLEEP = time.sleep


class FakeProvider:
    """An OpenAI-compatible /chat/completions endpoint on loopback."""

    def __init__(self, require_key=None, name="fake"):
        self.name = name
        self.require_key = require_key
        self.script = []            # queued responses, consumed in order
        self.default = None         # used when the script is empty
        self.requests = []          # every request received, for assertions
        self.fail_next = []         # queued failures: ("http", 503) / ("hang",)
        self.delay = 0.0
        os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
        os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                raw = body if isinstance(body, bytes) else \
                    json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = {"_unparseable": raw[:200].decode("utf-8", "replace")}
                outer.requests.append({
                    "path": self.path,
                    "payload": payload,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                })
                if outer.delay:
                    _REAL_SLEEP(outer.delay)
                # a queued failure takes precedence, so the retry ladder can
                # be driven deterministically
                if outer.fail_next:
                    kind, *rest = outer.fail_next.pop(0)
                    if kind == "http":
                        self._send(rest[0], {"error": {"message": "injected"}})
                        return
                    if kind == "garbage":
                        self._send(200, b"not json at all", "text/plain")
                        return
                    if kind == "empty_choices":
                        self._send(200, {"choices": [], "usage": {}})
                        return
                    if kind == "hang":
                        _REAL_SLEEP(rest[0] if rest else 30)
                        self._send(200, outer._next_body())
                        return
                if outer.require_key:
                    got = self.headers.get("Authorization", "")
                    if got != f"Bearer {outer.require_key}":
                        self._send(401, {"error": {"message":
                                                   "invalid api key"}})
                        return
                if not self.path.endswith("/chat/completions"):
                    self._send(404, {"error": {"message": "no such route"}})
                    return
                self._send(200, outer._next_body())

        self._srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._srv.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}/v1"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    # ---------------------------------------------------------------- script

    def reply(self, text=None, tool=None, args=None, usage=None, times=1):
        """Queue a response. `tool` produces a native tool_calls message;
        `text` produces a plain content message."""
        for _ in range(times):
            self.script.append(self._body(text, tool, args, usage))
        return self

    def always(self, text=None, tool=None, args=None, usage=None):
        self.default = self._body(text, tool, args, usage)
        return self

    def fail(self, code=503, times=1):
        for _ in range(times):
            self.fail_next.append(("http", code))
        return self

    def misbehave(self, kind, *rest):
        """`garbage`, `empty_choices` or `hang` — the shapes that are not
        HTTP errors and still break a naive client."""
        self.fail_next.append((kind, *rest))
        return self

    @staticmethod
    def _body(text=None, tool=None, args=None, usage=None):
        msg = {"role": "assistant", "content": text}
        if tool:
            msg["tool_calls"] = [{
                "id": "call_1", "type": "function",
                "function": {"name": tool,
                             "arguments": json.dumps(args or {})}}]
        return {"id": "chatcmpl-fake", "object": "chat.completion",
                "choices": [{"index": 0, "message": msg,
                             "finish_reason": "tool_calls" if tool else "stop"}],
                "usage": usage or {"prompt_tokens": 100,
                                   "completion_tokens": 20,
                                   "total_tokens": 120}}

    def _next_body(self):
        if self.script:
            return self.script.pop(0)
        if self.default is not None:
            return self.default
        return self._body(tool="finish_task", args={"summary": "done"})

    # ------------------------------------------------------------ assertions

    @property
    def last(self):
        return self.requests[-1] if self.requests else None

    def stop(self):
        try:
            self._srv.shutdown()
        except Exception:
            pass
        try:
            self._srv.server_close()
        except Exception:
            pass


def provider_block(name, base_url, key_env=None, key=None, native_tools=True,
                   headers=None):
    """The settings.toml text for a LIVE (non-mock) provider."""
    lines = [f"[providers.{name}]", f'base_url = "{base_url}"']
    if key_env:
        lines.append(f'api_key_env = "{key_env}"')
    if key:
        lines.append(f'api_key = "{key}"')
    if not native_tools:
        lines.append("native_tools = false")
    if headers:
        inner = ", ".join(f'{k} = "{v}"' for k, v in headers.items())
        lines.append(f"extra_headers = {{{inner}}}")
    return "\n".join(lines)
