"""HTTP state — the outward-facing world of the Semantic Operator Runtime.

docs/DESIGN-P8-http-operators.md names the rules this module enforces:

  - a worker never names a host. It names an ENDPOINT from the owner's
    [agent.http_endpoints.<name>] table in settings.toml (base URL, allowed
    methods, the NAME of the environment variable holding the bearer, a
    byte cap); the adapter builds the URL from the endpoint's base plus a
    screened relative path and a screened query. Empty table = every HTTP
    tool refuses, fail closed;
  - every WRITE declares how it will be READ BACK: after the request the
    adapter performs the declared GET and compares its canonical body (or
    a JSON-pointer projection) with `expect`. Equal, the effect stands;
    otherwise it is REFUSED AS UNVERIFIED — a remote write cannot be
    rolled back, and the receipt says so instead of saying ok;
  - bodies are DATA: canonical JSON (sorted keys, bounded size, depth and
    string length, no control characters), or refused. Redirects are never
    followed. Credentials are resolved at call time from the named
    variable through the one credential model (credentials.resolve) and
    appear in no capture, receipt or procedure — only the variable's name
    does; an endpoint whose variable is unset refuses rather than calling
    anonymously;
  - exactly-once across retries is the existing effects ledger's job
    (effects.py, in the worker tool); the adapter also sends the ledger key
    as an Idempotency-Key header for APIs that honour it, and says plainly
    that an API which ignores the header may double-write.

Tool-name mapping:
  http_observe  ->  observe (GET, canonical body)
  http_effect   ->  effect  (write, then re-observe, or refuse)

Authority: writing through an endpoint requires the owner-granted token
"http-write:<endpoint>" ([agent] http_write, default empty — fail closed).
Observation requires only that the endpoint exists.

Not a general HTTP client: no cookies, no sessions, no OAuth, no forms, no
streaming, no non-JSON bodies. Anything richer is a later phase.
"""
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 1024 * 1024
MAX_STRING = 65536
MAX_DEPTH = 32
MAX_QUERY = 32
TIMEOUT_SECONDS = 30
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_PATH_RE = re.compile(r"^[A-Za-z0-9_.~-]+(?:/[A-Za-z0-9_.~-]+)*$")
_POINTER_RE = re.compile(r"^(?:/[^/~]*(?:~[01][^/~]*)*)*$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _fail(why):
    raise ValueError(f"http state: {why}")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


# ------------------------------------------------------------ endpoints

def endpoints(cfg):
    """[agent.http_endpoints.<name>] -> {name: {base, methods, auth_env,
    max_bytes}}, every entry validated. The owner's table is the whole
    universe of hosts a worker can ever reach."""
    table = (cfg or {}).get("agent", {}).get("http_endpoints") or {}
    if not isinstance(table, dict):
        _fail("[agent] http_endpoints must be a table of endpoints")
    out = {}
    for name, entry in table.items():
        if not isinstance(name, str) or not _NAME_RE.match(name):
            _fail(f"endpoint name {name!r} is not acceptable")
        if not isinstance(entry, dict) or not isinstance(entry.get("base"), str):
            _fail(f"endpoint {name} needs a base URL")
        parts = urllib.parse.urlsplit(entry["base"])
        if parts.scheme not in ("http", "https") or not parts.hostname or \
                parts.query or parts.fragment or "@" in parts.netloc:
            _fail(f"endpoint {name} base must be an http(s) URL with a host, "
                  f"no query, no fragment, no userinfo")
        methods = entry.get("methods", ["GET"])
        if not isinstance(methods, list) or not methods or any(
                m not in METHODS for m in methods):
            _fail(f"endpoint {name} methods must be a list drawn from {METHODS}")
        auth_env = entry.get("auth_env", "")
        if auth_env and (not isinstance(auth_env, str)
                         or not _ENV_RE.match(auth_env)):
            _fail(f"endpoint {name} auth_env must name an environment variable")
        max_bytes = entry.get("max_bytes", MAX_BYTES)
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
            _fail(f"endpoint {name} max_bytes must be 1..{MAX_BYTES}")
        out[name] = {"base": entry["base"].rstrip("/"),
                     "methods": list(methods),
                     "auth_env": auth_env or "", "max_bytes": max_bytes}
    return out


def endpoint(cfg, name):
    table = endpoints(cfg)
    if not isinstance(name, str) or name not in table:
        _fail(f"endpoint {name!r} is not in the owner's [agent] "
              f"http_endpoints table (have {sorted(table)}) — nothing "
              f"self-grants a host")
    return table[name]


def load_settings(root):
    """The expert's settings.toml as a dict ({} when absent) — the same
    file the loop reads; a procedure arena carries a copy so the endpoint
    table is the owner's wherever the step runs."""
    import tomllib
    try:
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            return tomllib.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError):
        return {}


