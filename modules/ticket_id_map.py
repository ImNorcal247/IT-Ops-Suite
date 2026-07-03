"""
modules/ticket_id_map.py

Persistent internal ticket ID -> external system ID mapping.

CHANGED for dual-write support: an internal ticket (e.g. "INC-104800") can
now have a mapping entry for MORE THAN ONE backend at once — e.g. it might
exist as both a ClickUp task and a ServiceNow incident if TICKET_MODE=both.
Storage shape changed from a flat {internal_id: {...}} to a nested
{internal_id: {sink_name: {...}}}.

get(internal_id) with no sink returns the full per-sink dict.
get(internal_id, sink="clickup") returns just that sink's mapping, or None.
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


def get(internal_id: str, sink: str | None = None) -> dict | None:
    data = _load()
    entry = data.get(internal_id)
    if entry is None:
        return None
    if sink:
        return entry.get(sink)
    return entry  # {sink_name: {external_id, sys_id, url}, ...}


def set(internal_id: str, sink: str, external_id: str, url: str | None = None, sys_id: str | None = None):
    data = _load()
    entry = data.get(internal_id, {})
    entry[sink] = {"external_id": external_id, "sys_id": sys_id, "url": url}
    data[internal_id] = entry
    _save(data)


def seed_if_missing(internal_id: str, sink: str, external_id: str, url: str | None = None, sys_id: str | None = None):
    data = _load()
    entry = data.get(internal_id, {})
    if sink not in entry:
        entry[sink] = {"external_id": external_id, "sys_id": sys_id, "url": url}
        data[internal_id] = entry
        _save(data)
