"""
modules/ticket_id_map.py

Unchanged from the IT-Ticket-Orchestrator repo
(https://github.com/ImNorcal247/IT-Ticket-Orchestrator). Persistent
internal ticket ID -> external system ID mapping, used to post
duplicate-link comments on the correct real ticket.
"""

import json
import os

MAP_PATH = "id_map.json"


def _load() -> dict:
    if not os.path.exists(MAP_PATH):
        return {}
    with open(MAP_PATH) as f:
        return json.load(f)


def _save(data: dict):
    with open(MAP_PATH, "w") as f:
        json.dump(data, f, indent=2)


def get(internal_id: str) -> dict | None:
    return _load().get(internal_id)


def set(internal_id: str, sink: str, external_id: str, url: str | None = None, sys_id: str | None = None):
    data = _load()
    data[internal_id] = {"sink": sink, "external_id": external_id, "sys_id": sys_id, "url": url}
    _save(data)


def seed_if_missing(internal_id: str, sink: str, external_id: str, url: str | None = None, sys_id: str | None = None):
    data = _load()
    if internal_id not in data:
        data[internal_id] = {"sink": sink, "external_id": external_id, "sys_id": sys_id, "url": url}
        _save(data)
