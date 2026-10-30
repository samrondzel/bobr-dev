# 2-minute demo video: show the complete handover

**Aim:** 1:50–1:59 total. Record the screen (e.g., Windows Snipping Tool screen recording or OBS). 1080p is sufficient. Do not show `.env`, API credentials, bot PINs, database secrets or raw invitation token in terminal. All identities/clinical details shown are synthetic.

## Screen choreography (record real interactions, not fabricated results)

| Timestamp | Screen | Narration (English, adaptable) |
|---|---|---|
| 00:00–00:12 | Title slide: PGK Last Mile Gateway + diagram | “Closed clinical networks leave outside labs and rehabilitation clinics on fax and unencrypted email. We built a secure last-mile document handover prototype.” |
| 00:12–00:29 | Element as Lena, send lab `!request` | “A clinician creates a request from a Matrix room. The gateway sends a generic invitation with no patient name, birth date or document type.” |
| 00:29–00:51 | Mailpit + generic email; open link; mock eID | “An outside recipient opens the link without a PGK account or installation. The synthetic eID check confirms the named recipient before any patient details appear.” |
| 00:51–01:13 | Portal, upload lab result, success; Matrix confirmation | “We match the patient, extract LOINC-coded lab observations, store FHIR R4 resources and Provenance, and notify the doctor in Matrix.” |
| 01:13–01:29 | FHIR JSON/query and terminal showing 0 errors | “HAPI stores the transaction. Our official FHIR R4 validator check on this scenario reports zero errors.” **Only say this if the displayed output matches.** |
| 01:29–01:43 | M3 wrong patient, rejected, Matrix warning | “A document for a different patient is blocked before filing and the clinician is notified. Our tests also cover wrong-address and forwarded-link recipients.” |
| 01:43–01:53 | Rehab result, DocumentReference in FHIR or SMS simulator | “The same process supports rehabilitation reports sent by simulated SMS, recorded as DocumentReference without observations.” |
| 01:53–01:59 | Final scorecard | “The prototype uses synthetic data only; eID is simulated and the environment is not production hardened.” |

### Safer fallback if live demo is unstable

Use previously recorded **actual** clips from your successful local run, not fabricated animations or manipulated server output. Briefly explain which part did not run live. Organizers explicitly ask you to say what works and what does not. Aim to show at least: Matrix command → generic invitation → verification → FHIR result → error handling. Add metrics slides made from your measured data.

### Upload checks

- MP4 playable in browser; duration no more than 2:00; public-access link (test in incognito).
- Ensure microphone and screen text are legible.
- Do not publish real-looking secrets, actual credentials, or any non-synthetic medical data.
- Name the file `pgk-last-mile-demo.mp4`.
