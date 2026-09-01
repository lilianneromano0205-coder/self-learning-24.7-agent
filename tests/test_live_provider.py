#!/usr/bin/env python3
"""THE LIVE PROVIDER PATH, EXERCISED BEFORE IT EVER SEES A REAL KEY.

Every other test in this suite drives `type = "mock"`, which returns a
scripted message and never opens a socket. The LIVE branch of
`Agent.call_model` is ninety lines that, until this file existed, had only
ever run against a real provider with a real key and real money:

  * payload construction — model, messages, max_tokens, the tool schema
    filtered by the role's own allowlist
  * the Authorization header, and all four ways a key can be configured
  * `extra_headers`
  * response parsing: `choices[0].message`, `usage`
  * cost computed from the usage the PROVIDER reported, not from a guess
  * the 429/5xx backoff ladder, and the non-retryable break on 4xx
  * `permanent_net_error` — a refused connection fails over instantly
    instead of costing a minute of backoff per step
  * the fallback-provider chain
  * `native_tools = false`, where the tool call arrives as inline JSON

A bug in any of those spends somebody's money to discover. `fake_provider.py`
is a loopback server that speaks the same HTTP contract and can be told to
misbehave, so all of it is exercised offline.

WHAT THIS DOES NOT PROVE: that any real provider behaves like this server.
It proves the platform's HTTP CLIENT is correct against the documented shape.
A provider that deviates will still surprise us, and `python loop.py check`
remains the only live probe.

Run from the agent/ directory:  python tests/test_live_provider.py
"""

import io
import json
import os
import sys
import time

from common import AGENT_DIR, make_sandbox, read_state, run_drain
from fake_provider import FakeProvider, provider_block

sys.path.insert(0, AGENT_DIR)
import loop                    # noqa: E402
import modelgateway            # noqa: E402


def settings(root, blocks, roles, extra="", timeout=8):
    """Write a settings.toml with LIVE providers — no mock anywhere."""
    # a trusted keyless fixture: its gates carry this host's python path, and
    # the subject of this file is the HTTP client, not the execution backend
    body = ["[agent]", 'sandbox = "host"', "allow_unsafe_host = true",
            "poll_interval_seconds = 1", "max_task_usd = 5.0",
            "daily_budget_usd = 50.0", f"model_timeout_seconds = {timeout}",
            "reflect_after = []", extra, ""]
    body += blocks
    for role, spec in roles.items():
        body.append(f"\n[roles.{role}]")
        for k, v in spec.items():
            body.append(f'{k} = "{v}"' if isinstance(v, str) else f"{k} = {v}")
    with io.open(os.path.join(root, "settings.toml"), "w",
                 encoding="utf-8") as f:
        f.write("\n".join(body) + "\n")


# ------------------------------------------------------------------- checks

