"""
modules/ticket_sinks.py

Unchanged from the IT-Ticket-Orchestrator repo
(https://github.com/ImNorcal247/IT-Ticket-Orchestrator). Pluggable
backends (Mock / ClickUp / ServiceNow), each implementing search_existing()
for live duplicate checking and create() for writing new tickets.
"""

import os
import re
import json
import requests
import ticket_id_map


class TicketSink:
    def search_existing(self, category: str | None = None) -> list[dict]:
        raise NotImplementedError

    def create(self, ticket: dict) -> dict:
        raise NotImplementedError

    def link_duplicate(self, related_ticket_id: str, raw_input: str) -> dict:
        return {"action": "linked_to_existing", "linked_ticket_id": related_ticket_id, "note": "no comment posted (default behavior)"}


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


CLICKUP_PRIORITY_MAP = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}

CATEGORY_TO_LIST = {
    "Application": os.environ.get("CLICKUP_LIST_APPLICATION", ""),
    "Network": os.environ.get("CLICKUP_LIST_NETWORK", ""),
    "Hardware": os.environ.get("CLICKUP_LIST_HARDWARE", ""),
    "Access": os.environ.get("CLICKUP_LIST_ACCESS", ""),
    "Database": os.environ.get("CLICKUP_LIST_DATABASE", ""),
    "Security": os.environ.get("CLICKUP_LIST_SECURITY", ""),
}
LIST_TO_CATEGORY = {v: k for k, v in CATEGORY_TO_LIST.items() if v}
TICKET_ID_PREFIX_RE = re.compile(r"^\[(INC-\d+)\]\s*(.*)$")


class ClickUpSink(TicketSink):
    def __init__(self, dry_run: bool = False):
        self.token = os.environ.get("CLICKUP_API_TOKEN", "")
        self.default_list_id = os.environ.get("CLICKUP_LIST_ID_DEFAULT", "")
        self.dry_run = dry_run
        if not self.token:
            raise RuntimeError("CLICKUP_API_TOKEN is not set. search_existing() requires a real token even in dry-run mode.")

    def _lists_to_search(self, category: str | None) -> list[str]:
        ids = set(filter(None, CATEGORY_TO_LIST.values()))
        if self.default_list_id:
            ids.add(self.default_list_id)
        ordered = list(ids)
        target = CATEGORY_TO_LIST.get(category) if category else None
        if target and target in ordered:
            ordered.remove(target)
            ordered.insert(0, target)
        return ordered

    def search_existing(self, category: str | None = None) -> list[dict]:
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
                results.append({
                    "id": internal_id, "title": title,
                    "category": LIST_TO_CATEGORY.get(list_id, "Unknown"),
                    "subcategory": ", ".join(tag["name"] for tag in task.get("tags", [])) or "Unknown",
                    "status": task.get("status", {}).get("status", "unknown"),
                    "created": task.get("date_created", ""),
                })
        return results

    def create(self, ticket: dict) -> dict:
        list_id = CATEGORY_TO_LIST.get(ticket["category"]) or self.default_list_id
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
        mapping = ticket_id_map.get(related_ticket_id)
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


SERVICENOW_PRIORITY_MAP = {"P1": "1", "P2": "2", "P3": "3", "P4": "4"}
SERVICENOW_IMPACT_MAP = {"High": "1", "Medium": "2", "Low": "3"}
SERVICENOW_URGENCY_MAP = {"High": "1", "Medium": "2", "Low": "3"}


class ServiceNowSink(TicketSink):
    def __init__(self, dry_run: bool = False):
        self.instance = os.environ.get("SERVICENOW_INSTANCE", "")
        self.username = os.environ.get("SERVICENOW_USERNAME", "")
        self.password = os.environ.get("SERVICENOW_PASSWORD", "")
        self.dry_run = dry_run
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
        mapping = ticket_id_map.get(related_ticket_id)
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


def get_sink() -> TicketSink:
    sink_type = os.environ.get("TICKET_SINK", "mock").lower()
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    if sink_type == "clickup":
        return ClickUpSink(dry_run=dry_run)
    elif sink_type == "servicenow":
        return ServiceNowSink(dry_run=dry_run)
    else:
        return MockSink()
