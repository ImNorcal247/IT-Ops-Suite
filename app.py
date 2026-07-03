"""
app.py

IT Ops Suite — a single Streamlit application consolidating four
previously separate AI engineering projects into one shippable app:

  1. Ticket Dashboard      (from IT-Ticket-Dashboard)
  2. Ask Your Data          (from IT-Ticket-Dashboard, text-to-SQL)
  3. Policy Q&A             (from it-policy-qa-bot, RAG)
  4. Incident Classifier    (from it-incident-classifier, few-shot structured output)
  5. Ticket Orchestrator    (from IT-Ticket-Orchestrator, multi-agent pipeline)

Each tab's underlying logic is the same code from its original repo —
this file is the shell that wires them together, not a rewrite.

Usage:
    streamlit run app.py
"""

import os
import sys
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import anthropic

# Make modules/ importable, and let ticket_orchestrator.py's sibling
# imports (ticket_sinks, ticket_id_map) resolve without a package structure
sys.path.insert(0, str(Path(__file__).parent / "modules"))

from policy_qa import build_knowledge_base, query_policies
from incident_classifier import classify_incident
from ticket_orchestrator import create_ticket

DB_FILE = "it_tickets.db"

st.set_page_config(page_title="IT Ops Suite", page_icon="🛠️", layout="wide")


# ── Shared helpers (from IT-Ticket-Dashboard) ──────────────────────────────

@st.cache_data(ttl=30)
def load_tickets():
    if not Path(DB_FILE).exists():
        return pd.DataFrame()
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM tickets", conn)
    conn.close()
    return df


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


def get_claude_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=api_key) if api_key else None


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


# ── Header ──────────────────────────────────────────────────────────────────

st.title("🛠️ IT Ops Suite")
st.caption(
    "Four AI-engineering projects, one app — ticket analytics, policy Q&A, incident "
    "classification, and multi-agent ticket routing, unified into a single shippable tool."
)

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.warning("ANTHROPIC_API_KEY environment variable not found. Most tabs require it to function.")

df = load_tickets()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Ticket Dashboard", "💬 Ask Your Data", "📄 Policy Q&A",
    "🔧 Incident Classifier", "🎫 Ticket Orchestrator",
])


# ── TAB 1: Ticket Dashboard ──────────────────────────────────────────────