def check_a_real_http_call_carries_everything(root):
    """One call, and every field the provider is entitled to receive."""
    srv = FakeProvider(require_key="sk-test-abc123")
    try:
        settings(root,
                 [provider_block("live", srv.base_url, key_env="FAKE_KEY",
                                 headers={"X-Title": "Expert Fleet"})],
                 {"practitioner": {"provider": "live", "model": "gpt-test"}},
                 extra="max_output_tokens = 4096")
        os.environ["FAKE_KEY"] = "sk-test-abc123"
        srv.reply(tool="finish_task", args={"summary": "hello"})
        a = loop.Agent(root)
        msg, usage, prov = a.call_model("practitioner",
                                        [{"role": "user", "content": "hi"}])
        req = srv.last
        assert prov == "live"
        assert req["path"].endswith("/chat/completions"), req["path"]
        assert req["payload"]["model"] == "gpt-test"
        assert req["payload"]["messages"][0]["content"] == "hi"
        assert req["payload"]["max_tokens"] == 4096, (
            "the configured output ceiling never reached the provider")
        names = {t["function"]["name"] for t in req["payload"]["tools"]}
        assert names == set(a.allowed_tools("practitioner")), (
            f"the tool schema sent to the provider is not the role's own "
            f"allowlist: sent {sorted(names)}, allowed "
            f"{sorted(a.allowed_tools('practitioner'))}")
        assert req["headers"]["authorization"] == "Bearer sk-test-abc123"
        assert req["headers"]["x-title"] == "Expert Fleet", (
            "extra_headers never reached the wire")
        assert req["headers"]["content-type"] == "application/json"
        assert msg["tool_calls"][0]["function"]["name"] == "finish_task"
        assert usage["total_tokens"] == 120, usage
        # and the DEFAULT (0) must omit it, not send max_tokens: 0, which
        # some providers read as "produce nothing"
        settings(root,
                 [provider_block("live", srv.base_url, key_env="FAKE_KEY")],
                 {"practitioner": {"provider": "live", "model": "gpt-test"}})
        srv.reply(text="ok")
        loop.Agent(root).call_model("practitioner",
                                    [{"role": "user", "content": "hi"}])
        assert "max_tokens" not in srv.last["payload"], (
            "max_output_tokens = 0 means 'the provider's default'; sending "
            "max_tokens: 0 tells some providers to produce nothing")
        print(f"[wire] one real HTTP call carried the model, the messages, "
              f"the configured 4096-token ceiling, exactly the {len(names)} "
              f"tools this role is allowed, the bearer key and the configured "
              f"extra header — and with the ceiling left at its default, "
              f"max_tokens is omitted rather than sent as 0")
    finally:
        srv.stop()
        os.environ.pop("FAKE_KEY", None)


def check_cost_comes_from_the_provider(root):
    """Spend must be computed from the usage the provider reported.

    A client that estimates tokens locally is a client whose budget breaker
    is wrong by exactly the amount the estimate is wrong.
    """
    srv = FakeProvider()
    try:
        # the per-million rates live on the PROVIDER block, which is where
        # a provider's price list belongs
        settings(root,
                 [provider_block("live", srv.base_url, key="sk-inline"),
                  "input_per_mtok = 3.0", "output_per_mtok = 15.0"],
                 {"practitioner": {"provider": "live", "model": "m"}})
        srv.reply(text="ok", usage={"prompt_tokens": 1_000_000,
                                    "completion_tokens": 1_000_000,
                                    "total_tokens": 2_000_000})
        a = loop.Agent(root)
        read = lambda: json.load(io.open(a._spend_path(), encoding="utf-8")
                                 )["usd"] if os.path.isfile(a._spend_path()) else 0.0
        before = read()
        a.call_model("practitioner", [{"role": "user", "content": "x"}])
        spent = read() - before
        assert abs(spent - 18.0) < 0.001, (
            f"1M in at $3 + 1M out at $15 should cost $18.00, recorded "
            f"{spent:.4f} — the breaker is only as good as this number")
        rows = modelgateway.calls(root)
        assert rows and rows[-1]["tokens_in"] == 1_000_000, rows[-1]
        assert rows[-1]["provider"] == "live", rows[-1]
        print(f"[cost] the provider reported 1M+1M tokens and the ledger "
              f"charged ${spent:.2f} at the configured rates — spend is read "
              f"from the response, never estimated by the client")
    finally:
        srv.stop()


