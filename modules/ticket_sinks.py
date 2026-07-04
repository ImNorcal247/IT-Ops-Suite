"""
modules/ticket_sinks.py

Pluggable ticketing backends. Supports four modes via SinkConfig.mode:
"mock" | "clickup" | "servicenow" | "both"

"both" uses MultiSink to fan writes out to ClickUp AND ServiceNow
simultaneously, and merges duplicate-check reads across both.

Config (mode, dry_run, credentials) is passed explicitly via SinkConfig
rather than read from os.environ — the original Streamlit-only version
read process-global env vars, which isn't safe once this runs behind a
real multi-request server where Settings can be read/written per request
without depending on process env. Callers (e.g. a web Settings endpoint)
own a single shared SinkConfig instance and pass it in explicitly.
"""

import re
import json
from dataclasses import dataclass, field

import requests

import modules.ticket_id_map as ticket_id_map


@dataclass
class SinkConfig:
    mode: str = "mock"
    dry_run: bool = True
    clickup_token: str = ""
    clickup_default_list: str = ""
    clickup_lists: dict = field(default_factory=dict)  # {"Application": "list_id", ...}
    servicenow_instance: str = ""
    servicenow_username: str = ""
    servicenow_password: str = ""


# ── Sink interface ──────────────────────────────────────────────────────────

class TicketSink:
    def search_existing(self, category: str | None = None) -> list[dict]:
        raise NotImplementedError

    def create(self, ticket: dict) -> dict:
        raise NotImplementedError

    def link_duplicate(self, related_ticket_id: str, raw_input: str) -> dict:
        return {"action": "linked_to_existing", "linked_ticket_id": related_ticket_id, "note": "no comment posted (default behavior)"}


# ── Mock sink ────────────────────────────────────────────────────────────────

class MockSink(TicketSink):
    _tickets = [
        {"id": "INC-4821", "title": "Payment gateway timeouts — checkout flow", "category": "Application", "subcategory": "Payments", "status": "open", "created": "2025-06-29 08:14 UTC"},
        {"id": "INC-4798", "title": "Elevated latency after payment service v2.4.1 deploy", "category": "Application", "subcategory": "Payments", "status": "investigating", "created": "2025-06-14 04:05 UTC"},
        {"id": "INC-5102", "title": "VPN connection drops for remote users", "category": "Network", "subcategory": "VPN", "status": "open", "created": "2025-06-28 14:00 UTC"},
    ]

    def search_existing(self, category: str | None = None) -> list[dict]:
        results = [t for t in self._tickets if t["status"] != "resolved"]
        if category:
            results = [t for t in results if t["category"] == category] + [t for t in results if t["category"] != category]
        return results

    def create(self, ticket: dict) -> dict:
        self._tickets.append({
            "id": ticket["ticket_id"], "title": ticket["short_description"],
            "category": ticket["category"], "subcategory": ticket["subcategory"],
            "status": "open", "created": ticket["created_at"],
        })
        return {**ticket, "sink": "mock", "external_url": None}


# ── ClickUp sink ─────────────────────────────────────────────────────────────

CLICKUP_PRIORITY_MAP = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
TICKET_ID_PREFIX_RE = re.compile(r"^\[(INC-\d+)\]\s*(.*)$")


def get_category_to_list(config: SinkConfig) -> dict:
    return dict(config.clickup_lists)


def get_list_to_category(config: SinkConfig) -> dict:
    return {v: k for k, v in get_category_to_list(config).items() if v}


def test_clickup_connection(token: str) -> tuple[bool, str]:
    """Lightweight auth check for the Settings tab's Test Connection button."""
    try:
        resp = requests.get("https://api.clickup.com/api/v2/user", headers={"Authorization": token}, timeout=10)
        if resp.status_code == 200:
            username = resp.json().get("user", {}).get("username", "unknown")
            return True, f"Connected as {username}"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.exceptions.RequestException as e:
        return False, str(e)


