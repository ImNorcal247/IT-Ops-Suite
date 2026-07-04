"""
console/main.py

FastAPI app factory for the IT Ops Suite production console — the
logged-in tool wired to the real modules/*.py backend logic (app.py's
Streamlit shell stays a separate, still-working entry point).

Run with:
    uvicorn console.main:app --reload --port 8000

Requires ANTHROPIC_API_KEY set in the environment. Must run single-worker
(the default, no --workers flag) — app.state.sink_config and
app.state.policy_collection are shared in-process state, one instance per
worker process, not safe to split across multiple workers.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from console.db import ensure_import_sources_table, ensure_users_table
from console.routers import (
    ask_data,
    auth_routes,
    classifier_routes,
    dashboard,
    orchestrator_routes,
    pages,
    policy_qa_routes,
    settings_routes,
)
from modules.policy_qa import build_knowledge_base
from modules.ticket_sinks import SinkConfig

STATIC_DIR = Path(__file__).parent / "static"
AUTO_SYNC_CHECK_SECONDS = 60


async def _auto_sync_loop():
    """Checks every AUTO_SYNC_CHECK_SECONDS for data sources whose configured
    sync_interval_minutes has elapsed and syncs them. Runs for the life of
    the process — cancelled in lifespan's shutdown. dashboard.sync_due_sources()
    already isolates failures per-source, so one bad connection doesn't stop
    the others or crash this loop."""
    while True:
        await asyncio.sleep(AUTO_SYNC_CHECK_SECONDS)
        try:
            results = await asyncio.to_thread(dashboard.sync_due_sources)
            for r in results:
                if r["ok"]:
                    print(f"  [auto-sync] {r['label']}: {r['count']} ticket(s)")
                else:
                    print(f"  ⚠️  [auto-sync] {r['label']} failed: {r['error']}")
        except Exception as e:
            print(f"  ⚠️  [auto-sync] loop error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_users_table()
    ensure_import_sources_table()
    app.state.sink_config = SinkConfig()
    collection, chunk_count = build_knowledge_base()
    app.state.policy_collection = collection
    app.state.policy_chunk_count = chunk_count

    sync_task = asyncio.create_task(_auto_sync_loop())
    yield
    sync_task.cancel()


class NoCacheStaticFiles(StaticFiles):
    """Force revalidation on every request instead of letting browsers use
    heuristic disk caching for CSS/JS — small perf cost (a 304 round trip),
    but edits to these files take effect immediately instead of silently
    serving a stale cached copy."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", b"no-cache"))
                message["headers"] = headers
            await send(message)

        await super().__call__(scope, receive, send_wrapper)


app = FastAPI(title="IT Ops Suite Console", lifespan=lifespan)
app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth_routes.router)
app.include_router(pages.router)
app.include_router(dashboard.router)
app.include_router(ask_data.router)
app.include_router(policy_qa_routes.router)
app.include_router(classifier_routes.router)
app.include_router(orchestrator_routes.router)
app.include_router(settings_routes.router)