def check_the_retry_ladder(root):
    """429 and 5xx are weather; 4xx is a verdict."""
    srv = FakeProvider()
    try:
        settings(root, [provider_block("live", srv.base_url, key="k")],
                 {"practitioner": {"provider": "live", "model": "m"}})
        a = loop.Agent(root)
        # patch the sleep so the ladder is exercised without the wall clock
        slept = []
        real_sleep = time.sleep
        time.sleep = lambda s: slept.append(s)
        try:
            srv.fail(429).fail(503).reply(text="finally")
            msg, _u, _p = a.call_model("practitioner",
                                       [{"role": "user", "content": "x"}])
            assert msg["content"] == "finally", msg
            assert len(srv.requests) == 3, srv.requests
            assert slept and all(s > 0 for s in slept), slept
            assert slept == sorted(slept), (
                f"the backoff must grow, not repeat: {slept}")
            # a 400 is the caller's mistake and must NOT be retried
            srv.requests.clear()
            slept.clear()
            srv.fail(400, times=6).reply(text="never reached")
            try:
                a.call_model("practitioner", [{"role": "user", "content": "x"}])
                raise AssertionError("a 400 must not be retried into success")
            except RuntimeError as e:
                assert "HTTP 400" in str(e), str(e)
            assert len(srv.requests) == 1, (
                f"a non-retryable status was retried {len(srv.requests)} "
                f"times — every one of those is a paid call")
        finally:
            time.sleep = real_sleep
        print(f"[retry] 429 then 503 then success in 3 calls with growing "
              f"backoff; a 400 stopped after exactly 1 call instead of "
              f"burning five")

        # --- Retry-After: when the provider says HOW LONG, believe it
        # The ladder slept `2 ** attempt * 2` regardless of what the response
        # said. Both directions of ignoring that header are wrong. Sleeping 2s
        # when the provider asked for 45 burns the remaining retries against a
        # window that has not reopened, so the task fails for a reason that
        # would have cleared by itself; sleeping 30s when it asked for 1 throws
        # away 29 seconds on every rate limit, all day, on a fleet that runs
        # all day.
        #
        # The fake provider could not emit the header at all until now, which
        # is exactly why this went untested: a harness that cannot express what
        # real providers send will certify a client that ignores them.
        slept2 = []
        real_sleep2 = time.sleep
        time.sleep = lambda s: slept2.append(s)
        try:
            srv.requests.clear()
            # the 400 case above queued six failures and one reply, and
            # consumed a single failure — so both queues still hold its
            # leftovers. A test that inherits another test's queue is its own
            # flaky test.
            srv.fail_next.clear()
            srv.script.clear()
            srv.fail(429, retry_after=45).reply(text="after the window")
            msg2, _u2, _p2 = a.call_model("practitioner",
                                          [{"role": "user", "content": "x"}])
        finally:
            time.sleep = real_sleep2
        assert msg2["content"] == "after the window", msg2
        assert slept2, "the ladder did not back off at all"
        waited = slept2[0]
        assert 45 <= waited <= 47, (
            f"the provider asked for 45s and the ladder slept {waited:.1f}s. "
            f"Anything far below it retries into a window that has not "
            f"reopened; anything far above it wastes the difference on every "
            f"rate limit.")
        assert waited > 45, (
            f"slept exactly {waited}s with no jitter — several experts rate "
            f"limited by one provider at the same instant would all return in "
            f"lockstep and rate-limit each other again")

        # a SHORT Retry-After must not be rounded up to the blind backoff
        slept3 = []
        time.sleep = lambda s: slept3.append(s)
        try:
            srv.fail(503, retry_after=1).reply(text="quick")
            a.call_model("practitioner", [{"role": "user", "content": "x"}])
        finally:
            time.sleep = real_sleep2
        assert slept3 and slept3[0] < 3, (
            f"the provider said 1s and the ladder slept {slept3[0]:.1f}s — the "
            f"blind backoff would have been 2s or more, and on a fleet that "
            f"rate-limits often that difference is the whole day")
        log = io.open(os.path.join(root, "logs", "agent.log"),
                      encoding="utf-8", errors="replace").read()
        assert '"provider_retry_after"' in log, (
            "honouring the header was not recorded, so nobody can tell "
            "whether it happened")
        print(f"[retry-after] a 429 asking for 45s slept {waited:.1f}s (the "
              f"blind backoff would have been 2s and retried into a closed "
              f"window), a 503 asking for 1s slept {slept3[0]:.1f}s instead "
              f"of 2s or more, and both carry jitter so simultaneous experts "
              f"do not return in lockstep")
    finally:
        srv.stop()