with tab1:
    if df.empty:
        st.info("No ticket data found. Run `python setup_sample_data.py` first, then reload this page.")
    else:
        st.caption(f"{len(df)} tickets loaded from {df['source_entity'].nunique()} source entities")

        col_a, col_b = st.columns(2)
        entity_options = ["All Entities"] + sorted(df["source_entity"].dropna().unique().tolist())
        selected_entity = col_a.selectbox("Source Entity", entity_options)

        entity_scoped_df = df if selected_entity == "All Entities" else df[df["source_entity"] == selected_entity]
        team_options = ["All Teams"] + sorted(entity_scoped_df["assigned_team"].dropna().unique().tolist())
        selected_team = col_b.selectbox("Assigned Team", team_options)

        filtered_df = df
        if selected_entity != "All Entities":
            filtered_df = filtered_df[filtered_df["source_entity"] == selected_entity]
        if selected_team != "All Teams":
            filtered_df = filtered_df[filtered_df["assigned_team"] == selected_team]

        if filtered_df.empty:
            st.warning("No tickets found for this filter.")
        else:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Total Tickets", len(filtered_df))
            c2.metric("Source Entities", filtered_df["source_entity"].nunique())
            c3.metric("Open / In Progress", len(filtered_df[filtered_df["status"].isin(["Open", "In Progress"])]))
            c4.metric("Critical Priority", len(filtered_df[filtered_df["priority"] == "Critical"]))
            avg_res = filtered_df["resolution_hours"].dropna().mean()
            c5.metric("Avg Resolution (hrs)", f"{avg_res:.1f}" if pd.notna(avg_res) else "N/A")

            st.divider()

            if selected_entity == "All Entities" and filtered_df["source_entity"].nunique() > 1:
                st.subheader("Tickets by Source Entity")
                entity_counts = filtered_df["source_entity"].value_counts()
                st.plotly_chart(px.bar(x=entity_counts.index, y=entity_counts.values,
                                        labels={"x": "Source Entity", "y": "Ticket Count"}), use_container_width=True)
                st.divider()

            r1c1, r1c2 = st.columns(2)
            with r1c1:
                st.subheader("Tickets by Priority")
                priority_counts = filtered_df["priority"].value_counts().reindex(["Critical", "High", "Medium", "Low"]).dropna()
                if priority_counts.empty:
                    st.caption("No data for this filter.")
                else:
                    fig = px.bar(x=priority_counts.index, y=priority_counts.values, color=priority_counts.index,
                                 color_discrete_map={"Critical": "#d62728", "High": "#ff7f0e", "Medium": "#1f77b4", "Low": "#2ca02c"},
                                 labels={"x": "Priority", "y": "Ticket Count"})
                    fig.update_layout(showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)
            with r1c2:
                st.subheader("Tickets by Category")
                category_counts = filtered_df["category"].value_counts()
                if category_counts.empty:
                    st.caption("No data for this filter.")
                else:
                    st.plotly_chart(px.pie(values=category_counts.values, names=category_counts.index, hole=0.4), use_container_width=True)

            r2c1, r2c2 = st.columns(2)
            with r2c1:
                st.subheader("Ticket Volume Over Time")
                volume = filtered_df.groupby("created_date").size().reset_index(name="count")
                if volume.empty:
                    st.caption("No data for this filter.")
                else:
                    volume["created_date"] = pd.to_datetime(volume["created_date"])
                    volume = volume.sort_values("created_date")
                    fig = px.line(volume, x="created_date", y="count", markers=True)
                    fig.update_layout(xaxis_title="Date", yaxis_title="Tickets Created")
                    st.plotly_chart(fig, use_container_width=True)
            with r2c2:
                st.subheader("Avg Resolution Time by Team" if selected_team == "All Teams" else "Resolution Time Trend")
                if selected_team == "All Teams":
                    team_res = filtered_df.dropna(subset=["resolution_hours"]).groupby("assigned_team")["resolution_hours"].mean().sort_values()
                    if team_res.empty:
                        st.caption("No resolved tickets yet.")
                    else:
                        st.plotly_chart(px.bar(x=team_res.values, y=team_res.index, orientation="h",
                                                labels={"x": "Avg Hours to Resolve", "y": "Team"}), use_container_width=True)
                else:
                    resolved = filtered_df.dropna(subset=["resolution_hours"]).sort_values("created_date")
                    if resolved.empty:
                        st.caption("No resolved tickets yet for this team.")
                    else:
                        st.plotly_chart(px.bar(resolved, x="created_date", y="resolution_hours",
                                                labels={"created_date": "Date", "resolution_hours": "Hours to Resolve"}), use_container_width=True)

            st.divider()
            st.subheader("Raw Ticket Data")
            st.dataframe(filtered_df, use_container_width=True, height=300)


# ── TAB 2: Ask Your Data (text-to-SQL) ────────────────────────────────────

with tab2:
    st.subheader("Ask anything about your ticket data")
    client = get_claude_client()
    if client is None:
        st.error("ANTHROPIC_API_KEY environment variable not found.")
    elif df.empty:
        st.info("No ticket data found. Run `python setup_sample_data.py` first.")
    else:
        st.caption("Examples: " + " · ".join([
            "How many critical tickets are still open?",
            "What's the average resolution time for Network category tickets?",
            "Which team has the most open tickets?",
        ]))
        question = st.text_input("Your question:", placeholder="e.g. How many tickets were closed last month?")
        if st.button("Ask", type="primary") and question:
            schema = get_schema_summary(df)
            with st.spinner("Thinking..."):
                sql = generate_sql(client, question, schema)
                if sql == "INVALID_QUERY":
                    st.warning("I can't answer that question with the data available.")
                elif not is_safe_query(sql):
                    st.error("That query was blocked for safety reasons.")
                else:
                    try:
                        conn = sqlite3.connect(DB_FILE)
                        result_df = pd.read_sql_query(sql, conn)
                        conn.close()
                        answer = interpret_results(client, question, sql, result_df)
                        st.success(answer)
                        with st.expander("Show generated SQL and raw results"):
                            st.code(sql, language="sql")
                            st.dataframe(result_df, use_container_width=True)
                    except Exception as e:
                        st.error(f"Error running query: {e}")


# ── TAB 3: Policy Q&A (RAG) ────────────────────────────────────────────────

