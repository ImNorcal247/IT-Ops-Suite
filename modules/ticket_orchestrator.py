"""
modules/ticket_orchestrator.py

Unchanged pipeline logic from the IT-Ticket-Orchestrator repo
(https://github.com/ImNorcal247/IT-Ticket-Orchestrator): triage ->
duplicate check (live search_existing) -> assignment -> creation.
Logging to disk is stripped out here since the Streamlit tab handles
displaying run state directly in the UI instead.
"""

import json
import time
from datetime import datetime, timezone

import anthropic
from modules.ticket_sinks import get_active_sinks, SinkConfig

client = anthropic.Anthropic()
MODEL = "claude-opus-4-5"

ROUTING_TABLE = {
    "Application": "App Support — Tier 2",
    "Network": "Network Operations",
    "Hardware": "Desktop Support",
    "Access": "Identity & Access Management",
    "Database": "Database Administration",
    "Security": "Security Operations Center",
}

TRIAGE_SCHEMA = {
    "name": "submit_triage",
    "description": "Submit the triage classification for an IT issue.",
    "input_schema": {
        "type": "object",
        "properties": {
            "short_description": {"type": "string", "description": "One-line ticket title, max 80 chars"},
            "category": {"type": "string", "enum": ["Application", "Network", "Hardware", "Access", "Database", "Security"]},
            "subcategory": {"type": "string", "description": "More specific area, e.g. 'Payments', 'VPN', 'Laptop'"},
            "priority": {"type": "string", "enum": ["P1", "P2", "P3", "P4"]},
            "impact": {"type": "string", "enum": ["High", "Medium", "Low"]},
            "urgency": {"type": "string", "enum": ["High", "Medium", "Low"]},
            "affected_system": {"type": "string", "description": "Best-guess system or CI name"},
        },
        "required": ["short_description", "category", "subcategory", "priority", "impact", "urgency", "affected_system"],
    },
}

DUPLICATE_SCHEMA = {
    "name": "submit_duplicate_check",
    "description": "Submit the result of checking for duplicate/related existing tickets.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_duplicate": {"type": "boolean"},
            "related_ticket_id": {"type": "string"},
            "reasoning": {"type": "string"},
        },
        "required": ["is_duplicate", "related_ticket_id", "reasoning"],
    },
}

ASSIGNMENT_SCHEMA = {
    "name": "submit_assignment",
    "description": "Submit the team/queue this ticket should be routed to.",
    "input_schema": {
        "type": "object",
        "properties": {
            "assignment_group": {"type": "string", "description": "Exact team name from the routing table"},
            "reasoning": {"type": "string"},
        },
        "required": ["assignment_group", "reasoning"],
    },
}


def call_specialist(system_prompt: str, user_content: str, tool_schema: dict) -> dict:
    response = client.messages.create(
        model=MODEL, max_tokens=1024, system=system_prompt,
        tools=[tool_schema], tool_choice={"type": "tool", "name": tool_schema["name"]},
        messages=[{"role": "user", "content": user_content}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError(f"Specialist agent did not return a tool call: {response.content}")


def triage_stage(raw_input: str) -> dict:
    system = (
        "You are a Triage agent for an IT service desk. Classify the user's reported issue into "
        "structured ticket fields. Priority follows standard ITIL guidance: P1 = critical outage "
        "affecting many users, P2 = major degradation, P3 = minor issue with workaround, "
        "P4 = informational/low impact. Be decisive — pick the best fit, don't hedge."
    )
    return call_specialist(system, raw_input, TRIAGE_SCHEMA)


def duplicate_check_stage(triage: dict, sink) -> dict:
    system = (
        "You are a Duplicate Check agent for an IT service desk. Given a new ticket's classification "
        "and a list of existing open/active tickets, determine if this is a duplicate or closely "
        "related to an existing ticket. Only flag as duplicate if it's clearly the same underlying "
        "issue, not just the same category. If the existing-tickets list is empty, is_duplicate must be false."
    )
    existing = sink.search_existing(category=triage.get("category"))
    user_content = (
        f"New ticket classification:\n{json.dumps(triage, indent=2)}\n\n"
        f"Existing open/active tickets:\n{json.dumps(existing, indent=2)}"
    )
    return call_specialist(system, user_content, DUPLICATE_SCHEMA)


def assignment_stage(triage: dict) -> dict:
    system = (
        "You are an Assignment agent for an IT service desk. Given a ticket's category and the "
        "routing table below, choose the correct assignment_group. Use the exact team name from "
        "the table — do not invent new team names.\n\n"
        f"Routing table:\n{json.dumps(ROUTING_TABLE, indent=2)}"
    )
    user_content = f"Ticket classification:\n{json.dumps(triage, indent=2)}"
    return call_specialist(system, user_content, ASSIGNMENT_SCHEMA)


def create_ticket(raw_input: str, progress_callback=None, sink_config: SinkConfig | None = None) -> dict:
    """progress_callback(stage_name, result_dict) is called after each stage,
    letting a caller show live progress instead of only a final result.
    sink_config defaults to SinkConfig() (mock, dry_run) if not supplied."""
    sink = get_active_sinks(sink_config or SinkConfig())

    triage = triage_stage(raw_input)
    if progress_callback:
        progress_callback("triage", triage)

    dup = duplicate_check_stage(triage, sink)
    if progress_callback:
        progress_callback("duplicate_check", dup)

    if dup["is_duplicate"]:
        sink_result = sink.link_duplicate(dup["related_ticket_id"], raw_input)
        return {**sink_result, "triage": triage, "duplicate_check": dup}

    assignment = assignment_stage(triage)
    if progress_callback:
        progress_callback("assignment", assignment)

    ticket_id = f"INC-{datetime.now().strftime('%H%M%S')}"
    ticket = {
        "ticket_id": ticket_id,
        "short_description": triage["short_description"],
        "category": triage["category"], "subcategory": triage["subcategory"],
        "priority": triage["priority"], "impact": triage["impact"], "urgency": triage["urgency"],
        "affected_system": triage["affected_system"], "assignment_group": assignment["assignment_group"],
        "status": "New", "created_at": datetime.now(timezone.utc).isoformat(), "raw_input": raw_input,
    }

    sink_result = sink.create(ticket)
    if progress_callback:
        progress_callback("create", sink_result)

    return sink_result
