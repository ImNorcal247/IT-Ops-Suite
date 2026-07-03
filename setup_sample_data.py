"""
setup_sample_data.py

Unchanged from the IT-Ticket-Dashboard repo
(https://github.com/ImNorcal247/IT-Ticket-Dashboard). Generates a demo
SQLite database simulating a multi-entity ticket consolidation scenario.
Run once before starting the app: python setup_sample_data.py
"""

import sqlite3
import random
from datetime import datetime, timedelta

conn = sqlite3.connect("it_tickets.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sys_id TEXT UNIQUE,
    source_entity TEXT,
    description TEXT,
    category TEXT,
    priority TEXT,
    assigned_team TEXT,
    status TEXT,
    created_date TEXT,
    resolved_date TEXT,
    resolution_hours REAL
)
""")

entities = {
    "Acme Corp HQ": ["Network Operations", "Security Team", "Desktop Support", "DBA Team"],
    "West Region Franchise": ["IT Support", "Network Team"],
    "Riverside Acquisition": ["Help Desk", "Infrastructure"],
}

categories = ["Network", "Security", "Hardware", "Software", "Email", "Access Management", "Database"]
priorities = ["Critical", "High", "Medium", "Low"]
statuses = ["Closed", "Open", "In Progress", "Pending"]
descriptions = [
    "VPN connectivity issue", "Server disk failure warning", "Phishing email reported",
    "Password reset request", "Database replication lag", "Office Wi-Fi outage",
    "Outlook crashing on launch", "Account lockout", "PCI compliance scan failure",
    "Slow application performance", "Printer offline", "SSL certificate expired",
]

random.seed(42)
records = []
base_date = datetime(2026, 4, 1)
counter = 0

for entity, teams in entities.items():
    num_tickets = {"Acme Corp HQ": 70, "West Region Franchise": 30, "Riverside Acquisition": 20}[entity]
    for _ in range(num_tickets):
        created = base_date + timedelta(days=random.randint(0, 75), hours=random.randint(0, 23))
        status = random.choices(statuses, weights=[60, 15, 15, 10])[0]
        resolved = None
        resolution_hours = None
        if status == "Closed":
            resolved = created + timedelta(hours=random.uniform(0.5, 48))
            resolution_hours = round((resolved - created).total_seconds() / 3600, 2)
        records.append({
            "sys_id": f"sim{counter:04d}",
            "source_entity": entity,
            "description": random.choice(descriptions),
            "category": random.choice(categories),
            "priority": random.choices(priorities, weights=[10, 25, 40, 25])[0],
            "assigned_team": random.choice(teams),
            "status": status,
            "created_date": created.strftime("%Y-%m-%d"),
            "resolved_date": resolved.strftime("%Y-%m-%d") if resolved else None,
            "resolution_hours": resolution_hours,
        })
        counter += 1

cursor.executemany("""
INSERT OR REPLACE INTO tickets
(sys_id, source_entity, description, category, priority, assigned_team, status, created_date, resolved_date, resolution_hours)
VALUES (:sys_id, :source_entity, :description, :category, :priority, :assigned_team, :status, :created_date, :resolved_date, :resolution_hours)
""", records)

conn.commit()
conn.close()
print(f"Created {len(records)} sample tickets across {len(entities)} source entities")
