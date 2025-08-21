Username-on-first-Google-login + real email/password accounts

Added:
  - SQLite users table (data/auth.db auto-created)
  - /register, /login, /logout
  - /pick-username (shown after first Google sign-in if username missing)
  - Layout shows username when logged in

Files:
  - app.py
  - templates/login.html
  - templates/register.html
  - templates/pick_username.html
  - templates/layout.html (nav tweaks)
  - requirements.txt (ensures Authlib + requests)

How to apply:
  1) Stop your server (Ctrl+C) and back up your project.
  2) Copy these files over your project (same paths).
  3) Install deps:  python -m pip install -r requirements.txt
  4) Set env vars (each on its own line):
     $env:GOOGLE_CLIENT_ID="...apps.googleusercontent.com"
     $env:GOOGLE_CLIENT_SECRET="..."
     $env:OAUTHLIB_INSECURE_TRANSPORT="1"
  5) Run: python app.py
  6) Sign in with Google; you'll be sent to /pick-username once.
