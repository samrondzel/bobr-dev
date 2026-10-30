"""Local, trusted-operator mock eID enrollment; NOT a recipient signup form."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import connect, init_db
from app.mock_issuer import register_identity


def main() -> None:
    p = argparse.ArgumentParser(description="Provision a synthetic person in mock identity issuer")
    p.add_argument("command", choices=["enroll", "list"])
    p.add_argument("--name", help="Synthetic identity name, for enroll")
    args = p.parse_args()
    init_db()
    with connect() as cx:
        if args.command == "list":
            for row in cx.execute("SELECT subject_id,display_name,enabled FROM mock_issuer_identities ORDER BY created_at"):
                print(f'{row["subject_id"]}\t{row["display_name"]}\tactive={bool(row["enabled"])}')
            return
        if not args.name:
            p.error("--name required for enroll")
        try:
            subject, code = register_identity(cx, args.name)
        except ValueError as exc:
            p.error(str(exc))
        print("Synthetic issuer record created (not a PGK user account).")
        print("Subject ID:", subject)
        print("One-time display of mock credential:", code)
        print("Share the mock credential only with the designated synthetic test recipient.")


if __name__ == "__main__":
    main()
