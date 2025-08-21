#!/usr/bin/env python3
from pathlib import Path
import re

p = Path("app.py")
s = p.read_text(encoding="utf-8", errors="ignore")
orig = s

# Add a very small route if not present
if "/__envcheck" not in s:
    s = re.sub(r"(app\s*=\s*Flask\([^\)]*\)\s*)",
               r"\1\n\n@app.route('/__envcheck')\ndef __envcheck():\n    import os\n    return {\n        'GOOGLE_CLIENT_ID': (os.getenv('GOOGLE_CLIENT_ID') or '')[:8] + '...' if os.getenv('GOOGLE_CLIENT_ID') else 'missing',\n        'GOOGLE_CLIENT_SECRET': bool(os.getenv('GOOGLE_CLIENT_SECRET')),\n        'OAUTHLIB_INSECURE_TRANSPORT': os.getenv('OAUTHLIB_INSECURE_TRANSPORT', 'missing')\n    }\n",
               s, count=1, flags=re.M)

if s != orig:
    p.with_suffix(".py.envcheckbak").write_text(orig, encoding="utf-8")
    p.write_text(s, encoding="utf-8")
    print("app.py updated: added /__envcheck route.")
else:
    print("app.py already has /__envcheck or patch unnecessary.")
