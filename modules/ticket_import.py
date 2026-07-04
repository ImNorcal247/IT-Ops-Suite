"""
modules/ticket_import.py

Pulls tickets IN from third-party systems (or a CSV/XLSX upload) and
normalizes them into this app's tickets schema (source_entity, description,
category, priority, assigned_team, status, created_date, resolved_date,
resolution_hours), so the Dashboard can consolidate real ticket data instead
of only ever showing setup_sample_data.py's fixtures.

This is the read-in counterpart to modules/ticket_sinks.py (which pushes
newly-created tickets OUT to a single active backend for the Orchestrator).
Here, several sources can be configured at once, all feeding the same
consolidated tickets table — that's the whole point of "every ticket, from
every system, in one view."

Each external system's priority/status vocabulary is mapped into this app's
fixed set (Critical/High/Medium/Low, Open/In Progress/Resolved/Closed).
These mappings are reasonable defaults, not a guarantee for every possible
ServiceNow/Zendesk instance customization — adjust the *_PRIORITY_MAP /
*_STATUS_MAP dicts below if your instance uses non-standard values.
"""

import hashlib
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import pandas as pd
import requests

REQUIRED_UPLOAD_COLUMNS = {"description", "category", "priority", "assigned_team", "status"}
OPTIONAL_UPLOAD_COLUMNS = {"sys_id", "created_date", "resolved_date", "resolution_hours"}


# ── ServiceNow ───────────────────────────────────────────────────────────────

# Standard out-of-box ServiceNow incident values. Priority: 1=Critical,
# 2=High, 3=Moderate, 4=Low, 5=Planning. State: 1=New, 2=In Progress,
# 3=On Hold, 6=Resolved, 7=Closed, 8=Canceled.
SERVICENOW_PRIORITY_MAP = {"1": "Critical", "2": "High", "3": "Medium", "4": "Low", "5": "Low"}
SERVICENOW_STATE_MAP = {
    "1": "Open", "2": "In Progress", "3": "In Progress",
    "6": "Resolved", "7": "Closed", "8": "Closed",
}


def import_from_servicenow(instance: str, username: str, password: str) -> list[dict]:
    """Pulls the full incident history (not just active=true, unlike the
    Orchestrator's duplicate-check search) so the Dashboard can show
    resolved/closed tickets too."""
    rows = []
    offset = 0
    page_size = 200
    while True:
        resp = requests.get(
            f"https://{instance}.service-now.com/api/now/table/incident",
            auth=(username, password),
            headers={"Accept": "application/json"},
            params={
                "sysparm_limit": page_size,
                "sysparm_offset": offset,
                "sysparm_fields": "number,short_description,category,priority,state,"
                                  "assignment_group,opened_at,resolved_at,closed_at",
            },
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])
        if not results:
            break
        for inc in results:
            rows.append(_normalize_servicenow_incident(inc))
        if len(results) < page_size:
            break
        offset += page_size
    return rows


def _normalize_servicenow_incident(inc: dict) -> dict:
    opened = _parse_datetime(inc.get("opened_at"))
    resolved = _parse_datetime(inc.get("resolved_at") or inc.get("closed_at"))
    return {
        "sys_id": inc.get("number"),
        "description": inc.get("short_description", ""),
        "category": inc.get("category") or "Application",
        "priority": SERVICENOW_PRIORITY_MAP.get(str(inc.get("priority")), "Medium"),
        "assigned_team": _resolve_link_display(inc.get("assignment_group")) or "Unassigned",
        "status": SERVICENOW_STATE_MAP.get(str(inc.get("state")), "Open"),
        "created_date": opened.date().isoformat() if opened else None,
        "resolved_date": resolved.date().isoformat() if resolved else None,
        "resolution_hours": _hours_between(opened, resolved),
    }


def _resolve_link_display(value) -> str | None:
    """ServiceNow reference fields come back either as a plain string or as
    {"display_value": ..., "link": ...} depending on sysparm_display_value —
    handle both without requiring the caller to set that param."""
    if isinstance(value, dict):
        return value.get("display_value")
    return value or None


# ── ClickUp ──────────────────────────────────────────────────────────────────

CLICKUP_PRIORITY_MAP = {"1": "Critical", "2": "High", "3": "Medium", "4": "Low"}
CLICKUP_CLOSED_KEYWORDS = ("closed", "done", "resolved", "complete")
CLICKUP_PROGRESS_KEYWORDS = ("progress", "review", "testing")


