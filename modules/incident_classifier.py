"""
modules/incident_classifier.py

Structured IT incident classification, adapted from the standalone
it-incident-classifier repo
(https://github.com/ImNorcal247/it-incident-classifier) for import into
a Streamlit tab. Logic is unchanged from the original classifier.py —
only the CLI loop and print statements were stripped out, since the UI
now handles input/output.
"""

import json
import os

import anthropic

SYSTEM_PROMPT = """You are an expert IT incident classifier with 10+ years of enterprise IT operations experience.

When given an incident description, classify it and return ONLY a JSON object with this exact structure:
{
  "category": "",
  "subcategory": "",
  "priority": "",
  "assigned_team": "",
  "estimated_resolution_time": "",
  "similar_incidents": [],
  "immediate_actions": [],
  "escalate_if": ""
}

Category options: Network, Security, Hardware, Software, Email, Access Management, Data, Telephony, Other
Priority options: Critical, High, Medium, Low

Priority guidelines:
- Critical: Business stopped, revenue impact, security breach, 50+ users affected
- High: Major function degraded, 10-50 users affected
- Medium: Single user or non-critical system affected
- Low: Cosmetic issue, workaround available

Examples:
User: "No one in the office can access the internet or internal systems"
Output: {"category": "Network", "subcategory": "Total Outage", "priority": "Critical", "assigned_team": "Network Operations", "estimated_resolution_time": "1-4 hours", "similar_incidents": ["ISP outage", "Core switch failure", "Firewall misconfiguration"], "immediate_actions": ["Check ISP status page", "Verify core switch uptime", "Check firewall logs", "Initiate incident bridge"], "escalate_if": "Not resolved within 30 minutes or if core infrastructure confirmed down"}

User: "One user can't log into Salesforce"
Output: {"category": "Access Management", "subcategory": "Application Login Failure", "priority": "Low", "assigned_team": "Desktop Support", "estimated_resolution_time": "30 minutes", "similar_incidents": ["Expired password", "MFA token issue", "Account lockout"], "immediate_actions": ["Verify account status in Salesforce admin", "Check if MFA is configured", "Reset password if needed"], "escalate_if": "Multiple users reporting same issue with Salesforce"}"""


def classify_incident(description: str, context: str = "") -> dict:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    full_input = description
    if context:
        full_input = f"Incident: {description}\n\nAdditional context: {context}"

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": full_input}],
    )

    raw = message.content[0].text
    start = raw.find("{")
    end = raw.rfind("}") + 1
    json_str = raw[start:end]
    return json.loads(json_str)
