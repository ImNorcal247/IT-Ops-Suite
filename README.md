# IT Ops Suite — AI Engineering Capstone

An AI-powered IT operations suite consolidating four previously separate AI-engineering
projects into one tool: multi-entity ticket analytics, text-to-SQL, RAG-powered policy
Q&A, few-shot incident classification, and a multi-agent ticket orchestrator. Built as
the capstone of a 30-day applied AI engineering practice.

> **For portfolio and reference purposes only** — not intended for commercial
> sale or production deployment as-is. It demonstrates what's achievable
> building in-house AI tooling for IT operations, whether for a homegrown
> stack or an enterprise environment.

The suite now ships in two forms:

| | What it is | Who it's for |
|---|---|---|
| **Production console** (`console/`) | A real FastAPI web app — multi-user login, six logged-in screens, backed by the same modules below | The IT Admin or Executive to run and use this day to day |
| **Streamlit reference app** (`app.py`) | The original single-file prototype — no login, one shared session | Whoever wants to tinker with the original capstone artifact for quick local experimentation |

Both front ends call the exact same backend logic in `modules/`, so behavior is
identical either way — only the UI and auth model differ.

| Capability | Source project | Pattern |
|---|---|---|
| Ticket Dashboard | [IT-Ticket-Dashboard](https://github.com/ImNorcal247/IT-Ticket-Dashboard) | Multi-entity data consolidation & visualization |
| Ask Your Data | IT-Ticket-Dashboard | Text-to-SQL |
| Policy Q&A | [it-policy-qa-bot](https://github.com/ImNorcal247/it-policy-qa-bot) | RAG (ChromaDB) |
| Incident Classifier | [it-incident-classifier](https://github.com/ImNorcal247/it-incident-classifier) | Few-shot structured output |
| Ticket Orchestrator | [IT-Ticket-Orchestrator](https://github.com/ImNorcal247/IT-Ticket-Orchestrator) | Multi-agent pipeline, live ClickUp/ServiceNow integration |

There's also a static marketing/portfolio site in `website/` (build script + templates,
publishes to GitHub Pages) — that's a separate, unrelated-to-login public site describing
the product; see `website/build.py` if you need to touch it.

---

## Quick start — Production console (recommended)

```bash
pip install -r requirements.txt

# macOS/Linux
export ANTHROPIC_API_KEY="sk-ant-..."
# Windows PowerShell
$env:ANTHROPIC_API_KEY="sk-ant-..."

# Sample ticket data (~120 rows across 3 source entities)
python setup_sample_data.py

# Create your first login — prompts for a password, never takes it as a CLI arg
python scripts/create_user.py --email you@company.com --name "Your Name" --role "IT Operations"

# Run the server (single worker only — see Architecture notes below)
uvicorn console.main:app --reload --port 8000
```

Open `http://localhost:8000`, sign in with the account you just created, and you'll land
on the Ticket Dashboard. Use `python scripts/create_user.py` again any time to add more
operators or reset a password — there's no self-service signup by design (this mirrors
the source design: an internal ops tool, not a public product).

### The six console screens

**Ticket Dashboard** (`/dashboard`)
Two dropdowns — Source Entity and Assigned Team — filter every metric, chart, and table
row on the page live, with no page reload. Picking an entity narrows the team dropdown
to only teams that actually have tickets there (cascading filters), so you never see an
empty, confusing list. Below the filters: 5 metric cards (total tickets, source
entities, open/in-progress, critical priority, average resolution hours), a bar chart of
tickets by priority, a donut chart of tickets by category, and a table of the first 8
matching tickets with a "+N more" footer. Everything reads directly from `it_tickets.db`
on each filter change — there's no separate refresh button, just change a dropdown. To get all desired data into `it_tickets.db`, just configure your API endpoints, or import the data with the available excel template which can be downloaded from the site directly. 

**Ask Your Data** (`/ask-data`)
Type a plain-English question about the ticket data (or click one of the three example
chips) and hit Ask / Enter. Behind the scenes: Claude converts your question into a
single SQLite `SELECT` query against the real schema, the query is safety-checked (only
`SELECT` is ever allowed — anything containing `DROP`/`DELETE`/`UPDATE`/`INSERT`/`ALTER`
is rejected before it runs), the query executes against `it_tickets.db`, and the raw
results are handed back to Claude to phrase as a plain-English answer. Click "Show
generated SQL and raw results" under the answer to see exactly what ran.

**Policy Q&A** (`/policy-qa`)
Ask a question about and Enterprise policy in plain English. The three `.txt` files in
`docs/policies/` (password, incident response, remote access) are chunked and embedded
into an in-memory ChromaDB collection once at server startup; your question is matched
against that index, and only chunks under a similarity-distance threshold are used as
context — Claude is instructed to answer using *only* that retrieved text. The answer
comes back with a "Sources: ..." line naming which document(s) it drew from and a
Confidence badge (High/Medium/Low, derived from how close the match was). If nothing
relevant is found, it says so instead of guessing. Add your own `.txt` files to
`docs/policies/` and restart the server to ground answers in real organizational policy.

**Incident Classifier** (`/classifier`)
Describe an incident in a sentence (optionally add one line of extra context) and click
Classify. This calls Claude with a few-shot prompt (two worked examples baked into the
system prompt) that forces one exact JSON shape back every time: category, subcategory,
priority (Critical/High/Medium/Low, following the ITIL-style guidance in the prompt),
assigned team, an estimated resolution time, a numbered list of immediate actions,
similar past incidents, and an escalation condition. Same prompt and schema as the
original standalone classifier project — nothing simplified for the demo.

**Ticket Orchestrator** (`/orchestrator`)
Describe a problem in one line and click Submit. This is a **fixed, deterministic
pipeline**, not an open-ended autonomous agent: Triage → Duplicate check → Assignment →
Create, each stage a single forced tool-call to Claude (Opus), run in that exact order
because ticket routing is a business process with a correct sequence. You'll watch each
stage complete live, one at a time, streamed over Server-Sent Events as it actually
happens (not a fake timed animation) — real triage classification, then a real duplicate
search against existing open tickets in the active backend, then real routing per the
category → team table, then real ticket creation. If a duplicate is found, the pipeline
stops there and links your report to the existing ticket instead of filing a new one.
Where "real" tickets actually go depends on the backend chosen in Settings.

**Settings** (`/settings`)
Choose the Orchestrator's backend — **Mock** (in-memory fake tickets, no credentials,
the default), **ClickUp only**, **ServiceNow only**, or **Both — dual write** (every
create and duplicate-check fans out to both systems and merges the results). Toggle
**Dry run** to validate payloads and log what *would* happen without actually writing
anywhere — recommended the first time you point this at a real system. Enter credentials
directly in the form and use **Test Connection** to verify against the live API before
saving. Settings apply for the rest of the running server process and are **never
written to disk** — restarting the server resets everything back to Mock. This is one
shared configuration for the whole tool (not per-user), matching how the original
Streamlit version worked.

---

## Quick start — Streamlit reference app

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."       # or $env:ANTHROPIC_API_KEY on Windows
python setup_sample_data.py                  # if not already generated
streamlit run app.py
```

Opens automatically at `http://localhost:8501`. Same six capabilities as the tabs in the
table above, no login — this is the original single-operator prototype, kept working
as-is for quick local checks. Its own Settings tab writes `TICKET_MODE`/`DRY_RUN`/
`CLICKUP_*`/`SERVICENOW_*` as environment variables instead of the console's in-memory
config, so the two front ends' backend selections are independent of each other.

Equivalent environment variables, if you'd rather set the orchestrator backend before
launch instead of through either app's Settings UI:

```bash
export TICKET_MODE=clickup        # mock | clickup | servicenow | both
export DRY_RUN=true
export CLICKUP_API_TOKEN="pk_..."
export CLICKUP_LIST_ID_DEFAULT="your_list_id"
streamlit run app.py
```

---

## Architecture notes

- **Shared backend, two front ends.** `modules/*.py` holds all the actual logic (RAG,
  text-to-SQL, classification, the orchestrator pipeline, pluggable ticket sinks) and is
  imported unchanged by both `app.py` (Streamlit) and `console/` (FastAPI) — neither is a
  fork of the other's logic.
- **`SinkConfig`, not `os.environ`, inside the shared modules.** `modules/ticket_sinks.py`
  and `modules/ticket_orchestrator.py` take an explicit `SinkConfig` object rather than
  reading process env vars directly, since a real multi-request server can't safely share
  Streamlit's single-process-global config model. `app.py` builds a `SinkConfig` from its
  own env vars right before calling the orchestrator, so its behavior is unchanged;
  `console/` keeps one shared `SinkConfig` on `app.state`, mutated by the Settings screen.
- **Console sessions.** Login uses a signed cookie (`itsdangerous`), not a server-side
  session store. The signing key is read from a `SESSION_SECRET_KEY` env var if set,
  otherwise generated once and persisted to a gitignored `console/.secret_key` — so
  `uvicorn --reload` restarts during development don't silently log everyone out.
- **Single worker only.** The console's shared Settings (`app.state.sink_config`) and the
  Policy Q&A ChromaDB collection (`app.state.policy_collection`) are in-memory, one
  instance per process. Running `uvicorn` with `--workers > 1` would give each worker its
  own independent copy of both — silently breaking "one shared config" and wastefully
  rebuilding the policy index per worker. Stick to the default single worker unless this
  gets re-architected for multi-worker/multi-instance deployment.
- **Two deliberately different agentic patterns.** The Orchestrator's pipeline is a
  fixed, deterministic sequence (triage → dedup → assign → create) using forced
  single-tool calls, because ticket routing has a correct order. Everything else uses
  simpler single-shot structured generation. Neither is an open-ended autonomous agent
  loop — that pattern lives in a separate investigation-agent project, intentionally kept
  out of this consolidation since it solves a different problem.
- **Dual-write mode** (`TICKET_MODE=both` / Settings → "Both — dual write"): `MultiSink`
  fans every create and duplicate-check call out to ClickUp and ServiceNow simultaneously
  and merges the results. The two systems are not kept in sync afterward — closing or
  updating a ticket in one does not propagate to the other. Dual-write only guarantees
  both copies exist at creation time.
- **Security**: never commit real API tokens, ClickUp/ServiceNow credentials, or
  `console/.secret_key` — see `.gitignore`. Console passwords are bcrypt-hashed; there is
  no plaintext password storage anywhere.

## What's intentionally out of scope

- Real-time sync between screens/tabs — a ticket created via the Orchestrator doesn't
  appear in the Dashboard, since they use different data stores (SQLite for the
  dashboard vs. live ClickUp/ServiceNow or an in-memory mock for the orchestrator).
- Multi-worker / horizontally-scaled deployment of the console (see single-worker note
  above) — it's built for one shared team, one process, running locally or on a single
  host.
- A persistent chat history across screens or sessions.
- Public self-service signup for the console — accounts are created by an administrator
  via `scripts/create_user.py`.

## Repo layout

```
app.py                 Streamlit reference app (legacy front end)
modules/                Shared backend logic — RAG, text-to-SQL, classifier, orchestrator, sinks
console/                Production FastAPI app (auth, 6 screens, real backend calls)
scripts/create_user.py  CLI to seed console login accounts
website/                Static marketing/portfolio site (unrelated to login), deployed via GitHub Pages
docs/policies/          Sample policy documents indexed by Policy Q&A
setup_sample_data.py    Generates the demo it_tickets.db
```

