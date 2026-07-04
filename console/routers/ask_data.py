import sqlite3

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from console.db import DB_FILE
from console.deps import require_user_api
from modules.ticket_qa import generate_sql, get_claude_client, get_schema_summary, interpret_results, is_safe_query

router = APIRouter(prefix="/api", tags=["ask-data"])


class AskDataBody(BaseModel):
    question: str


@router.post("/ask-data")
def ask_data(body: AskDataBody, user=Depends(require_user_api)):
    client = get_claude_client()
    if client is None:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY environment variable not found.")
    if not DB_FILE.exists():
        raise HTTPException(status_code=503, detail="No ticket data found. Run `python setup_sample_data.py` first.")

    conn = sqlite3.connect(DB_FILE)
    try:
        df = pd.read_sql_query("SELECT * FROM tickets", conn)
        if df.empty:
            raise HTTPException(status_code=503, detail="No ticket data found.")

        schema = get_schema_summary(df)
        try:
            sql = generate_sql(client, body.question, schema)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Error generating query: {e}")
        if sql == "INVALID_QUERY":
            return {"answer": "I can't answer that question with the data available.", "sql": None, "rows": []}
        if not is_safe_query(sql):
            raise HTTPException(status_code=400, detail="That query was blocked for safety reasons.")

        try:
            result_df = pd.read_sql_query(sql, conn)
            answer = interpret_results(client, body.question, sql, result_df)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Error running query: {e}")
        rows = result_df.to_dict(orient="records")
        rows = [{k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in r.items()} for r in rows]
        return {"answer": answer, "sql": sql, "rows": rows}
    finally:
        conn.close()
