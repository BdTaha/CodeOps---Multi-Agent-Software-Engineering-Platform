# developer-demo

A dependency-free Python API with a registration form and an existing email
validation helper. Registration intentionally returns 501 until implemented.
This is a CodeOps exercise repository, not an authentication service.

Goal: **Add user registration with input validation and persistent storage.**

Reuse `validation.normalize_email`, store name/email in SQLite, reject malformed
and duplicate emails, and add unittest coverage. No passwords, login, or external
services are needed. Keep the HTTP interface in `app.py` compatible.

Run `python -m unittest discover -s tests -v`, then `python app.py`.
Open http://127.0.0.1:8000/. Preview uses `/health` and the same command.
SQLite data belongs inside the isolated preview volume, never in the source.
