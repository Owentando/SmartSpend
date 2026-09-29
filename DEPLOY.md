# Deploying SmartSpend on Render

1. Push this folder to a new GitHub repo (`git init && git add . && git commit -m "SmartSpend" && git push`).
2. Render dashboard -> New -> Blueprint -> pick the repo (it reads `render.yaml`).
3. Enter a value for `ADMIN_INVITE_CODE` when prompted, then Apply.
4. Open the `*.onrender.com` URL and smoke-test: register, login, search, add to budget list, download PDF.

Local run (Windows PowerShell):
    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    python app.py

Local runs use dev fallbacks for SECRET_KEY / ADMIN_INVITE_CODE (dev-admin-code).
On Render both are required or the app refuses to start.

Notes
- The SQLite file lives on the persistent disk at /var/data. Without a disk (free plan) data resets on every restart.
- CSRF protection is ON. To switch it off for debugging, set env var CSRF_DISABLED=1.
- Keep --workers 1: products are cached in memory at startup and login rate limits are per-process.