def load_endpoint(root, name):
    return endpoint(load_settings(root), name)


def resolve_token(entry, root):
    """The bearer for this endpoint, resolved at call time through the one
    credential model; "" when the endpoint declares no auth. An endpoint
    that declares a variable which is unset REFUSES — a request that was
    meant to be authenticated never goes out anonymously."""
    if not entry.get("auth_env"):
        return ""
    import credentials
    token = credentials.resolve({"api_key_env": entry["auth_env"]}, root)
    if not token:
        _fail(f"credential {entry['auth_env']} is not set (environment or "
              f"agent.env) — nothing self-grants; the owner supplies it")
    return token


# ------------------------------------------------------------ screening

def canonical_path(value):
    if not isinstance(value, str) or not _PATH_RE.match(value) or \
            ".." in value.split("/") or len(value) > 512:
        _fail(f"path {value!r} is not acceptable: relative segments of "
              f"[A-Za-z0-9_.~-], no '..', no scheme, no '@', no '?'")
    return value


def canonical_query(text):
    if text is None or (isinstance(text, str) and not text.strip()):
        return "{}"
    try:
        query = json.loads(text) if isinstance(text, str) else None
    except ValueError as exc:
        _fail(f"query is not valid JSON ({exc})")
    if not isinstance(query, dict) or len(query) > MAX_QUERY or any(
            not isinstance(k, str) or not k or len(k) > 64
            or not isinstance(v, str) or len(v) > 512
            for k, v in query.items()):
        _fail(f"query must be an object of at most {MAX_QUERY} string "
              f"parameters (values at most 512 chars)")
    return _canonical(query)


def _bounded(value, depth=0):
    if depth > MAX_DEPTH:
        _fail(f"JSON nests deeper than {MAX_DEPTH}")
    if isinstance(value, str):
        if len(value) > MAX_STRING:
            _fail(f"a string exceeds {MAX_STRING} chars")
        if _CONTROL_RE.search(value):
            _fail("a string carries a control character")
        return value
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        _fail(f"{value!r} is a float — approximate numbers are not exact "
              f"evidence; APIs that must carry money carry cents or text")
    if isinstance(value, list):
        return [_bounded(v, depth + 1) for v in value]
    if isinstance(value, dict):
        return {str(k): _bounded(v, depth + 1) for k, v in value.items()}
    _fail(f"unsupported JSON value {type(value).__name__}")


def canonical_json(text):
    """Any JSON text -> canonical, bounded JSON text (the shape of every
    body, every expectation, every observation)."""
    if isinstance(text, (bytes, bytearray)):
        if len(text) > MAX_BYTES:
            _fail(f"body exceeds {MAX_BYTES} bytes")
        try:
            text = text.decode("utf-8", "strict") if text else "null"
        except UnicodeDecodeError as exc:
            _fail(f"body is not UTF-8 ({exc})")
    if not isinstance(text, str):
        _fail("JSON must be text")
    try:
        value = json.loads(text)
    except ValueError as exc:
        _fail(f"not valid JSON ({exc})")
    return _canonical(_bounded(value))


def canonical_readback(text):
    """{path, expect, query?, pointer?} -> canonical JSON. `expect` is the
    exact canonical value the readback (or its pointer projection) must
    equal for the effect to stand."""
    try:
        readback = json.loads(text) if isinstance(text, str) else None
    except ValueError as exc:
        _fail(f"readback is not valid JSON ({exc})")
    if not isinstance(readback, dict) or "path" not in readback or \
            "expect" not in readback or set(readback) - {"path", "query",
                                                          "expect", "pointer"}:
        _fail("readback is {path, expect, query?, pointer?} — a write with "
              "no declared readback is not verified and refuses")
    # values, not nested text: canonicalizing a canonical readback again
    # must yield the same bytes, so `expect` and `query` are stored as the
    # JSON values they are and serialized exactly once, here
    query = readback.get("query", {})
    if isinstance(query, str):
        query = json.loads(canonical_query(query))
    out = {"path": canonical_path(readback["path"]),
           "query": json.loads(canonical_query(_canonical(query))),
           "expect": _bounded(readback["expect"])}
    if "pointer" in readback:
        pointer = readback["pointer"]
        if not isinstance(pointer, str) or not _POINTER_RE.match(pointer) or \
                len(pointer) > 256:
            _fail("pointer must be a JSON pointer such as /items/0/id")
        out["pointer"] = pointer
    return _canonical(out)


def canonical_method(value):
    if not isinstance(value, str) or value.upper() not in METHODS:
        _fail(f"method must be one of {METHODS}")
    return value.upper()


