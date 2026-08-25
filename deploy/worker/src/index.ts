/**
 * EXPERT FLEET ON CLOUDFLARE — the Worker half.
 *
 * CLOUDFLARE.md §6 items 4 and 5. The Python platform never runs on Workers
 * and never should: the agent loop is a long-lived process that shells out,
 * holds a mutex, and writes state after every step, and none of that fits a
 * request-scoped isolate with no filesystem. §3.1 works through why. What
 * runs on Workers is this: a thin control plane in front of a Container that
 * runs the real thing.
 *
 * It does exactly two jobs.
 *
 * 1. IT WAKES THE FLEET (item 4).
 *
 *    A container sleeps after `sleepAfter` and its disk is ephemeral — "the
 *    next time it is started, it will have a fresh disk as defined by its
 *    container image" (Cloudflare's own words, containers/platform-details).
 *    That is why deploy/entrypoint.sh restores from R2 at boot and snapshots
 *    back before it sleeps. But something has to START it, or a sleeping
 *    fleet stays asleep forever and the queue never drains.
 *
 *    A Durable Object alarm is the cheapest thing that can: it costs nothing
 *    while it waits, fires on a schedule, and has "guaranteed at-least-once
 *    execution" with automatic retries. So the alarm pokes the container in
 *    FLEET_MODE=drain, the container empties its queue, snapshots to R2 and
 *    sleeps again. You pay for the minutes it works, not for the hours it
 *    waits.
 *
 *    AT-LEAST-ONCE IS THE IMPORTANT WORD. The alarm can fire twice for one
 *    scheduled time. Draining twice is harmless here — the second drain finds
 *    an empty queue — but the alarm is rescheduled FIRST, before any work,
 *    so a drain that throws cannot leave the fleet with no future alarm and
 *    silently stop the whole deployment.
 *
 * 2. IT LENDS THE FLEET A SANDBOX (item 5).
 *
 *    sandbox.py has four backends; `cloudflare` is the fifth. Cloudflare's
 *    Sandbox SDK is TypeScript called from a Worker, so a Python client
 *    cannot call it directly — it needs a small REST surface, which is the
 *    `/exec` route below and is deliberately the same request shape the
 *    e2b/daytona backends already speak, so sandbox.py needed no new client.
 *
 *    /exec RUNS COMMANDS, so it is the most dangerous route in this repo. It
 *    requires a bearer token compared in constant time, it is the ONLY route
 *    that requires one, and the token is a dedicated secret rather than your
 *    Cloudflare API token — see FLEET_EXEC_TOKEN below.
 *
 * Deploy:  npx wrangler deploy      (see README.md — do that first)
 */

import { Container, getContainer } from "@cloudflare/containers";
import { getSandbox, Sandbox } from "@cloudflare/sandbox";

export { Sandbox } from "@cloudflare/sandbox";

export interface Env {
  FLEET: DurableObjectNamespace<FleetContainer>;
  // Parameterised deliberately. Declaring this as a bare
  // `DurableObjectNamespace` compiles to `DurableObjectNamespace<undefined>`,
  // and `getSandbox` then rejects it — the stub would have none of the RPC
  // methods the SDK exposes. Caught by `tsc --noEmit`, which is the only
  // reason this file is worth more than a plausible-looking sketch.
  Sandbox: DurableObjectNamespace<Sandbox>;
  /** Shared secret for /exec. NOT your Cloudflare API token: that token can
   *  create Workers, read R2 and spend money account-wide, and sending it
   *  here would mean holding full account authority in order to run `ls`.
   *  Generate a random one and set it in BOTH places:
   *      npx wrangler secret put FLEET_EXEC_TOKEN
   *      CLOUDFLARE_SANDBOX_TOKEN=<same value>   in the fleet's agent.env
   *  If it is unset, /exec refuses every request rather than running them
   *  unauthenticated — fail closed, always. */
  FLEET_EXEC_TOKEN?: string;
  /** Minutes between wake-ups. Default 60. */
  FLEET_DRAIN_MINUTES?: string;
}

const DEFAULT_DRAIN_MINUTES = 60;
const MIN_DRAIN_MINUTES = 5;

/** Constant-time comparison.
 *
 *  `a === b` on a secret leaks its length and its matching prefix through
 *  timing. That is a real attack against a token this powerful, and the fix
 *  is four lines, so there is no reason to accept the risk. */
