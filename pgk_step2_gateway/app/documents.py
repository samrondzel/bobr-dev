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


def valid_loinc_code(code: str) -> bool:
    """LOINC numeric codes use a Mod-10/Luhn check digit, not just a regex."""
    if not re.fullmatch(r"\d{1,7}-\d", code):
        return False
    digits = code.replace("-", "")
    total = 0
    for pos, character in enumerate(reversed(digits)):
        digit = int(character)
        if pos % 2:
            digit *= 2
            digit = digit // 10 + digit % 10
        total += digit
    return total % 10 == 0


def _column_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name.strip().strip("*` ").casefold())
    return {"value": "result", "units": "unit", "loinc": "loinc code",
            "loinc-code": "loinc code", "reference interval": "reference range"}.get(name, name)


def parse_lab_rows(markdown: str) -> list[dict]:
    """Parse every matching lab table; fail closed on malformed or partial tables.

    Different patients or new tests are allowed in the input *format*, but their
    identity and LOINC integrity are checked before any clinical filing.
    """
    lines = [line.strip() for line in markdown.splitlines()]
    results: list[dict] = []
    seen_lab = False
    pos = 0
    required = {"test", "result", "unit", "loinc code"}
    while pos < len(lines):
        line = lines[pos]
        if not (line.startswith("|") and line.endswith("|")):
            pos += 1
            continue
        fields = [_column_name(part) for part in line.strip("|").split("|")]
        is_lab = required.issubset(fields)
        partial_lab = ("loinc code" in fields or ("test" in fields and "result" in fields))
        if partial_lab and not is_lab:
            raise InvalidDocument("Incomplete laboratory table headers")
        if not is_lab:
            pos += 1
            continue
        if len(fields) != len(set(fields)):
            raise InvalidDocument("Duplicate laboratory table columns")
        seen_lab = True
        pos += 1
        if pos >= len(lines) or not re.fullmatch(r"\|[\s:|\-]+\|", lines[pos]):
            raise InvalidDocument("Lab table is missing a Markdown separator")
        pos += 1
        count = 0
        while pos < len(lines) and lines[pos].startswith("|") and lines[pos].endswith("|"):
            cells = [part.strip() for part in lines[pos].strip("|").split("|")]
            if len(cells) != len(fields):
                raise InvalidDocument("Laboratory table row has incorrect column count")
            record = dict(zip(fields, cells))
            raw_value = record["result"]
            match = re.fullmatch(r"(<=|>=|<|>)?\s*([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+))", raw_value)
            if not match:
                raise InvalidDocument("Non-numeric laboratory result")
            value = float(match.group(2).replace(",", "."))
            from math import isfinite
            if not isfinite(value):
                raise InvalidDocument("Non-finite laboratory result")
            loinc = record["loinc code"]
            if not valid_loinc_code(loinc):
                raise InvalidDocument("Invalid LOINC code or check digit")
            if not record["test"]:
                raise InvalidDocument("Laboratory test name is required")
            result = {"test": record["test"], "value": value,
                      "unit": record["unit"], "loinc": loinc,
                      "reference_range": record.get("reference range", "")}
            if match.group(1):
                result["comparator"] = match.group(1)
            results.append(result)
            count += 1
            pos += 1
        if count == 0:
            raise InvalidDocument("Laboratory table contains no values")
    if not seen_lab:
        raise InvalidDocument("Laboratory report requires a Markdown table with Test, Result, Unit and LOINC code")
    return results


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