class ClickUpSink(TicketSink):
    def __init__(self, config: SinkConfig):
        self.config = config
        self.token = config.clickup_token
        self.default_list_id = config.clickup_default_list
        self.dry_run = config.dry_run
        if not self.token:
            raise RuntimeError("CLICKUP_API_TOKEN is not set. search_existing() requires a real token even in dry-run mode.")

    def _lists_to_search(self, category: str | None) -> list[str]:
        category_to_list = get_category_to_list(self.config)
        ids = set(filter(None, category_to_list.values()))
        if self.default_list_id:
            ids.add(self.default_list_id)
        ordered = list(ids)
        target = category_to_list.get(category) if category else None
        if target and target in ordered:
            ordered.remove(target)
            ordered.insert(0, target)
        return ordered

    def search_existing(self, category: str | None = None) -> list[dict]:
        list_to_category = get_list_to_category(self.config)
        results = []
        for list_id in self._lists_to_search(category):
            try:
                resp = requests.get(
                    f"https://api.clickup.com/api/v2/list/{list_id}/task",
                    headers={"Authorization": self.token},
                    params={"archived": "false", "include_closed": "false"},
                    timeout=10,
                )
                resp.raise_for_status()
            except requests.exceptions.RequestException as e:
                print(f"  ⚠️  [ClickUp] search_existing failed for list {list_id}: {e}")
                continue
            for task in resp.json().get("tasks", []):
                name = task.get("name", "")
                m = TICKET_ID_PREFIX_RE.match(name)
                internal_id, title = (m.group(1), m.group(2)) if m else (task["id"], name)
                if m:
                    # This task was created by this pipeline — backfill the
                    # ID map opportunistically so a future duplicate match
                    # against it can post a real comment, same as ServiceNow
                    # already does during its own search_existing().
                    ticket_id_map.seed_if_missing(internal_id, "clickup", task["id"], url=task.get("url"))
                results.append({
                    "id": internal_id, "title": title,
                    "category": list_to_category.get(list_id, "Unknown"),
                    "subcategory": ", ".join(tag["name"] for tag in task.get("tags", [])) or "Unknown",
                    "status": task.get("status", {}).get("status", "unknown"),
                    "created": task.get("date_created", ""),
                })
        return results

    def create(self, ticket: dict) -> dict:
        category_to_list = get_category_to_list(self.config)
        list_id = category_to_list.get(ticket["category"]) or self.default_list_id
        if not list_id:
            raise RuntimeError(f"No ClickUp List ID configured for category '{ticket['category']}' and no CLICKUP_LIST_ID_DEFAULT set.")

        payload = {
            "name": f"[{ticket['ticket_id']}] {ticket['short_description']}",
            "description": (
                f"**Category:** {ticket['category']} / {ticket['subcategory']}\n"
                f"**Impact:** {ticket['impact']}  |  **Urgency:** {ticket['urgency']}\n"
                f"**Affected system:** {ticket['affected_system']}\n"
                f"**Assignment group (source pipeline):** {ticket['assignment_group']}\n\n"
                f"**Original report:**\n{ticket['raw_input']}"
            ),
            "priority": CLICKUP_PRIORITY_MAP.get(ticket["priority"], 3),
            "tags": [ticket["category"].lower(), ticket["subcategory"].lower()],
        }

        if self.dry_run:
            return {**ticket, "sink": "clickup", "external_url": "(dry run — no real ticket created)"}

        resp = requests.post(
            f"https://api.clickup.com/api/v2/list/{list_id}/task",
            headers={"Authorization": self.token, "Content-Type": "application/json"},
            json=payload, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        external_id = data.get("id")
        external_url = data.get("url")
        ticket_id_map.set(ticket["ticket_id"], "clickup", external_id, url=external_url)
        return {**ticket, "sink": "clickup", "external_id": external_id, "external_url": external_url}

    def link_duplicate(self, related_ticket_id: str, raw_input: str) -> dict:
        mapping = ticket_id_map.get(related_ticket_id, sink="clickup")
        if not mapping or not mapping.get("external_id"):
            return {"action": "linked_to_existing", "linked_ticket_id": related_ticket_id, "sink": "clickup", "comment_posted": False}

        task_id = mapping["external_id"]
        comment_text = f"New report received, linked as duplicate by the triage agent:\n\n\"{raw_input}\""

        if self.dry_run:
            return {"action": "linked_to_existing", "linked_ticket_id": related_ticket_id, "sink": "clickup", "comment_posted": "dry_run"}

        resp = requests.post(
            f"https://api.clickup.com/api/v2/task/{task_id}/comment",
            headers={"Authorization": self.token, "Content-Type": "application/json"},
            json={"comment_text": comment_text}, timeout=10,
        )
        resp.raise_for_status()
        return {"action": "linked_to_existing", "linked_ticket_id": related_ticket_id, "sink": "clickup", "comment_posted": True}


# ── ServiceNow sink ──────────────────────────────────────────────────────────

SERVICENOW_PRIORITY_MAP = {"P1": "1", "P2": "2", "P3": "3", "P4": "4"}
SERVICENOW_IMPACT_MAP = {"High": "1", "Medium": "2", "Low": "3"}
SERVICENOW_URGENCY_MAP = {"High": "1", "Medium": "2", "Low": "3"}


def test_servicenow_connection(instance: str, username: str, password: str) -> tuple[bool, str]:
    try:
        resp = requests.get(
            f"https://{instance}.service-now.com/api/now/table/incident",
            auth=(username, password),
            headers={"Accept": "application/json"},
            params={"sysparm_limit": "1"},
            timeout=10,
        )
        if resp.status_code == 200:
            return True, "Connected successfully"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.exceptions.RequestException as e:
        return False, str(e)


class ServiceNowSink(TicketSink):
    def __init__(self, config: SinkConfig):
        self.instance = config.servicenow_instance
        self.username = config.servicenow_username
        self.password = config.servicenow_password
        self.dry_run = config.dry_run
        if not (self.instance and self.username and self.password):
            raise RuntimeError("SERVICENOW_INSTANCE, SERVICENOW_USERNAME, SERVICENOW_PASSWORD must all be set.")

    def search_existing(self, category: str | None = None) -> list[dict]:
        query = "active=true^stateNOT IN6,7"
        if category:
            query += f"^category={category}"
        try:
            resp = requests.get(
                f"https://{self.instance}.service-now.com/api/now/table/incident",
                auth=(self.username, self.password),
                headers={"Accept": "application/json"},
                params={"sysparm_query": query, "sysparm_limit": "50", "sysparm_fields": "number,sys_id,short_description,category,subcategory,state,sys_created_on"},
                timeout=10,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️  [ServiceNow] search_existing failed: {e}")
            return []

        results = []
        for inc in resp.json().get("result", []):
            results.append({
                "id": inc.get("number"), "title": inc.get("short_description", ""),
                "category": inc.get("category", "Unknown"), "subcategory": inc.get("subcategory", "Unknown"),
                "status": inc.get("state", "unknown"), "created": inc.get("sys_created_on", ""),
            })
            ticket_id_map.seed_if_missing(inc.get("number"), "servicenow", inc.get("number"), sys_id=inc.get("sys_id"))
        return results

    def create(self, ticket: dict) -> dict:
        payload = {
            "short_description": ticket["short_description"],
            "description": f"Affected system: {ticket['affected_system']}\n\nOriginal report:\n{ticket['raw_input']}",
            "category": ticket["category"], "subcategory": ticket["subcategory"],
            "priority": SERVICENOW_PRIORITY_MAP.get(ticket["priority"], "3"),
            "impact": SERVICENOW_IMPACT_MAP.get(ticket["impact"], "2"),
            "urgency": SERVICENOW_URGENCY_MAP.get(ticket["urgency"], "2"),
            "assignment_group": ticket["assignment_group"],
        }

        if self.dry_run:
            return {**ticket, "sink": "servicenow", "external_url": "(dry run — no real incident created)"}

        url = f"https://{self.instance}.service-now.com/api/now/table/incident"
        resp = requests.post(
            url, auth=(self.username, self.password),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            params={"sysparm_input_display_value": "true"}, json=payload, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("result", {})
        external_id = data.get("number")
        sys_id = data.get("sys_id")
        external_url = f"https://{self.instance}.service-now.com/nav_to.do?uri=incident.do?sys_id={sys_id}"
        ticket_id_map.set(ticket["ticket_id"], "servicenow", external_id, url=external_url, sys_id=sys_id)
        return {**ticket, "sink": "servicenow", "external_id": external_id, "external_url": external_url}

    def link_duplicate(self, related_ticket_id: str, raw_input: str) -> dict:
        mapping = ticket_id_map.get(related_ticket_id, sink="servicenow")
        if not mapping or not mapping.get("sys_id"):
            return {"action": "linked_to_existing", "linked_ticket_id": related_ticket_id, "sink": "servicenow", "comment_posted": False}

        sys_id = mapping["sys_id"]
        work_note = f"New report received, linked as duplicate by the triage agent:\n\n{raw_input}"

        if self.dry_run:
            return {"action": "linked_to_existing", "linked_ticket_id": related_ticket_id, "sink": "servicenow", "comment_posted": "dry_run"}

        url = f"https://{self.instance}.service-now.com/api/now/table/incident/{sys_id}"
        resp = requests.patch(
            url, auth=(self.username, self.password),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"work_notes": work_note}, timeout=10,
        )
        resp.raise_for_status()
        return {"action": "linked_to_existing", "linked_ticket_id": related_ticket_id, "sink": "servicenow", "comment_posted": True}


# ── MultiSink: dual-write to ClickUp + ServiceNow simultaneously ────────────

class MultiSink(TicketSink):
    """Fans writes out to every active sink and merges reads across them.
    Used when TICKET_MODE=both. Each underlying sink still owns its own
    credentials and API logic — this class only orchestrates calling them."""

    def __init__(self, sinks: dict[str, TicketSink]):
        self.sinks = sinks  # e.g. {"clickup": ClickUpSink(...), "servicenow": ServiceNowSink(...)}

    def search_existing(self, category: str | None = None) -> list[dict]:
        merged = []
        for sink in self.sinks.values():
            merged.extend(sink.search_existing(category=category))
        return merged

    def create(self, ticket: dict) -> dict:
        results = {}
        for name, sink in self.sinks.items():
            try:
                results[name] = sink.create(ticket)
            except requests.exceptions.RequestException as e:
                results[name] = {"error": str(e)}
        external_urls = {name: r.get("external_url") for name, r in results.items() if isinstance(r, dict)}
        return {**ticket, "sink": "both", "results": results, "external_urls": external_urls}

    def link_duplicate(self, related_ticket_id: str, raw_input: str) -> dict:
        mapping = ticket_id_map.get(related_ticket_id) or {}
        results = {}
        for name, sink in self.sinks.items():
            if name in mapping:
                results[name] = sink.link_duplicate(related_ticket_id, raw_input)
            else:
                results[name] = {"comment_posted": False, "reason": "no mapping for this backend yet"}
        return {"action": "linked_to_existing", "linked_ticket_id": related_ticket_id, "sink": "both", "results": results}


# ── Factory ──────────────────────────────────────────────────────────────────

def get_active_sinks(config: SinkConfig) -> TicketSink:
    """Given a SinkConfig, returns a single sink instance, or a MultiSink
    for dual-write ("both") mode. All returned objects implement the same
    TicketSink interface, so callers never need to know which mode is active."""
    mode = (config.mode or "mock").lower()

    if mode == "both":
        sinks = {}
        sinks["clickup"] = ClickUpSink(config)
        sinks["servicenow"] = ServiceNowSink(config)
        return MultiSink(sinks)
    elif mode == "clickup":
        return ClickUpSink(config)
    elif mode == "servicenow":
        return ServiceNowSink(config)
    else:
        return MockSink()


# Back-compat alias — the original single-sink API used this name.
get_sink = get_active_sinks
