import os
from pathlib import Path
try:
    from dotenv import dotenv_values
except Exception:
    dotenv_values = None

def _mask(v): 
    return (v[:8] + "...") if v else "missing"

def _load():
    here = Path(__file__).resolve().parent
    env_file = here / ".env"
    if not env_file.exists():
        print(f"[env_boot] .env not found at {env_file}")
        return
    if dotenv_values is None:
        print("[env_boot] python-dotenv not installed")
        return
    vals = dotenv_values(str(env_file))
    for k, v in (vals or {}).items():
        if v is None: 
            continue
        # do NOT override anything already set in the OS/session
        if os.getenv(k) is None:
            os.environ[k] = v
    print(f"[env_boot] .env loaded from {env_file}")
    print("[env_boot] GOOGLE_CLIENT_ID:", _mask(os.getenv("GOOGLE_CLIENT_ID")))
    print("[env_boot] GOOGLE_CLIENT_SECRET:", "present" if os.getenv("GOOGLE_CLIENT_SECRET") else "missing")
    print("[env_boot] OAUTHLIB_INSECURE_TRANSPORT:", os.getenv("OAUTHLIB_INSECURE_TRANSPORT", "missing"))

_load()
