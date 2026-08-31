"""LIFT-001A public TRAIN workload corpus, separate from tiny CI acceptance tasks.

Original synthetic fixtures, no imported benchmark data. Offline workflow
components are labeled; they do not establish browser/live research capability.
Final expected outputs live in the trusted runner, never in the actor workspace.
"""
import copy
import hashlib
import json

VERSION = "lift-001a-train-v1"


def _task(family, index, instruction, inputs, expected, scope="offline-workflow"):
    return {"id": f"{family}-{index}", "family": family, "split": "train",
            "task": instruction + " Read eval/in/input.json; write the requested JSON object to eval/out/result.json. Preserve all input files. Do not invent missing evidence.",
            "fixture": {"eval/in/input.json": json.dumps(inputs, indent=2)},
            "expected": expected, "scope": scope,
            # The loop may use this public structural gate; correctness is
            # independently evaluated after it exits, without revealing gold.
            "check": "import json; d=json.load(open('eval/out/result.json')); assert isinstance(d,dict)"}


def tasks(split="train"):
    if split != "train":
        raise ValueError("this public development corpus has no secret holdout")
    out = []
    for n in (1, 2):
        suffix = str(n)
        out.append(_task("terminal-system", n,
            "Diagnose service incidents: ignore successful health checks, group non-2xx requests by service, distinguish timeout from application errors, and identify the service with the most user-visible failures. Return failures_by_service, timeout_request_ids, primary_service.",
            {"logs": [{"id": "a", "service": "api", "status": 503, "cause": "timeout"},
                      {"id": "b", "service": "api", "status": 500, "cause": "application"},
                      {"id": "c", "service": "web", "status": 200, "cause": "ok"},
                      {"id": "d", "service": "worker" + suffix, "status": 504, "cause": "timeout"},
                      {"id": "e", "service": "api", "status": 200, "cause": "health"}]},
            {"failures_by_service": {"api": 2, "worker" + suffix: 1}, "timeout_request_ids": ["a", "d"], "primary_service": "api"}))
        out.append(_task("software-engineering", n,
            "Evaluate the proposed cache patch against the supplied behavioral contract. Identify failing cases by ID and give the smallest corrected expression for expires_at (Python, using now and ttl). Zero TTL means immediately expired; None means never expires. Return failing_cases and corrected_expression.",
            {"patch": "expires_at = now + ttl if ttl else None", "cases": [
                {"id": "zero" + suffix, "now": 100*n, "ttl": 0, "expected": 100*n},
                {"id": "none" + suffix, "now": 100*n, "ttl": None, "expected": None},
                {"id": "positive" + suffix, "now": 100*n, "ttl": 5, "expected": 100*n+5}]},
            {"failing_cases": ["zero" + suffix], "corrected_expression": "None if ttl is None else now + ttl"}))
        out.append(_task("browser-web", n,
            "Use the offline storefront state to prepare a checkout without placing an order. Choose the lowest total eligible in-stock item with size M, deliverable to CA; include shipping once. Disabled controls cannot be used. Return product_id, total_cents, next_action (review_checkout).",
            {"country": "CA", "size": "M", "products": [
                {"id": "cheap", "price": 100, "shipping": 0, "sizes": ["S"], "stock": 8, "countries": ["CA"]},
                {"id": "sold", "price": 500, "shipping": 0, "sizes": ["M"], "stock": 0, "countries": ["CA"]},
                {"id": "eligible"+suffix, "price": 1200*n, "shipping": 300, "sizes": ["M"], "stock": 2, "countries": ["CA"]},
                {"id": "foreign", "price": 200, "shipping": 0, "sizes": ["M"], "stock": 2, "countries": ["US"]}]},
            {"product_id": "eligible"+suffix, "total_cents": 1200*n+300, "next_action": "review_checkout"}, "offline-browser-state-component"))
        out.append(_task("research-evidence", n,
            "Synthesize the current evidence for service availability. Current first-party notice outranks older documentation and third-party rumor. Return current_regions (sorted), supporting_source_ids, contradicted_source_ids, and unresolved_claims; do not turn missing evidence into a claim.",
            {"sources": [{"id": "old", "date": "2025-01-01", "authority": "vendor", "regions": ["US"]},
                         {"id": "current"+suffix, "date": "2026-08-01", "authority": "vendor", "regions": ["US", "CA"]},
                         {"id": "rumor", "date": "2026-08-02", "authority": "third-party", "regions": ["US", "EU"]}],
             "question_without_evidence": "uptime SLA"},
            {"current_regions": ["CA", "US"], "supporting_source_ids": ["current"+suffix],
             "contradicted_source_ids": ["rumor"], "unresolved_claims": ["uptime SLA"]}, "offline-evidence-synthesis"))
        out.append(_task("long-term-memory", n,
            "Resolve the event history as of day 40. Latest valid update wins; revoked facts must not be recalled. Return current_city, active_contact, and forgotten_keys. Preserve no revoked contact value in the output.",
            {"events": [{"day": 1, "key": "city", "value": "Ottawa"}, {"day": 20, "key": "city", "value": "Toronto" if n == 1 else "Montreal"},
                        {"day": 3, "key": "contact", "value": "synthetic@example.invalid"},
                        {"day": 30, "key": "contact", "action": "revoke"},
                        {"day": 50, "key": "city", "value": "future"}]},
            {"current_city": "Toronto" if n == 1 else "Montreal", "active_contact": None, "forgotten_keys": ["contact"]}, "offline-temporal-memory-component"))
        out.append(_task("business-workflow", n,
            "Reconcile settled payments against invoices. Deduplicate by event ID, subtract refunds, exclude pending payments, and return net_paid_cents, outstanding_cents, duplicate_event_ids.",
            {"invoice_cents": 5000*n, "events": [
                {"id": "p1", "kind": "payment", "status": "settled", "cents": 4000*n},
                {"id": "p1", "kind": "payment", "status": "settled", "cents": 4000*n},
                {"id": "r1", "kind": "refund", "status": "settled", "cents": 500*n},
                {"id": "p2", "kind": "payment", "status": "pending", "cents": 2000*n}]},
            {"net_paid_cents": 3500*n, "outstanding_cents": 1500*n, "duplicate_event_ids": ["p1"]}))
        out.append(_task("failure-recovery", n,
            "Plan recovery from the effects ledger. Never replay known-completed effects or an ambiguous effect whose remote outcome is unknown. A definitely not-sent idempotent effect may retry. Return retry_ids, reconcile_ids, skip_ids, sorted.",
            {"effects": [{"id": "done"+suffix, "state": "completed"},
                         {"id": "uncertain"+suffix, "state": "started", "remote_outcome": "unknown"},
                         {"id": "safe"+suffix, "state": "not_sent", "idempotent": True}]},
            {"retry_ids": ["safe"+suffix], "reconcile_ids": ["uncertain"+suffix], "skip_ids": ["done"+suffix]}))
        out.append(_task("partial-information-planning", n,
            "Plan only currently authorized observable steps. Build depends on source; test depends on build; deploy depends on tests and owner approval. Approval is unknown. Return executable_order, blocked_step, missing_observations. Do not assume unknown approval.",
            {"steps": {"source"+suffix: [], "build"+suffix: ["source"+suffix], "test"+suffix: ["build"+suffix],
                       "deploy"+suffix: ["test"+suffix, "owner_approval"]}, "observations": {"owner_approval": None}},
            {"executable_order": ["source"+suffix, "build"+suffix, "test"+suffix], "blocked_step": "deploy"+suffix,
             "missing_observations": ["owner_approval"]}))
        out.append(_task("tool-acquisition-use", n,
            "Select a tool installation candidate without installing anything. Require an exact version, passing sealed probe and matching observed/expected digest. Return selected_id or null and rejected IDs sorted. Mutable latest and unverified probes are ineligible.",
            {"candidates": [{"id": "floating", "version": "latest", "probe": True, "expected_digest": "abc", "observed_digest": "abc"},
                            {"id": "mismatch", "version": "1.2.3", "probe": True, "expected_digest": "abc", "observed_digest": "def"},
                            {"id": "verified"+suffix, "version": "1.2."+suffix, "probe": True, "expected_digest": "abc", "observed_digest": "abc"},
                            {"id": "unproven", "version": "1.0.0", "probe": None, "expected_digest": "abc", "observed_digest": "abc"}]},
            {"selected_id": "verified"+suffix, "rejected_ids": ["floating", "mismatch", "unproven"]}, "offline-acquisition-decision-component"))
        out.append(_task("cross-tool-workflow", n,
            "Join exported CRM contacts to orders, exclude cancelled orders, aggregate cents per contact, and prepare (do not send) reminders for unpaid balances. Unknown contacts must be quarantined. Return reminders sorted by contact_id, quarantined_order_ids, and send_performed=false.",
            {"contacts": [{"id": "c1", "email": "a@example.invalid"}, {"id": "c2", "email": "b@example.invalid"}],
             "orders": [{"id": "o1", "contact_id": "c1", "status": "open", "total": 1000*n, "paid": 250*n},
                        {"id": "o2", "contact_id": "c1", "status": "open", "total": 500*n, "paid": 0},
                        {"id": "o3", "contact_id": "c2", "status": "cancelled", "total": 300, "paid": 0},
                        {"id": "orphan", "contact_id": "missing", "status": "open", "total": 200, "paid": 0}]},
            {"reminders": [{"contact_id": "c1", "balance_cents": 1250*n}], "quarantined_order_ids": ["orphan"], "send_performed": False}))
    return copy.deepcopy(out)


def corpus_hash():
    return hashlib.sha256(json.dumps(tasks(), sort_keys=True).encode()).hexdigest()


def grade(root, task):
    """Independent, non-executing final grader. Actor-controlled code is never imported."""
    from pathlib import Path
    root = Path(root)
    try:
        for rel, value in task["fixture"].items():
            if (root / rel).read_text(encoding="utf-8") != value:
                return False
        output = root / "eval/out/result.json"
        if output.is_symlink() or output.stat().st_size > 1_000_000:
            return False
        return json.loads(output.read_text(encoding="utf-8")) == task["expected"]
    except (OSError, ValueError):
        return False
