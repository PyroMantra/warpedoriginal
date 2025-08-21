#!/usr/bin/env python3
from pathlib import Path
import re

p = Path("app.py")
src = p.read_text(encoding="utf-8", errors="ignore")
orig = src

# If not already imported, insert `import env_boot` as the very first non-shebang line.
if "import env_boot" not in src:
    m = re.match(r"^(\#\!.*\n)?", src)
    pos = m.end() if m else 0
    src = src[:pos] + "import env_boot  # must be first\n" + src[pos:]

if src != orig:
    p.with_suffix(".py.envbootbak").write_text(orig, encoding="utf-8")
    p.write_text(src, encoding="utf-8")
    print("app.py updated: inserted `import env_boot` as first import.")
else:
    print("app.py already imports env_boot (or patch not needed).")