def check_retry_after_is_parsed_not_guessed(root):
    """The header itself, across every shape a real provider sends.

    The end-to-end check above proves the ladder HONOURS Retry-After, but it
    can only drive one header at a time through a live socket. The parser is
    where the sharp edges are: two legal formats (delta-seconds and an
    HTTP-date, RFC 9110 10.2.3), plus everything a provider sends that is
    neither. Each of these has a specific wrong answer that is worse than
    having no header at all, so each is pinned:

      * a value we cannot read must return None -> BLIND BACKOFF, the old
        behaviour. Reading "banana" as 0 would turn a rate limit into a hot
        retry loop against a provider that just asked us to stop.
      * "99999" must be CAPPED. A provider asking for a 27-hour wait is not
        asking us to wait; the fallback provider exists for that.
      * a negative or already-past value must clamp to 0, never a negative
        sleep and never a rewind.
      * nan and inf are floats and would pass a naive float() check straight
        into time.sleep(), which is either an error or an eternity.
    """
    import email.utils
    import datetime

    class Resp:
        """Just the attribute the real HTTPError carries."""
        def __init__(self, v):
            self.headers = {} if v is None else {"Retry-After": v}

    now = 1_700_000_000.0
    at = lambda off: email.utils.format_datetime(
        datetime.datetime.fromtimestamp(now + off, datetime.timezone.utc))

    CASES = [
        # (header, expected seconds or None, why this one matters)
        ("30",      30.0,  "the ordinary case: delta-seconds"),
        ("1",        1.0,  "a short window must stay short, not round up"),
        ("0",        0.0,  "retry immediately is a legal answer"),
        ("99999",  120.0,  "capped — an hour is the fallback provider's job"),
        ("30.5",    30.5,  "fractional: int() would have rejected it into "
                           "blind backoff"),
        ("1e2",    100.0,  "exponent notation is still a number"),
        ("-5",       0.0,  "clamped; a negative sleep is an exception"),
        ("nan",     None,  "a float that is not a duration"),
        ("inf",     None,  "ditto, and time.sleep(inf) never returns"),
        ("-inf",    None,  "ditto"),
        ("banana",  None,  "unreadable -> blind backoff, never 0"),
        ("",        None,  "empty is absent"),
        (None,      None,  "absent is absent"),
        (at(45),    45.0,  "the HTTP-date form, which many providers send"),
        (at(-600),   0.0,  "a date already past means now, not a rewind"),
    ]
    bad = []
    for raw, want, why in CASES:
        got = loop.retry_after_seconds(Resp(raw), now=now)
        ok = (got is None and want is None) or (
            got is not None and want is not None and abs(got - want) < 0.01)
        if not ok:
            bad.append(f"{raw!r} ({why}): expected {want}, got {got}")
    assert not bad, "Retry-After parsed wrong:\n  " + "\n  ".join(bad)

    # and the cap is a constant a reader can find, not a magic number
    assert loop.MAX_RETRY_AFTER == 120, loop.MAX_RETRY_AFTER
    assert (loop.retry_after_seconds(Resp("100000"), now=now)
            == loop.MAX_RETRY_AFTER)

    # a header-less exception must not raise — the ladder calls this on EVERY
    # retryable status, including the many that carry nothing
    class Bare:
        pass
    assert loop.retry_after_seconds(Bare()) is None, (
        "an exception with no headers attribute must read as 'no header', "
        "not blow up inside the retry ladder")
    print(f"[retry-after] the header parser pinned across {len(CASES)} shapes: "
          f"both legal formats, the {loop.MAX_RETRY_AFTER}s cap, negatives and "
          f"past dates clamped to 0, and every unreadable value falling back "
          f"to blind backoff rather than to 0")


