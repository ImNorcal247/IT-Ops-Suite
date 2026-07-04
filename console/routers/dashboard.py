import sqlite3
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from console.db import DB_FILE, get_connection
from console.deps import require_user_api
from modules.ticket_import import (
    import_from_clickup,
    import_from_dataframe,
    import_from_servicenow,
    import_from_zendesk,
    test_zendesk_connection,
    upsert_tickets,
)
from modules.ticket_sinks import test_clickup_connection, test_servicenow_connection

router = APIRouter(prefix="/api/tickets", tags=["dashboard"])

PRIORITIES = ["Critical", "High", "Medium", "Low"]
MAX_CHART_CATEGORIES = 6  # any beyond this get folded into "Other" so the donut stays readable
VALID_KINDS = {"servicenow", "clickup", "zendesk"}


def _load_tickets_df() -> pd.DataFrame:
    if not DB_FILE.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(DB_FILE)
    try:
        return pd.read_sql_query("SELECT * FROM tickets", conn)
    finally:
        conn.close()


def _clean_row(row: dict) -> dict:
    return {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in row.items()}


@router.get("/meta")
def tickets_meta(user=Depends(require_user_api)):
    df = _load_tickets_df()
    if df.empty:
        return {"entities": [], "teams_by_entity": {"All Entities": []}}

    entities = sorted(df["source_entity"].dropna().unique().tolist())
    teams_by_entity = {"All Entities": sorted(df["assigned_team"].dropna().unique().tolist())}
    for entity in entities:
        scoped = df[df["source_entity"] == entity]
        teams_by_entity[entity] = sorted(scoped["assigned_team"].dropna().unique().tolist())
    return {"entities": entities, "teams_by_entity": teams_by_entity}


@router.get("")
def tickets(source_entity: str = "All Entities", assigned_team: str = "All Teams", user=Depends(require_user_api)):
    df = _load_tickets_df()
    if df.empty:
        return {"has_data": False}

    filtered = df
    if source_entity != "All Entities":
        filtered = filtered[filtered["source_entity"] == source_entity]
    if assigned_team != "All Teams":
        filtered = filtered[filtered["assigned_team"] == assigned_team]

    if filtered.empty:
        return {"has_data": True, "empty": True}

    avg_res = filtered["resolution_hours"].dropna().mean()

    # Categories are whatever's actually present in the data (real imported
    # tickets from ServiceNow/ClickUp/Zendesk/uploads won't all fit a fixed
    # 6-item list the way the original sample-data-only categories did) —
    # top N by count, anything smaller folded into "Other".
    category_series = filtered["category"].fillna("Unknown")
    category_counts_full = category_series.value_counts()
    top_categories = category_counts_full.head(MAX_CHART_CATEGORIES)
    category_counts = {str(k): int(v) for k, v in top_categories.items()}
    other_count = int(category_counts_full.iloc[MAX_CHART_CATEGORIES:].sum())
    if other_count:
        category_counts["Other"] = other_count

    return {
        "has_data": True,
        "empty": False,
        "metrics": {
            "total": int(len(filtered)),
            "entities": int(filtered["source_entity"].nunique()),
            "open": int(len(filtered[filtered["status"].isin(["Open", "In Progress"])])),
            "critical": int(len(filtered[filtered["priority"] == "Critical"])),
            "avg_resolution": round(float(avg_res), 1) if pd.notna(avg_res) else None,
        },
        "priority_counts": {p: int(len(filtered[filtered["priority"] == p])) for p in PRIORITIES},
        "category_counts": category_counts,
        "rows": [_clean_row(r) for r in filtered.sort_values("id").head(8).to_dict(orient="records")],
        "has_more": len(filtered) > 8,
        "more_count": max(0, len(filtered) - 8),
    }


# ── Data source connections ──────────────────────────────────────────────────

class SourceBody(BaseModel):
    label: str
    kind: str  # servicenow | clickup | zendesk
    instance: str = ""       # servicenow instance / zendesk subdomain
    username: str = ""       # servicenow username / zendesk email
    token: str = ""          # clickup token / zendesk api token / servicenow password
    list_or_view_id: str = ""  # clickup list id
    sync_interval_minutes: int = 0  # 0 = manual only


class SourceIntervalBody(BaseModel):
    sync_interval_minutes: int


def _row_to_source_dict(row) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "kind": row["kind"],
        "instance": row["instance"],
        "username": row["username"],
        "has_token": bool(row["token"]),
        "list_or_view_id": row["list_or_view_id"],
        "sync_interval_minutes": row["sync_interval_minutes"],
        "last_synced_at": row["last_synced_at"],
        "last_sync_count": row["last_sync_count"],
    }