def import_from_clickup(token: str, list_id: str) -> list[dict]:
    rows = []
    page = 0
    while True:
        resp = requests.get(
            f"https://api.clickup.com/api/v2/list/{list_id}/task",
            headers={"Authorization": token},
            params={"archived": "false", "include_closed": "true", "page": page},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        tasks = data.get("tasks", [])
        if not tasks:
            break
        rows.extend(_normalize_clickup_task(t) for t in tasks)
        if data.get("last_page", True):
            break
        page += 1
    return rows


def _normalize_clickup_task(task: dict) -> dict:
    status_name = (task.get("status", {}) or {}).get("status", "").lower()
    if any(k in status_name for k in CLICKUP_CLOSED_KEYWORDS):
        status = "Closed" if "closed" in status_name else "Resolved"
    elif any(k in status_name for k in CLICKUP_PROGRESS_KEYWORDS):
        status = "In Progress"
    else:
        status = "Open"

    priority = (task.get("priority") or {}).get("id")
    created = _parse_epoch_ms(task.get("date_created"))
    resolved = _parse_epoch_ms(task.get("date_closed"))
    tags = [tag["name"] for tag in task.get("tags", [])]

    return {
        "sys_id": task.get("id"),
        "description": task.get("name", ""),
        "category": (tags[0].title() if tags else "Application"),
        "priority": CLICKUP_PRIORITY_MAP.get(str(priority), "Medium"),
        "assigned_team": ", ".join(a.get("username", "") for a in task.get("assignees", [])) or "Unassigned",
        "status": status,
        "created_date": created.date().isoformat() if created else None,
        "resolved_date": resolved.date().isoformat() if resolved else None,
        "resolution_hours": _hours_between(created, resolved),
    }


# ── Zendesk ──────────────────────────────────────────────────────────────────

ZENDESK_PRIORITY_MAP = {"urgent": "Critical", "high": "High", "normal": "Medium", "low": "Low"}
ZENDESK_STATUS_MAP = {
    "new": "Open", "open": "Open", "pending": "In Progress", "hold": "In Progress",
    "solved": "Resolved", "closed": "Closed",
}


def test_zendesk_connection(subdomain: str, email: str, token: str) -> tuple[bool, str]:
    try:
        resp = requests.get(
            f"https://{subdomain}.zendesk.com/api/v2/users/me.json",
            auth=(f"{email}/token", token),
            timeout=10,
        )
        if resp.status_code == 200:
            name = resp.json().get("user", {}).get("name", "unknown")
            return True, f"Connected as {name}"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.exceptions.RequestException as e:
        return False, str(e)


def import_from_zendesk(subdomain: str, email: str, token: str) -> list[dict]:
    auth = (f"{email}/token", token)
    groups = _zendesk_group_names(subdomain, auth)

    rows = []
    url = f"https://{subdomain}.zendesk.com/api/v2/tickets.json"
    while url:
        resp = requests.get(url, auth=auth, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        for ticket in data.get("tickets", []):
            rows.append(_normalize_zendesk_ticket(ticket, groups))
        url = data.get("next_page")
    return rows


def _zendesk_group_names(subdomain: str, auth: tuple) -> dict:
    try:
        resp = requests.get(f"https://{subdomain}.zendesk.com/api/v2/groups.json", auth=auth, timeout=10)
        resp.raise_for_status()
        return {g["id"]: g["name"] for g in resp.json().get("groups", [])}
    except requests.exceptions.RequestException:
        return {}


def _normalize_zendesk_ticket(ticket: dict, groups: dict) -> dict:
    status = ticket.get("status", "").lower()
    created = _parse_datetime(ticket.get("created_at"))
    updated = _parse_datetime(ticket.get("updated_at"))
    is_done = status in ("solved", "closed")

    return {
        "sys_id": str(ticket.get("id")),
        "description": ticket.get("subject") or (ticket.get("description") or "")[:200],
        "category": (ticket.get("type") or "Application").title(),
        "priority": ZENDESK_PRIORITY_MAP.get(ticket.get("priority") or "", "Medium"),
        "assigned_team": groups.get(ticket.get("group_id"), "Unassigned"),
        "status": ZENDESK_STATUS_MAP.get(status, "Open"),
        "created_date": created.date().isoformat() if created else None,
        "resolved_date": updated.date().isoformat() if (is_done and updated) else None,
        "resolution_hours": _hours_between(created, updated) if is_done else None,
    }


# ── CSV / XLSX upload ─────────────────────────────────────────────────────────

def import_from_dataframe(df: pd.DataFrame, source_entity: str) -> list[dict]:
    columns = {c.strip().lower() for c in df.columns}
    missing = REQUIRED_UPLOAD_COLUMNS - columns
    if missing:
        raise ValueError(
            f"Missing required column(s): {', '.join(sorted(missing))}. "
            f"Expected at least: {', '.join(sorted(REQUIRED_UPLOAD_COLUMNS))}."
        )

    df = df.rename(columns={c: c.strip().lower() for c in df.columns})
    rows = []
    for _, r in df.iterrows():
        row = {
            "description": str(r.get("description", "")).strip(),
            "category": str(r.get("category", "")).strip() or "Application",
            "priority": str(r.get("priority", "")).strip() or "Medium",
            "assigned_team": str(r.get("assigned_team", "")).strip() or "Unassigned",
            "status": str(r.get("status", "")).strip() or "Open",
            "created_date": _clean_upload_date(r.get("created_date")),
            "resolved_date": _clean_upload_date(r.get("resolved_date")),
            "resolution_hours": float(r["resolution_hours"]) if pd.notna(r.get("resolution_hours")) else None,
        }
        raw_sys_id = r.get("sys_id")
        row["sys_id"] = str(raw_sys_id).strip() if pd.notna(raw_sys_id) and str(raw_sys_id).strip() else _synth_sys_id(row, source_entity)
        rows.append(row)
    return rows


TEMPLATE_COLUMNS = [
    # (header, is_required, example_1, example_2)
    ("sys_id", False, "", ""),
    ("description", True, "Printer jam in accounting", "VPN gateway flapping"),
    ("category", True, "Hardware", "Network"),
    ("priority", True, "Low", "Critical"),
    ("assigned_team", True, "Desktop Support", "Network Operations"),
    ("status", True, "Open", "In Progress"),
    ("created_date", False, "2026-06-01", "2026-06-03"),
    ("resolved_date", False, "", ""),
    ("resolution_hours", False, "", ""),
]
VALID_PRIORITIES = ["Critical", "High", "Medium", "Low"]
VALID_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]

REQUIRED_FILL = PatternFill(start_color="FFE0F2F1", end_color="FFE0F2F1", fill_type="solid")
HEADER_FONT = Font(bold=True)


def build_upload_template() -> BytesIO:
    """Generates the downloadable .xlsx template from the same column
    contract import_from_dataframe() validates against, so the two can't
    drift out of sync with each other."""
    wb = Workbook()

    ws = wb.active
    ws.title = "Tickets"
    for col_idx, (header, required, ex1, ex2) in enumerate(TEMPLATE_COLUMNS, start=1):
        # Header text is exactly what import_from_dataframe() expects — no
        # decoration like a "*" suffix — so this file can be re-uploaded
        # as-is (after replacing the two example rows with real data)
        # without editing column headers first. "Required" is conveyed by
        # styling only.
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = HEADER_FONT
        if required:
            cell.fill = REQUIRED_FILL
        ws.cell(row=2, column=col_idx, value=ex1)
        ws.cell(row=3, column=col_idx, value=ex2)
        ws.column_dimensions[get_column_letter(col_idx)].width = max(14, len(header) + 4)
    ws.freeze_panes = "A2"

    instructions = wb.create_sheet("Instructions")
    lines = [
        ("Required columns (highlighted in the Tickets sheet):", True),
        (", ".join(h for h, req, *_ in TEMPLATE_COLUMNS if req), False),
        ("", False),
        ("Optional columns:", True),
        (", ".join(h for h, req, *_ in TEMPLATE_COLUMNS if not req), False),
        ("", False),
        ("Valid priority values:", True),
        (", ".join(VALID_PRIORITIES), False),
        ("", False),
        ("Valid status values (others are accepted but won't match dashboard filters as cleanly):", True),
        (", ".join(VALID_STATUSES), False),
        ("", False),
        ("sys_id:", True),
        ("Optional — leave blank and one will be generated from the row's content. "
         "Re-uploading a file with the same sys_id values updates those tickets instead "
         "of creating duplicates.", False),
        ("", False),
        ("category / assigned_team:", True),
        ("Free text — use whatever values match your organization. New categories show up "
         "automatically on the Dashboard's category chart.", False),
    ]
    for row_idx, (text, bold) in enumerate(lines, start=1):
        cell = instructions.cell(row=row_idx, column=1, value=text)
        cell.font = Font(bold=bold)
        cell.alignment = Alignment(wrap_text=True)
    instructions.column_dimensions["A"].width = 100

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def _clean_upload_date(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        return value.strip() or None
    parsed = _parse_datetime(str(value))
    return parsed.date().isoformat() if parsed else str(value)


def _synth_sys_id(row: dict, source_entity: str) -> str:
    """No natural external ID in a spreadsheet — hash the content so
    re-uploading the exact same row upserts instead of duplicating, while
    genuinely different rows still get distinct ids."""
    basis = "|".join([source_entity, row["description"], row["category"], str(row.get("created_date"))])
    return "upload_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


# ── Shared helpers ───────────────────────────────────────────────────────────

def _parse_datetime(value) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[: len(fmt) + 2], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_epoch_ms(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000)
    except (ValueError, OSError):
        return None


def _hours_between(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    return round((end - start).total_seconds() / 3600, 1)


# ── Persistence ──────────────────────────────────────────────────────────────

UPSERT_SQL = """
INSERT INTO tickets
    (sys_id, source_entity, description, category, priority, assigned_team,
     status, created_date, resolved_date, resolution_hours)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(sys_id, source_entity) DO UPDATE SET
    description=excluded.description, category=excluded.category,
    priority=excluded.priority, assigned_team=excluded.assigned_team,
    status=excluded.status, created_date=excluded.created_date,
    resolved_date=excluded.resolved_date, resolution_hours=excluded.resolution_hours
"""


def upsert_tickets(conn, rows: list[dict], source_entity: str) -> int:
    """conn is a caller-owned sqlite3 connection (console/db.py's
    get_connection()) — this module doesn't own the connection lifecycle."""
    for row in rows:
        conn.execute(UPSERT_SQL, (
            row["sys_id"], source_entity, row["description"], row["category"],
            row["priority"], row["assigned_team"], row["status"],
            row.get("created_date"), row.get("resolved_date"), row.get("resolution_hours"),
        ))
    conn.commit()
    return len(rows)
