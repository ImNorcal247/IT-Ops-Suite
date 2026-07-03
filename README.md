# IT Ops Suite — AI Engineering Capstone

A single Streamlit application consolidating four previously separate AI-engineering
projects into one shippable tool. Built as the capstone of a 30-day applied AI
engineering practice, combining RAG, structured output, text-to-SQL, and multi-agent
orchestration behind one interface.

| Tab | Source project | Pattern |
|---|---|---|
| 📊 Ticket Dashboard | [IT-Ticket-Dashboard](https://github.com/ImNorcal247/IT-Ticket-Dashboard) | Multi-entity data consolidation & visualization |
| 💬 Ask Your Data | IT-Ticket-Dashboard | Text-to-SQL |
| 📄 Policy Q&A | [it-policy-qa-bot](https://github.com/ImNorcal247/it-policy-qa-bot) | RAG (ChromaDB) |
| 🔧 Incident Classifier | [it-incident-classifier](https://github.com/ImNorcal247/it-incident-classifier) | Few-shot structured output |
| 🎫 Ticket Orchestrator | [IT-Ticket-Orchestrator](https://github.com/ImNorcal247/IT-Ticket-Orchestrator) | Multi-agent pipeline, live ClickUp/ServiceNow integration |

Each tab reuses the actual logic from its original standalone repo — this project is the
integration layer, not a rewrite. See each linked repo for that capability's own
detailed README and commit history.

## Setup

```bash
pip install -r requirements.txt
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."        # macOS/Linux
$env:ANTHROPIC_API_KEY="sk-ant-..."          # Windows PowerShell
```

Generate sample ticket data (needed for Tabs 1 and 2):

```bash
python setup_sample_data.py
```

Run the app:

```bash
streamlit run app.py
```

Opens automatically at `http://localhost:8501`.

## Tab 5 — Ticket Orchestrator backend

By default, Tab 5 runs against an in-memory mock ticketing backend — no external
credentials needed to try it. To point it at a real ClickUp or ServiceNow instance,
set the same environment variables documented in the
[IT-Ticket-Orchestrator README](https://github.com/ImNorcal247/IT-Ticket-Orchestrator)
before launching:

```bash
export TICKET_SINK=clickup
export DRY_RUN=true
export CLICKUP_API_TOKEN="pk_..."
export CLICKUP_LIST_ID_DEFAULT="your_list_id"
streamlit run app.py
```

## Tab 3 — Policy Q&A documents

Sample policy documents ship in `docs/policies/` (password, incident response, remote
access) so the tab works out of the box. Drop your own `.txt` files into that folder to
ground answers in real organizational policy instead.

## Architecture notes

- **Two deliberately different agentic patterns** live in this app: Tab 5's pipeline is
  a fixed, deterministic sequence (triage → dedup → assign → create) using forced
  single-tool calls, because ticket routing is a business process with a correct order.
  Everything else uses simpler single-shot structured generation. Neither uses an
  open-ended autonomous agent loop — that pattern lives in a separate investigation-agent
  project, intentionally kept out of this consolidation since it solves a different
  problem (open-ended diagnosis vs. structured classification).
- **Streamlit caching**: `policy_qa.py`'s knowledge base build is wrapped in
  `@st.cache_resource` so it only runs once per session — the original standalone
  `bot.py` rebuilt it on every script execution, which is correct for a CLI tool but
  would rebuild the vector index on every click inside Streamlit's rerun model.
- **Security**: never commit real API tokens or ClickUp/ServiceNow credentials. See
  `.gitignore`.

## What's intentionally out of scope

- Real-time sync between tabs (e.g., a ticket created in Tab 5 doesn't yet appear in
  Tab 1's dashboard, since they use different data stores — SQLite for the dashboard,
  live ClickUp/ServiceNow or an in-memory mock for the orchestrator)
- Authentication / multi-user support — this is a single-operator local tool
- A persistent chat history across tabs

## License

MIT
