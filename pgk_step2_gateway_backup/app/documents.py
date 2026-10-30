"""Strict, intentionally small parser for the supplied *synthetic* Markdown format.

Does not infer identities or LOINC codes. Invalid/unknown data is rejected.
This is NOT a clinical document interpretation engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class PatientClaim:
    name: str
    birth_date: str  # ISO 8601 date


class InvalidDocument(ValueError):
    pass


def parse_birth_date(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip()).strip(" .")
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(normalized, fmt).date().isoformat()
        except ValueError:
            pass
    raise InvalidDocument("Patient birth date is missing or unsupported")


def parse_patient_claim(markdown: str) -> PatientClaim:
    claims = re.findall(r"^\s*Patient\s*:\s*(.+?)\s*$", markdown, re.IGNORECASE | re.MULTILINE)
    if len(claims) != 1:
        raise InvalidDocument("Document must contain exactly one Patient: line")
    line = claims[0].strip()
    match = re.fullmatch(r"(.+?),?\s*,\s*born\s+(.+)", line, flags=re.IGNORECASE)
    if match:
        name, birth = match.group(1), match.group(2)
    else:
        name = line
        dates = re.findall(r"^\s*(?:Date of birth|Birth date|DOB)\s*:\s*(.*?)\s*$",
                           markdown, re.IGNORECASE | re.MULTILINE)
        if len(dates) != 1:
            raise InvalidDocument("Document must include patient's birth date")
        birth = dates[0]
    name = re.sub(r"\s+", " ", name.strip())
    if len(name) < 3 or len(name) > 150:
        raise InvalidDocument("Patient name is invalid")
    return PatientClaim(name=name, birth_date=parse_birth_date(birth))


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).casefold()


def expected_patient_file() -> Path:
    # Prefer the organizer's original scenario, with a standalone fixture fallback.
    import os
    config = os.getenv("PGK_PATIENT_JSON")
    if config:
        return Path(config)
    official = Path(__file__).resolve().parents[2] / "scenario" / "patient.json"
    if official.is_file():
        return official
    return Path(__file__).resolve().parents[1] / "fixtures" / "patient.json"


def expected_patient() -> dict:
    try:
        patient = json.loads(expected_patient_file().read_text(encoding="utf-8"))
        if patient.get("resourceType") != "Patient":
            raise ValueError("Not a FHIR Patient")
        return {
            "reference": "Patient/" + patient["id"],
            "name": " ".join(patient["name"][0].get("given", []) + [patient["name"][0]["family"]]),
            "birth_date": patient["birthDate"],
        }
    except (ValueError, OSError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Unable to load configured FHIR Patient") from exc


def parse_lab_rows(markdown: str) -> list[dict]:
    lines = [line.strip() for line in markdown.splitlines()]
    header_idx = None
    columns = None
    for i, line in enumerate(lines):
        if not (line.startswith("|") and line.endswith("|")):
            continue
        fields = [part.strip().casefold() for part in line.strip("|").split("|")]
        if {"test", "result", "unit", "loinc code"}.issubset(fields):
            header_idx = i
            columns = fields
            break
    if header_idx is None or columns is None:
        raise InvalidDocument("Laboratory report requires a Markdown table with Test, Result, Unit and LOINC code")
    if header_idx + 1 >= len(lines) or not re.fullmatch(r"\|[\s:|\-]+\|", lines[header_idx + 1]):
        raise InvalidDocument("Lab table is missing a Markdown separator")
    values = []
    for line in lines[header_idx + 2:]:
        if not line.startswith("|") or not line.endswith("|"):
            break
        cells = [part.strip() for part in line.strip("|").split("|")]
        if len(cells) != len(columns):
            raise InvalidDocument("Laboratory table row has incorrect column count")
        record = dict(zip(columns, cells))
        try:
            value = float(record["result"].replace(",", "."))
        except ValueError as exc:
            raise InvalidDocument("Non-numeric laboratory result") from exc
        from math import isfinite
        if not isfinite(value):
            raise InvalidDocument("Non-finite laboratory result")
        loinc = record["loinc code"]
        if not re.fullmatch(r"\d{1,7}-\d", loinc):
            raise InvalidDocument("Missing/invalid LOINC code format")
        values.append({
            "test": record["test"], "value": value,
            "unit": record["unit"], "loinc": loinc,
            "reference_range": record.get("reference range", ""),
        })
    if not values:
        raise InvalidDocument("Laboratory table contains no values")
    return values


def parse_submission(markdown: str, kind: str) -> tuple[PatientClaim, dict]:
    claim = parse_patient_claim(markdown)
    if kind == "lab":
        rows = parse_lab_rows(markdown)
        return claim, {"kind": "lab", "observations": rows}
    if kind == "rehab":
        # Prevent a lab table from being accepted under a rehab request.
        if re.search(r"\|\s*test\s*\|.*\bloinc\s+code\b", markdown, flags=re.IGNORECASE):
            raise InvalidDocument("Lab report does not match rehab request")
        if len(markdown.strip()) < 40:
            raise InvalidDocument("Rehabilitation document is too short")
        return claim, {"kind": "rehab", "body_text": markdown}
    raise InvalidDocument("Unsupported document kind")