with tab3:
    st.subheader("Ask a question about IT policy")
    st.caption("Retrieval-augmented — answers are grounded only in the policy documents in `docs/policies/`.")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY environment variable not found.")
    else:
        collection, chunk_count = build_knowledge_base()
        if collection is None:
            st.info("No policy documents found in `docs/policies/`. Add `.txt` files there and reload.")
        else:
            st.caption(f"Knowledge base ready — {chunk_count} chunks indexed.")
            example_qs = [
                "How long before passwords expire?",
                "What do I do if I suspect a SEV1 incident?",
                "Can I use my personal laptop to VPN into the network?",
            ]
            st.caption("Examples: " + " · ".join(example_qs))
            policy_question = st.text_input("Your question:", key="policy_q", placeholder="e.g. How many failed logins before account lockout?")
            if st.button("Ask", type="primary", key="policy_ask") and policy_question:
                with st.spinner("Searching policies..."):
                    result = query_policies(collection, policy_question)
                st.success(result["answer"])
                st.caption(f"Sources: {', '.join(result['sources']) if result['sources'] else 'none'} · Confidence: {result['confidence']}")


# ── TAB 4: Incident Classifier ──────────────────────────────────────────────

with tab4:
    st.subheader("Classify an IT incident")
    st.caption("Few-shot structured classification — category, priority, routing, and immediate actions.")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY environment variable not found.")
    else:
        incident_desc = st.text_area("Incident description:", placeholder="e.g. The entire Las Vegas office has no internet and can't reach any internal systems")
        incident_context = st.text_input("Additional context (optional):")
        if st.button("Classify", type="primary") and incident_desc:
            with st.spinner("Classifying..."):
                try:
                    result = classify_incident(incident_desc, incident_context)
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Category", f"{result['category']}")
                    c1.caption(result["subcategory"])
                    c2.metric("Priority", result["priority"])
                    c3.metric("Assigned Team", result["assigned_team"])
                    st.caption(f"Estimated resolution time: {result['estimated_resolution_time']}")

                    st.markdown("**Immediate Actions**")
                    for i, action in enumerate(result["immediate_actions"], 1):
                        st.markdown(f"{i}. {action}")

                    st.markdown(f"**Similar Incidents:** {', '.join(result['similar_incidents'])}")
                    st.markdown(f"**Escalate If:** {result['escalate_if']}")
                except Exception as e:
                    st.error(f"Classification failed: {e}")


# ── TAB 5: Ticket Orchestrator ──────────────────────────────────────────────

with tab5:
    st.subheader("Submit a problem — auto-triage, dedup, route, and file")
    st.caption(
        "Multi-agent pipeline: triage → live duplicate check → assignment → ticket creation. "
        f"Current backend: **{os.environ.get('TICKET_SINK', 'mock').upper()}**"
        + (" (dry run)" if os.environ.get("DRY_RUN", "false").lower() == "true" else "")
    )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY environment variable not found.")
    else:
        problem_desc = st.text_area(
            "Describe the problem:",
            placeholder="e.g. My laptop screen is flickering and sometimes goes completely black",
            key="orchestrator_input",
        )
        if st.button("Submit", type="primary") and problem_desc:
            progress_area = st.container()
            stages_seen = []

            def show_progress(stage_name, result):
                stages_seen.append((stage_name, result))
                with progress_area:
                    if stage_name == "triage":
                        st.write(f"✅ **Triage** → {result['category']}/{result['subcategory']} | {result['priority']}")
                    elif stage_name == "duplicate_check":
                        st.write(f"✅ **Duplicate check** → duplicate={result['is_duplicate']} — {result['reasoning']}")
                    elif stage_name == "assignment":
                        st.write(f"✅ **Assignment** → {result['assignment_group']}")
                    elif stage_name == "create":
                        st.write(f"✅ **Ticket created** → {result.get('ticket_id', 'unknown')}")

            with st.spinner("Running pipeline..."):
                try:
                    final = create_ticket(problem_desc, progress_callback=show_progress)
                    st.divider()
                    if final.get("action") == "linked_to_existing":
                        st.info(f"Linked as duplicate of **{final['linked_ticket_id']}**")
                    else:
                        st.success(f"Ticket **{final.get('ticket_id')}** created and routed to **{final.get('assignment_group')}**")
                        if final.get("external_url"):
                            st.markdown(f"[View in {final.get('sink', 'system')}]({final['external_url']})")
                    with st.expander("Full result"):
                        st.json(final)
                except Exception as e:
                    st.error(f"Pipeline failed: {e}")
