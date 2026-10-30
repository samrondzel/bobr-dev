# Submission form copy-ready template

**Project:** PGK Last Mile Gateway

**Repository:** <PASTE_YOUR_PUBLIC_GITHUB_REPO_URL>

**Demo video (≤2 min):** <PASTE_PUBLIC_VIDEO_URL>

**Results:** FHIR R4 lab scenario: 0 errors in the previously validated bundle (note: latest new document validation must be checked). Outside respondent: <MEASURED_SECONDS> s / <INSTALLS> installations / <ACCOUNTS> PGK accounts. Misdelivery: M1 <RESULT>, M2 <RESULT>, M3 <RESULT>. Audit coverage: <X>/6.

**What works:** Matrix request through bot; email and synthetic SMS invitation; browser recipient verification by simulated eID; Markdown upload and patient match; LOINC-coded FHIR `Observation` for labs; `DocumentReference` for rehab; `Provenance`, HAPI FHIR filing, status notification and audit. Automated Python tests passed locally; official HL7 Validator was run for the provided laboratory sample.

**Known limitations:** Simulated eID is not real ID Austria; the test environment uses local HTTP and a non-E2EE demo room, with no production FHIR access controls; Markdown parser targets challenge formats; no clinical PDF/OCR pipeline. All content is synthetic.

**Important:** Replace ALL angle-bracket placeholders and any unverified claims before submission. Check GitHub and video URLs from an incognito browser.
