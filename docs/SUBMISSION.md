# Final submission checklist — practical sequence

## 1. Commit the code and submission README

1. Put `README_SUBMISSION.md` in the **repository root** (not inside `pgk_step2_gateway`), then replace the organizer's root README with the team's README after preserving the original as `CHALLENGE_README.md` if you want to keep it.
2. Add the `docs/` folder and `pgk_step2_gateway/tools/report_metrics.py`. Do not overwrite `.env` or SQLite.
3. Run `python -m pytest -q` **from `pgk_step2_gateway`**; record the result.
4. Check `git status` and `git diff --cached --stat`; publish only source/docs. Avoid secrets, raw local data, big JARs, `.venv`, `.pytest_cache` and private credentials.

## 2. Measure before claiming

Use `docs/METRICS.md` and the new metric script. For first-time recipient timing start at opening the email and stop at successful submission; type measured seconds. For M1/M2/M3 give actual request IDs and verify no filing and the required audit/Matrix behavior. For FHIR run the official Validator against exported **Bundle**, and record warnings distinctly from errors.

## 3. Record and upload the video

Follow `docs/DEMO_VIDEO.md`, keep it <= 120 seconds and test that the shared URL works in an incognito browser. If the full 2-minute video is not ready, prioritize a short truthful working demo over polished editing. You may use clips of a real run; do not fabricate outputs.

## 4. Public repository

When all secret checks pass, change the team GitHub repository visibility to Public (Settings → General → Danger Zone → Change repository visibility). You need owner permissions. Before doing this, review **all committed history** for accidentally committed secrets; `.gitignore` does not erase secrets that are already in history. Rotate anything that has leaked. Confirm incognito read access to the repository, README, and video link.

## 5. What to submit

- Public GitHub repository URL containing actual runnable code, root README, five design answers and metric results.
- Publicly accessible video URL (<=2 minutes), with working and nonworking parts explained.
- Actual four metric outcomes: FHIR errors; outside-person installs/accounts/time; M1/M2/M3; six audited steps.

## Minimum acceptable last-minute submission

Public repo + 2-minute truthful screen recording + simple measured metrics table + five design answers. Avoid spending the last 20 minutes on cosmetic UI or untested additional features.
