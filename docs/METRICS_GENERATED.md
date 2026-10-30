# PGK Gateway — Generated Metrics (Synthetic Demo)
Generated at 2026-10-30T13:20:01+00:00 (UTC).

**Scope:** only request IDs supplied to this command. Only events with recorded `who` and `when` count for audit coverage.

| Organizer metric | Observed | Interpretation |
|---|---|---|
| FHIR R4 validation | NOT MEASURED (provide --validator-log) | Official Java validator log (if provided); validate all newly filed resources separately as needed |
| Outside person effort | NOT FULLY MEASURED | NOT CONFIRMED; timed with a real first-time participant, not from DB events |
| Misdelivery M1 | NOT VERIFIED (request missing) | Must confirm no patient disclosure, no filing, audit |
| Misdelivery M2 | NOT VERIFIED (request missing) | Must confirm colleague not filed and audit |
| Misdelivery M3 | NOT VERIFIED (request missing) | Must confirm Matrix notice actually delivered |
| Audit coverage | 5/6 | Event types present in selected local records |

## Audit coverage details
| Required event | Present with who / what / when? |
|---|---|
| `REQUEST_SENT` | YES |
| `LINK_OPENED` | YES |
| `IDENTITY_CHECKED` | YES |
| `ANSWER_SENT` | YES |
| `ANSWER_FILED` | YES |
| `MISDELIVERY_CAUGHT` | NO |

## Request filing summaries
| Scenario | Request ID | Status | Resources in gateway filing record |
|---|---|---|---|
| LAB | `req_6f24e09ad2d7432b` | filed | DocumentReference:1, Observation:4, Patient:1, Practitioner:1, Provenance:1 |
| REHAB | `req_REHAB_ID` | REQUEST NOT FOUND | none |
| M1 | `req_M1_ID` | REQUEST NOT FOUND | none |
| M2 | `req_M2_ID` | REQUEST NOT FOUND | none |
| M3 | `req_M3_ID` | REQUEST NOT FOUND | none |

**Limitations:** FHIR filing status is gateway state, not an independently verified HAPI read; the parser is deterministic; mock eID is NOT real governmental identification; M1/M2 still require direct browser disclosure check. This summary does not expose tokens, PINs, email addresses or clinical text.
