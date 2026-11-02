Optional: put PEM root certificates (`*.crt`) of a TLS-inspecting corporate proxy or antivirus here
when `docker compose build` fails with `CERTIFICATE_VERIFY_FAILED`. They are trusted only while
downloading build dependencies (all packages are still hash-verified) and never enter the runtime image.
`*.crt` files here are ignored by git.