def project(value, pointer):
    """RFC 6901 projection; a missing step is a refusal, not None."""
    if not pointer:
        return value
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not token.isdigit() or int(token) >= len(value):
                _fail(f"pointer step {token!r} is outside the list")
            value = value[int(token)]
        elif isinstance(value, dict):
            if token not in value:
                _fail(f"pointer step {token!r} is not in the object")
            value = value[token]
        else:
            _fail(f"pointer step {token!r} descends into a scalar")
    return value


# ------------------------------------------------------------- requests

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _fail(f"redirect ({code}) refused: the adapter never follows one, "
              f"so a credential never travels to a host the owner did not name")


_OPENER = urllib.request.build_opener(_NoRedirect)


def build_url(entry, path, query_text):
    query = json.loads(canonical_query(query_text))
    url = entry["base"] + "/" + canonical_path(path)
    if query:
        url += "?" + urllib.parse.urlencode(sorted(query.items()))
    if urllib.parse.urlsplit(url).netloc != \
            urllib.parse.urlsplit(entry["base"]).netloc:
        _fail("the request would leave the endpoint's host")
    return url


def _send(entry, method, url, body_text, token, extra_headers=None):
    if method not in entry["methods"]:
        _fail(f"method {method} is not allowed on this endpoint "
              f"(allowed: {entry['methods']})")
    headers = {"Accept": "application/json",
               "User-Agent": "agent-httpstate/1"}
    data = None
    if body_text is not None:
        data = body_text.encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    headers.update(extra_headers or {})
    request = urllib.request.Request(url, data=data, method=method,
                                     headers=headers)
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(entry["max_bytes"] + 1)
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read(entry["max_bytes"] + 1) if exc.fp else b""
        status = exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # a ValueError here is our own redirect refusal, re-raised whole
        if isinstance(exc, ValueError) and str(exc).startswith("http state:"):
            raise
        _fail(f"{method} {path_of(url)} failed: {exc}")
    if len(raw) > entry["max_bytes"]:
        _fail(f"response exceeds the endpoint's {entry['max_bytes']} bytes")
    return status, raw


def path_of(url):
    """The path part only — never the host in a message, never a query
    value: what the model is told about a failure is bounded too."""
    parts = urllib.parse.urlsplit(url)
    return parts.path


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def observe(entry, path, query_text, token):
    """GET -> canonical JSON body text; a non-2xx status or a non-JSON body
    refuses (an observation that cannot be canonical is not evidence)."""
    url = build_url(entry, path, query_text)
    status, raw = _send(entry, "GET", url, None, token)
    if not 200 <= status < 300:
        _fail(f"GET {path} answered {status}")
    return canonical_json(raw)


def check(entry, readback_text, token):
    """Perform the declared readback NOW and compare. -> (ok, why)."""
    readback = json.loads(canonical_readback(readback_text))
    want = _canonical(readback["expect"])
    try:
        body = observe(entry, readback["path"], _canonical(readback["query"]),
                       token)
        got = _canonical(project(json.loads(body),
                                 readback.get("pointer", "")))
    except ValueError as exc:
        return False, str(exc)
    if got != want:
        return False, (f"readback {readback['path']} observed {got[:160]!r}, "
                       f"declared {want[:160]!r}")
    return True, ""


def readback_state(entry, readback_text, token):
    """The readback as EVIDENCE: {"exists": the GET answered canonical JSON,
    "hash": sha256 of that canonical body (None when it did not answer)} —
    the before/after snapshot a trajectory records for an http effect."""
    readback = json.loads(canonical_readback(readback_text))
    try:
        body = observe(entry, readback["path"], _canonical(readback["query"]),
                       token)
    except ValueError:
        return {"exists": False, "hash": None}
    return {"exists": True, "hash": _digest(body)}


def effect(entry, method, path, body_text, readback_text, token,
           idempotency_key):
    """The write, then the declared readback. -> receipt dict with
    verified=True, or raises with the receipt's reason: the request WAS
    sent — a remote write cannot be rolled back — and the effect is
    refused as unverified."""
    method = canonical_method(method)
    readback = canonical_readback(readback_text)
    body = canonical_json(body_text) if body_text not in (None, "") else None
    url = build_url(entry, path, "{}")
    status, raw = _send(entry, method, url, body, token,
                        {"Idempotency-Key": idempotency_key}
                        if idempotency_key else None)
    receipt = {"method": method, "path": path, "status": status,
               "request_sha256": _digest(body or ""),
               "response_sha256": hashlib.sha256(raw).hexdigest(),
               "readback": readback, "verified": False}
    if not 200 <= status < 300:
        _fail(f"{method} {path} answered {status} — effect unverified; "
              f"receipt {_canonical(receipt)}")
    ok, why = check(entry, readback, token)
    if not ok:
        _fail(f"effect unverified — the write was sent but its readback did "
              f"not match: {why}; receipt {_canonical(receipt)}")
    receipt["verified"] = True
    return receipt
