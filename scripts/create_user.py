"""
scripts/create_user.py

Seed a console login user. There's no signup screen (the design handoff
never had one) — operators are created manually with this CLI.

Usage:
    python scripts/create_user.py --email you@company.com --name "Alex Rivera" --role "IT Operations"
"""

import argparse
import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from console.auth import hash_password
from console.db import ensure_users_table, get_connection


def main():
    parser = argparse.ArgumentParser(description="Create or update a console login user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="Full name shown in the sidebar")
    parser.add_argument("--role", default="IT Operations")
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords don't match.")
        sys.exit(1)
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)

    ensure_users_table()
    password_hash = hash_password(password)
    conn = get_connection()
    try:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (args.email,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE users SET password_hash = ?, full_name = ?, role = ? WHERE email = ?",
                (password_hash, args.name, args.role, args.email),
            )
            print(f"Updated existing user {args.email}.")
        else:
            conn.execute(
                "INSERT INTO users (email, password_hash, full_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (args.email, password_hash, args.name, args.role, datetime.now(timezone.utc).isoformat()),
            )
            print(f"Created user {args.email}.")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
