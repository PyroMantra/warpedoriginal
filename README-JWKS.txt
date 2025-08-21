Fix: RuntimeError Missing "jwks_uri" in metadata

What changed:
  - Updated Google OAuth registration to use OpenID Discovery:
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration'
    This provides 'jwks_uri' to Authlib so ID token validation works.

How to apply:
  1) Stop your server (Ctrl+C).
  2) Replace your app.py with the one in this zip.
  3) Re-run in the same PowerShell window where you set the env vars:
     $env:GOOGLE_CLIENT_ID="...apps.googleusercontent.com"
     $env:GOOGLE_CLIENT_SECRET="..."
     $env:OAUTHLIB_INSECURE_TRANSPORT="1"   # local only
     python app.py
  4) Try Google sign-in again.