def check_unreachable_fails_over_instantly(root):
    """A refused connection is a verdict, not weather.

    Five backoffs cost a minute per step. On a 24/7 fleet with one
    misconfigured base_url, every task pays it.
    """
    srv = FakeProvider()
    try:
        # a port nothing is listening on, then a working fallback
        settings(root,
                 [provider_block("dead", "http://127.0.0.1:1/v1", key="k"),
                  provider_block("live", srv.base_url, key="k")],
                 {"practitioner": {"provider": "dead", "model": "m",
                                   "fallback_provider": "live",
                                   "fallback_model": "m"}})
        srv.always(text="the fallback answered")
        a = loop.Agent(root)
        t0 = time.time()
        msg, _u, prov = a.call_model("practitioner",
                                     [{"role": "user", "content": "x"}])
        took = time.time() - t0
        assert prov == "live" and msg["content"] == "the fallback answered"
        assert took < 10, (
            f"failover took {took:.1f}s — a refused connection should not "
            f"walk the backoff ladder before trying the fallback")
        log = io.open(os.path.join(root, "logs", "agent.log"),
                      encoding="utf-8", errors="replace").read()
        assert "provider_unreachable" in log, (
            "an unreachable provider must be logged as such, or the operator "
            "cannot tell a broken base_url from a slow one")
        print(f"[unreachable] a refused connection failed over to the "
              f"fallback in {took:.2f}s and was logged as unreachable, "
              f"instead of costing five backoffs per step forever")
    finally:
        srv.stop()


def check_all_four_key_sources_reach_the_wire(root):
    """`credentials.py` resolves four sources. The HTTP client must honour
    every one of them, or a perfectly configured key silently sends nothing."""
    keyfile = os.path.join(root, "keys", "p.key")
    os.makedirs(os.path.dirname(keyfile), exist_ok=True)
    with io.open(keyfile, "w", encoding="utf-8") as f:
        f.write("sk-from-a-file\n")
    cases = [
        ("env", provider_block("live", "", key_env="ONLY_IN_ENV"),
         "sk-from-the-env", {"ONLY_IN_ENV": "sk-from-the-env"}),
        ("inline", provider_block("live", "", key="sk-inline-value"),
         "sk-inline-value", {}),
        ("file", f'[providers.live]\nbase_url = ""\n'
                 f'api_key_file = "{keyfile.replace(os.sep, "/")}"',
         "sk-from-a-file", {}),
    ]
    for label, block, expect, env in cases:
        srv = FakeProvider(require_key=expect)
        try:
            for k, v in env.items():
                os.environ[k] = v
            settings(root, [block.replace('base_url = ""',
                                          f'base_url = "{srv.base_url}"')],
                     {"practitioner": {"provider": "live", "model": "m"}})
            srv.always(text="authorised")
            a = loop.Agent(root)
            msg, _u, _p = a.call_model("practitioner",
                                       [{"role": "user", "content": "x"}])
            assert msg["content"] == "authorised", (
                f"the {label} key never reached the Authorization header — "
                f"the server rejected it")
            assert srv.last["headers"]["authorization"] == f"Bearer {expect}"
        finally:
            srv.stop()
            for k in env:
                os.environ.pop(k, None)
    print(f"[keys] all {len(cases)} configured key sources (env, inline, "
          f"file) reached the Authorization header and were accepted by a "
          f"server that checks them")


