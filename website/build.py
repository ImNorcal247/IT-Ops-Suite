"""
website/build.py

Static site generator for the IT Ops Suite marketing site. Renders the
Jinja2 templates in templates/ (ported from the Claude Design handoff in
"Repository website setup/design_handoff_it_ops_suite_website/") into
plain static HTML in dist/, and copies static/ alongside them.

Usage:
    python website/build.py
    python -m http.server 8000 --directory website/dist   # preview
"""

import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

SITE_DIR = Path(__file__).parent
TEMPLATES_DIR = SITE_DIR / "templates"
STATIC_DIR = SITE_DIR / "static"
DIST_DIR = SITE_DIR / "dist"

GITHUB_URL = "https://github.com/ImNorcal247/IT-Ops-Suite"
CONTACT_EMAIL = "nickpwaller@gmail.com"

# (output filename, template, active nav key, <title>, meta description)
PAGES = [
    ("Home.html", "home.html", "home",
     "IT operations, running on autopilot",
     "AI-powered IT operations suite: ticket dashboard, text-to-SQL, policy Q&A, "
     "incident classification, and multi-agent ticket routing."),
    ("Ticket-Dashboard.html", "ticket-dashboard.html", "dashboard",
     "Ticket Dashboard",
     "See every ticket, from every system, in one filterable, live-updating view."),
    ("Ask-Your-Data.html", "ask-your-data.html", "ask-data",
     "Ask Your Data",
     "Ask a plain-English question about your ticket data and get a straight answer — no SQL required."),
    ("Policy-QA.html", "policy-qa.html", "policy-qa",
     "Policy Q&A",
     "Policy answers grounded only in your real IT policy documents, with sources and a confidence rating."),
    ("Incident-Classifier.html", "incident-classifier.html", "classifier",
     "Incident Classifier",
     "Instant, structured incident triage: category, priority, owning team, and next actions."),
    ("Ticket-Orchestrator.html", "ticket-orchestrator.html", "orchestrator",
     "Ticket Orchestrator",
     "Submit a problem in one line — triaged, deduped, routed, and filed automatically."),
]


def asset(path: str) -> str:
    """All pages live flat in dist/, so a bare relative path works
    regardless of what subpath the site is eventually hosted under."""
    return path


def build():
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    env.globals["asset"] = asset
    env.globals["github_url"] = GITHUB_URL
    env.globals["contact_email"] = CONTACT_EMAIL

    for out_name, template_name, active, title, description in PAGES:
        template = env.get_template(template_name)
        html = template.render(active=active, page_title=title, page_description=description)
        (DIST_DIR / out_name).write_text(html, encoding="utf-8")
        print(f"built {out_name}")

    shutil.copytree(STATIC_DIR, DIST_DIR / "static")
    # index.html so the site works at a bare host root too
    shutil.copy(DIST_DIR / "Home.html", DIST_DIR / "index.html")
    print(f"\nDone. Output in {DIST_DIR}")


if __name__ == "__main__":
    build()
