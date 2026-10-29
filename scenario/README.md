# Scenario

Everyone in this scenario is made up.

## The network

The closed network works like PGK: members are listed in a directory and only members can be reached. One member sends the requests:

| Member | Role | Matrix ID |
|---|---|---|
| Dr. Lena Hofer | Internal medicine, Klinikum Beispielstadt | `@lena.hofer:klinikum.example` |

Run one Matrix server for `klinikum.example`. You can add more members if you need them.

## Outside the network

These two people are not in the directory. Dr. Hofer only knows their name, role and one contact. The request is always for the named person. A colleague is not allowed to answer for them.

| Person | Role | Contact | Sends back |
|---|---|---|---|
| Dr. Eva Brandl | Lab physician at Labor Kanalstraße, a lab that is not in the network | `eva.brandl@labor-kanal.example` (her personal work address) | Lab result |
| Stefan Kern | Discharge manager at Reha Waldblick, a rehab clinic | `+43 660 000 0101` | Rehab discharge report |

The `.example` addresses cannot receive mail and the phone number is made up. Do not send real email or SMS to them. Use a local mail catcher such as Mailpit, which accepts any address and a simulated SMS screen. Emails and SMS must not contain the patient's name, her birth date or what kind of document is requested.

## The patient

Maria Beispiel, born 12 March 1961, female. Her FHIR R4 Patient resource is in [`patient.json`](patient.json). Both requests are about her.

## Requests to run

1. Dr. Hofer asks Dr. Brandl for Maria's latest blood clotting tests before a planned procedure. Dr. Brandl answers with [`documents/lab-result-maria-beispiel.md`](documents/lab-result-maria-beispiel.md).
2. Dr. Hofer asks Stefan Kern for Maria's rehab discharge report. He answers with [`documents/rehab-report-maria-beispiel.md`](documents/rehab-report-maria-beispiel.md).

The outside person can upload the file or type the content into a form. That is up to you. A form must ask for the patient's name and birth date, so your service can check the answer is about the right patient. When testing, copy the name and birth date from the document file.

## Tools

- Matrix server: Synapse (`matrixdotorg/synapse` on Docker) or Conduit. Chat app: Element Web.
- FHIR server: HAPI FHIR (`hapiproject/hapi` on Docker) or the public test server `https://hapi.fhir.org/baseR4`. On the public server, give the patient your own ID so your data does not mix with other teams'.
- Email in tests: Mailpit (`axllent/mailpit` on Docker).
- SMS in tests: a page in your app that shows the SMS your service would send. A real SMS service is optional.
- FHIR validator: needs Java. Download `validator_cli.jar` from the releases of `hapifhir/org.hl7.fhir.core` on GitHub, then run `java -jar validator_cli.jar your-resource.json -version 4.0`.
