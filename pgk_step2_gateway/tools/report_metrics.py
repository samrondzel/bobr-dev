"""Produce an honest hackathon scorecard from local SQLite and optional measurements.

Run from pgk_step2_gateway: python tools/report_metrics.py [--lab req_...] ...
Stdlib only; never exports credentials, patient contents, or bearer tokens.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import sqlite3

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
AUDIT_EVENTS = ("REQUEST_SENT", "LINK_OPENED", "IDENTITY_CHECKED", "ANSWER_SENT", "ANSWER_FILED", "MISDELIVERY_CAUGHT")


def cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=APP / "data" / "gateway.sqlite3")
    for key in ("lab", "rehab", "m1", "m2", "m3"):
        p.add_argument(f"--{key}", default=None, help="Actual req_... ID for this test")
    p.add_argument("--outside-seconds", type=float, help="Measured elapsed time from opening email to submission")
    p.add_argument("--installs", type=int, help="Number of installations required for outside participant")
    p.add_argument("--accounts", type=int, help="Number of PGK accounts created by outside participant")
    p.add_argument("--validator-log", type=Path, help="Text log of HL7 validator run on one transaction Bundle")
    p.add_argument("--out", type=Path, default=ROOT / "docs" / "METRICS_GENERATED.md")
    return p.parse_args()


def read_rows(cx: sqlite3.Connection, sql: str, *params):
    return cx.execute(sql, params).fetchall()


def get_one(cx: sqlite3.Connection, sql: str, *params):
    return cx.execute(sql, params).fetchone()


def request_state(cx: sqlite3.Connection, req_id: str | None) -> dict:
    if not req_id:
        return {"status": "NOT SUPPLIED"}
    row = get_one(cx, "SELECT request_id,document_kind,delivery_channel,delivery_status FROM requests WHERE request_id=?", req_id)
    if row is None:
        return {"status": "REQUEST NOT FOUND", "id": req_id}
    evs = read_rows(cx, "SELECT what,who,when_at,details_json FROM audit_events WHERE request_id=? ORDER BY rowid", req_id)
    events = []
    for e in evs:
        try:
            details = json.loads(e["details_json"] or "{}")
        except json.JSONDecodeError:
            details = {}
        events.append({"type": e["what"], "who": e["who"], "when": e["when_at"], "reason": details.get("reason")})
    filing = get_one(cx, "SELECT status,resource_refs_json FROM fhir_filings WHERE request_id=?", req_id)
    notifications = read_rows(cx, "SELECT status,body FROM matrix_notifications WHERE request_id=?", req_id)
    types = []
    if filing and filing["resource_refs_json"]:
        try:
            types = [r.split("/", 1)[0] for r in json.loads(filing["resource_refs_json"])]
        except (ValueError, AttributeError):
            types = []
    return {
        "status": "FOUND", "id": req_id,
        "kind": row["document_kind"], "channel": row["delivery_channel"],
        "delivery": row["delivery_status"],
        "filing": filing["status"] if filing else "not filed",
        "types": types, "events": events,
        "notifications": [n["status"] for n in notifications],
    }


def validate_log(path: Path | None):
    if not path:
        return "NOT MEASURED (provide --validator-log)"
    if not path.exists():
        return "VALIDATOR LOG MISSING"
    data = path.read_text(encoding="utf-8-sig", errors="replace")
    findings = re.findall(r"(?:Success|\*FAILURE\*)\s*:\s*(\d+)\s+errors?\s*,\s*(\d+)\s+warnings?", data, re.I)
    if not findings:
        return "NO PARSEABLE VALIDATOR SUMMARY — inspect log manually"
    if len(findings) > 1:
        return "LOG HAS MULTIPLE VALIDATIONS — individual summaries: " + "; ".join(f"{e} errors / {w} warnings" for e, w in findings)
    e, w = findings[0]
    return f"{e} errors, {w} warnings; " + ("PASS" if int(e) == 0 else "FAIL")


def m_check(label: str, s: dict) -> str:
    if s["status"] != "FOUND":
        return "NOT VERIFIED (request missing)"
    types = {e["type"] for e in s["events"]}
    reasons = {e["reason"] for e in s["events"]}
    filed = s["filing"] == "filed" or "ANSWER_FILED" in types
    if label in ("M1", "M2"):
        if "recipient_identity_mismatch" in reasons and not filed:
            return "Audit mismatch logged; not filed. **Verify no disclosure / HTTP 403 manually.**"
        return "NOT CONFIRMED from logs (identity mismatch + no filing required)"
    if "wrong_patient" in reasons and not filed:
        if "sent" in s["notifications"]:
            return "Wrong patient blocked, not filed, Matrix warning marked delivered. **Verify in Element.**"
        return "Wrong patient blocked, not filed; **Matrix delivery not confirmed.**"
    return "NOT CONFIRMED from logs (wrong patient + no filing + Matrix notice required)"


def main():
    a = cli()
    if not a.db.exists():
        raise SystemExit(f"SQLite database not found: {a.db}\nRun this script on your local gateway machine, or use --db PATH.")
    cx = sqlite3.connect(f"file:{a.db.resolve()}?mode=ro", uri=True)
    cx.row_factory = sqlite3.Row
    try:
        ids = {k: getattr(a, k) for k in ("lab", "rehab", "m1", "m2", "m3")}
        states = {k: request_state(cx, v) for k, v in ids.items()}
        supplied = [v for v in ids.values() if v]
        if supplied:
            events = []
            for key, s in states.items():
                if s["status"] == "FOUND":
                    events += s["events"]
            scope = "only request IDs supplied to this command"
        else:
            rows = read_rows(cx, "SELECT what,who,when_at FROM audit_events")
            events = [{"type": x["what"], "who": x["who"], "when": x["when_at"]} for x in rows]
            scope = "all historical requests in this local SQLite database (not necessarily current scenario)"
        covered = {}
        for etype in AUDIT_EVENTS:
            matched = [e for e in events if e["type"] == etype]
            covered[etype] = bool(matched) and all(bool(e.get("who")) and bool(e.get("when")) for e in matched)
        cover_count = sum(covered.values())
        types_lab = states["lab"].get("types", [])
        types_rehab = states["rehab"].get("types", [])
        outside = (f"{a.installs} installs; {a.accounts} PGK accounts; {a.outside_seconds:.1f} seconds"
                   if None not in (a.installs, a.accounts, a.outside_seconds) else "NOT FULLY MEASURED")
        outside_pass = None not in (a.installs, a.accounts, a.outside_seconds) and a.installs == a.accounts == 0 and a.outside_seconds < 120
        result = [
            "# PGK Gateway — Generated Metrics (Synthetic Demo)",
            f"Generated at {datetime.now(timezone.utc).isoformat(timespec='seconds')} (UTC).",
            "",
            f"**Scope:** {scope}. Only events with recorded `who` and `when` count for audit coverage.",
            "",
            "| Organizer metric | Observed | Interpretation |",
            "|---|---|---|",
            f"| FHIR R4 validation | {validate_log(a.validator_log)} | Official Java validator log (if provided); validate all newly filed resources separately as needed |",
            f"| Outside person effort | {outside} | {'PASS' if outside_pass else 'NOT CONFIRMED'}; timed with a real first-time participant, not from DB events |",
            f"| Misdelivery M1 | {m_check('M1', states['m1'])} | Must confirm no patient disclosure, no filing, audit |",
            f"| Misdelivery M2 | {m_check('M2', states['m2'])} | Must confirm colleague not filed and audit |",
            f"| Misdelivery M3 | {m_check('M3', states['m3'])} | Must confirm Matrix notice actually delivered |",
            f"| Audit coverage | {cover_count}/6 | Event types present in selected local records |",
            "",
            "## Audit coverage details",
            "| Required event | Present with who / what / when? |",
            "|---|---|",
        ]
        for event, ok in covered.items():
            result.append(f"| `{event}` | {'YES' if ok else 'NO'} |")
        result.extend(["", "## Request filing summaries", "| Scenario | Request ID | Status | Resources in gateway filing record |", "|---|---|---|---|"])
        for key in ("lab", "rehab", "m1", "m2", "m3"):
            s = states[key]
            counts = {kind: s.get("types", []).count(kind) for kind in sorted(set(s.get("types", [])))}
            result.append(f"| {key.upper()} | `{s.get('id', 'not supplied')}` | {s.get('filing', s['status'])} | {', '.join(f'{k}:{v}' for k, v in counts.items()) or 'none'} |")
        result.extend(["", "**Limitations:** FHIR filing status is gateway state, not an independently verified HAPI read; "
                       "the parser is deterministic; mock eID is NOT real governmental identification; "
                       "M1/M2 still require direct browser disclosure check. "
                       "This summary does not expose tokens, PINs, email addresses or clinical text.", ""])
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text("\n".join(result), encoding="utf-8")
        print(f"Report written: {a.out}")
        print(f"Audit coverage: {cover_count}/6 ({scope})")
        print(f"FHIR validator: {validate_log(a.validator_log)}")
        print(f"Outside effort: {outside}")
        if states["lab"]["status"] == "FOUND":
            print(f"Lab filing: {states['lab']['filing']}; Observations recorded: {types_lab.count('Observation')}")
        if states["rehab"]["status"] == "FOUND":
            print(f"Rehab filing: {states['rehab']['filing']}; Observations recorded: {types_rehab.count('Observation')}")
    finally:
        cx.close()


if __name__ == "__main__":
    main()
