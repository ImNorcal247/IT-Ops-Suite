"""
modules/ticket_qa.py

Text-to-SQL Q&A over the tickets table, extracted from app.py's Tab 2
("Ask Your Data") so both the Streamlit app and the FastAPI console share
one implementation instead of duplicating the prompts/logic.
"""

import os

import anthropic


def get_claude_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=api_key) if api_key else None


def get_schema_summary(df):
    return f"""
Table: tickets
Columns:
- id (INTEGER): unique ticket ID
- source_entity (TEXT): which company/franchise/system this ticket came from. Actual values: {sorted(df['source_entity'].dropna().unique().tolist())}
- description (TEXT): brief description of the issue
- category (TEXT): actual values: {sorted(df['category'].dropna().unique().tolist())}
- priority (TEXT): actual values: {sorted(df['priority'].dropna().unique().tolist())}
- assigned_team (TEXT): actual values: {sorted(df['assigned_team'].dropna().unique().tolist())}
- status (TEXT): actual values: {sorted(df['status'].dropna().unique().tolist())}
- created_date (TEXT): format YYYY-MM-DD
- resolved_date (TEXT): format YYYY-MM-DD, may be NULL if not yet resolved
- resolution_hours (REAL): hours taken to resolve, may be NULL if not yet resolved
"""


def generate_sql(client, question, schema):
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=f"""You are a SQL expert. Convert the user's question into a single SQLite query.

DATABASE SCHEMA:
{schema}

IMPORTANT CONTEXT:
- The current year for relative date references is 2026
- Match the user's wording to the ACTUAL values listed in the schema

Rules:
- Return ONLY the SQL query, no explanation, no markdown, no backticks
- Only generate SELECT statements — never INSERT, UPDATE, DELETE, DROP, ALTER
- If the question can't be answered with this schema, return: INVALID_QUERY""",
        messages=[{"role": "user", "content": question}],
    )
    sql = message.content[0].text.strip()
    return sql.replace("```sql", "").replace("```", "").strip()


def is_safe_query(sql):
    sql_upper = sql.upper().strip()
    if not sql_upper.startswith("SELECT"):
        return False
    return not any(kw in sql_upper for kw in ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "EXEC"])


def interpret_results(client, question, sql, result_df):
    results_text = result_df.head(20).to_string(index=False)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system="You are a helpful IT operations analyst. Given a question and query results, "
               "give a clear, concise, natural language answer. Don't mention SQL or technical "
               "details. If results are empty, say so clearly.",
        messages=[{"role": "user", "content": f"Question: {question}\nSQL used: {sql}\nResults:\n{results_text}"}],
    )
    return message.content[0].text
