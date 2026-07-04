import sqlite3

import pandas as pd
from fastapi import APIRouter, Depends

from console.db import DB_FILE
from console.deps import require_user_api

router = APIRouter(prefix="/api/tickets", tags=["dashboard"])

PRIORITIES = ["Critical", "High", "Medium", "Low"]
CATEGORIES = ["Network", "Application", "Hardware", "Access", "Database", "Security"]


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
        "category_counts": {c: int(len(filtered[filtered["category"] == c])) for c in CATEGORIES},
        "rows": [_clean_row(r) for r in filtered.sort_values("id").head(8).to_dict(orient="records")],
        "has_more": len(filtered) > 8,
        "more_count": max(0, len(filtered) - 8),
    }
