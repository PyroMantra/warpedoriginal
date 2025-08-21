#!/usr/bin/env python3
import re
from pathlib import Path

p = Path("app.py")
src = p.read_text(encoding="utf-8", errors="ignore")
orig = src
changed = False

# Insert the dotenv loader right after the very first imports block
loader = r"""
# ==== .env LOADER (autopatch) ====
import os
from pathlib import Path as _Path
try:
    from dotenv import load_dotenv, find_dotenv
    _env_path = _Path(__file__).with_name(".env")
    # Load .env even if CWD is different; do NOT overwrite real env
    load_dotenv(dotenv_path=_env_path, override=False)
    if os.getenv("GOOGLE_CLIENT_ID"):
        _gid = os.getenv("GOOGLE_CLIENT_ID") or ""
        print("[env] GOOGLE_CLIENT_ID loaded:", (_gid[:8] + "..."))
    else:
        print("[env] GOOGLE_CLIENT_ID missing")
    if os.getenv("GOOGLE_CLIENT_SECRET"):
        print("[env] GOOGLE_CLIENT_SECRET present")
    else:
        print("[env] GOOGLE_CLIENT_SECRET missing")
except Exception as _e:
    print("[env] dotenv load failed:", _e)
# ==== .env LOADER END ====
"""

if "dotenv" not in src:
    # find the end of the initial import section and drop loader after it
    m = re.search(r"^(?:from\s+\S+\s+import\s+\S+|import\s+\S+).*?(?:\n(?!from|import).*)", src, re.S|re.M)
    if m:
        pos = m.end()
        src = src[:pos] + "\n\n" + loader.strip() + "\n\n" + src[pos:]
        changed = True
    else:
        # fallback: prepend
        src = loader.strip() + "\n\n" + src
        changed = True

# Ensure any oauth.register uses env values (if hardcoded)
src = re.sub(r"(client_id\s*=\s*)['\"][^'\"]+['\"]", r"\1os.getenv('GOOGLE_CLIENT_ID')", src)
src = re.sub(r"(client_secret\s*=\s*)['\"][^'\"]+['\"]", r"\1os.getenv('GOOGLE_CLIENT_SECRET')", src)

if changed:
    p.with_suffix(".py.envbak").write_text(orig, encoding="utf-8")
    p.write_text(src, encoding="utf-8")
    print("app.py updated: .env loader inserted and oauth set to read env.")
else:
    print("No changes made (dotenv already present).")
