# Step 5 validation fix: LOINC and Bundle references

Overlay only `pgk_step2_gateway/app/fhir.py` and `pgk_step2_gateway/tests/test_fhir.py` onto the existing step 5 project. Do not replace .env / database / Docker volumes.

Changes:
1. Correct canonical LOINC display for 6301-6, 14979-9, 777-3 and 3255-7. Unknown codes retain the original test name in `code.text` without a fabricated `coding.display`.
2. Use an absolute RESTful `Bundle.entry.fullUrl` matching the resource PUT target (`PGK_FHIR_BASE_URL/ResourceType/id`). This resolves relative references and avoids malformed `urn:uuid` values.
3. Add short XHTML generated narratives to satisfy best-practice `dom-6`.
4. Replace undocumented proprietary Provenance activity coding with a text-only CodeableConcept, preserving the fact that eID was simulated. The mock eID identity remains in Practitioner.identifier; verification events remain in the audit log.
5. Add tests to verify relative bundle links and canonical display.

From pgk_step2_gateway:
```powershell
python -m pytest -q
# restart FastAPI then re-export JSON for the original request
python tools/export_fhir.py req_6f24e09ad2d7432b
$reqId = 'req_6f24e09ad2d7432b'
Get-ChildItem ".\fhir-validation\$reqId\*.json" | ForEach-Object {
  Write-Host "Validating $($_.Name)"
  java -jar .\validator_cli.jar $_.FullName -version 4.0.1
}
```

Note: `GET /internal/fhir/export/{request_id}` rebuilds the Bundle with the latest code, but does not change resources that have already been stored on HAPI. To update the stored resources, use a new request with a fresh submission, or explicitly retry/re-file with a controlled change. Do not delete the HAPI volume.

The tests run without the actual HAPI server; rerun the official HL7 validator on your own Windows environment for the final zero-error metric.