def check_a_malformed_response_is_not_a_crash(root):
    """A 200 carrying something that is not a chat completion.

    This is ordinary provider weather — a proxy's HTML error page, a
    truncated stream, a gateway answering 200 with {"error": ...}. It used to
    raise JSONDecodeError straight out of the retry ladder, which meant the
    task died AND the fallback provider was never tried: the one situation
    the fallback exists for. Found by tightening an assertion in this file
    that could not fail.
    """
    srv = FakeProvider()
    fallback = FakeProvider()
    try:
        settings(root,
                 [provider_block("live", srv.base_url, key="k"),
                  provider_block("spare", fallback.base_url, key="k")],
                 {"practitioner": {"provider": "live", "model": "m",
                                   "fallback_provider": "spare",
                                   "fallback_model": "m"}})
        fallback.always(text="the fallback answered")
        a = loop.Agent(root)
        real_sleep, slept = time.sleep, []
        time.sleep = lambda s: slept.append(s)
        try:
            for kind in ("garbage", "empty_choices"):
                srv.requests.clear()
                fallback.requests.clear()
                srv.fail_next.clear()
                for _ in range(5):
                    srv.misbehave(kind)
                msg, _u, prov = a.call_model(
                    "practitioner", [{"role": "user", "content": "x"}])
                assert prov == "spare" and msg["content"] == "the fallback answered", (
                    f"a {kind} body did not fail over to the configured "
                    f"fallback: got {prov}/{msg}")
                assert len(srv.requests) == 5, (
                    f"a {kind} body was retried {len(srv.requests)} times, "
                    f"not the full ladder — a garbled response is usually "
                    f"transient")
                assert len(fallback.requests) == 1, fallback.requests
        finally:
            time.sleep = real_sleep
        # and the operator can tell WHICH provider misbehaved
        log = io.open(os.path.join(root, "logs", "agent.log"),
                      encoding="utf-8", errors="replace").read()
        assert '"provider_malformed"' in log and '"provider": "live"' in log, (
            "a malformed body must be logged against the provider that sent "
            "it, or an operator with four providers cannot tell which is "
            "broken")
        # …and when there is NO fallback, the error still names the provider
        settings(root, [provider_block("live", srv.base_url, key="k")],
                 {"practitioner": {"provider": "live", "model": "m"}})
        a2 = loop.Agent(root)
        time.sleep = lambda s: None
        try:
            srv.fail_next.clear()
            for _ in range(6):
                srv.misbehave("garbage")
            try:
                a2.call_model("practitioner",
                              [{"role": "user", "content": "x"}])
                raise AssertionError("a garbage body was accepted as a reply")
            except RuntimeError as e:
                assert "live" in str(e), (
                    f"the final error does not name the provider: {e}")
        finally:
            time.sleep = real_sleep
        print("[malformed] a non-JSON body and a body with no choices are "
              "each retried through the full ladder, then failed over to the "
              "configured fallback, and logged against the provider that "
              "sent them — they used to raise straight out of the loop, "
              "killing the task and never trying the fallback")
    finally:
        srv.stop()
        fallback.stop()


def check_a_timeout_is_bounded(root):
    """`model_timeout_seconds` must actually bound the wait."""
    srv = FakeProvider()
    try:
        settings(root, [provider_block("live", srv.base_url, key="k")],
                 {"practitioner": {"provider": "live", "model": "m"}},
                 timeout=2)
        srv.misbehave("hang", 20)
        srv.always(text="after the hang")
        a = loop.Agent(root)
        assert a.model_timeout == 2, a.model_timeout
        real_sleep, slept = time.sleep, []
        time.sleep = lambda s: slept.append(s)
        t0 = time.time()
        try:
            msg, _u, _p = a.call_model("practitioner",
                                       [{"role": "user", "content": "x"}])
        finally:
            time.sleep = real_sleep
        took = time.time() - t0
        assert msg["content"] == "after the hang", msg
        assert took < 15, (
            f"a 2-second timeout let a 20-second hang run for {took:.1f}s")
        assert len(srv.requests) == 2, (
            "the timed-out call should have been retried once")
        print(f"[timeout] a provider that hung for 20s was cut off by the "
              f"2s ceiling and retried, finishing in {took:.1f}s — the "
              f"timeout is a real bound, not a suggestion")
    finally:
        srv.stop()


