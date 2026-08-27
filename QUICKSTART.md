# Quickstart — from zero to your first VERIFIED goal, today

Five steps, ~15 minutes, one API key (or none — see step 2's local lane).
Every command runs from this `agent/` directory. Python 3.11+.

## 1. Bootstrap

```bash
python bootstrap.py
```

Idempotent: creates `agent.env` from the example, tells you exactly what is
missing (numbered, with the fix), creates your first expert if none exists,
and starts the control panel.

## 2. Wire ONE model key — any provider works

The platform is provider-universal: every provider below speaks the same
OpenAI-compatible contract, so a key is two lines of config away. Pick one
lane:

| Lane | Get a key at | Put in `agent.env` | Cost |
|---|---|---|---|
| **OpenRouter** (recommended first) | openrouter.ai | `OPENROUTER_API_KEY=` | one key reaches every major model; `:free` model ids run at $0 |
| DeepSeek (official) | platform.deepseek.com | `DEEPSEEK_API_KEY=` | best value paid lane |
| Cloudflare Workers AI | dash.cloudflare.com | `CLOUDFLARE_API_TOKEN=` | 10,000 free Neurons/day standing |
| Google Gemini (official) | aistudio.google.com | `GEMINI_API_KEY=` | standing free flash quota |
| Anthropic / OpenAI / xAI (official) | their consoles | `ANTHROPIC_API_KEY=` / `OPENAI_API_KEY=` / `XAI_API_KEY=` | paid |
| **Local — no key at all** | ollama.com (pull a tools-capable model) | `OLLAMA_API_KEY=local` | $0, fully offline |

Write the key without ever showing it on screen:

```bash
python bootstrap.py --key OPENROUTER_API_KEY=paste-your-key-here
```

Then activate the provider: in `settings.toml`, the openrouter/deepseek
blocks are already live; for others, uncomment their `[providers.*]` block
(each carries its verified base_url and honest free-tier note) and point the
roles at it. **Set a spend cap at the provider's dashboard first.**

## 3. Prove the wiring

```bash
python loop.py check
```

One real request per role. Every role must say OK. If something is wrong it
names the exact variable or setting to fix — `python doctor.py` for the
full health picture.

## 4. Create an expert and give it a goal WITH graders

```bash
python fleet.py create builder --identity "ships small verified deliverables"

python goal.py pursue "produce out/report.md summarizing the three files in inbox/" \
    --expert builder --drive \
    --accept "report exists::python -c \"import os,sys;sys.exit(0 if os.path.exists('experts/builder/out/report.md') else 1)\"" \
    --max-usd 1.00
```

The `--accept` flag is the whole philosophy in one argument: a command that
must exit 0, **frozen and sealed before any planning happens**, run by the
harness at the end. The agent cannot edit it, cannot grade itself against
it, and cannot talk past it. Give every goal at least one; a goal without
graders can end "achieved" (a judged opinion) but never **VERIFIED**.

What happens next, automatically: machine path first (if a proven runbook
or existing artifact already satisfies the graders — zero model calls) →
plan → gated milestones → independent judge on another model family →
judge overruled if the graders disagree → repair from recorded errors →
repeat within budget → the frozen graders decide.

## 5. Watch it, steer it, verify it

```bash
python ui.py          # the control panel (auto-opened by bootstrap)
```

Open your agent → **Goals** tab → click the pursuit. That cockpit shows the
contract, each grader's live PASS/FAIL, budgets, milestones, and the event
ledger. Type into the **steering box** to guide the next cycle mid-flight
(advice reaches the planner; it can never waive the graders). Or from the
terminal:

```bash
python steer.py add experts/builder <goal-id> "prefer bullet points, cite filenames"
python contract.py verify experts/builder <goal-id>    # re-run the graders yourself
```

## After the first win

- **Teach it**: drop files in `experts/builder/inbox/`, or
  `python ingest.py add-url <url> --root experts/builder` — it studies into
  cited atoms it can be examined on.
- **Let it run 24/7**: `python loop.py run --root experts/builder` (or the
  panel's start-loop button; `agent.service` for systemd).
- **Prove competence on unseen work**:
  `python mastery.py run . builder responsive-pricing --drive` — the sealed
  exam it cannot read or edit, with pretest → exam lift measured.
- Everything else: [README.md](README.md) → [ARCHITECTURE.md](ARCHITECTURE.md).