def _get_source_or_404(conn, source_id: int):
    row = conn.execute("SELECT * FROM import_sources WHERE id = ?", (source_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Data source not found.")
    return row


def run_source_sync(conn, row) -> int:
    """Shared by the manual /sync endpoint, "sync all", and the background
    auto-sync loop in console/main.py — raises plain exceptions (not
    HTTPException) so each caller can handle failure its own way (the API
    routes translate to a 502, the background loop just logs and moves on)."""
    if row["kind"] == "servicenow":
        rows = import_from_servicenow(row["instance"], row["username"], row["token"])
    elif row["kind"] == "clickup":
        rows = import_from_clickup(row["token"], row["list_or_view_id"])
    else:
        rows = import_from_zendesk(row["instance"], row["username"], row["token"])

    count = upsert_tickets(conn, rows, row["label"])
    conn.execute(
        "UPDATE import_sources SET last_synced_at = ?, last_sync_count = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), count, row["id"]),
    )
    conn.commit()
    return count


def sync_due_sources() -> list[dict]:
    """Called periodically by the background loop in console/main.py. Syncs
    every source whose sync_interval_minutes > 0 and whose interval has
    elapsed since last_synced_at (or that has never synced yet). Returns a
    list of {id, label, ok, count_or_error} so the caller can log results —
    one source's failure doesn't stop the others."""
    conn = get_connection()
    results = []
    try:
        rows = conn.execute(
            "SELECT * FROM import_sources WHERE sync_interval_minutes > 0"
        ).fetchall()
        now = datetime.now(timezone.utc)
        for row in rows:
            if row["last_synced_at"]:
                elapsed_minutes = (now - datetime.fromisoformat(row["last_synced_at"])).total_seconds() / 60
                if elapsed_minutes < row["sync_interval_minutes"]:
                    continue
            try:
                count = run_source_sync(conn, row)
                results.append({"id": row["id"], "label": row["label"], "ok": True, "count": count})
            except Exception as e:
                results.append({"id": row["id"], "label": row["label"], "ok": False, "error": str(e)})
    finally:
        conn.close()
    return results


@router.get("/sources")
def list_sources(user=Depends(require_user_api)):
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM import_sources ORDER BY id").fetchall()
        return {"sources": [_row_to_source_dict(r) for r in rows]}
    finally:
        conn.close()


@router.post("/sources")
def create_source(body: SourceBody, user=Depends(require_user_api)):
    if body.kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(VALID_KINDS)}")
    if not body.label.strip():
        raise HTTPException(status_code=400, detail="label is required.")

    if body.sync_interval_minutes < 0:
        raise HTTPException(status_code=400, detail="sync_interval_minutes can't be negative.")

    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO import_sources "
            "(label, kind, instance, username, token, list_or_view_id, sync_interval_minutes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (body.label.strip(), body.kind, body.instance, body.username, body.token,
             body.list_or_view_id, body.sync_interval_minutes, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM import_sources WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_source_dict(row)
    finally:
        conn.close()


@router.patch("/sources/{source_id}")
def update_source_interval(source_id: int, body: SourceIntervalBody, user=Depends(require_user_api)):
    if body.sync_interval_minutes < 0:
        raise HTTPException(status_code=400, detail="sync_interval_minutes can't be negative.")
    conn = get_connection()
    try:
        _get_source_or_404(conn, source_id)
        conn.execute(
            "UPDATE import_sources SET sync_interval_minutes = ? WHERE id = ?",
            (body.sync_interval_minutes, source_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM import_sources WHERE id = ?", (source_id,)).fetchone()
        return _row_to_source_dict(row)
    finally:
        conn.close()


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, user=Depends(require_user_api)):
    conn = get_connection()
    try:
        _get_source_or_404(conn, source_id)
        conn.execute("DELETE FROM import_sources WHERE id = ?", (source_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.post("/sources/{source_id}/test")
def test_source(source_id: int, user=Depends(require_user_api)):
    conn = get_connection()
    try:
        row = _get_source_or_404(conn, source_id)
    finally:
        conn.close()

    if row["kind"] == "servicenow":
        ok, message = test_servicenow_connection(row["instance"], row["username"], row["token"])
    elif row["kind"] == "clickup":
        ok, message = test_clickup_connection(row["token"])
    else:
        ok, message = test_zendesk_connection(row["instance"], row["username"], row["token"])
    return {"ok": ok, "message": message}


@router.post("/sources/{source_id}/sync")
def sync_source(source_id: int, user=Depends(require_user_api)):
    conn = get_connection()
    try:
        row = _get_source_or_404(conn, source_id)
        try:
            count = run_source_sync(conn, row)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Sync failed: {e}")
        return {"ok": True, "count": count}
    finally:
        conn.close()


@router.post("/sources/sync-all")
def sync_all_sources(user=Depends(require_user_api)):
    """Manual "sync everything right now" — unlike sync_due_sources() (used
    by the background loop), this ignores each source's interval and syncs
    unconditionally."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM import_sources ORDER BY id").fetchall()
        results = []
        for row in rows:
            try:
                count = run_source_sync(conn, row)
                results.append({"id": row["id"], "label": row["label"], "ok": True, "count": count})
            except Exception as e:
                results.append({"id": row["id"], "label": row["label"], "ok": False, "error": str(e)})
        return {"results": results}
    finally:
        conn.close()


@router.post("/upload")
def upload_tickets(
    source_entity: str = Form(...),
    file: UploadFile = File(...),
    user=Depends(require_user_api),
):
    if not source_entity.strip():
        raise HTTPException(status_code=400, detail="source_entity is required.")

    filename = (file.filename or "").lower()
    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(file.file)
        elif filename.endswith(".xlsx"):
            df = pd.read_excel(file.file)
        else:
            raise HTTPException(status_code=400, detail="Only .csv and .xlsx files are supported.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Couldn't read the file: {e}")

    try:
        rows = import_from_dataframe(df, source_entity.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    conn = get_connection()
    try:
        count = upsert_tickets(conn, rows, source_entity.strip())
        return {"ok": True, "count": count}
    finally:
        conn.close()