def check_the_whole_loop_over_real_http(root):
    """The end-to-end proof: a task driven to completion, gate and all,
    with every model call going over a socket."""
    srv = FakeProvider()
    try:
        settings(root, [provider_block("live", srv.base_url, key="k")],
                 {"practitioner": {"provider": "live", "model": "m"},
                  "examiner": {"provider": "live", "model": "m"}})
        srv.reply(tool="write_file",
                  args={"path": "out/live.md", "content": "written over HTTP"})
        srv.reply(tool="finish_task", args={"summary": "wrote it"})
        srv.always(tool="finish_task", args={"summary": "ok"})
        a = loop.Agent(root)
        tid = a.add_task("practitioner", "write a file over real HTTP",
                         done_check='python -c "import os,sys;sys.exit('
                                    "0 if os.path.exists('out/live.md') "
                                    'else 1)"')
        run_drain(root, timeout=180)
        done = [t for t in read_state(root)["tasks"]
                if t["id"] == tid and t["status"] == "done"]
        assert done, (
            "a task could not be completed over the live HTTP path — "
            + json.dumps([{k: t.get(k) for k in ("status", "error")}
                          for t in read_state(root)["tasks"]])[:400])
        assert os.path.isfile(os.path.join(root, "out", "live.md"))
        # Every call is metered against the provider that ACTUALLY served it.
        # Asserting over the whole ledger was wrong: earlier checks in this
        # file deliberately fail over to a spare provider, and their rows
        # live in the same file. The claim that matters is per task.
        rows = [r for r in modelgateway.calls(root) if r.get("task") == tid]
        assert rows, "no call for this task reached the model gateway"
        assert all(r["provider"] == "live" for r in rows), (
            f"this task's calls were attributed to "
            f"{sorted({r['provider'] for r in rows})}, but only 'live' "
            f"served it")
        assert len(srv.requests) >= 2, srv.requests
        print(f"[end-to-end] a gated task was completed with "
              f"{len(srv.requests)} model calls over a real socket, the "
              f"artefact exists, the gate passed, and all {len(rows)} of "
              f"THIS task's calls are metered against the provider that "
              f"actually served them")
    finally:
        srv.stop()


def check_inline_tools_for_providers_without_function_calling(root):
    """`native_tools = false` — the tool call arrives in the content, and no
    tool schema is sent at all."""
    srv = FakeProvider()
    try:
        settings(root, [provider_block("live", srv.base_url, key="k",
                                       native_tools=False)],
                 {"practitioner": {"provider": "live", "model": "m"}})
        srv.always(text=json.dumps({"tool": "finish_task",
                                    "args": {"summary": "inline"}}))
        a = loop.Agent(root)
        msg, _u, _p = a.call_model("practitioner",
                                   [{"role": "user", "content": "x"}])
        assert "tools" not in srv.last["payload"], (
            "a provider declared as having no function calling was still "
            "sent a tool schema — many of them 400 on it")
        assert "finish_task" in (msg.get("content") or ""), msg
        print("[inline] a provider with native_tools = false received NO tool "
              "schema and answered with inline JSON, which the loop parses")
    finally:
        srv.stop()


def main():
    home = make_sandbox("live-provider",
                        providers={"unused": {"script": "s.json"}},
                        roles={"practitioner": "unused"},
                        scripts={"s.json": []})
    check_a_real_http_call_carries_everything(home)
    check_cost_comes_from_the_provider(home)
    check_the_retry_ladder(home)
    check_retry_after_is_parsed_not_guessed(home)
    check_unreachable_fails_over_instantly(home)
    check_all_four_key_sources_reach_the_wire(home)
    check_a_malformed_response_is_not_a_crash(home)
    check_a_timeout_is_bounded(home)
    check_inline_tools_for_providers_without_function_calling(home)
    check_the_whole_loop_over_real_http(home)
    print("PASS test_live_provider")


if __name__ == "__main__":
    main()
