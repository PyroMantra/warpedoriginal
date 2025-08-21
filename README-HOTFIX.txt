Hotfix: Add missing Google routes + lock SERVER_NAME + whoami

Files:
  - app.py
  - templates/login.html (only if your file didn't already have the button)

Install:
  1) Close your running server (Ctrl+C).
  2) Copy app.py into your project folder (replace the existing file).
  3) If login.html is included, copy it to templates/login.html.
  4) In PowerShell (same window you run the app in):
     $env:GOOGLE_CLIENT_ID="your_client_id.apps.googleusercontent.com"
     $env:GOOGLE_CLIENT_SECRET="your_client_secret"
     $env:OAUTHLIB_INSECURE_TRANSPORT="1"
  5) Start: python app.py
  6) Test: http://localhost:5000/  then  http://localhost:5000/whoami

Notes:
  - Keep SERVER_NAME only for local dev; remove before deploying to production.
  - If you still see 'redirect_uri_mismatch', add both callback URLs in Google Cloud:
    http://localhost:5000/auth/google/callback
    http://127.0.0.1:5000/auth/google/callback