function secretEquals(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export class FleetContainer extends Container<Env> {
  /** The control panel's port, as the Dockerfile EXPOSEs it. */
  defaultPort = 7777;

  /** Generously long on purpose. Every sleep costs a full restore-from-R2 on
   *  the next boot (tens of seconds and an R2 GET), so a container that naps
   *  between two tasks arriving a minute apart is slower AND more expensive
   *  than one that stays up. CLOUDFLARE.md §5.1 has the arithmetic. */
  sleepAfter = "20m";

  envVars = {
    // `serve` runs the panel; the alarm overrides this per-request for a
    // drain. See deploy/entrypoint.sh.
    FLEET_MODE: "serve",
    PYTHONUNBUFFERED: "1",
    PYTHONUTF8: "1",
  };

  override onStart() {
    console.log(JSON.stringify({
      event: "container_start",
      note: "entrypoint.sh is restoring from R2 before it serves",
    }));
  }

  override onStop() {
    // The container has already snapshotted by now: entrypoint.sh traps
    // SIGTERM and pushes to R2 before exiting. If that trap ever stops
    // working, everything since the last interval snapshot is gone — which
    // is why deploy/README.md documents the data-loss window explicitly
    // instead of implying there is none.
    console.log(JSON.stringify({
      event: "container_stop",
      note: "entrypoint.sh should have snapshotted to R2 on SIGTERM",
    }));
  }

  override onError(error: unknown) {
    console.error(JSON.stringify({
      event: "container_error",
      error: String(error),
    }));
  }

  /** Wake up, drain the queue, go back to sleep. */
  override async alarm() {
    // RESCHEDULE BEFORE WORKING, not after.
    //
    // If the drain throws and the reschedule sits after it, the alarm is
    // never set again and the fleet stops forever — a total outage caused by
    // one bad task, discovered days later by someone noticing the queue is
    // long. Rescheduling first means the worst a failed drain costs is one
    // missed cycle.
    const minutes = Math.max(
      MIN_DRAIN_MINUTES,
      Number(this.env.FLEET_DRAIN_MINUTES ?? DEFAULT_DRAIN_MINUTES) ||
        DEFAULT_DRAIN_MINUTES,
    );
    await this.ctx.storage.setAlarm(Date.now() + minutes * 60_000);

    try {
      // The container's own HTTP surface. `/drain` is served by the panel
      // inside the container; the entrypoint's FLEET_MODE=drain path is for
      // a one-shot container, whereas this one is already serving.
      const res = await this.containerFetch(
        new Request("http://fleet/drain", { method: "POST" }),
      );
      console.log(JSON.stringify({
        event: "alarm_drain",
        status: res.status,
        next_minutes: minutes,
      }));
    } catch (error) {
      // Swallowed DELIBERATELY. An uncaught throw here makes the runtime
      // retry the alarm with exponential backoff up to six times, and a
      // container that is simply busy would be hammered by retries that
      // cannot help. The next scheduled alarm is already set.
      console.error(JSON.stringify({
        event: "alarm_drain_failed",
        error: String(error),
        next_minutes: minutes,
        note: "next alarm was already scheduled before this ran",
      }));
    }
  }

  /** Arm the schedule if nothing has armed it yet. Idempotent. */
  async ensureAlarm(): Promise<number> {
    const existing = await this.ctx.storage.getAlarm();
    if (existing !== null) return existing;
    const minutes = Math.max(
      MIN_DRAIN_MINUTES,
      Number(this.env.FLEET_DRAIN_MINUTES ?? DEFAULT_DRAIN_MINUTES) ||
        DEFAULT_DRAIN_MINUTES,
    );
    const at = Date.now() + minutes * 60_000;
    await this.ctx.storage.setAlarm(at);
    return at;
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // ---------------------------------------------------------- /exec
    // The sandbox backend for sandbox.py. Same request shape as the
    // e2b/daytona backends so the Python client needed no new code.
    if (path === "/exec") {
      if (request.method !== "POST") {
        return json({ error: "POST only" }, 405);
      }
      const expected = env.FLEET_EXEC_TOKEN;
      if (!expected) {
        // FAIL CLOSED. An unset secret must never mean "no authentication
        // required" — that is how a route that runs commands ends up open
        // to the internet because a deploy step was skipped.
        return json({
          error:
            "FLEET_EXEC_TOKEN is not set on this Worker, so /exec refuses " +
            "every request. Set it with `npx wrangler secret put " +
            "FLEET_EXEC_TOKEN` and put the same value in the fleet's " +
            "agent.env as CLOUDFLARE_SANDBOX_TOKEN.",
        }, 503);
      }
      const auth = request.headers.get("authorization") ?? "";
      const bearer = auth.startsWith("Bearer ") ? auth.slice(7) : "";
      if (!bearer || !secretEquals(bearer, expected)) {
        return json({ error: "unauthorized" }, 401);
      }

      let body: { cmd?: string; cwd?: string; envs?: Record<string, string>;
                  timeoutMs?: number };
      try {
        body = await request.json();
      } catch {
        return json({ error: "body must be JSON" }, 400);
      }
      const cmd = (body.cmd ?? "").trim();
      if (!cmd) return json({ error: "cmd is required" }, 400);

      try {
        // One sandbox per caller-supplied session would let a caller collide
        // with another's; a fixed name keeps this simple and the sandbox is
        // torn down by its own idle timeout.
        const sandbox = getSandbox(env.Sandbox, "fleet-exec");
        const result = await sandbox.exec(cmd, {
          cwd: body.cwd ?? "/workspace",
          env: body.envs ?? {},
        });
        // Exactly the keys sandbox.py._hosted reads.
        return json({
          exitCode: result.exitCode ?? 0,
          stdout: result.stdout ?? "",
          stderr: result.stderr ?? "",
        });
      } catch (error) {
        return json({
          exitCode: 127,
          stdout: "",
          stderr: `cloudflare sandbox failed: ${String(error)}`,
        });
      }
    }

    // ---------------------------------------------------------- /wake
    // Arm the drain schedule, and start the container if it is asleep.
    // Idempotent, so it is safe to curl after every deploy.
    if (path === "/wake") {
      const fleet = getContainer(env.FLEET, "default");
      const at = await fleet.ensureAlarm();
      return json({
        armed: true,
        next_alarm_utc: new Date(at).toISOString(),
        note: "the alarm reschedules itself before each drain",
      });
    }

    if (path === "/health") {
      return json({ ok: true, service: "expert-fleet-worker" });
    }

    // ------------------------------------------------- everything else
    // Straight through to the control panel inside the container. The panel
    // has its own authentication and CSRF protection; this Worker adds no
    // authorisation of its own here and must not be treated as if it did.
    const fleet = getContainer(env.FLEET, "default");
    return await fleet.fetch(request);
  },
};
