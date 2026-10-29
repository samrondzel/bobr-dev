# Misdelivery tests

Run all three. A test counts as caught if its "Caught if" condition holds and your service writes the event to the audit log. Run them on request 1, with Dr. Brandl, who is reached by email.

## M1: Wrong address

Dr. Hofer types Dr. Brandl's address with a capital I instead of a lowercase l: `eva.brandl@labor-kanaI.example`. Someone who is not Dr. Brandl opens the email, clicks the link and tries to answer.

Caught if: that person cannot see the patient or the type of document, cannot answer and the failed identity check is in the audit log.

## M2: Forwarded request

Dr. Brandl forwards the email to a colleague, `kollege@labor-kanal.example`, who tries to answer it.

Caught if: the colleague's answer is not filed. Your service either blocks it or shows it to Dr. Hofer clearly marked as sent by someone other than Dr. Brandl.

## M3: Wrong patient

Dr. Brandl answers the request about Maria Beispiel with [`documents/lab-result-max-beispiel.md`](documents/lab-result-max-beispiel.md), a result for Max Beispiel, born 1 January 1960.

Caught if: Dr. Hofer is told about the mismatch in her Matrix room and the result is not filed for Maria.
